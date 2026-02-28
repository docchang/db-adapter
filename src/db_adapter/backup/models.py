"""Backup schema models for declarative table hierarchy.

Consuming applications declare their table structure, FK relationships,
and the backup/restore engine handles ID remapping automatically.

Usage:
    from db_adapter.backup.models import BackupSchema, TableDef, ForeignKey

    schema = BackupSchema(tables=[
        TableDef(name="authors", pk="id", slug_field="slug", user_field="user_id"),
        TableDef(name="books", pk="id", slug_field="slug", user_field="user_id",
                 parent=ForeignKey(table="authors", field="author_id")),
        TableDef(name="chapters", pk="id", slug_field="slug", user_field="user_id",
                 parent=ForeignKey(table="books", field="book_id"),
                 optional_refs=[ForeignKey(table="authors", field="editor_id")]),
    ])
"""

from pydantic import BaseModel, Field


class ForeignKey(BaseModel):
    """Foreign key reference to a parent table."""

    table: str          # parent table name
    field: str          # FK column in this table


class TableDef(BaseModel):
    """Definition of a table for backup/restore operations."""

    name: str                                       # table name
    pk: str = "id"                                  # primary key column
    slug_field: str = "slug"                        # slug column for matching
    user_field: str = "user_id"                     # user ownership column
    parent: ForeignKey | None = None                # required FK (skip record if parent missing)
    optional_refs: list[ForeignKey] = Field(default_factory=list)  # optional FKs (null if ref missing)


class BackupSchema(BaseModel):
    """Declarative backup schema. Tables ordered by dependency (parents first)."""

    tables: list[TableDef]
