# config.py
"""
Централизованная загрузка переменных окружения.
Никаких .env — только os.getenv() и явные ошибки при их отсутствии.
"""

import os


def get_env_var(var_name: str, default: str = None) -> str:
    value = os.getenv(var_name, default)
    if value is None:
        raise ValueError(f"❌ Обязательная переменная окружения не задана: '{var_name}'")
    return value


# ——— TELEGRAM ———
TELEGRAM_MANAGER_BOT_TOKEN = get_env_var("TELEGRAM_MANAGER_BOT_TOKEN")
TELEGRAM_APPLICANT_BOT_TOKEN = get_env_var("TELEGRAM_APPLICANT_BOT_TOKEN")
BOT_FOR_APPLICANTS_USERNAME = get_env_var("BOT_FOR_APPLICANTS_USERNAME", "YourApplicantBot")

# ——— DATABASE ———
DATABASE_URL = get_env_var("DATABASE_URL")

# ——— HH.RU API ———
HH_CLIENT_ID = get_env_var("HH_CLIENT_ID")
HH_CLIENT_SECRET = get_env_var("HH_CLIENT_SECRET")
OAUTH_REDIRECT_URL = get_env_var("OAUTH_REDIRECT_URL")
USER_AGENT = get_env_var("USER_AGENT", "HR Screening Bot")

# ——— SECURITY ———
BOT_SHARED_SECRET = get_env_var("BOT_SHARED_SECRET")  # Должен быть длинным и случайным
ADMIN_ID = int(get_env_var("ADMIN_ID"))  # Telegram ID админа

# ——— PATHS ———
PROMPT_DIR = "prompts"
# For local development, use a relative path (./users_data)
# For production (Render), set USERS_DATA_DIR env var to /tmp/users_data
USERS_DATA_DIR = os.getenv("USERS_DATA_DIR", "./users_data")  # Default: local directory