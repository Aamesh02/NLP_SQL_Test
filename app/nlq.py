import json
import logging
import re
import time
from pathlib import Path

from openai import AsyncOpenAI

from config import get_settings
from app.db import run_query
from app.exceptions import SQLGenerationError, SQLExecutionError


logger = logging.getLogger("nlq")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

SQL_PROMPT_JSON_PATH = Path(__file__).resolve().parent.parent / "prompts" / "nl_to_sql.json"
SCHEMA_JSON_PATH = Path(__file__).resolve().parent.parent / "prompts" / "schema.json"


def _load_prompt_config(path: Path) -> dict:
    if not path.exists():
        raise SQLGenerationError("Prompt config file not found.", detail=str(path))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SQLGenerationError("Failed to parse prompt config JSON.", detail=str(e)) from e


def _load_schema_text() -> str:
    """
    Load a human-readable schema description from schema.json if present.
    This file is expected to be written by scripts.check_db.py.
    """
    if not SCHEMA_JSON_PATH.exists():
        # Fallback: high-level description without exact columns
        return (
            "- meta_campaigns(meta_campaign_id, ...)\n"
            "- meta_adsets(adset_id, campaign_id, ...)\n"
            "- meta_ads(ad_id, adset_id, ...)\n"
            "- meta_insight(date, campaign_id, adset_id, ad_id, impressions, clicks, spend, ...)\n"
            "- meta_insight_age_gender(date, age, gender, impressions, clicks, spend, ...)\n"
            "- meta_insight_region(date, region, impressions, clicks, spend, ...)"
        )

    try:
        raw = json.loads(SCHEMA_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        # If schema.json is corrupt, fall back to generic description
        return (
            f"(schema.json could not be parsed: {e})\n"
            "- meta_campaigns(...)\n"
            "- meta_adsets(...)\n"
            "- meta_ads(...)\n"
            "- meta_insight(...)\n"
            "- meta_insight_age_gender(...)\n"
            "- meta_insight_region(...)"
        )

    tables = raw.get("tables", {})
    lines: list[str] = []
    for table_name, info in tables.items():
        cols = info.get("columns", [])
        col_parts = []
        for c in cols:
            col_name = c.get("name")
            col_type = c.get("type")
            nullable = c.get("nullable")
            if col_name:
                piece = col_name
                if col_type:
                    piece += f" {col_type}"
                if nullable is not None:
                    piece += " NULL" if nullable else " NOT NULL"
                col_parts.append(piece)
        if col_parts:
            lines.append(f"- {table_name}(" + ", ".join(col_parts) + ")")
        else:
            lines.append(f"- {table_name}(...)")

    return "\n".join(lines)


def _build_messages(question: str) -> tuple[list[dict], str]:
    cfg = _load_prompt_config(SQL_PROMPT_JSON_PATH)
    system_prompt = cfg.get("system", "").strip()
    user_template = cfg.get("user_template", "").strip()
    if not system_prompt or not user_template:
        raise SQLGenerationError("Prompt config JSON must contain 'system' and 'user_template' keys.")

    schema_text = _load_schema_text()
    user_prompt = (
        user_template.replace("{{question}}", question.strip())
        .replace("{{schema}}", schema_text)
        .strip()
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return messages, user_prompt


def _extract_sql(raw: str) -> str:
    raw = raw.strip()
    # Remove markdown code block if present
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


def _is_read_only(sql: str) -> bool:
    normalized = sql.upper().strip()
    # Must start with SELECT or WITH (for CTEs)
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        return False

    # Disallow any DML/DDL keywords anywhere in the query
    forbidden = [
        " INSERT ",
        " UPDATE ",
        " DELETE ",
        " ALTER ",
        " DROP ",
        " CREATE ",
        " TRUNCATE ",
        " MERGE ",
        " GRANT ",
        " REVOKE ",
    ]
    padded = f" {normalized} "
    if any(word in padded for word in forbidden):
        return False

    # Disallow multiple statements separated by semicolons
    stripped = normalized.strip()
    if ";" in stripped[:-1]:
        return False

    return True


async def ask(question: str) -> dict:
    """Turn a question into SQL, run it, and return rows."""
    settings = get_settings()
    started_at = time.perf_counter()
    logger.info("Received NL question: %s", question)
    if not settings.openai_api_key:
        raise SQLGenerationError("OpenAI API key not configured.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # First stage: generate SQL OR a plain-text non-data message (same model does both).
    messages, _ = _build_messages(question)

    try:
        logger.info("Calling GPT-4o mini to generate SQL.")
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            max_tokens=500,
        )
    except Exception as e:
        logger.exception("LLM call for SQL generation failed.")
        raise SQLGenerationError("Failed to generate SQL.", detail=str(e)) from e

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise SQLGenerationError("Model returned empty content.")

    sql_stage_seconds = time.perf_counter() - started_at
    logger.info("SQL/explanation stage took %.3f seconds.", sql_stage_seconds)

    # Decide if the model returned SQL or a plain explanation.
    leading = content.lstrip()
    upper_leading = leading.upper()
    is_sql = upper_leading.startswith("SELECT") or upper_leading.startswith("WITH") or leading.startswith("```")

    if not is_sql:
        logger.info("Model returned a non-SQL explanation instead of SQL.")
        raise SQLGenerationError(
            "Question cannot be answered from this reporting schema.",
            detail=content,
        )

    # Extract and validate SQL
    sql = _extract_sql(content)
    logger.info("Generated SQL: %s", sql)
    if not _is_read_only(sql):
        raise SQLGenerationError("Generated SQL is not read-only (only SELECT/WITH allowed).", detail=sql)

    db_started_at = time.perf_counter()
    try:
        logger.info("Running SQL against database.")
        rows = await run_query(sql)
        db_seconds = time.perf_counter() - db_started_at
        logger.info("DB query took %.3f seconds and returned %d rows.", db_seconds, len(rows))
    except SQLExecutionError as e:
        logger.exception("SQL execution failed for SQL: %s", sql)
        raise

    elapsed = time.perf_counter() - started_at
    logger.info("End-to-end pipeline took %.3f seconds.", elapsed)
    return {
        "sql": sql,
        "rows": rows,
        "elapsed_seconds": elapsed,
    }
