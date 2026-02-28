"""Configuration loader for db-adapter.

Loads database profiles from a TOML configuration file (db.toml).
The config file is expected in the consuming project's working directory.

Usage:
    >>> from db_adapter.config.loader import load_db_config
    >>> config = load_db_config()  # reads ./db.toml
    >>> config = load_db_config(Path("/path/to/db.toml"))
"""

import tomllib
from pathlib import Path

from db_adapter.config.models import DatabaseConfig, DatabaseProfile


def load_db_config(config_path: Path | None = None) -> DatabaseConfig:
    """Load database configuration from TOML file.

    Args:
        config_path: Path to db.toml. Defaults to ``Path.cwd() / "db.toml"``
            so the library reads config from the consuming project's working
            directory, not from inside the installed package.

    Returns:
        DatabaseConfig with all profiles.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config format is invalid.
    """
    if config_path is None:
        config_path = Path.cwd() / "db.toml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Database config not found: {config_path}\n"
            f"Copy db.toml.example to db.toml and configure your profiles."
        )

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Parse profiles
    profiles: dict[str, DatabaseProfile] = {}
    for name, profile_data in data.get("profiles", {}).items():
        profiles[name] = DatabaseProfile(**profile_data)

    # Parse schema settings
    schema_settings: dict = data.get("schema", {})

    return DatabaseConfig(
        profiles=profiles,
        schema_file=schema_settings.get("file", "schema.sql"),
        validate_on_connect=schema_settings.get("validate_on_connect", True),
    )
