import os
import sqlite3
from datetime import date


def backup_database(db_path: str, backup_dir: str, keep_last_n: int = 7) -> str:
    """Back up db_path to backup_dir/flights_YYYY-MM-DD.db and prune old backups.

    Uses sqlite3.backup() which is safe for live databases under concurrent writes.
    Returns the path of the newly written backup file.
    """
    os.makedirs(backup_dir, exist_ok=True)
    today = date.today().isoformat()
    backup_path = os.path.join(backup_dir, f"flights_{today}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    existing = sorted(
        f for f in os.listdir(backup_dir)
        if f.startswith("flights_") and f.endswith(".db")
    )
    for old in existing[:-keep_last_n]:
        os.remove(os.path.join(backup_dir, old))
    return backup_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
    path = backup_database(config.DATABASE_PATH, config.BACKUP_DIR, config.BACKUP_KEEP_LAST_N)
    print(f"Backup written to {path}")
