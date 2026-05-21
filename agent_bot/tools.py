import os
import asyncio
import pathlib
import re
from pathlib import Path
from agent_bot import config

TOOLS_SCHEMA = [
    {
        "name": "run_command",
        "description": "Execute shell command in WORK_DIR. For: tests, git, install, build. NOT for deploy or secrets — use request_approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read file contents. Returns text content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from WORK_DIR"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write or overwrite a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from WORK_DIR"},
                "content": {"type": "string", "description": "Full file content"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_files",
        "description": "List directory contents recursively (max depth 2).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from WORK_DIR", "default": "."}
            }
        }
    },
    {
        "name": "request_approval",
        "description": "Ask user for approval before dangerous actions: deploy, delete, secret input. Bot sends inline keyboard, waits for user tap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "What needs approval"},
                "reason": {"type": "string", "description": "Why this action is needed"},
                "approval_type": {
                    "type": "string",
                    "enum": ["confirm", "secret_input"],
                    "description": "confirm = yes/no buttons. secret_input = user types secret, message auto-deleted."
                }
            },
            "required": ["action", "reason", "approval_type"]
        }
    }
]

# FORBIDDEN COMMAND LIST (Case-insensitive matching)
FORBIDDEN_COMMANDS = [
    "rm -rf /", 
    "sudo", 
    "format", 
    "mkfs", 
    "dd if=",
    "rmdir /s",
    "del /f"
]

def verify_path_safe(path_str: str) -> str:
    """Verifies that the target path does not escape from the config.WORK_DIR."""
    resolved_work_dir = os.path.realpath(config.WORK_DIR)
    
    if os.path.isabs(path_str):
        resolved_target = os.path.realpath(path_str)
    else:
        resolved_target = os.path.realpath(os.path.join(resolved_work_dir, path_str))
        
    try:
        # Check if target_path is relative to (inside or equal to) resolved_work_dir
        Path(resolved_target).relative_to(Path(resolved_work_dir))
    except ValueError:
        raise PermissionError("Access denied: path is outside the workspace directory.")
        
    return resolved_target

def get_safe_env() -> dict:
    """Returns a copy of os.environ with sensitive environment variables filtered out."""
    safe_env = {}
    sensitive_keys = {"telegram_token", "anthropic_api_key", "allowed_user_id"}
    sensitive_keywords = {"token", "key", "secret", "password", "auth", "passcode"}
    for k, v in os.environ.items():
        k_lower = k.lower()
        if k_lower in sensitive_keys or any(kw in k_lower for kw in sensitive_keywords):
            continue
        safe_env[k] = v
    return safe_env

def check_redirections(command: str):
    """Parses command for redirection operators and verifies that targets are safe."""
    pattern = r'(?:\d+|\*|&)?(?:>>|>|<)\s*(?:"([^"]+)"|\'([^\']+)\'|([^\s&|;<>]+))'
    for match in re.finditer(pattern, command):
        target = match.group(1) or match.group(2) or match.group(3)
        if target:
            # Allow /dev/null and nul (case-insensitive) as safe targets
            if target.lower() in ("/dev/null", "nul"):
                continue
            # Check for env vars or shell expansion in target
            if any(char in target for char in ('$', '%', '`')):
                raise PermissionError("Access denied: Redirection to dynamic or environment-based paths is blocked.")
            # Verify target path safety
            verify_path_safe(target)

async def execute_run_command(command: str, timeout: int = 30) -> str:
    # Safety checks
    cmd_lower = command.lower()
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in cmd_lower:
            return f"Error: Command is blocked for safety. Found forbidden sequence: '{forbidden}'"
            
    try:
        check_redirections(command)
    except PermissionError as e:
        return f"Error: Command is blocked for safety. {str(e)}"

    try:
        # Filter env
        safe_env = get_safe_env()
        # Run process
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=config.WORK_DIR,
            env=safe_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace')
            return out[:3000]
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"

async def execute_read_file(path: str) -> str:
    try:
        safe_path = verify_path_safe(path)
        if not os.path.exists(safe_path):
            return f"Error: File not found: {path}"
        if not os.path.isfile(safe_path):
            return f"Error: Path is not a file: {path}"
            
        with open(safe_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        content_with_lines = "".join(f"{i+1}: {line}" for i, line in enumerate(lines))
        return content_with_lines[:5000]
    except Exception as e:
        return f"Error reading file: {str(e)}"

async def execute_write_file(path: str, content: str) -> str:
    try:
        safe_path = verify_path_safe(path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully written {len(content)} characters to {path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

async def execute_list_files(path: str = ".") -> str:
    try:
        safe_path = verify_path_safe(path)
        if not os.path.exists(safe_path):
            return f"Error: Path does not exist: {path}"
            
        output = []
        for root, dirs, files in os.walk(safe_path):
            # Filter directories in-place to control recursion
            dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__', '.venv', 'venv', '.pytest_cache']]
            
            rel_root = os.path.relpath(root, safe_path)
            if rel_root == ".":
                depth = 0
            else:
                depth = len(Path(rel_root).parts)
                
            if depth > 2:
                continue
            if depth == 2:
                dirs[:] = []  # stop traversing deeper
                
            indent = "  " * depth
            folder_name = os.path.basename(root) if rel_root != "." else "."
            output.append(f"{indent}📁 {folder_name}/")
            for file in files:
                output.append(f"{indent}  📄 {file}")
                
        return "\n".join(output)
    except Exception as e:
        return f"Error listing files: {str(e)}"
