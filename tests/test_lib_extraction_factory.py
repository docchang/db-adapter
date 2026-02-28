"""Tests for Step 8: Convert Factory to Async.

Verifies that factory.py has been stripped of Mission Control-specific code
(from Step 4) and that connect_and_validate() and get_adapter() are now
async functions using async with SchemaIntrospector.

This file replaces the Step 4 sync factory tests with async equivalents.
"""

import ast
import asyncio
import inspect
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Path to factory.py source for AST inspection
FACTORY_PATH = Path(__file__).parent.parent / "src" / "db_adapter" / "factory.py"


# ============================================================================
# Test: MC-Specific Code Removed (preserved from Step 4)
# ============================================================================


class TestMCCodeRemoved:
    """Verify all Mission Control-specific code is removed from factory.py."""

    def _get_factory_source(self) -> str:
        """Read factory.py source code."""
        return FACTORY_PATH.read_text()

    def _get_factory_ast(self) -> ast.Module:
        """Parse factory.py into AST."""
        return ast.parse(self._get_factory_source())

    def _get_top_level_names(self) -> set[str]:
        """Get all top-level class, function, and assignment names."""
        tree = self._get_factory_ast()
        names: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def test_no_authentication_error(self) -> None:
        """AuthenticationError class must be removed."""
        names = self._get_top_level_names()
        assert "AuthenticationError" not in names

    def test_no_get_dev_user_id(self) -> None:
        """get_dev_user_id() must be removed."""
        names = self._get_top_level_names()
        assert "get_dev_user_id" not in names

    def test_no_get_user_id_from_ctx(self) -> None:
        """get_user_id_from_ctx() must be removed."""
        names = self._get_top_level_names()
        assert "get_user_id_from_ctx" not in names

    def test_no_cleanup_project_all_dbs(self) -> None:
        """cleanup_project_all_dbs() must be removed."""
        names = self._get_top_level_names()
        assert "cleanup_project_all_dbs" not in names

    def test_no_cleanup_projects_pattern(self) -> None:
        """cleanup_projects_pattern() must be removed."""
        names = self._get_top_level_names()
        assert "cleanup_projects_pattern" not in names

    def test_no_reset_client(self) -> None:
        """reset_client() must be removed."""
        names = self._get_top_level_names()
        assert "reset_client" not in names

    def test_no_get_db_adapter(self) -> None:
        """get_db_adapter() must be removed (renamed to get_adapter)."""
        names = self._get_top_level_names()
        assert "get_db_adapter" not in names

    def test_no_global_adapter_cache(self) -> None:
        """Module-level _adapter global must be removed."""
        names = self._get_top_level_names()
        assert "_adapter" not in names

    def test_no_global_statement(self) -> None:
        """No 'global _adapter' statements should exist."""
        source = self._get_factory_source()
        assert "global _adapter" not in source

    def test_no_removed_comments(self) -> None:
        """No '# REMOVED:' comments should remain."""
        source = self._get_factory_source()
        assert "# REMOVED:" not in source

    def test_no_mc_imports(self) -> None:
        """No imports from fastmcp, creational, or mcp.server.auth."""
        tree = self._get_factory_ast()
        forbidden = {"fastmcp", "creational", "mcp"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root_module = node.module.split(".")[0]
                assert root_module not in forbidden, (
                    f"Found forbidden import: from {node.module}"
                )

    def test_no_mc_specific_references_in_strings(self) -> None:
        """No 'MC_DATABASE_URL' or 'python -m schema' in string literals."""
        source = self._get_factory_source()
        assert "MC_DATABASE_URL" not in source
        assert "python -m schema" not in source


# ============================================================================
# Test: Kept Functions Exist
# ============================================================================


class TestKeptFunctions:
    """Verify the expected functions and classes remain."""

    def test_profile_not_found_error_exists(self) -> None:
        """ProfileNotFoundError must exist."""
        from db_adapter.factory import ProfileNotFoundError

        assert issubclass(ProfileNotFoundError, Exception)

    def test_read_profile_lock_exists(self) -> None:
        """read_profile_lock() must exist."""
        from db_adapter.factory import read_profile_lock

        assert callable(read_profile_lock)

    def test_write_profile_lock_exists(self) -> None:
        """write_profile_lock() must exist."""
        from db_adapter.factory import write_profile_lock

        assert callable(write_profile_lock)

    def test_clear_profile_lock_exists(self) -> None:
        """clear_profile_lock() must exist."""
        from db_adapter.factory import clear_profile_lock

        assert callable(clear_profile_lock)

    def test_get_active_profile_name_exists(self) -> None:
        """get_active_profile_name() must exist."""
        from db_adapter.factory import get_active_profile_name

        assert callable(get_active_profile_name)

    def test_get_active_profile_exists(self) -> None:
        """get_active_profile() must exist."""
        from db_adapter.factory import get_active_profile

        assert callable(get_active_profile)

    def test_resolve_url_exists(self) -> None:
        """resolve_url() must exist (public, renamed from _resolve_url)."""
        from db_adapter.factory import resolve_url

        assert callable(resolve_url)

    def test_connect_and_validate_exists(self) -> None:
        """connect_and_validate() must exist."""
        from db_adapter.factory import connect_and_validate

        assert callable(connect_and_validate)

    def test_get_adapter_exists(self) -> None:
        """get_adapter() must exist (renamed from get_db_adapter)."""
        from db_adapter.factory import get_adapter

        assert callable(get_adapter)


# ============================================================================
# Test: Profile Lock File Uses cwd
# ============================================================================


class TestProfileLockPath:
    """Verify _PROFILE_LOCK_FILE uses Path.cwd() not Path(__file__).parent."""

    def test_lock_file_not_inside_package(self) -> None:
        """_PROFILE_LOCK_FILE must NOT be inside the package directory."""
        source = FACTORY_PATH.read_text()
        assert 'Path(__file__).parent / ".db-profile"' not in source

    def test_lock_file_uses_cwd(self) -> None:
        """_PROFILE_LOCK_FILE must use Path.cwd()."""
        source = FACTORY_PATH.read_text()
        assert 'Path.cwd() / ".db-profile"' in source


# ============================================================================
# Test: resolve_url() Password Substitution
# ============================================================================


class TestResolveUrl:
    """Verify resolve_url() handles password substitution correctly."""

    def test_password_substitution(self) -> None:
        """Replaces [YOUR-PASSWORD] with actual password."""
        from db_adapter.config.models import DatabaseProfile
        from db_adapter.factory import resolve_url

        profile = DatabaseProfile(
            url="postgresql://user:[YOUR-PASSWORD]@host:5432/db",
            provider="postgres",
            db_password="s3cr3t!@#",
        )
        result = resolve_url(profile)
        assert "[YOUR-PASSWORD]" not in result
        assert "s3cr3t" in result

    def test_no_password_no_change(self) -> None:
        """When no password in profile, URL returned as-is."""
        from db_adapter.config.models import DatabaseProfile
        from db_adapter.factory import resolve_url

        profile = DatabaseProfile(
            url="postgresql://user:pass@host:5432/db",
            provider="postgres",
        )
        result = resolve_url(profile)
        assert result == "postgresql://user:pass@host:5432/db"

    def test_url_encoding(self) -> None:
        """Special characters in password are URL-encoded."""
        from db_adapter.config.models import DatabaseProfile
        from db_adapter.factory import resolve_url

        profile = DatabaseProfile(
            url="postgresql://user:[YOUR-PASSWORD]@host/db",
            provider="postgres",
            db_password="p@ss/w0rd",
        )
        result = resolve_url(profile)
        # @ should be encoded as %40, / as %2F
        assert "%40" in result or "%2F" in result
        assert "[YOUR-PASSWORD]" not in result


# ============================================================================
# Test: get_active_profile_name() with env_prefix
# ============================================================================


class TestGetActiveProfileName:
    """Verify get_active_profile_name() reads env var with configurable prefix."""

    def test_default_prefix_reads_db_profile(self) -> None:
        """Default prefix '' reads DB_PROFILE env var."""
        from db_adapter.factory import get_active_profile_name

        with patch.dict(os.environ, {"DB_PROFILE": "local"}, clear=False):
            result = get_active_profile_name()
            assert result == "local"

    def test_mc_prefix_reads_mc_db_profile(self) -> None:
        """Prefix 'MC_' reads MC_DB_PROFILE env var."""
        from db_adapter.factory import get_active_profile_name

        with patch.dict(os.environ, {"MC_DB_PROFILE": "rds"}, clear=False):
            result = get_active_profile_name(env_prefix="MC_")
            assert result == "rds"

    def test_custom_prefix(self) -> None:
        """Custom prefix reads corresponding env var."""
        from db_adapter.factory import get_active_profile_name

        with patch.dict(os.environ, {"MYAPP_DB_PROFILE": "staging"}, clear=False):
            result = get_active_profile_name(env_prefix="MYAPP_")
            assert result == "staging"

    def test_lock_file_fallback(self, tmp_path: Path) -> None:
        """Falls back to lock file when env var not set."""
        from db_adapter.factory import get_active_profile_name

        lock_file = tmp_path / ".db-profile"
        lock_file.write_text("docker")

        # Clear relevant env vars and patch lock file path
        env_clean = {k: v for k, v in os.environ.items() if k != "DB_PROFILE"}
        with patch.dict(os.environ, env_clean, clear=True), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            result = get_active_profile_name()
            assert result == "docker"

    def test_raises_when_no_profile(self, tmp_path: Path) -> None:
        """Raises ProfileNotFoundError when no env var and no lock file."""
        from db_adapter.factory import ProfileNotFoundError, get_active_profile_name

        lock_file = tmp_path / ".db-profile"
        # Ensure lock file does not exist

        env_clean = {k: v for k, v in os.environ.items() if k != "DB_PROFILE"}
        with patch.dict(os.environ, env_clean, clear=True), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            with pytest.raises(ProfileNotFoundError):
                get_active_profile_name()

    def test_error_message_uses_generic_references(self) -> None:
        """Error message references db-adapter, not Mission Control."""
        from db_adapter.factory import ProfileNotFoundError, get_active_profile_name

        with patch.dict(os.environ, {}, clear=True), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", Path("/nonexistent/.db-profile")):
            with pytest.raises(ProfileNotFoundError, match="db-adapter"):
                get_active_profile_name()


# ============================================================================
# Test: Functions Are Async (Step 8 specific)
# ============================================================================


class TestAsyncFunctions:
    """Verify connect_and_validate and get_adapter are async def."""

    def test_connect_and_validate_is_coroutine_function(self) -> None:
        """connect_and_validate must be an async def (coroutine function)."""
        from db_adapter.factory import connect_and_validate

        assert inspect.iscoroutinefunction(connect_and_validate), (
            "connect_and_validate must be async def"
        )

    def test_get_adapter_is_coroutine_function(self) -> None:
        """get_adapter must be an async def (coroutine function)."""
        from db_adapter.factory import get_adapter

        assert inspect.iscoroutinefunction(get_adapter), (
            "get_adapter must be async def"
        )

    def test_connect_and_validate_is_async_in_ast(self) -> None:
        """AST inspection: connect_and_validate is AsyncFunctionDef."""
        tree = ast.parse(FACTORY_PATH.read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "connect_and_validate":
                return  # Found it as async
        pytest.fail("connect_and_validate not found as AsyncFunctionDef in AST")

    def test_get_adapter_is_async_in_ast(self) -> None:
        """AST inspection: get_adapter is AsyncFunctionDef."""
        tree = ast.parse(FACTORY_PATH.read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_adapter":
                return  # Found it as async
        pytest.fail("get_adapter not found as AsyncFunctionDef in AST")

    def test_no_sync_with_introspector(self) -> None:
        """No sync 'with SchemaIntrospector' usage -- only 'async with'."""
        source = FACTORY_PATH.read_text()
        # Check that every SchemaIntrospector context manager usage is async
        # by verifying no bare 'with SchemaIntrospector' without 'async' prefix
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            if "SchemaIntrospector" in stripped and stripped.startswith("with "):
                pytest.fail(
                    f"Found sync 'with SchemaIntrospector' usage: {stripped}"
                )

    def test_async_with_introspector_present(self) -> None:
        """async with SchemaIntrospector(...) pattern is present."""
        source = FACTORY_PATH.read_text()
        assert "async with SchemaIntrospector(" in source

    def test_await_get_column_names_present(self) -> None:
        """await introspector.get_column_names() is present."""
        source = FACTORY_PATH.read_text()
        assert "await introspector.get_column_names()" in source

    def test_sync_helper_functions_remain_sync(self) -> None:
        """Profile lock and resolve_url functions remain sync (no I/O)."""
        from db_adapter.factory import (
            read_profile_lock,
            write_profile_lock,
            clear_profile_lock,
            get_active_profile_name,
            get_active_profile,
            resolve_url,
        )
        for fn in [read_profile_lock, write_profile_lock, clear_profile_lock,
                    get_active_profile_name, get_active_profile, resolve_url]:
            assert not inspect.iscoroutinefunction(fn), (
                f"{fn.__name__} should remain sync"
            )


# ============================================================================
# Test: get_adapter() Async Factory Function
# ============================================================================


class TestGetAdapterAsync:
    """Verify async get_adapter() creates adapters without caching."""

    @pytest.mark.asyncio
    async def test_direct_url_returns_adapter(self) -> None:
        """When database_url provided, returns AsyncPostgresAdapter directly."""
        from db_adapter.factory import get_adapter
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None):
            adapter = await get_adapter(database_url="postgresql://user:pass@localhost:5432/testdb")
            assert adapter is not None
            assert isinstance(adapter, AsyncPostgresAdapter)

    @pytest.mark.asyncio
    async def test_direct_url_ignores_profile(self) -> None:
        """When database_url provided, profile_name is ignored."""
        from db_adapter.factory import get_adapter
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None):
            adapter = await get_adapter(
                profile_name="nonexistent",
                database_url="postgresql://user:pass@localhost:5432/testdb",
            )
            assert adapter is not None

    @pytest.mark.asyncio
    async def test_no_caching(self) -> None:
        """Each call creates a new adapter instance."""
        from db_adapter.factory import get_adapter
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None):
            adapter1 = await get_adapter(database_url="postgresql://user:pass@localhost:5432/db1")
            adapter2 = await get_adapter(database_url="postgresql://user:pass@localhost:5432/db2")
            assert adapter1 is not adapter2

    @pytest.mark.asyncio
    async def test_raises_profile_not_found(self, tmp_path: Path) -> None:
        """Raises ProfileNotFoundError when no configuration available."""
        from db_adapter.factory import ProfileNotFoundError, get_adapter

        lock_file = tmp_path / ".db-profile"
        env_clean = {k: v for k, v in os.environ.items() if k != "DB_PROFILE"}
        with patch.dict(os.environ, env_clean, clear=True), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            with pytest.raises(ProfileNotFoundError):
                await get_adapter()

    @pytest.mark.asyncio
    async def test_profile_name_resolution(self, tmp_path: Path) -> None:
        """When profile_name provided, loads from config."""
        from db_adapter.factory import get_adapter
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        mock_config = DatabaseConfig(
            profiles={
                "test": DatabaseProfile(
                    url="postgresql://user:pass@localhost/testdb",
                    provider="postgres",
                ),
            },
        )

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch.object(AsyncPostgresAdapter, "__init__", return_value=None):
            adapter = await get_adapter(profile_name="test")
            assert adapter is not None
            assert isinstance(adapter, AsyncPostgresAdapter)

    @pytest.mark.asyncio
    async def test_passes_jsonb_columns_to_adapter(self) -> None:
        """get_adapter() forwards jsonb_columns to AsyncPostgresAdapter."""
        from db_adapter.factory import get_adapter
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None) as mock_init:
            await get_adapter(
                database_url="postgresql://user:pass@localhost/db",
                jsonb_columns=["metadata", "config"],
            )
            mock_init.assert_called_once_with(
                database_url="postgresql://user:pass@localhost/db",
                jsonb_columns=["metadata", "config"],
            )

    @pytest.mark.asyncio
    async def test_passes_jsonb_columns_none(self) -> None:
        """get_adapter() forwards jsonb_columns=None to AsyncPostgresAdapter."""
        from db_adapter.factory import get_adapter
        from db_adapter.adapters.postgres import AsyncPostgresAdapter

        with patch.object(AsyncPostgresAdapter, "__init__", return_value=None) as mock_init:
            await get_adapter(
                database_url="postgresql://user:pass@localhost/db",
            )
            mock_init.assert_called_once_with(
                database_url="postgresql://user:pass@localhost/db",
                jsonb_columns=None,
            )

    @pytest.mark.asyncio
    async def test_creates_async_postgres_adapter(self) -> None:
        """get_adapter creates AsyncPostgresAdapter (not PostgresAdapter)."""
        source = FACTORY_PATH.read_text()
        assert "AsyncPostgresAdapter" in source
        # Verify it does NOT reference the old name
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "PostgresAdapter":
                pytest.fail("Found reference to old 'PostgresAdapter' -- should be 'AsyncPostgresAdapter'")


# ============================================================================
# Test: connect_and_validate() Async with expected_columns
# ============================================================================


class TestConnectAndValidateAsync:
    """Verify async connect_and_validate() handles all modes correctly."""

    @pytest.mark.asyncio
    async def test_skips_validation_when_expected_columns_none(self, tmp_path: Path) -> None:
        """When expected_columns is None, returns success without validation."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        lock_file = tmp_path / ".db-profile"

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            result = await connect_and_validate(
                profile_name="local",
                expected_columns=None,
            )

        assert result.success is True
        assert result.profile_name == "local"
        # schema_valid is None (not validated)
        assert result.schema_valid is None

    @pytest.mark.asyncio
    async def test_writes_lock_file_on_connection_only(self, tmp_path: Path) -> None:
        """Connection-only mode writes lock file when validate_only=False."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        lock_file = tmp_path / ".db-profile"

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            await connect_and_validate(
                profile_name="local",
                expected_columns=None,
                validate_only=False,
            )

        assert lock_file.exists()
        assert lock_file.read_text() == "local"

    @pytest.mark.asyncio
    async def test_no_lock_file_when_validate_only(self, tmp_path: Path) -> None:
        """Connection-only mode does NOT write lock file when validate_only=True."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        lock_file = tmp_path / ".db-profile"

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            await connect_and_validate(
                profile_name="local",
                expected_columns=None,
                validate_only=True,
            )

        assert not lock_file.exists()

    @pytest.mark.asyncio
    async def test_profile_not_found_returns_error(self, tmp_path: Path) -> None:
        """Returns error when profile not in config."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        with patch("db_adapter.factory.load_db_config", return_value=mock_config):
            result = await connect_and_validate(
                profile_name="nonexistent",
                expected_columns=None,
            )

        assert result.success is False
        assert "nonexistent" in result.error
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_env_prefix_forwarded(self, tmp_path: Path) -> None:
        """env_prefix is forwarded to get_active_profile_name."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "rds": DatabaseProfile(
                    url="postgresql://user:pass@rds-host/db",
                    provider="postgres",
                ),
            },
        )

        lock_file = tmp_path / ".db-profile"

        with patch.dict(os.environ, {"MC_DB_PROFILE": "rds"}, clear=False), \
             patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file):
            result = await connect_and_validate(
                env_prefix="MC_",
                expected_columns=None,
            )

        assert result.success is True
        assert result.profile_name == "rds"

    @pytest.mark.asyncio
    async def test_config_file_not_found_returns_error(self) -> None:
        """Returns error when db.toml file not found."""
        from db_adapter.factory import connect_and_validate

        with patch(
            "db_adapter.factory.load_db_config",
            side_effect=FileNotFoundError("db.toml not found"),
        ):
            result = await connect_and_validate(
                profile_name="any",
                expected_columns=None,
            )

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_with_expected_columns_valid_schema(self, tmp_path: Path) -> None:
        """When expected_columns provided and schema is valid, returns success."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        expected = {"users": {"id", "name", "email"}}
        actual = {"users": {"id", "name", "email"}}

        lock_file = tmp_path / ".db-profile"

        # Mock SchemaIntrospector as async context manager
        mock_introspector = MagicMock()
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)
        mock_introspector.get_column_names = AsyncMock(return_value=actual)

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file), \
             patch("db_adapter.factory.SchemaIntrospector", return_value=mock_introspector):
            result = await connect_and_validate(
                profile_name="local",
                expected_columns=expected,
            )

        assert result.success is True
        assert result.schema_valid is True
        assert lock_file.exists()
        assert lock_file.read_text() == "local"

    @pytest.mark.asyncio
    async def test_with_expected_columns_invalid_schema(self, tmp_path: Path) -> None:
        """When expected_columns provided and schema is invalid, returns failure."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        expected = {"users": {"id", "name", "email", "phone"}}
        actual = {"users": {"id", "name"}}

        lock_file = tmp_path / ".db-profile"

        # Mock SchemaIntrospector as async context manager
        mock_introspector = MagicMock()
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)
        mock_introspector.get_column_names = AsyncMock(return_value=actual)

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file), \
             patch("db_adapter.factory.SchemaIntrospector", return_value=mock_introspector):
            result = await connect_and_validate(
                profile_name="local",
                expected_columns=expected,
            )

        assert result.success is False
        assert result.schema_valid is False
        assert result.schema_report is not None
        assert result.schema_report.error_count > 0
        # Lock file should NOT be written for invalid schema
        assert not lock_file.exists()

    @pytest.mark.asyncio
    async def test_introspector_connection_failure(self, tmp_path: Path) -> None:
        """When introspector fails to connect, returns error."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        expected = {"users": {"id", "name"}}

        # Mock SchemaIntrospector that raises on __aenter__
        mock_introspector = MagicMock()
        mock_introspector.__aenter__ = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )
        mock_introspector.__aexit__ = AsyncMock(return_value=False)

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory.SchemaIntrospector", return_value=mock_introspector):
            result = await connect_and_validate(
                profile_name="local",
                expected_columns=expected,
            )

        assert result.success is False
        assert "Failed to connect" in result.error

    @pytest.mark.asyncio
    async def test_passes_expected_columns_to_validate_schema(self, tmp_path: Path) -> None:
        """connect_and_validate passes expected_columns to validate_schema."""
        from db_adapter.factory import connect_and_validate
        from db_adapter.config.models import DatabaseConfig, DatabaseProfile
        from db_adapter.schema.models import SchemaValidationResult

        mock_config = DatabaseConfig(
            profiles={
                "local": DatabaseProfile(
                    url="postgresql://user:pass@localhost/db",
                    provider="postgres",
                ),
            },
        )

        expected = {"users": {"id", "name"}}
        actual = {"users": {"id", "name"}}

        lock_file = tmp_path / ".db-profile"

        mock_introspector = MagicMock()
        mock_introspector.__aenter__ = AsyncMock(return_value=mock_introspector)
        mock_introspector.__aexit__ = AsyncMock(return_value=False)
        mock_introspector.get_column_names = AsyncMock(return_value=actual)

        mock_validation = SchemaValidationResult(valid=True)

        with patch("db_adapter.factory.load_db_config", return_value=mock_config), \
             patch("db_adapter.factory._PROFILE_LOCK_FILE", lock_file), \
             patch("db_adapter.factory.SchemaIntrospector", return_value=mock_introspector), \
             patch("db_adapter.factory.validate_schema", return_value=mock_validation) as mock_vs:
            await connect_and_validate(
                profile_name="local",
                expected_columns=expected,
            )
            # Verify validate_schema was called with actual and expected
            mock_vs.assert_called_once_with(actual, expected)


# ============================================================================
# Test: Function Signatures
# ============================================================================


class TestFunctionSignatures:
    """Verify function signatures have the expected parameters."""

    def test_get_active_profile_name_has_env_prefix(self) -> None:
        """get_active_profile_name() accepts env_prefix parameter."""
        from db_adapter.factory import get_active_profile_name

        sig = inspect.signature(get_active_profile_name)
        assert "env_prefix" in sig.parameters
        assert sig.parameters["env_prefix"].default == ""

    def test_get_active_profile_has_env_prefix(self) -> None:
        """get_active_profile() accepts env_prefix parameter."""
        from db_adapter.factory import get_active_profile

        sig = inspect.signature(get_active_profile)
        assert "env_prefix" in sig.parameters

    def test_connect_and_validate_has_expected_columns(self) -> None:
        """connect_and_validate() accepts expected_columns parameter."""
        from db_adapter.factory import connect_and_validate

        sig = inspect.signature(connect_and_validate)
        assert "expected_columns" in sig.parameters
        assert sig.parameters["expected_columns"].default is None

    def test_connect_and_validate_has_env_prefix(self) -> None:
        """connect_and_validate() accepts env_prefix parameter."""
        from db_adapter.factory import connect_and_validate

        sig = inspect.signature(connect_and_validate)
        assert "env_prefix" in sig.parameters
        assert sig.parameters["env_prefix"].default == ""

    def test_get_adapter_has_database_url(self) -> None:
        """get_adapter() accepts database_url parameter."""
        from db_adapter.factory import get_adapter

        sig = inspect.signature(get_adapter)
        assert "database_url" in sig.parameters
        assert sig.parameters["database_url"].default is None

    def test_get_adapter_has_jsonb_columns(self) -> None:
        """get_adapter() accepts jsonb_columns parameter."""
        from db_adapter.factory import get_adapter

        sig = inspect.signature(get_adapter)
        assert "jsonb_columns" in sig.parameters
        assert sig.parameters["jsonb_columns"].default is None

    def test_get_adapter_has_env_prefix(self) -> None:
        """get_adapter() accepts env_prefix parameter."""
        from db_adapter.factory import get_adapter

        sig = inspect.signature(get_adapter)
        assert "env_prefix" in sig.parameters
        assert sig.parameters["env_prefix"].default == ""

    def test_get_adapter_has_profile_name(self) -> None:
        """get_adapter() accepts profile_name parameter."""
        from db_adapter.factory import get_adapter

        sig = inspect.signature(get_adapter)
        assert "profile_name" in sig.parameters
        assert sig.parameters["profile_name"].default is None

    def test_resolve_url_is_public(self) -> None:
        """resolve_url (not _resolve_url) is importable."""
        from db_adapter.factory import resolve_url

        assert callable(resolve_url)

    def test_private_resolve_url_not_importable(self) -> None:
        """_resolve_url should not exist (renamed to resolve_url)."""
        import db_adapter.factory as f

        assert not hasattr(f, "_resolve_url")
