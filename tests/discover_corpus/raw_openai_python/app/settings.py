import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    model: str = os.environ.get("SUPPORT_MODEL", "gpt-4o-mini")
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./shop.db")
    feedback_db_path: str = os.environ.get("FEEDBACK_DB", "./feedback.db")
    fx_api_base: str = os.environ.get("FX_API_BASE", "https://api.frankfurter.app")
    max_turns: int = int(os.environ.get("MAX_TOOL_TURNS", "8"))


settings = Settings()
