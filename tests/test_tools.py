import os
import pytest
import tempfile
import shutil
import asyncio
from pathlib import Path
from agent_bot import config, tools

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

def test_verify_path_safe_valid():
    # Relative path
    safe_path = tools.verify_path_safe("subfolder/file.txt")
    assert safe_path.endswith(os.path.join("subfolder", "file.txt"))
    
    # Absolute path inside WORK_DIR
    absolute_safe = os.path.join(config.WORK_DIR, "another_sub", "file2.txt")
    resolved = tools.verify_path_safe(absolute_safe)
    assert resolved == os.path.abspath(absolute_safe)

def test_verify_path_safe_traversal():
    # Escaping via parent directory relative path
    with pytest.raises(PermissionError):
        tools.verify_path_safe("../escaped.txt")
        
    # Escaping via absolute path outside WORK_DIR
    # We use a system path that is guaranteed to be outside config.WORK_DIR (which is in temp folder)
    outside_path = "/etc/passwd" if os.name != "nt" else "C:\\Windows\\System32\\cmd.exe"
    # Make sure it's not somehow mapped to config.WORK_DIR
    with pytest.raises(PermissionError):
        tools.verify_path_safe(outside_path)

@pytest.mark.asyncio
async def test_execute_run_command_forbidden():
    # Test forbidden command blocking
    res = await tools.execute_run_command("sudo service nginx start")
    assert "Error: Command is blocked for safety" in res
    
    res = await tools.execute_run_command("rm -rf /")
    assert "Error: Command is blocked for safety" in res

    res = await tools.execute_run_command("format C:")
    assert "Error: Command is blocked for safety" in res

@pytest.mark.asyncio
async def test_execute_run_command_safe():
    # Test a safe command
    if os.name == "nt":
        res = await tools.execute_run_command("cmd.exe /c echo Hello World")
    else:
        res = await tools.execute_run_command("echo Hello World")
    assert "Hello World" in res
