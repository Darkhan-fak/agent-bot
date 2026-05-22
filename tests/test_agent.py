import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agent_bot.agent import get_openai_completion

@pytest.mark.asyncio
async def test_get_openai_completion():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "let me call a tool"},
            {"type": "tool_use", "id": "call_123", "name": "run_command", "input": {"command": "echo hello"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_123", "content": "hello"}
        ]}
    ]
    
    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "done",
                    "tool_calls": []
                },
                "finish_reason": "stop"
            }
        ]
    }
    
    with patch("agent_bot.config.OPENAI_API_BASE", "https://mock.api/v1"), \
         patch("agent_bot.config.MODEL", "gemma4:latest"), \
         patch("agent_bot.config.MAX_TOKENS", 4096), \
         patch("agent_bot.config.OPENAI_API_KEY", "mockkey"):
        
        mock_response = MagicMock()
        mock_response.json.return_value = mock_resp_data
        mock_response.raise_for_status = MagicMock()
        
        mock_post = AsyncMock(return_value=mock_response)
        
        with patch("httpx.AsyncClient.post", mock_post):
            res = await get_openai_completion(messages, "You are a system prompt")
            
            assert res.stop_reason == "end_turn"
            assert len(res.content) == 1
            assert res.content[0].type == "text"
            assert res.content[0].text == "done"
            
            mock_post.assert_called_once()
            _, call_kwargs = mock_post.call_args
            payload = call_kwargs["json"]
            assert payload["model"] == "gemma4:latest"
            assert payload["messages"][0] == {"role": "system", "content": "You are a system prompt"}
            assert payload["messages"][1] == {"role": "user", "content": "hello"}
            assert payload["messages"][2]["role"] == "assistant"
            assert payload["messages"][2]["content"] == "let me call a tool"
            assert payload["messages"][2]["tool_calls"][0]["id"] == "call_123"
            assert payload["messages"][3] == {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "run_command",
                "content": "hello"
            }
