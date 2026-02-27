"""Configuration management for Mission Control MCP."""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field

from creational.common.config import SharedSettings

from schema.models import DatabaseConfig, DatabaseProfile


class Settings(SharedSettings):
    """Application settings for Mission Control.

    Inherits from SharedSettings for auth credentials (Supabase URL/key).
    Data connections are handled separately via db.toml profiles.

    Separation of concerns:
    - SharedSettings: Auth & feedback (Supabase connection)
    - db.toml: Data connections (RDS/local profiles)
    """

    # Service identity
    service_slug: str = "mission-control-mcp"

    # Development mode
    dev_user_id: str = "7270cadc-1dea-457b-bb8e-d9708a867bdc"

    # Override supabase_key to accept multiple env var names
    supabase_key: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_KEY", "SUPABASE_SERVICE_KEY"),
    )

    # OAuth base URL - MC_BASE_URL takes precedence over BASE_URL
    # Allows MC and VP to have different base URLs in shared gateway container
    base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MC_BASE_URL", "BASE_URL"),
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_db_config(config_path: Path | None = None) -> DatabaseConfig:
    """Load database configuration from TOML file.

    Args:
        config_path: Path to db.toml (default: core/db.toml)

    Returns:
        DatabaseConfig with all profiles

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config format is invalid
    """
    if config_path is None:
        config_path = Path(__file__).parent / "db.toml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Database config not found: {config_path}\n"
            f"Copy db.toml.example to db.toml and configure your profiles."
        )

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Parse profiles
    profiles = {}
    for name, profile_data in data.get("profiles", {}).items():
        profiles[name] = DatabaseProfile(**profile_data)

    # Parse schema settings
    schema_settings = data.get("schema", {})

    return DatabaseConfig(
        profiles=profiles,
        schema_file=schema_settings.get("file", "schema.sql"),
        validate_on_connect=schema_settings.get("validate_on_connect", True),
    )
