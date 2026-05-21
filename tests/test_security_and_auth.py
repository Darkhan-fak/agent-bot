import os
import pytest
import re
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
from agent_bot import config, tools, bot

class MockMessage:
    def __init__(self, text="", message_id=1):
        self.text = text
        self.message_id = message_id
        self.reply_text = AsyncMock()

class MockUpdate:
    def __init__(self, text="", is_command=False, args=None, user_id=None, message_id=1):
        self.effective_user = MagicMock()
        self.effective_user.id = user_id or config.ALLOWED_USER_ID
        self.message = MockMessage(text, message_id)
        self.callback_query = None

class MockContext:
    def __init__(self, args=None):
        self.args = args or []
        self.bot = MagicMock()

@pytest.fixture(autouse=True)
def setup_test_work_dir():
    # Setup temporary directory for WORK_DIR
    temp_dir = tempfile.mkdtemp()
    old_work_dir = config.WORK_DIR
    config.WORK_DIR = temp_dir
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)
    config.WORK_DIR = old_work_dir

def test_verify_path_safe_symlink_mock(monkeypatch):
    original_realpath = os.path.realpath
    
    # Target outside WORK_DIR
    outside_target = os.path.join(os.path.dirname(config.WORK_DIR), "outside_file.txt")
    bad_link_path = os.path.join(config.WORK_DIR, "bad_link")
    
    # Mock os.path.realpath to resolve bad_link_path to outside_target
    def mock_realpath(path):
        if path == bad_link_path:
            return original_realpath(outside_target)
        return original_realpath(path)
        
    monkeypatch.setattr(os.path, "realpath", mock_realpath)
    
    with pytest.raises(PermissionError):
        tools.verify_path_safe("bad_link")

def test_get_safe_env(monkeypatch):
    # Set up environment variables
    monkeypatch.setenv("TELEGRAM_TOKEN", "super-secret-telegram-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-secret-key")
    monkeypatch.setenv("ALLOWED_USER_ID", "12345")
    monkeypatch.setenv("SAFE_VAR", "safe_value")
    monkeypatch.setenv("SOME_PASSWORD", "mypassword")
    
    safe_env = tools.get_safe_env()
    
    # Verify sensitive variables are excluded
    assert "TELEGRAM_TOKEN" not in safe_env
    assert "ANTHROPIC_API_KEY" not in safe_env
    assert "ALLOWED_USER_ID" not in safe_env
    assert "SOME_PASSWORD" not in safe_env
    # Verify normal variable is preserved
    assert safe_env.get("SAFE_VAR") == "safe_value"

def test_check_redirections():
    # Test valid/safe redirections
    # Redirection to local file is fine (target is relative, verify_path_safe will resolve to inside WORK_DIR)
    tools.check_redirections("echo 'hello' > output.txt")
    tools.check_redirections("cat < input.txt")
    tools.check_redirections("echo 'hello' > /dev/null")
    tools.check_redirections("echo 'hello' > nul")
    tools.check_redirections("echo 'hello' 2>&1")  # No file path to verify
    
    # Test unsafe redirections
    outside_path = "/etc/passwd" if os.name != "nt" else "C:\\Windows\\System32\\cmd.exe"
    
    with pytest.raises(PermissionError):
        tools.check_redirections(f"echo 'hello' > {outside_path}")
        
    with pytest.raises(PermissionError):
        tools.check_redirections(f"cat < {outside_path}")

    # Redirection to env vars or dynamic targets should be blocked
    with pytest.raises(PermissionError):
        tools.check_redirections("echo 'hello' > $VAR")
        
    with pytest.raises(PermissionError):
        tools.check_redirections("echo 'hello' > %TEMP%\\test.txt")

    with pytest.raises(PermissionError):
        tools.check_redirections("echo 'hello' > `echo test`")

@pytest.mark.asyncio
async def test_auth_flow():
    # Save original settings
    orig_is_auth = config.IS_AUTHORIZED
    orig_passcode = config.PASSCODE
    orig_allowed = config.ALLOWED_USER_ID
    
    try:
        config.IS_AUTHORIZED = False
        config.PASSCODE = "1234"
        config.ALLOWED_USER_ID = 99999
        
        # 1. Attempt /start command when locked
        update = MockUpdate("/start", is_command=True, user_id=99999)
        context = MockContext()
        await bot.handle_start(update, context)
        update.message.reply_text.assert_called_with("🔒 Bot is locked. Please unlock by typing `/auth <code>`.")
        
        # 2. Attempt /auth with incorrect code
        update = MockUpdate("/auth 5555", is_command=True, user_id=99999)
        context = MockContext(args=["5555"])
        await bot.handle_auth(update, context)
        update.message.reply_text.assert_called_with("❌ Incorrect passcode. Access denied.")
        assert not config.IS_AUTHORIZED
        
        # 3. Attempt /auth with correct code
        update = MockUpdate("/auth 1234", is_command=True, user_id=99999)
        context = MockContext(args=["1234"])
        await bot.handle_auth(update, context)
        update.message.reply_text.assert_called_with("🔓 Bot successfully unlocked! Ready for tasks.")
        assert config.IS_AUTHORIZED
        
        # 4. Attempt /start command when unlocked
        update = MockUpdate("/start", is_command=True, user_id=99999)
        context = MockContext()
        await bot.handle_start(update, context)
        update.message.reply_text.assert_called_with(
            "🤖 *AgentBot ready.*\nSend me a coding task or check my status with /status.",
            parse_mode="Markdown"
        )
    finally:
        config.IS_AUTHORIZED = orig_is_auth
        config.PASSCODE = orig_passcode
        config.ALLOWED_USER_ID = orig_allowed
