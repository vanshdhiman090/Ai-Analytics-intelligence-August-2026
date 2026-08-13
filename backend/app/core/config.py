"""
Core config — reads from environment / .env file.
LLM provider is swappable (Section 3.5 of master plan): change LLM_PROVIDER
without touching any agent logic.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    # gemini-2.0-flash-lite is the real free-tier model (gemini-3.1-flash-lite does not exist)
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")
    CHECKPOINT_BACKEND: str = os.environ.get("CHECKPOINT_BACKEND", "postgres").lower()
    CHECKPOINT_POOL_SIZE: int = int(os.environ.get("CHECKPOINT_POOL_SIZE", "4"))
    RUN_WORKERS: int = int(os.environ.get("RUN_WORKERS", "2"))
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "5"))
    DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "data")).resolve()
    MAX_UPLOAD_BYTES: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    # Comma-separated API keys for simple bearer auth. Empty = auth disabled (local dev).
    API_KEYS: set[str] = {
        k.strip()
        for k in os.environ.get("API_KEYS", "").split(",")
        if k.strip()
    }
    # Files older than this (days) whose session is complete/error are eligible for cleanup.
    FILE_TTL_DAYS: int = int(os.environ.get("FILE_TTL_DAYS", "7"))
    # Stable local namespace for cross-run learning memory. Deployments should
    # set this to a tenant/workspace identifier and never share it across tenants.
    MEMORY_SCOPE: str = os.environ.get("MEMORY_SCOPE", "local-workspace").strip()
    # Read-only Google Intelligence Connector Pack.  Tokens are process
    # configuration only; they are never persisted in the database or passed
    # into agent prompts.
    GOOGLE_ACCESS_TOKEN: str = os.environ.get("GOOGLE_ACCESS_TOKEN", "").strip()
    GOOGLE_REFRESH_TOKEN: str = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
    GOOGLE_OAUTH_CLIENT_ID: str = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    GOOGLE_CONNECTOR_TIMEOUT_SECONDS: float = float(os.environ.get("GOOGLE_CONNECTOR_TIMEOUT_SECONDS", "20"))
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3010,http://127.0.0.1:3010",
        ).split(",")
        if origin.strip()
    ]

    def validate(self):
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if self.LLM_PROVIDER == "gemini" and not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}. Check your .env file.")
        if self.CHECKPOINT_BACKEND not in {"postgres", "memory"}:
            raise RuntimeError("CHECKPOINT_BACKEND must be 'postgres' or 'memory'.")
        if self.CHECKPOINT_POOL_SIZE < 1 or self.RUN_WORKERS < 1 or self.DB_POOL_SIZE < 1:
            raise RuntimeError("Database/checkpoint pool sizes and run worker count must be positive.")
        if not self.MEMORY_SCOPE:
            raise RuntimeError("MEMORY_SCOPE must not be empty.")


settings = Settings()
