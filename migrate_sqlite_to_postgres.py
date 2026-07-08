"""
One-time migration: copies all rows from the local cases.db (SQLite) into
the Postgres database pointed at by the DATABASE_URL environment variable.

Usage (run this from your local machine, inside the backend/ folder, with
your virtualenv activated and cases.db present):

    export DATABASE_URL="<External Database URL from Render>"
    python migrate_sqlite_to_postgres.py

Add --wipe if you've run this before and want to clear the Postgres tables
first (avoids duplicate-key errors on a re-run):

    python migrate_sqlite_to_postgres.py --wipe

Notes:
- Row IDs are preserved so foreign keys (notification_log -> cases) stay
  consistent, and each table's auto-increment sequence is reset afterwards
  so future inserts via the app don't collide with the migrated IDs.
- This only touches Postgres; your local cases.db is untouched.
"""

import os
import sys
import sqlite3
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "cases.db")

TABLES = ["cases", "devices", "notification_log"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true",
                         help="Delete existing rows in the Postgres tables before inserting.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit(
            "ERROR: DATABASE_URL is not set.\n"
            "Set it to your Render Postgres connection string first, e.g.:\n"
            '  export DATABASE_URL="postgresql://user:pass@host/dbname"\n'
            "(Use the External Database URL if running this from your own machine.)"
        )
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if not os.path.exists(SQLITE_PATH):
        sys.exit(f"ERROR: {SQLITE_PATH} not found.")

    # Import here so this script can give a clean error above before pulling in
    # the app/Flask machinery.
    from app import app  # noqa: E402  (Flask app already wires DATABASE_URL -> Postgres)
    from extensions import db  # noqa: E402
    from sqlalchemy import text  # noqa: E402

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row

    with app.app_context():
        # Tables are created automatically by app.py's db.create_all() on
        # import, but make sure just in case this script runs first.
        db.create_all()

        if args.wipe:
            for table in reversed(TABLES):  # respect FK order on delete
                db.session.execute(text(f"DELETE FROM {table}"))
            db.session.commit()
            print("Wiped existing rows from Postgres tables.")

        total_inserted = 0
        for table in TABLES:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"{table}: no rows to migrate.")
                continue

            columns = rows[0].keys()
            col_list = ", ".join(columns)
            placeholders = ", ".join(f":{c}" for c in columns)
            insert_sql = text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})")

            for row in rows:
                db.session.execute(insert_sql, dict(row))
            db.session.commit()

            # Reset the auto-increment sequence so new rows created via the
            # app don't collide with the migrated IDs.
            db.session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            ))
            db.session.commit()

            print(f"{table}: migrated {len(rows)} rows.")
            total_inserted += len(rows)

    sqlite_conn.close()
    print(f"Done. Migrated {total_inserted} rows total into Postgres.")


if __name__ == "__main__":
    main()
