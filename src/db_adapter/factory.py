"""Database client factory.

Supports two configuration modes:
1. Profile mode (db.toml + .db-profile): Multi-database profiles with schema validation
2. Legacy mode (DATABASE_URL in .env): Single database connection for backwards compatibility
"""

import os
from pathlib import Path
from urllib.parse import quote

from fastmcp import Context

from adapters import DatabaseClient, PostgresAdapter
from config import get_settings, load_db_config
from schema.comparator import validate_schema
from schema.introspector import SchemaIntrospector
from schema.models import ConnectionResult, DatabaseProfile

# Adapter cache
_adapter: DatabaseClient | None = None

# Profile lock file path
_PROFILE_LOCK_FILE = Path(__file__).parent / ".db-profile"


# ============================================================================
# Profile Lock File Operations
# ============================================================================


class ProfileNotFoundError(Exception):
    """Raised when no database profile is configured."""

    pass


class AuthenticationError(Exception):
    """Raised when user authentication is missing or invalid."""

    pass


def read_profile_lock() -> str | None:
    """Read profile name from lock file.

    Returns:
        Profile name if lock file exists, None otherwise
    """
    if _PROFILE_LOCK_FILE.exists():
        return _PROFILE_LOCK_FILE.read_text().strip()
    return None


def write_profile_lock(profile_name: str) -> None:
    """Write profile name to lock file.

    Only call this after successful schema validation.

    Args:
        profile_name: Name of validated profile
    """
    _PROFILE_LOCK_FILE.write_text(profile_name)


def clear_profile_lock() -> None:
    """Remove profile lock file."""
    if _PROFILE_LOCK_FILE.exists():
        _PROFILE_LOCK_FILE.unlink()


def get_active_profile_name() -> str:
    """Get active profile name from env var or lock file.

    Priority:
    1. MC_DB_PROFILE env var (for initial connect or CI/CD)
    2. .db-profile file (validated profile from previous connect)
    3. Raise ProfileNotFoundError

    Returns:
        Profile name

    Raises:
        ProfileNotFoundError: If no profile is configured
    """
    # Check env var first
    env_profile = os.environ.get("MC_DB_PROFILE")
    if env_profile:
        return env_profile

    # Check lock file
    lock_profile = read_profile_lock()
    if lock_profile:
        return lock_profile

    raise ProfileNotFoundError(
        "No database profile configured.\n"
        "Run: MC_DB_PROFILE=<name> python -m schema connect\n"
        "Available profiles: rds, supabase, local, docker"
    )


def get_active_profile() -> tuple[str, DatabaseProfile]:
    """Get active profile name and configuration.

    Returns:
        Tuple of (profile_name, DatabaseProfile)

    Raises:
        ProfileNotFoundError: If no profile configured
        KeyError: If profile not found in db.toml
    """
    profile_name = get_active_profile_name()
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


def _resolve_url(profile: DatabaseProfile) -> str:
    """Resolve profile URL with password substitution.

    Args:
        profile: Database profile from config

    Returns:
        Connection URL with password substituted
    """
    url = profile.url
    if profile.db_password and "[YOUR-PASSWORD]" in url:
        url = url.replace("[YOUR-PASSWORD]", quote(profile.db_password, safe=""))
    return url


def connect_and_validate(
    profile_name: str | None = None,
    validate_only: bool = False,
) -> ConnectionResult:
    """Connect to database and validate schema.

    This is the primary setup API. Call this once to validate and persist
    the profile selection. Subsequent calls to get_db_adapter() will use
    the validated profile.

    Args:
        profile_name: Profile name from db.toml. If None, uses MC_DB_PROFILE
                     env var or existing .db-profile lock file.
        validate_only: If True, only validate schema without writing lock file
                      or creating adapter. Used by schema fix command.

    Returns:
        ConnectionResult with success status and validation report

    Example:
        >>> result = connect_and_validate("rds")
        >>> if result.success:
        ...     print(f"Connected to {result.profile_name}")
        ... else:
        ...     print(f"Failed: {result.error}")
    """
    global _adapter

    # Resolve profile name
    if profile_name is None:
        try:
            profile_name = get_active_profile_name()
        except ProfileNotFoundError as e:
            return ConnectionResult(
                success=False,
                error=str(e),
            )

    # Load profile config
    try:
        config = load_db_config()
        if profile_name not in config.profiles:
            available = ", ".join(config.profiles.keys())
            return ConnectionResult(
                success=False,
                profile_name=profile_name,
                error=f"Profile '{profile_name}' not found. Available: {available}",
            )
        profile = config.profiles[profile_name]
    except FileNotFoundError as e:
        return ConnectionResult(
            success=False,
            error=str(e),
        )

    # Get connection URL (handle password placeholder)
    introspect_url = _resolve_url(profile)

    # Introspect live schema (get column names only)
    try:
        with SchemaIntrospector(introspect_url) as introspector:
            actual_columns = introspector.get_column_names()
    except Exception as e:
        return ConnectionResult(
            success=False,
            profile_name=profile_name,
            error=f"Failed to connect to database: {e}",
        )

    # Validate schema using DB Models as source of truth
    validation = validate_schema(actual_columns)

    # If valid, write profile lock and create adapter (unless validate_only)
    if validation.valid:
        if not validate_only:
            write_profile_lock(profile_name)

            # Create adapter based on profile
            _adapter = PostgresAdapter(database_url=introspect_url)

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


def get_db_adapter() -> DatabaseClient:
    """Get database adapter based on configuration.

    Behavior depends on configuration mode:

    1. Profile mode (db.toml exists + .db-profile exists):
       Returns adapter for validated profile.

    2. Legacy mode (DATABASE_URL in .env):
       Returns adapter configured from DATABASE_URL.

    Returns:
        DatabaseClient instance (PostgresAdapter)

    Raises:
        ProfileNotFoundError: If no database configuration found

    Example:
        >>> adapter = get_db_adapter()
        >>> projects = adapter.select("projects", "*")
    """
    global _adapter
    if _adapter is not None:
        return _adapter

    # Check for profile mode (db.toml exists)
    db_toml_path = Path(__file__).parent / "db.toml"
    if db_toml_path.exists():
        # Profile mode - check for validated profile
        try:
            profile_name, profile = get_active_profile()
            introspect_url = _resolve_url(profile)
            _adapter = PostgresAdapter(database_url=introspect_url)
            return _adapter
        except ProfileNotFoundError:
            # Fall through to legacy mode if .env has DATABASE_URL
            pass

    # Legacy mode - use MC_DATABASE_URL from environment
    database_url = os.environ.get("MC_DATABASE_URL")
    if database_url:
        _adapter = PostgresAdapter(database_url=database_url)
        return _adapter

    # No configuration found
    raise ProfileNotFoundError(
        "No database configuration found.\n"
        "Either:\n"
        "  1. Create db.toml and run: MC_DB_PROFILE=<name> python -m schema connect\n"
        "  2. Set MC_DATABASE_URL in .env"
    )


def get_dev_user_id() -> str:
    """Get dev/test user ID from settings.

    Use this for utility scripts, test fixtures, and cleanup functions
    that operate outside MCP Context (e.g., seed scripts, backup/restore).

    For MCP tools, use get_user_id_from_ctx(ctx) instead.
    """
    settings = get_settings()
    return settings.dev_user_id


def get_user_id_from_ctx(ctx: Context) -> str:
    """Extract user_id from MCP Context.

    Uses FastMCP's auth context to get the authenticated user's ID.
    The DualTokenVerifier sets client_id to the user UUID for both
    JWT tokens (from 'sub' claim) and API tokens (from token_data.user_id).

    Args:
        ctx: FastMCP Context object

    Returns:
        User ID as string (consistent with database filters)

    Raises:
        AuthenticationError: If no authenticated user found
    """
    import logging

    from mcp.server.auth.middleware.auth_context import get_access_token

    logger = logging.getLogger(__name__)

    access_token = get_access_token()
    if access_token is not None and access_token.client_id:
        logger.debug(f"[MC Auth] User ID from access_token: {access_token.client_id}")
        return access_token.client_id

    # Fallback: try request.user (Starlette AuthenticationMiddleware)
    try:
        request = ctx.request_context.request
        if hasattr(request, 'user') and request.user:
            user = request.user
            if hasattr(user, 'access_token') and user.access_token:
                logger.debug(f"[MC Auth] User ID from request.user fallback: {user.access_token.client_id}")
                return user.access_token.client_id
    except (AttributeError, TypeError):
        pass

    logger.warning("[MC Auth] No authenticated user found in context")
    raise AuthenticationError(
        "No authenticated user. Bearer token or OAuth required."
    )


def reset_client() -> None:
    """Reset adapter (useful for testing).

    Closes existing adapter connection and clears cached instance.
    """
    global _adapter
    if _adapter is not None:
        _adapter.close()
        _adapter = None


def cleanup_project_all_dbs(slug: str) -> None:
    """Delete project from configured database (test helper).

    This helper ensures cleanup works correctly. It uses get_db_adapter()
    which respects the current DATABASE_URL configuration.

    **PROTECTED PROJECTS:** Cannot delete production projects.

    Useful for test cleanup to avoid orphaned records.

    Args:
        slug: Project slug to delete

    Raises:
        ValueError: If attempting to delete a protected project
    """
    # Protect production data
    PROTECTED_PROJECTS = {"mission-control"}
    if slug in PROTECTED_PROJECTS:
        raise ValueError(
            f"Cannot delete protected project '{slug}'. "
            f"Protected projects: {PROTECTED_PROJECTS}"
        )

    adapter = get_db_adapter()
    user_id = get_dev_user_id()
    adapter.delete("projects", filters={"user_id": user_id, "slug": slug})


def cleanup_projects_pattern(pattern: str = None, slugs: list[str] = None) -> None:
    """Delete multiple projects from database using pattern or slug list.

    Handles patterns that the simple adapter.delete() can't handle (like, in, etc).
    Uses database adapter pattern for portability.

    **PROTECTED PROJECTS:** Will skip protected projects in the pattern/list.

    Args:
        pattern: SQL LIKE pattern (e.g., "test-blocked-%")
        slugs: List of slugs to delete
    """
    PROTECTED_PROJECTS = {"mission-control"}

    # Filter out protected slugs if list provided
    if slugs:
        slugs = [s for s in slugs if s not in PROTECTED_PROJECTS]
        if not slugs:  # All slugs were protected
            return

    adapter = get_db_adapter()
    user_id = get_dev_user_id()

    # Clean from the configured database using adapter pattern
    if pattern:
        # Query all projects, then filter in Python using fnmatch
        import fnmatch
        fn_pattern = pattern.replace('%', '*')
        all_projects = adapter.select(
            table="projects",
            columns="slug",
            filters={"user_id": user_id}
        )
        matching_slugs = [
            p['slug'] for p in all_projects
            if fnmatch.fnmatch(p['slug'], fn_pattern)
            and p['slug'] not in PROTECTED_PROJECTS  # Skip protected
        ]
        # Delete matching slugs
        for slug in matching_slugs:
            adapter.delete("projects", filters={"user_id": user_id, "slug": slug})
    elif slugs:
        # Delete provided slugs (already filtered for protected projects)
        for slug in slugs:
            adapter.delete("projects", filters={"user_id": user_id, "slug": slug})
