"""Tests for Step 3: Remove MC-Specific Code from Config Loader.

Verifies that config/loader.py is clean of MC-specific code and that
load_db_config() works correctly as a standalone TOML loader.
"""

import ast
import importlib
import inspect
import textwrap
from pathlib import Path

import pytest

from db_adapter.config.loader import load_db_config
from db_adapter.config.models import DatabaseConfig, DatabaseProfile

# Path to the loader source file
LOADER_PATH = Path(__file__).resolve().parent.parent / "src" / "db_adapter" / "config" / "loader.py"
INIT_PATH = Path(__file__).resolve().parent.parent / "src" / "db_adapter" / "config" / "__init__.py"


class TestMCCodeRemoved:
    """Verify all MC-specific code has been removed from config/loader.py."""

    def test_no_settings_class(self) -> None:
        """Settings class must not exist in loader.py."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        class_names = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ]
        assert "Settings" not in class_names, (
            "Settings class still exists in config/loader.py"
        )

    def test_no_get_settings_function(self) -> None:
        """get_settings() function must not exist in loader.py."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        func_names = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        assert "get_settings" not in func_names, (
            "get_settings() function still exists in config/loader.py"
        )

    def test_no_shared_settings_reference(self) -> None:
        """No reference to SharedSettings (import or comment) in loader.py."""
        source = LOADER_PATH.read_text()
        assert "SharedSettings" not in source, (
            "SharedSettings reference still exists in config/loader.py"
        )

    def test_no_creational_import(self) -> None:
        """No import from creational package in loader.py."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("creational"), (
                    f"Found creational import: from {node.module}"
                )

    def test_no_functools_import(self) -> None:
        """No functools import in loader.py (was used for lru_cache on get_settings)."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "functools", (
                        "functools import still exists in config/loader.py"
                    )
            if isinstance(node, ast.ImportFrom) and node.module == "functools":
                pytest.fail("from functools import still exists in config/loader.py")

    def test_no_pydantic_import(self) -> None:
        """No direct pydantic import in loader.py (pydantic is used in models.py only)."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pydantic"):
                pytest.fail(f"pydantic import found in loader.py: from {node.module}")

    def test_no_removed_comments(self) -> None:
        """No '# REMOVED:' comments left over from Step 2."""
        source = LOADER_PATH.read_text()
        assert "# REMOVED:" not in source, (
            "'# REMOVED:' comments still exist in config/loader.py"
        )

    def test_only_expected_imports(self) -> None:
        """loader.py should only import tomllib, Path, and db_adapter.config.models."""
        source = LOADER_PATH.read_text()
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        expected = {"tomllib", "pathlib", "db_adapter.config.models"}
        actual = set(imports)
        assert actual == expected, (
            f"Unexpected imports in loader.py: {actual - expected}. "
            f"Missing expected: {expected - actual}"
        )


class TestLoadDbConfig:
    """Test load_db_config() TOML parsing functionality."""

    def test_load_valid_toml(self, tmp_path: Path) -> None:
        """load_db_config() parses a valid TOML file with profiles."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost:5432/devdb"
            description = "Development database"
            provider = "postgres"

            [profiles.staging]
            url = "postgresql://staging.example.com:5432/stagingdb"
            description = "Staging database"
            db_password = "secret123"

            [schema]
            file = "custom_schema.sql"
            validate_on_connect = false
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert isinstance(config, DatabaseConfig)
        assert len(config.profiles) == 2
        assert "dev" in config.profiles
        assert "staging" in config.profiles

        dev = config.profiles["dev"]
        assert isinstance(dev, DatabaseProfile)
        assert dev.url == "postgresql://localhost:5432/devdb"
        assert dev.description == "Development database"
        assert dev.provider == "postgres"
        assert dev.db_password is None

        staging = config.profiles["staging"]
        assert staging.db_password == "secret123"

        assert config.schema_file == "custom_schema.sql"
        assert config.validate_on_connect is False

    def test_load_minimal_toml(self, tmp_path: Path) -> None:
        """load_db_config() handles minimal TOML with defaults."""
        toml_content = textwrap.dedent("""\
            [profiles.local]
            url = "postgresql://localhost/mydb"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert len(config.profiles) == 1
        local = config.profiles["local"]
        assert local.url == "postgresql://localhost/mydb"
        assert local.description == ""
        assert local.provider == "postgres"
        assert local.db_password is None
        assert config.schema_file == "schema.sql"
        assert config.validate_on_connect is True

    def test_load_empty_profiles(self, tmp_path: Path) -> None:
        """load_db_config() handles TOML with no profiles section."""
        toml_content = textwrap.dedent("""\
            [schema]
            file = "schema.sql"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert isinstance(config, DatabaseConfig)
        assert len(config.profiles) == 0

    def test_file_not_found_raises(self) -> None:
        """load_db_config() raises FileNotFoundError for missing file."""
        missing_path = Path("/nonexistent/path/db.toml")
        with pytest.raises(FileNotFoundError, match="Database config not found"):
            load_db_config(config_path=missing_path)

    def test_default_path_uses_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Default config_path uses Path.cwd() / 'db.toml', not package directory."""
        # Inspect the source to verify the default path logic
        source = LOADER_PATH.read_text()
        assert 'Path.cwd() / "db.toml"' in source, (
            "Default config_path should use Path.cwd() / 'db.toml'"
        )
        assert 'Path(__file__).parent' not in source, (
            "Default config_path should NOT use Path(__file__).parent"
        )

    def test_default_path_reads_from_cwd_at_runtime(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When no config_path given, load_db_config() reads from cwd."""
        # Create a db.toml in tmp_path
        toml_content = textwrap.dedent("""\
            [profiles.test]
            url = "postgresql://localhost/testdb"
        """)
        (tmp_path / "db.toml").write_text(toml_content)

        # Change cwd to tmp_path
        monkeypatch.chdir(tmp_path)

        config = load_db_config()

        assert "test" in config.profiles
        assert config.profiles["test"].url == "postgresql://localhost/testdb"

    def test_default_path_missing_raises_from_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When no config_path given and cwd has no db.toml, raises FileNotFoundError."""
        # tmp_path has no db.toml
        monkeypatch.chdir(tmp_path)

        with pytest.raises(FileNotFoundError, match="Database config not found"):
            load_db_config()

    def test_multiple_profiles_preserve_all_fields(self, tmp_path: Path) -> None:
        """All DatabaseProfile fields are preserved through TOML parsing."""
        toml_content = textwrap.dedent("""\
            [profiles.prod]
            url = "postgresql://prod.example.com:5432/proddb"
            description = "Production database"
            db_password = "prod-secret"
            provider = "supabase"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)
        prod = config.profiles["prod"]

        assert prod.url == "postgresql://prod.example.com:5432/proddb"
        assert prod.description == "Production database"
        assert prod.db_password == "prod-secret"
        assert prod.provider == "supabase"


class TestConfigInitExports:
    """Verify config/__init__.py exports the right symbols."""

    def test_import_load_db_config_from_config(self) -> None:
        """load_db_config is importable from db_adapter.config."""
        from db_adapter.config import load_db_config as fn
        assert callable(fn)

    def test_import_database_profile_from_config(self) -> None:
        """DatabaseProfile is importable from db_adapter.config."""
        from db_adapter.config import DatabaseProfile as cls
        assert issubclass(cls, DatabaseProfile)

    def test_import_database_config_from_config(self) -> None:
        """DatabaseConfig is importable from db_adapter.config."""
        from db_adapter.config import DatabaseConfig as cls
        assert issubclass(cls, DatabaseConfig)

    def test_all_exports(self) -> None:
        """__all__ contains exactly the expected exports."""
        import db_adapter.config as config_mod
        assert hasattr(config_mod, "__all__")
        expected = {"load_db_config", "DatabaseConfig", "DatabaseProfile"}
        assert set(config_mod.__all__) == expected

    def test_no_settings_or_get_settings_in_config(self) -> None:
        """Settings and get_settings must NOT be importable from db_adapter.config."""
        import db_adapter.config as config_mod
        assert not hasattr(config_mod, "Settings"), (
            "Settings should not be exported from db_adapter.config"
        )
        assert not hasattr(config_mod, "get_settings"), (
            "get_settings should not be exported from db_adapter.config"
        )


class TestLoaderModuleAttributes:
    """Verify the loader module only contains expected public API."""

    def test_load_db_config_is_only_public_function(self) -> None:
        """The only public function in loader.py should be load_db_config."""
        import db_adapter.config.loader as loader_mod
        public_functions = [
            name for name, obj in inspect.getmembers(loader_mod, inspect.isfunction)
            if not name.startswith("_") and obj.__module__ == "db_adapter.config.loader"
        ]
        assert public_functions == ["load_db_config"], (
            f"Expected only load_db_config, found: {public_functions}"
        )

    def test_no_classes_in_loader(self) -> None:
        """No classes should be defined in loader.py (they belong in models.py)."""
        import db_adapter.config.loader as loader_mod
        classes = [
            name for name, obj in inspect.getmembers(loader_mod, inspect.isclass)
            if obj.__module__ == "db_adapter.config.loader"
        ]
        assert classes == [], (
            f"Unexpected classes in loader.py: {classes}"
        )


class TestDatabaseConfigNewFields:
    """Verify new optional fields on DatabaseConfig for config-driven CLI defaults."""

    def _minimal_profiles(self) -> dict[str, DatabaseProfile]:
        """Return a minimal profiles dict for constructing DatabaseConfig."""
        return {"dev": DatabaseProfile(url="postgresql://localhost/dev")}

    def test_backward_compatible_no_new_fields(self) -> None:
        """DatabaseConfig with only profiles (no new fields) still works."""
        config = DatabaseConfig(profiles=self._minimal_profiles())

        assert len(config.profiles) == 1
        assert config.schema_file == "schema.sql"
        assert config.validate_on_connect is True

    def test_new_fields_default_to_none(self) -> None:
        """All four new fields default to None when not provided."""
        config = DatabaseConfig(profiles=self._minimal_profiles())

        assert config.column_defs is None
        assert config.backup_schema is None
        assert config.sync_tables is None
        assert config.user_id_env is None

    def test_all_new_fields_populated(self) -> None:
        """DatabaseConfig with all new fields set parses correctly."""
        config = DatabaseConfig(
            profiles=self._minimal_profiles(),
            column_defs="defs.json",
            backup_schema="bs.json",
            sync_tables=["t1", "t2"],
            user_id_env="DEV_USER_ID",
        )

        assert config.column_defs == "defs.json"
        assert config.backup_schema == "bs.json"
        assert config.sync_tables == ["t1", "t2"]
        assert config.user_id_env == "DEV_USER_ID"

    def test_column_defs_type(self) -> None:
        """column_defs accepts a string and defaults to None."""
        config_with = DatabaseConfig(
            profiles=self._minimal_profiles(), column_defs="column-defs.json"
        )
        config_without = DatabaseConfig(profiles=self._minimal_profiles())

        assert config_with.column_defs == "column-defs.json"
        assert config_without.column_defs is None

    def test_backup_schema_type(self) -> None:
        """backup_schema accepts a string and defaults to None."""
        config_with = DatabaseConfig(
            profiles=self._minimal_profiles(), backup_schema="backup-schema.json"
        )
        config_without = DatabaseConfig(profiles=self._minimal_profiles())

        assert config_with.backup_schema == "backup-schema.json"
        assert config_without.backup_schema is None

    def test_sync_tables_type(self) -> None:
        """sync_tables accepts a list of strings and defaults to None."""
        config_with = DatabaseConfig(
            profiles=self._minimal_profiles(), sync_tables=["users", "orders", "items"]
        )
        config_without = DatabaseConfig(profiles=self._minimal_profiles())

        assert config_with.sync_tables == ["users", "orders", "items"]
        assert isinstance(config_with.sync_tables, list)
        assert config_without.sync_tables is None

    def test_user_id_env_type(self) -> None:
        """user_id_env accepts a string and defaults to None."""
        config_with = DatabaseConfig(
            profiles=self._minimal_profiles(), user_id_env="MC_USER_ID"
        )
        config_without = DatabaseConfig(profiles=self._minimal_profiles())

        assert config_with.user_id_env == "MC_USER_ID"
        assert config_without.user_id_env is None

    def test_sync_tables_empty_list(self) -> None:
        """sync_tables accepts an empty list (distinct from None)."""
        config = DatabaseConfig(profiles=self._minimal_profiles(), sync_tables=[])

        assert config.sync_tables == []
        assert config.sync_tables is not None

    def test_new_fields_with_existing_schema_settings(self) -> None:
        """New fields coexist with existing schema_file and validate_on_connect."""
        config = DatabaseConfig(
            profiles=self._minimal_profiles(),
            schema_file="custom.sql",
            validate_on_connect=False,
            column_defs="defs.json",
            backup_schema="bs.json",
            sync_tables=["t1"],
            user_id_env="USER_ID_VAR",
        )

        assert config.schema_file == "custom.sql"
        assert config.validate_on_connect is False
        assert config.column_defs == "defs.json"
        assert config.backup_schema == "bs.json"
        assert config.sync_tables == ["t1"]
        assert config.user_id_env == "USER_ID_VAR"


class TestLoadDbConfigNewSections:
    """Test load_db_config() parsing of new [schema], [sync], and [defaults] sections."""

    def test_all_new_sections_parsed(self, tmp_path: Path) -> None:
        """TOML with all new sections returns DatabaseConfig with all new fields populated."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [schema]
            file = "schema.sql"
            column_defs = "column-defs.json"
            backup_schema = "backup-schema.json"

            [sync]
            tables = ["projects", "milestones", "tasks"]

            [defaults]
            user_id_env = "DEV_USER_ID"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.column_defs == "column-defs.json"
        assert config.backup_schema == "backup-schema.json"
        assert config.sync_tables == ["projects", "milestones", "tasks"]
        assert config.user_id_env == "DEV_USER_ID"

    def test_minimal_toml_new_fields_are_none(self, tmp_path: Path) -> None:
        """TOML with only [profiles] returns DatabaseConfig with all new fields as None."""
        toml_content = textwrap.dedent("""\
            [profiles.local]
            url = "postgresql://localhost/mydb"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.column_defs is None
        assert config.backup_schema is None
        assert config.sync_tables is None
        assert config.user_id_env is None

    def test_sync_section_only(self, tmp_path: Path) -> None:
        """TOML with [sync] but no [defaults] parses sync_tables, user_id_env stays None."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [sync]
            tables = ["users", "orders"]
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.sync_tables == ["users", "orders"]
        assert config.user_id_env is None

    def test_defaults_section_only(self, tmp_path: Path) -> None:
        """TOML with [defaults] but no [sync] parses user_id_env, sync_tables stays None."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [defaults]
            user_id_env = "MY_USER_ID"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.sync_tables is None
        assert config.user_id_env == "MY_USER_ID"

    def test_schema_section_with_column_defs_only(self, tmp_path: Path) -> None:
        """TOML with column_defs in [schema] but no backup_schema."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [schema]
            file = "schema.sql"
            column_defs = "col-defs.json"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.column_defs == "col-defs.json"
        assert config.backup_schema is None

    def test_schema_section_with_backup_schema_only(self, tmp_path: Path) -> None:
        """TOML with backup_schema in [schema] but no column_defs."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [schema]
            file = "schema.sql"
            backup_schema = "bs.json"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.column_defs is None
        assert config.backup_schema == "bs.json"

    def test_sync_tables_is_list_type(self, tmp_path: Path) -> None:
        """sync_tables field is list[str] when provided in TOML."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [sync]
            tables = ["t1", "t2", "t3"]
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert isinstance(config.sync_tables, list)
        assert len(config.sync_tables) == 3
        assert all(isinstance(t, str) for t in config.sync_tables)

    def test_existing_fields_unaffected_by_new_sections(self, tmp_path: Path) -> None:
        """Existing schema_file and validate_on_connect still work alongside new fields."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"
            description = "Dev DB"

            [schema]
            file = "custom.sql"
            validate_on_connect = false
            column_defs = "defs.json"
            backup_schema = "bs.json"

            [sync]
            tables = ["t1"]

            [defaults]
            user_id_env = "UID"
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        # Existing fields
        assert config.schema_file == "custom.sql"
        assert config.validate_on_connect is False
        assert len(config.profiles) == 1
        assert config.profiles["dev"].description == "Dev DB"

        # New fields
        assert config.column_defs == "defs.json"
        assert config.backup_schema == "bs.json"
        assert config.sync_tables == ["t1"]
        assert config.user_id_env == "UID"

    def test_empty_sync_section(self, tmp_path: Path) -> None:
        """TOML with empty [sync] section (no tables key) leaves sync_tables as None."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [sync]
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.sync_tables is None

    def test_empty_defaults_section(self, tmp_path: Path) -> None:
        """TOML with empty [defaults] section (no keys) leaves user_id_env as None."""
        toml_content = textwrap.dedent("""\
            [profiles.dev]
            url = "postgresql://localhost/dev"

            [defaults]
        """)
        config_file = tmp_path / "db.toml"
        config_file.write_text(toml_content)

        config = load_db_config(config_path=config_file)

        assert config.user_id_env is None
