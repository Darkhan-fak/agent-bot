import json
import logging
import httpx
from anthropic import AsyncAnthropic
from agent_bot import config, tools

logger = logging.getLogger("agent_bot.agent")

class MockBlock:
    def __init__(self, block_type, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason

async def get_openai_completion(messages: list, system_prompt: str) -> MockResponse:
    """
    Translates Anthropic-formatted messages and tools schemas into OpenAI-compatible format,
    sends request to config.OPENAI_API_BASE, and maps responses back to Anthropic structures.
    """
    openai_messages = []
    
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
        
    tool_id_to_name = {}
    
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        
        if role == "user":
            if isinstance(content, str):
                openai_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        tool_use_id = block["tool_use_id"]
                        tool_name = tool_id_to_name.get(tool_use_id, "unknown")
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_use_id,
                            "name": tool_name,
                            "content": block.get("content", "")
                        })
                    else:
                        openai_messages.append({"role": "user", "content": str(block)})
        elif role == "assistant":
            if isinstance(content, str):
                openai_messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                openai_msg = {"role": "assistant"}
                text_parts = []
                tool_calls = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_id = block["id"]
                        t_name = block["name"]
                        tool_id_to_name[tool_id] = t_name
                        tool_calls.append({
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": t_name,
                                "arguments": json.dumps(block["input"])
                            }
                        })
                if text_parts:
                    openai_msg["content"] = "\n".join(text_parts)
                if tool_calls:
                    openai_msg["tool_calls"] = tool_calls
                openai_messages.append(openai_msg)

    openai_tools = []
    for t in tools.TOOLS_SCHEMA:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"]
            }
        })
        
    payload = {
        "model": config.MODEL,
        "messages": openai_messages,
        "tools": openai_tools,
        "max_tokens": config.MAX_TOKENS
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    if config.OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {config.OPENAI_API_KEY}"
        
    logger.info(f"Sending payload to OpenAI base {config.OPENAI_API_BASE}: {json.dumps(payload, ensure_ascii=False)[:300]}...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{config.OPENAI_API_BASE.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        resp_data = response.json()
        
    choice = resp_data["choices"][0]
    message = choice["message"]
    finish_reason = choice.get("finish_reason")
    
    content_blocks = []
    
    text_content = message.get("content")
    if text_content:
        content_blocks.append(MockBlock("text", text=text_content))
        
    tool_calls = message.get("tool_calls", [])
    for tc in tool_calls:
        tc_id = tc["id"]
        tc_name = tc["function"]["name"]
        tc_args_str = tc["function"]["arguments"]
        
        # In some providers, the arguments might already be a dict/object
        if isinstance(tc_args_str, str):
            try:
                tc_args = json.loads(tc_args_str)
            except Exception:
                tc_args = tc_args_str
        else:
            tc_args = tc_args_str
            
        content_blocks.append(MockBlock("tool_use", id=tc_id, name=tc_name, input=tc_args))
        
    stop_reason = "end_turn"
    if finish_reason == "tool_calls" or tool_calls:
        stop_reason = "tool_use"
        
    return MockResponse(content_blocks, stop_reason)


async def run_agent(task: str, status_callback, approval_callback) -> str:
    """
    Main asynchronous agent loop that communicates with Anthropic Claude or OpenAI-compatible backend.
    Keeps conversation history, parses tool calls, executes them, and feeds responses back.
    """
    if not config.ANTHROPIC_API_KEY and not config.OPENAI_API_BASE:
        error_msg = "Neither ANTHROPIC_API_KEY nor OPENAI_API_BASE is set in environment variables!"
        await status_callback(f"❌ {error_msg}")
        return error_msg

    if not config.OPENAI_API_BASE:
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    else:
        client = None
    
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
            logger.info("Sending request to LLM API...")
            if client:
                response = await client.messages.create(
                    model=config.MODEL,
                    max_tokens=config.MAX_TOKENS,
                    system=system_prompt,
                    messages=messages,
                    tools=tools.TOOLS_SCHEMA
                )
            else:
                response = await get_openai_completion(messages, system_prompt)
        except Exception as e:
            error_msg = f"LLM API Error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await status_callback(f"❌ {error_msg}")
            return error_msg

        logger.info(f"Received response from LLM. Stop reason: {response.stop_reason}")

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
