import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Setup logging
LOG_FILE = os.getenv("LOG_FILE", "agent_bot.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)
logger = logging.getLogger("agent_bot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID_STR = os.getenv("ALLOWED_USER_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "any")

if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN is missing from environment variables!")
if not ALLOWED_USER_ID_STR:
    logger.error("ALLOWED_USER_ID is missing from environment variables!")
if not ANTHROPIC_API_KEY and not OPENAI_API_BASE:
    logger.error("Neither ANTHROPIC_API_KEY nor OPENAI_API_BASE is set in environment variables!")

try:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID_STR) if ALLOWED_USER_ID_STR else None
except ValueError:
    logger.error(f"ALLOWED_USER_ID must be an integer, got: {ALLOWED_USER_ID_STR}")
    ALLOWED_USER_ID = None

# Defaults
raw_work_dir = os.getenv("WORK_DIR", "~/projects")
WORK_DIR = os.path.abspath(os.path.expanduser(raw_work_dir))

# Ensure WORK_DIR exists
os.makedirs(WORK_DIR, exist_ok=True)
logger.info(f"WORK_DIR set to: {WORK_DIR}")

MODEL = os.getenv("MODEL", "claude-3-5-sonnet-20241022")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

# Passcode verification state
IS_AUTHORIZED = False
PASSCODE = None


def update_work_dir(new_path: str) -> bool:
    """Updates the WORK_DIR dynamically if path exists."""
    global WORK_DIR
    resolved_path = os.path.abspath(os.path.expanduser(new_path))
    if os.path.isdir(resolved_path):
        WORK_DIR = resolved_path
        logger.info(f"WORK_DIR dynamically updated to: {WORK_DIR}")
        return True
    return False
