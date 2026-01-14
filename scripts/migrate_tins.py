"""
TIN Migration Script.

Encrypts existing plain-text TINs in the filers and recipients tables.
Run this AFTER applying the 006_tin_encryption.sql migration.

Usage:
    python scripts/migrate_tins.py [--dry-run]

Options:
    --dry-run    Show what would be migrated without making changes
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from src.encryption import encrypt_tin, normalize_tin


def get_supabase_admin():
    """Get Supabase client with service role key (bypasses RLS)."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    return create_client(url, key)


def migrate_table(supabase, table_name: str, dry_run: bool = False) -> dict:
    """
    Migrate TINs in a table.

    Returns:
        Dict with migration stats
    """
    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": [],
    }

    # Fetch all records that need migration (have tin but no tin_encrypted)
    response = supabase.table(table_name).select("id, tin, tin_type, tin_encrypted").execute()
    records = response.data

    stats["total"] = len(records)

    for record in records:
        record_id = record["id"]
        tin = record.get("tin")
        tin_type = record.get("tin_type", "SSN")
        tin_encrypted = record.get("tin_encrypted")

        # Skip if already migrated
        if tin_encrypted:
            stats["skipped"] += 1
            continue

        # Skip if no TIN
        if not tin:
            stats["skipped"] += 1
            continue

        try:
            # Normalize and validate TIN
            normalized = normalize_tin(tin)

            # Encrypt
            encrypted, last4, hash_val, key_version = encrypt_tin(tin)

            if dry_run:
                print(f"  [DRY RUN] Would migrate {table_name} {record_id}: {tin_type} ***-**-{last4}")
                stats["migrated"] += 1
            else:
                # Update record
                supabase.table(table_name).update({
                    "tin_encrypted": encrypted,
                    "tin_last4": last4,
                    "tin_hash": hash_val,
                    "tin_key_version": key_version,
                }).eq("id", record_id).execute()

                print(f"  Migrated {table_name} {record_id}: {tin_type} ***-**-{last4}")
                stats["migrated"] += 1

        except Exception as e:
            error_msg = f"{table_name} {record_id}: {e}"
            stats["errors"].append(error_msg)
            print(f"  ERROR: {error_msg}")

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate plain-text TINs to encrypted format")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without making changes")
    args = parser.parse_args()

    # Check encryption key is set
    if not os.getenv("TIN_ENCRYPTION_KEY"):
        print("ERROR: TIN_ENCRYPTION_KEY environment variable not set.")
        print("Generate a key with:")
        print('  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        sys.exit(1)

    print("=" * 60)
    print("TIN Migration Script")
    print("=" * 60)

    if args.dry_run:
        print("MODE: Dry run (no changes will be made)")
    else:
        print("MODE: Live migration")

    print()

    supabase = get_supabase_admin()

    # Migrate filers
    print("Migrating FILERS table...")
    filer_stats = migrate_table(supabase, "filers", args.dry_run)
    print(f"  Total: {filer_stats['total']}, Migrated: {filer_stats['migrated']}, Skipped: {filer_stats['skipped']}")

    print()

    # Migrate recipients
    print("Migrating RECIPIENTS table...")
    recipient_stats = migrate_table(supabase, "recipients", args.dry_run)
    print(f"  Total: {recipient_stats['total']}, Migrated: {recipient_stats['migrated']}, Skipped: {recipient_stats['skipped']}")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Filers:     {filer_stats['migrated']}/{filer_stats['total']} migrated")
    print(f"Recipients: {recipient_stats['migrated']}/{recipient_stats['total']} migrated")

    all_errors = filer_stats["errors"] + recipient_stats["errors"]
    if all_errors:
        print()
        print("ERRORS:")
        for error in all_errors:
            print(f"  - {error}")

    if not args.dry_run and (filer_stats['migrated'] > 0 or recipient_stats['migrated'] > 0):
        print()
        print("NEXT STEPS:")
        print("1. Verify encryption by checking a few records in Supabase")
        print("2. Test the application to ensure TINs display correctly")
        print("3. Once verified, you can drop the old 'tin' column:")
        print("   ALTER TABLE filers DROP COLUMN tin;")
        print("   ALTER TABLE recipients DROP COLUMN tin;")


if __name__ == "__main__":
    main()
