from typing import Any
from urllib.parse import urlparse

import aiomysql

from config import get_settings
from app.exceptions import DatabaseConnectionError, SQLExecutionError

_pool: aiomysql.Pool | None = None


def _mysql_params() -> dict[str, Any]:
    url = get_settings().get_database_url()
    if not url:
        raise DatabaseConnectionError(
            "Database URL not set. Use DATABASE_URL or DB_HOST, DB_USERNAME, DB_PASSWORD, DB_NAME."
        )
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise DatabaseConnectionError(
            f"Expected a MySQL URL (mysql://), got scheme '{parsed.scheme}'."
        )
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": (parsed.path or "/").lstrip("/"),
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def get_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        try:
            params = _mysql_params()
            _pool = await aiomysql.create_pool(
                minsize=1,
                maxsize=10,
                **params,
            )
        except Exception as e:
            raise DatabaseConnectionError(
                "Failed to connect to the database.",
                detail=str(e),
            ) from e
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def run_query(sql: str, *args: Any) -> list[dict[str, Any]]:
    """Run a SELECT and return rows as dicts."""
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args or None)
                rows = await cur.fetchall()
                columns = [col[0] for col in cur.description] if cur.description else []
    except Exception as e:
        raise SQLExecutionError(
            "Query execution failed.",
            detail=str(e),
        ) from e

    if not rows or not columns:
        return []
    return [dict(zip(columns, row)) for row in rows]
