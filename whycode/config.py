"""Settings loaded from .env (or the process environment).

Errors name the offending variable and never include its value: pydantic's own
ValidationError text echoes inputs, so it is replaced, not wrapped.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid. Message holds names only."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # an empty value counts as missing
        extra="ignore",
        case_sensitive=False,
    )

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: SecretStr
    neo4j_database: str

    gemini_api_key: SecretStr
    groq_api_key: SecretStr
    gemini_model: str
    groq_model: str
    llm_max_calls: int = Field(ge=0)

    github_token: SecretStr
    postgres_dsn: SecretStr


def load_settings(**overrides) -> Settings:
    """Build Settings, turning validation errors into a ConfigError that names variables only."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing, invalid = [], []
        for err in exc.errors():
            name = str(err["loc"][0]).upper() if err["loc"] else "?"
            (missing if err["type"] == "missing" else invalid).append(name)
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(sorted(set(missing))))
        if invalid:
            parts.append("invalid value for: " + ", ".join(sorted(set(invalid))))
        msg = "Configuration error (" + "; ".join(parts) + "). Set these in .env; see .env.example."
        raise ConfigError(msg) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, loaded on first use so imports never require a .env."""
    return load_settings()
