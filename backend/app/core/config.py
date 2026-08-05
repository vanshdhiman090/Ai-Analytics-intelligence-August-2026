"""
Core config — reads from environment / .env file.
LLM provider is swappable (Section 3.5 of master plan): change LLM_PROVIDER
without touching any agent logic.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    def validate(self):
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if self.LLM_PROVIDER == "gemini" and not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}. Check your .env file.")


settings = Settings()
