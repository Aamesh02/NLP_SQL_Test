import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# so we can import app and config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import aiomysql
from config import get_settings


TABLES = [
    "meta_adsets",
    "meta_ads",
    "meta_campaigns",
    "meta_insight",
    "meta_insight_age_gender",
    "meta_insight_region",
]


def _mysql_params_from_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError(f"Expected mysql URL, got scheme '{parsed.scheme}'")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": (parsed.path or "/").lstrip("/"),
        "charset": "utf8mb4",
    }


async def main() -> None:
    settings = get_settings()
    url = settings.get_database_url()
    if not url:
        print("ERROR: Set DATABASE_URL (or DB_HOST, DB_USERNAME, DB_PASSWORD, DB_NAME) in .env")
        sys.exit(1)

    try:
        params = _mysql_params_from_url(url)
        conn = await aiomysql.connect(**params)
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    schema_data: dict = {"tables": {}}

    async with conn.cursor() as cur:
        print("=== Schema (columns per table) ===\n")
        for table in TABLES:
            try:
                await cur.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )
                rows = await cur.fetchall()
                if not rows:
                    print(f"  {table}: (not found or no columns)\n")
                    continue
                print(f"  {table}")
                cols_for_table = []
                for col_name, data_type, is_nullable in rows:
                    print(f"    - {col_name}: {data_type} (nullable: {is_nullable})")
                    cols_for_table.append(
                        {
                            "name": col_name,
                            "type": data_type,
                            "nullable": (str(is_nullable).upper() == "YES"),
                        }
                    )
                schema_data["tables"][table] = {"columns": cols_for_table}
                print()
            except Exception as e:
                print(f"  {table}: error - {e}\n")

        print("=== Table sizes (approximate row counts) ===\n")
        for table in TABLES:
            try:
                await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
                (n,) = await cur.fetchone()
                print(f"  {table}: {n:,} rows")
                if table in schema_data["tables"]:
                    schema_data["tables"][table]["row_count"] = int(n)
            except Exception as e:
                print(f"  {table}: error - {e}")

    conn.close()

    # Write schema to JSON for the NLQ prompt to consume
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    schema_path = prompts_dir / "schema.json"
    schema_path.write_text(json.dumps(schema_data, indent=2), encoding="utf-8")
    print(f"\nWrote schema to {schema_path}")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
