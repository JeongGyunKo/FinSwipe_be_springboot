from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Gemini
    gemini_api_key: str

    # DB — asyncpg DSN (postgresql://user:pass@host:5432/dbname)
    # Spring Boot는 jdbc:postgresql://... 형식 — jdbc: 접두사를 자동으로 제거
    db_url: str
    db_username: str
    db_password: str
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Server
    port: int = 8000
    cors_origins: str = "*"

    # Gemini model
    gemini_model: str = "gemini-2.5-flash"

    @property
    def asyncpg_dsn(self) -> str:
        """JDBC URL 또는 plain postgresql:// URL을 asyncpg DSN으로 변환"""
        url = self.db_url
        if url.startswith("jdbc:"):
            url = url[5:]
        # credentials 없으면 주입
        if "@" not in url:
            url = url.replace(
                "postgresql://",
                f"postgresql://{self.db_username}:{self.db_password}@",
                1,
            )
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
