"""Configuration management: profiles, TOML loading, and config models.

Usage:
    >>> from db_adapter.config import load_db_config, DatabaseProfile, DatabaseConfig
"""

from db_adapter.config.loader import load_db_config
from db_adapter.config.models import DatabaseConfig, DatabaseProfile

__all__ = ["load_db_config", "DatabaseConfig", "DatabaseProfile"]
