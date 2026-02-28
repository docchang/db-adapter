"""Database client factory (async).

Provides profile-based database adapter creation with schema validation.
All factory functions that perform I/O or create adapters are async.

Configuration uses db.toml profiles with a .db-profile lock file to persist
the validated profile selection. The factory reads config from the consuming
project's working directory.

Usage:
    from db_adapter.factory import get_adapter, connect_and_validate

    # Direct URL (simplest)
    adapter = await get_adapter(database_url="postgresql://user:pass@localhost/mydb")

    # Profile-based (reads db.toml + .db-profile)
    adapter = await get_adapter(profile_name="local")

    # Connect and validate schema first
    result = await connect_and_validate("local", expected_columns=my_expected)
    if result.success:
        adapter = await get_adapter(profile_name="local")
"""

import os
from pathlib import Path
from urllib.parse import quote

from db_adapter.adapters import AsyncPostgresAdapter, DatabaseClient
from db_adapter.config.loader import load_db_config
from db_adapter.schema.comparator import validate_schema
from db_adapter.schema.introspector import SchemaIntrospector
from db_adapter.schema.models import ConnectionResult
from db_adapter.config.models import DatabaseProfile


# Profile lock file path (in consuming project's working directory)
_PROFILE_LOCK_FILE = Path.cwd() / ".db-profile"


# ============================================================================
# Profile Lock File Operations
# ============================================================================


class ProfileNotFoundError(Exception):
    """Raised when no database profile is configured."""

    pass


def read_profile_lock() -> str | None:
    """Read profile name from lock file.

    Returns:
        Profile name if lock file exists, None otherwise.
    """
    if _PROFILE_LOCK_FILE.exists():
        return _PROFILE_LOCK_FILE.read_text().strip()
    return None


def write_profile_lock(profile_name: str) -> None:
    """Write profile name to lock file.

    Only call this after successful schema validation.

    Args:
        profile_name: Name of validated profile.
    """
    _PROFILE_LOCK_FILE.write_text(profile_name)


def clear_profile_lock() -> None:
    """Remove profile lock file."""
    if _PROFILE_LOCK_FILE.exists():
        _PROFILE_LOCK_FILE.unlink()


def get_active_profile_name(env_prefix: str = "") -> str:
    """Get active profile name from env var or lock file.

    Priority:
    1. ``{env_prefix}DB_PROFILE`` env var (for initial connect or CI/CD)
    2. ``.db-profile`` file (validated profile from previous connect)
    3. Raise ``ProfileNotFoundError``

    Args:
        env_prefix: Prefix for environment variable lookup.  When ``""``
            (default), reads ``DB_PROFILE``.  When ``"MC_"``, reads
            ``MC_DB_PROFILE``.

    Returns:
        Profile name.

    Raises:
        ProfileNotFoundError: If no profile is configured.

    Example:
        >>> # Reads DB_PROFILE env var
        >>> name = get_active_profile_name()
        >>> # Reads MC_DB_PROFILE env var
        >>> name = get_active_profile_name(env_prefix="MC_")
    """
    env_var = f"{env_prefix}DB_PROFILE"
    env_profile: str | None = os.environ.get(env_var)
    if env_profile:
        return env_profile

    # Check lock file
    lock_profile: str | None = read_profile_lock()
    if lock_profile:
        return lock_profile

    raise ProfileNotFoundError(
        "No database profile configured.\n"
        f"Run: {env_var}=<name> db-adapter connect\n"
        "Or set a profile in .db-profile lock file."
    )


def get_active_profile(
    env_prefix: str = "",
) -> tuple[str, DatabaseProfile]:
    """Get active profile name and configuration.

    Args:
        env_prefix: Prefix for environment variable lookup (forwarded to
            ``get_active_profile_name``).

    Returns:
        Tuple of ``(profile_name, DatabaseProfile)``.

    Raises:
        ProfileNotFoundError: If no profile configured.
        KeyError: If profile not found in db.toml.
    """
    profile_name: str = get_active_profile_name(env_prefix=env_prefix)
    config = load_db_config()

    if profile_name not in config.profiles:
        raise KeyError(
            f"Profile '{profile_name}' not found in db.toml.\n"
            f"Available profiles: {', '.join(config.profiles.keys())}"
        )

    return profile_name, config.profiles[profile_name]


# ============================================================================
# Connection and Validation
# ============================================================================


def resolve_url(profile: DatabaseProfile) -> str:
    """Resolve profile URL with password substitution.

    Replaces the ``[YOUR-PASSWORD]`` placeholder in the profile URL with
    the actual password from ``profile.db_password``, URL-encoded.

    Args:
        profile: Database profile from config.

    Returns:
        Connection URL with password substituted.

    Example:
        >>> from db_adapter.config.models import DatabaseProfile
        >>> p = DatabaseProfile(
        ...     url="postgresql://user:[YOUR-PASSWORD]@host/db",
        ...     db_password="s3cr3t",
        ... )
        >>> resolve_url(p)
        'postgresql://user:s3cr3t@host/db'
    """
    url: str = profile.url
    if profile.db_password and "[YOUR-PASSWORD]" in url:
        url = url.replace("[YOUR-PASSWORD]", quote(profile.db_password, safe=""))
    return url


async def connect_and_validate(
    profile_name: str | None = None,
    expected_columns: dict[str, set[str]] | None = None,
    env_prefix: str = "",
    validate_only: bool = False,
) -> ConnectionResult:
    """Connect to database and optionally validate schema.

    This is the primary setup API.  Call this once to validate and persist
    the profile selection.  Subsequent calls to ``get_adapter()`` will use
    the validated profile.

    When *expected_columns* is ``None``, schema validation is skipped
    (connection-only mode).  When provided, the live schema is introspected
    and compared against the expected columns.

    Args:
        profile_name: Profile name from db.toml.  If ``None``, uses
            ``{env_prefix}DB_PROFILE`` env var or existing ``.db-profile``
            lock file.
        expected_columns: Dict mapping table name to set of expected column
            names.  If ``None``, skip schema validation.
        env_prefix: Prefix for environment variable lookup.
        validate_only: If ``True``, only validate schema without writing
            lock file.  Used by schema fix command.

    Returns:
        ``ConnectionResult`` with success status and validation report.

    Example:
        >>> result = await connect_and_validate("local")
        >>> if result.success:
        ...     print(f"Connected to {result.profile_name}")
        ... else:
        ...     print(f"Failed: {result.error}")
    """
    # Resolve profile name
    if profile_name is None:
        try:
            profile_name = get_active_profile_name(env_prefix=env_prefix)
        except ProfileNotFoundError as e:
            return ConnectionResult(
                success=False,
                error=str(e),
            )

    # Load profile config
    try:
        config = load_db_config()
        if profile_name not in config.profiles:
            available: str = ", ".join(config.profiles.keys())
            return ConnectionResult(
                success=False,
                profile_name=profile_name,
                error=f"Profile '{profile_name}' not found. Available: {available}",
            )
        profile: DatabaseProfile = config.profiles[profile_name]
    except FileNotFoundError as e:
        return ConnectionResult(
            success=False,
            error=str(e),
        )

    # Get connection URL (handle password placeholder)
    introspect_url: str = resolve_url(profile)

    # If no expected_columns, skip validation (connection-only mode)
    if expected_columns is None:
        if not validate_only:
            write_profile_lock(profile_name)
        return ConnectionResult(
            success=True,
            profile_name=profile_name,
            schema_valid=None,
        )

    # Introspect live schema (get column names only)
    try:
        async with SchemaIntrospector(introspect_url) as introspector:
            actual_columns: dict[str, set[str]] = await introspector.get_column_names()
    except Exception as e:
        return ConnectionResult(
            success=False,
            profile_name=profile_name,
            error=f"Failed to connect to database: {e}",
        )

    # Validate schema (sync call -- comparator is pure logic)
    validation = validate_schema(actual_columns, expected_columns)

    # If valid, write profile lock (unless validate_only)
    if validation.valid:
        if not validate_only:
            write_profile_lock(profile_name)

        return ConnectionResult(
            success=True,
            profile_name=profile_name,
            schema_valid=True,
            schema_report=validation,
        )
    else:
        # Schema invalid - return report but don't write lock
        return ConnectionResult(
            success=False,
            profile_name=profile_name,
            schema_valid=False,
            schema_report=validation,
            error=f"Schema validation failed: {validation.error_count} errors",
        )


# ============================================================================
# Database Adapter Factory
# ============================================================================


async def get_adapter(
    profile_name: str | None = None,
    env_prefix: str = "",
    database_url: str | None = None,
    jsonb_columns: list[str] | None = None,
) -> DatabaseClient:
    """Create a database adapter.

    No caching -- creates a new adapter on each call.

    **Parameter precedence**:

    1. If *database_url* is provided, use it directly (ignore *profile_name*
       and *env_prefix*).
    2. If *database_url* is ``None``, resolve profile: use *profile_name* if
       given, otherwise resolve from lock file / env var with *env_prefix*.

    Args:
        profile_name: Profile name from db.toml.  Ignored when *database_url*
            is provided.
        env_prefix: Prefix for environment variable lookup.  Ignored when
            *database_url* is provided.
        database_url: Direct PostgreSQL connection URL.  Takes precedence
            over profile-based resolution.
        jsonb_columns: List of JSONB column names for serialization.

    Returns:
        ``DatabaseClient`` instance (currently ``AsyncPostgresAdapter``).

    Raises:
        ProfileNotFoundError: If no database configuration found.

    Example:
        >>> # Direct URL
        >>> adapter = await get_adapter(database_url="postgresql://user:pass@localhost/db")

        >>> # Profile-based
        >>> adapter = await get_adapter(profile_name="local")

        >>> # Env-var resolution with prefix
        >>> adapter = await get_adapter(env_prefix="MC_")
    """
    # Direct URL takes precedence
    if database_url is not None:
        return AsyncPostgresAdapter(
            database_url=database_url,
            jsonb_columns=jsonb_columns,
        )

    # Profile-based resolution
    if profile_name is not None:
        config = load_db_config()
        if profile_name not in config.profiles:
            available: str = ", ".join(config.profiles.keys())
            raise ProfileNotFoundError(
                f"Profile '{profile_name}' not found in db.toml. "
                f"Available: {available}"
            )
        profile: DatabaseProfile = config.profiles[profile_name]
        url: str = resolve_url(profile)
        return AsyncPostgresAdapter(
            database_url=url,
            jsonb_columns=jsonb_columns,
        )

    # Resolve from lock file / env var
    name, profile = get_active_profile(env_prefix=env_prefix)
    url = resolve_url(profile)
    return AsyncPostgresAdapter(
        database_url=url,
        jsonb_columns=jsonb_columns,
    )
