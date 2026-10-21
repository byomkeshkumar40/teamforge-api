from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application settings, read from environment variables (and a local .env file).

    Real environment variables always take priority over the .env file.
    """

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_name: str = "TeamForge API"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    # Swagger UI / ReDoc / openapi.json. Consider turning off for public deployments.
    enable_api_docs: bool = True

    postgres_user: str = "teamforge"
    postgres_password: SecretStr
    postgres_db: str = "teamforge"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)

    invitation_expire_hours: int = Field(default=72, gt=0)
    # Development convenience: return the raw invitation token once, in the
    # "create invitation" response. Refused at startup when APP_ENV=production.
    expose_invitation_tokens: bool = False

    @model_validator(mode="after")
    def _forbid_token_exposure_in_production(self) -> "Settings":
        if self.app_env == "production" and self.expose_invitation_tokens:
            raise ValueError("EXPOSE_INVITATION_TOKENS must be false when APP_ENV=production")
        return self

    @property
    def sqlalchemy_url(self) -> URL:
        # URL.create escapes special characters in the password safely.
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
