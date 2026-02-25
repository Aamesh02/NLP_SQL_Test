from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    openai_api_key: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Optional overrides if you use separate host/user/pwd env vars
    db_host: Optional[str] = None
    db_username: Optional[str] = None
    db_password: Optional[str] = None
    db_name: Optional[str] = None

    def get_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if all([self.db_host, self.db_username, self.db_password, self.db_name]):
            from urllib.parse import quote_plus
            user = quote_plus(self.db_username)
            pwd = quote_plus(self.db_password)
            return f"mysql://{user}:{pwd}@{self.db_host}:3306/{self.db_name}"
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
