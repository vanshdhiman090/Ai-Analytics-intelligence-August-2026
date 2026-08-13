"""Read-only SQL import for analysis snapshots.

Connection details are used for one request only and never stored in the
application database, logs, dataset name, or artifact metadata.
"""

from __future__ import annotations

import re
import uuid
from hashlib import sha256
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


class SqlSourceError(ValueError):
    pass


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|grant|revoke|copy|call|execute)\b", re.I)


def validate_read_only_query(query: str) -> str:
    cleaned = query.strip()
    if not cleaned or ";" in cleaned.rstrip(";") or not re.match(r"^(select|with)\b", cleaned, re.I) or _FORBIDDEN.search(cleaned):
        raise SqlSourceError("Use one read-only SELECT or WITH query. Data-changing SQL is not allowed.")
    return cleaned.rstrip(";")


def snapshot_sql_query(connection_url: str, query: str, data_dir: Path, limit: int = 100_000) -> tuple[Path, str]:
    if not re.match(r"^(sqlite|postgresql|postgres|mysql)(\+[\w]+)?://", connection_url, re.I):
        raise SqlSourceError("Supported connections are SQLite, PostgreSQL, and MySQL URLs.")
    safe_query = validate_read_only_query(query)
    engine = create_engine(connection_url, pool_pre_ping=True)
    try:
        frame = pd.read_sql_query(text(f"SELECT * FROM ({safe_query}) AS analytics_source LIMIT {int(limit)}"), engine)
    except Exception as exc:
        raise SqlSourceError("Could not read the SQL query. Check the connection, permissions, and query.") from exc
    finally:
        engine.dispose()
    if frame.empty:
        raise SqlSourceError("The query returned no rows.")
    destination = data_dir / "uploads" / f"sql-{uuid.uuid4()}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return destination, sha256(destination.read_bytes()).hexdigest()
