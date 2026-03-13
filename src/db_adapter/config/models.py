"""Pydantic models for database configuration.

This module contains configuration-domain models only:
- DatabaseProfile: a single connection profile from db.toml
- DatabaseConfig: the full parsed db.toml structure

Introspection and validation models live in db_adapter.schema.models.
"""

from pydantic import BaseModel


class DatabaseProfile(BaseModel):
    """Database connection profile from db.toml.

    Example:
        >>> profile = DatabaseProfile(url="postgresql://localhost:5432/mydb")
        >>> profile.provider
        'postgres'
    """

    url: str
    description: str = ""
    db_password: str | None = None  # For [YOUR-PASSWORD] placeholder substitution
    provider: str = "postgres"  # Defaults to postgres


class DatabaseConfig(BaseModel):
    """Complete database configuration from db.toml.

    Example:
        >>> config = DatabaseConfig(profiles={"dev": DatabaseProfile(url="postgresql://localhost/dev")})
        >>> config.validate_on_connect
        True
        >>> config.column_defs is None
        True
    """

    profiles: dict[str, DatabaseProfile]
    schema_file: str = "schema.sql"
    validate_on_connect: bool = True

    # Config-driven CLI defaults (all optional for backward compatibility)
    column_defs: str | None = None
    backup_schema: str | None = None
    sync_tables: list[str] | None = None
    user_id_env: str | None = None
