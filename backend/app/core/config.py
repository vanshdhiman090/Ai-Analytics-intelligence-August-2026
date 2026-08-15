"""
Core config — reads from environment / .env file.
LLM provider is swappable (Section 3.5 of master plan): change LLM_PROVIDER
without touching any agent logic.
"""

import math
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _environment_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


class Settings:
    DEPLOYMENT_MODE: str = os.environ.get("DEPLOYMENT_MODE", "development").strip().lower()
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
    # Bounded public portfolio mode. The backend owns this boundary; the
    # browser flag only controls presentation and cannot enable ingestion.
    RECRUITER_DEMO_MODE: bool = _environment_bool("RECRUITER_DEMO_MODE")
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
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}. Check your .env file.")
        if self.DEPLOYMENT_MODE not in {"development", "test", "controlled_pilot"}:
            raise RuntimeError("DEPLOYMENT_MODE must be 'development', 'test', or 'controlled_pilot'.")
        if not isinstance(self.RECRUITER_DEMO_MODE, bool):
            raise RuntimeError("RECRUITER_DEMO_MODE must be a boolean value.")
        if self.LLM_PROVIDER != "gemini":
            raise RuntimeError("LLM_PROVIDER must be 'gemini'.")
        if self.CHECKPOINT_BACKEND not in {"postgres", "memory"}:
            raise RuntimeError("CHECKPOINT_BACKEND must be 'postgres' or 'memory'.")
        positive_values = {
            "CHECKPOINT_POOL_SIZE": self.CHECKPOINT_POOL_SIZE,
            "RUN_WORKERS": self.RUN_WORKERS,
            "DB_POOL_SIZE": self.DB_POOL_SIZE,
            "MAX_UPLOAD_BYTES": self.MAX_UPLOAD_BYTES,
            "FILE_TTL_DAYS": self.FILE_TTL_DAYS,
        }
        invalid_positive = [name for name, value in positive_values.items() if value < 1]
        if invalid_positive:
            raise RuntimeError(f"Operational limits must be positive: {', '.join(invalid_positive)}.")
        if self.MAX_UPLOAD_BYTES > 2_147_483_647:
            raise RuntimeError("MAX_UPLOAD_BYTES must fit the dataset size storage boundary.")
        if not math.isfinite(self.GOOGLE_CONNECTOR_TIMEOUT_SECONDS) or not 0 < self.GOOGLE_CONNECTOR_TIMEOUT_SECONDS <= 300:
            raise RuntimeError("GOOGLE_CONNECTOR_TIMEOUT_SECONDS must be greater than 0 and no more than 300.")
        if self.CHECKPOINT_BACKEND == "postgres" and not self.DATABASE_URL.lower().startswith(("postgresql://", "postgresql+", "postgres://")):
            raise RuntimeError("CHECKPOINT_BACKEND=postgres requires a PostgreSQL DATABASE_URL.")
        if self.DATA_DIR == Path(self.DATA_DIR.anchor):
            raise RuntimeError("DATA_DIR must not be a filesystem root.")
        if not self.MEMORY_SCOPE:
            raise RuntimeError("MEMORY_SCOPE must not be empty.")
        if self.DEPLOYMENT_MODE == "controlled_pilot":
            if not self.API_KEYS:
                raise RuntimeError("controlled_pilot mode requires API_KEYS.")
            if any(len(key) < 16 for key in self.API_KEYS):
                raise RuntimeError("controlled_pilot API_KEYS must be at least 16 characters.")
            if not self.CORS_ORIGINS or any(origin == "*" for origin in self.CORS_ORIGINS):
                raise RuntimeError("controlled_pilot mode requires explicit CORS_ORIGINS without wildcards.")
            if self.MEMORY_SCOPE == "local-workspace":
                raise RuntimeError("controlled_pilot mode requires an explicit unique MEMORY_SCOPE.")


settings = Settings()
