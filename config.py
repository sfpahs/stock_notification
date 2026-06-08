import os
from pathlib import Path

# Base Directory of the Project
BASE_DIR = Path(__file__).resolve().parent

# Database Configuration
DATABASE_PATH = BASE_DIR / "alerts.db"

# Default settings values
DEFAULT_CHECK_INTERVAL = 60  # seconds (1 minute)
DEFAULT_TELEGRAM_TOKEN = ""
DEFAULT_TELEGRAM_CHAT_ID = ""
