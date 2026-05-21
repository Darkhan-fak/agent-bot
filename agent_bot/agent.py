import json
import logging
from anthropic import AsyncAnthropic
from agent_bot import config, tools

logger = logging.getLogger("agent_bot.agent")

async def run_agent(task: str, status_callback, approval_callback) -> str:
    """
    Main asynchronous agent loop that communicates with Anthropic Claude.
    Keeps conversation history, parses tool calls, executes them, and feeds responses back.
    """
    if not config.ANTHROPIC_API_KEY:
        error_msg = "Anthropic API Key is not set in config/environment!"
        await status_callback(f"❌ {error_msg}")
        return error_msg

    client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    
    system_prompt = (
        "You are a coding agent with access to the user's project directory.\n"
        "You can run commands, read/write files, and list directories.\n"
        "For dangerous actions (deploy, delete data, secret input), you MUST use the request_approval tool.\n"
        "Work autonomously. Report progress after each significant step.\n"
        "Keep responses concise — they go to Telegram (char limit)."
    )
    
    messages = [{"role": "user", "content": task}]
    
    await status_callback("🤖 Starting agent loop...")
    logger.info(f"Agent started with task: {task}")
    
    while True:
        try:
            logger.info("Sending request to Anthropic API...")
            response = await client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=tools.TOOLS_SCHEMA
            )
        except Exception as e:
            error_msg = f"Anthropic API Error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await status_callback(f"❌ {error_msg}")
            return error_msg

        logger.info(f"Received response from Anthropic. Stop reason: {response.stop_reason}")

        assistant_content = []
        tool_results_content = []
        
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                # Send text response to user
                await status_callback(block.text)
                
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })
                
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id
                
                await status_callback(f"🛠️ Calling tool: `{tool_name}`")
                logger.info(f"Executing tool {tool_name} (ID: {tool_use_id}) with inputs: {tool_input}")
                
                try:
                    if tool_name == "request_approval":
                        action = tool_input.get("action", "")
                        reason = tool_input.get("reason", "")
                        approval_type = tool_input.get("approval_type", "confirm")
                        
                        await status_callback(f"⚠️ Requesting approval: {action}")
                        result = await approval_callback(action, reason, approval_type)
                        tool_result = f"User decision/input: {result}"
                        
                    elif tool_name == "run_command":
                        cmd = tool_input.get("command")
                        timeout = tool_input.get("timeout", 30)
                        tool_result = await tools.execute_run_command(cmd, timeout)
                        
                    elif tool_name == "read_file":
                        path = tool_input.get("path")
                        tool_result = await tools.execute_read_file(path)
                        
                    elif tool_name == "write_file":
                        path = tool_input.get("path")
                        content = tool_input.get("content")
                        tool_result = await tools.execute_write_file(path, content)
                        
                    elif tool_name == "list_files":
                        path = tool_input.get("path", ".")
                        tool_result = await tools.execute_list_files(path)
                        
                    else:
                        tool_result = f"Error: Unknown tool '{tool_name}'"
                except Exception as e:
                    tool_result = f"Error executing tool: {str(e)}"
                    logger.error(f"Tool execution failed: {tool_result}", exc_info=True)
                
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result
                })
                
        # Append assistant message to context
        messages.append({
            "role": "assistant",
            "content": assistant_content
        })
        
        # If tools were used, append the results to history
        if tool_results_content:
            messages.append({
                "role": "user",
                "content": tool_results_content
            })
            
        if response.stop_reason == "end_turn":
            break

    logger.info("Agent task execution completed.")
    return "Agent completed task."
