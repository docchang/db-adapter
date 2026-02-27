#!/usr/bin/env python3
"""Command-line interface for Mission Control backup and restore.

Usage:
    python backup_cli.py backup
    python backup_cli.py backup --project mission-control
    python backup_cli.py restore backup/backups/backup-2025-12-30.json
    python backup_cli.py restore backup/backups/backup.json --mode overwrite
    python backup_cli.py restore backup/backups/backup.json --dry-run
    python backup_cli.py validate backup/backups/backup.json
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports when run directly
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from backup.backup_restore import backup_database, restore_database, validate_backup


def cmd_backup(args):
    """Handle backup command."""
    try:
        backup_path = backup_database(
            output_path=args.output,
            project_slugs=args.projects if args.projects else None,
        )

        # Create 'latest.json' symlink if full backup
        if not args.projects and not args.output:
            # Use path relative to backup module
            backups_dir = Path(__file__).parent / "backups"
            latest_path = backups_dir / "latest.json"
            if latest_path.exists() or latest_path.is_symlink():
                latest_path.unlink()
            latest_path.symlink_to(Path(backup_path).name)
            print(f"   Latest: backup/backups/latest.json -> {Path(backup_path).name}")

        return 0
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return 1


def cmd_restore(args):
    """Handle restore command."""
    # Confirm unless --yes flag
    if not args.yes and not args.dry_run:
        print(f"⚠️  This will restore data from: {args.backup_path}")
        print(f"   Mode: {args.mode}")
        if args.mode == "overwrite":
            print(f"   WARNING: Existing records will be overwritten!")
        response = input("Continue? [y/N] ")
        if response.lower() not in ["y", "yes"]:
            print("Cancelled.")
            return 0

    try:
        summary = restore_database(
            backup_path=args.backup_path,
            mode=args.mode,
            dry_run=args.dry_run,
        )

        # Check for failures
        total_failed = sum(
            counts.get("failed", 0)
            for table, counts in summary.items()
            if isinstance(counts, dict)
        )

        if total_failed > 0:
            print(f"\n⚠️  Restore completed with {total_failed} failures")
            return 1

        return 0
    except Exception as e:
        print(f"❌ Restore failed: {e}")
        return 1


def cmd_validate(args):
    """Handle validate command."""
    try:
        result = validate_backup(args.backup_path)

        print(f"📋 Validating: {args.backup_path}")

        if result["errors"]:
            print(f"\n❌ INVALID - Found {len(result['errors'])} errors:")
            for error in result["errors"]:
                print(f"   - {error}")

        if result["warnings"]:
            print(f"\n⚠️  Found {len(result['warnings'])} warnings:")
            for warning in result["warnings"]:
                print(f"   - {warning}")

        if result["valid"]:
            if result["warnings"]:
                print(f"\n✅ Backup is valid (with warnings)")
            else:
                print(f"\n✅ Backup is valid")
            return 0
        else:
            print(f"\n❌ Backup is invalid")
            return 1

    except Exception as e:
        print(f"❌ Validation failed: {e}")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Mission Control backup and restore utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backup entire database
  python backup_cli.py backup

  # Backup specific project
  python backup_cli.py backup --project mission-control

  # Backup multiple projects
  python backup_cli.py backup --project mission-control --project hexar

  # Restore from backup (skip existing records)
  python backup_cli.py restore backup/backups/backup-2025-12-30.json

  # Restore with overwrite (replace existing)
  python backup_cli.py restore backup/backups/backup.json --mode overwrite --yes

  # Preview what would be restored (dry run)
  python backup_cli.py restore backup/backups/backup.json --dry-run

  # Validate backup file
  python backup_cli.py validate backup/backups/backup.json

  # Migrate Supabase → PostgreSQL
  DB_PROVIDER=supabase python backup_cli.py backup
  DB_PROVIDER=postgres python backup_cli.py restore backups/latest.json
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.required = True

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create database backup")
    backup_parser.add_argument(
        "--output", "-o",
        help="Output file path (default: backup/backup/backups/backup-{timestamp}.json)"
    )
    backup_parser.add_argument(
        "--project", "-p",
        action="append",
        dest="projects",
        help="Backup specific project(s) by slug (can be used multiple times)"
    )
    backup_parser.set_defaults(func=cmd_backup)

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument(
        "backup_path",
        help="Path to backup JSON file"
    )
    restore_parser.add_argument(
        "--mode", "-m",
        choices=["skip", "overwrite", "fail"],
        default="skip",
        help="How to handle existing records (default: skip)"
    )
    restore_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )
    restore_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )
    restore_parser.set_defaults(func=cmd_restore)

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate backup file")
    validate_parser.add_argument(
        "backup_path",
        help="Path to backup JSON file"
    )
    validate_parser.set_defaults(func=cmd_validate)

    # Parse arguments and run command
    args = parser.parse_args()

    # Ensure backups directory exists (relative to backup module)
    backups_dir = Path(__file__).parent / "backups"
    backups_dir.mkdir(exist_ok=True)

    # Run the appropriate command function
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
