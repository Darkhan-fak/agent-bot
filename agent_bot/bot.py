import os
import uuid
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from agent_bot import config, approval
from agent_bot.agent import run_agent

logger = logging.getLogger("agent_bot.bot")

# Global variables to track the active agent task
active_task: asyncio.Task | None = None
current_task_desc: str | None = None

def check_user(func):
    """Decorator to ignore requests from users other than ALLOWED_USER_ID."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != config.ALLOWED_USER_ID:
            logger.warning(f"Ignored request from unauthorized user ID: {user.id if user else 'Unknown'}")
            return
        return await func(update, context)
    return wrapper

def split_text(text: str, max_chars: int = 4000) -> list[str]:
    """Splits text into chunks of at most max_chars."""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split_pos = text.rfind('\n', 0, max_chars)
        if split_pos == -1:
            split_pos = text.rfind(' ', 0, max_chars)
        if split_pos == -1:
            split_pos = max_chars
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    return chunks

@check_user
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends start message."""
    await update.message.reply_text(
        "🤖 *AgentBot ready.*\nSend me a coding task or check my status with /status.",
        parse_mode="Markdown"
    )

@check_user
async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reports status of the agent."""
    global active_task, current_task_desc
    if active_task and not active_task.done():
        status = f"🔄 *Working on task:* {current_task_desc}"
    else:
        status = "💤 *Idle.* Ready for a new task."
    await update.message.reply_text(status, parse_mode="Markdown")

@check_user
async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current running agent task."""
    global active_task, current_task_desc
    if active_task and not active_task.done():
        await update.message.reply_text("⏳ Cancelling the running agent task...")
        active_task.cancel()
        try:
            await active_task
        except asyncio.CancelledError:
            pass
        active_task = None
        current_task_desc = None
        await update.message.reply_text("🛑 Agent task cancelled successfully.")
    else:
        await update.message.reply_text("⚠️ No active agent task is running.")

@check_user
async def handle_dir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays or changes the WORK_DIR configuration."""
    if not context.args:
        await update.message.reply_text(f"📁 Current WORK_DIR: `{config.WORK_DIR}`", parse_mode="Markdown")
        return
        
    new_path = " ".join(context.args)
    resolved = os.path.abspath(os.path.expanduser(new_path))
    if not os.path.exists(resolved):
        await update.message.reply_text(f"❌ Directory does not exist: `{new_path}`")
        return
        
    if not os.path.isdir(resolved):
        await update.message.reply_text(f"❌ Path is not a directory: `{new_path}`")
        return
        
    if config.update_work_dir(resolved):
        await update.message.reply_text(f"📁 WORK_DIR updated to: `{config.WORK_DIR}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to update WORK_DIR.")

def find_pending_secret_request() -> tuple[str, approval.ApprovalRequest] | None:
    """Finds a pending approval request that is waiting for secret input."""
    for req_id, req in list(approval.pending.items()):
        if req.approval_type == "secret_input" and not req.event.is_set():
            return req_id, req
    return None

async def run_agent_flow(task_text: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asynchronous wrapper that manages status and approval callbacks during agent execution."""
    global active_task, current_task_desc
    chat_id = update.effective_chat.id
    
    async def status_callback(text: str):
        try:
            for chunk in split_text(text, 4000):
                await context.bot.send_message(chat_id=chat_id, text=chunk)
        except Exception as e:
            logger.error(f"Error sending message callback: {e}")

    async def approval_callback(action: str, reason: str, approval_type: str) -> str:
        req_id = str(uuid.uuid4())[:8]
        req = approval.ApprovalRequest(
            action=action,
            reason=reason,
            approval_type=approval_type
        )
        approval.pending[req_id] = req
        
        if approval_type == "confirm":
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{req_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ *Approval Required*\n\n*Action:* {action}\n*Reason:* {reason}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            req.message_id = msg.message_id
        else:  # secret_input
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔑 *Secret Input Required*\n\n*Action:* {action}\n*Reason:* {reason}\n\n_Please send the secret in your next message. It will be deleted immediately._",
                parse_mode="Markdown"
            )
            req.message_id = msg.message_id
            
        result = await approval.wait_for_approval(req_id, timeout=300)
        
        # Clean up the inline keyboard / message
        try:
            if result == "approved":
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=req.message_id,
                    text=f"✅ Approved: {action}"
                )
            elif result == "rejected" or result is None:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=req.message_id,
                    text=f"❌ Rejected/Timed out: {action}"
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=req.message_id,
                    text=f"🔒 Secret Input Captured: {action}"
                )
        except Exception as e:
            logger.error(f"Failed to update approval message display: {e}")
            
        return result or "rejected"

    try:
        await run_agent(task_text, status_callback, approval_callback)
    except asyncio.CancelledError:
        logger.info("Agent execution cancelled via CancelledError.")
        await context.bot.send_message(chat_id=chat_id, text="🛑 Task execution cancelled.")
        raise
    except Exception as e:
        logger.error(f"Unhandled error in agent execution: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Execution failed: {str(e)}")
    finally:
        active_task = None
        current_task_desc = None

@check_user
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes either text tasks or captures secret inputs if requested."""
    global active_task, current_task_desc
    
    # 1. Check if there's a pending secret input request
    pending_secret = find_pending_secret_request()
    if pending_secret:
        req_id, req = pending_secret
        secret_val = update.message.text
        req.result = secret_val
        req.event.set()
        
        # Immediately delete the message containing the secret
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        except Exception as e:
            logger.error(f"Could not delete message containing secret: {e}")
            
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🔒 Secret captured and message deleted.")
        return

    # 2. Otherwise treat it as a new coding task
    if active_task and not active_task.done():
        await update.message.reply_text(
            f"⚠️ *Agent is busy!*\nWorking on: {current_task_desc}\nPlease wait or run /cancel to abort.",
            parse_mode="Markdown"
        )
        return
        
    task_text = update.message.text
    current_task_desc = task_text
    
    await update.message.reply_text(f"🔄 *Starting agent for:* {task_text}\n_Reporting updates shortly..._", parse_mode="Markdown")
    
    # Start agent in background task to keep bot fully responsive
    active_task = asyncio.create_task(run_agent_flow(task_text, update, context))

@check_user
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline keyboard responses (approve/reject buttons)."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("approve_"):
        req_id = data.replace("approve_", "")
        if req_id in approval.pending:
            req = approval.pending[req_id]
            req.result = "approved"
            req.event.set()
    elif data.startswith("reject_"):
        req_id = data.replace("reject_", "")
        if req_id in approval.pending:
            req = approval.pending[req_id]
            req.result = "rejected"
            req.event.set()

def main():
    """Starts the bot application."""
    if not config.TELEGRAM_TOKEN:
        logger.critical("TELEGRAM_TOKEN environment variable is not set. Exiting.")
        return

    if config.ALLOWED_USER_ID is None:
        logger.critical("ALLOWED_USER_ID environment variable is missing or invalid. Exiting.")
        return

    logger.info("Initializing AgentBot Telegram application...")
    application = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("status", handle_status))
    application.add_handler(CommandHandler("cancel", handle_cancel))
    application.add_handler(CommandHandler("dir", handle_dir))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    logger.info("Telegram Bot starts polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
