import logging
import os
import shutil
import sqlite3
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


def backup_database(
    db_path: str, backup_dir: str, keep_last_n: int = 7, offsite_dir: str = ""
) -> str:
    """Back up db_path to backup_dir/flights_YYYY-MM-DD.db and prune old backups.

    Uses sqlite3.backup() which is safe for live databases under concurrent writes.
    Optionally copies the backup to offsite_dir (non-fatal if offsite copy fails).
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
        f
        for f in os.listdir(backup_dir)
        if f.startswith("flights_") and f.endswith(".db")
    )
    for old in existing[:-keep_last_n]:
        os.remove(os.path.join(backup_dir, old))

    if offsite_dir:
        try:
            os.makedirs(offsite_dir, exist_ok=True)
            dest = os.path.join(offsite_dir, os.path.basename(backup_path))
            shutil.copy2(backup_path, dest)
            existing_offsite = sorted(
                f
                for f in os.listdir(offsite_dir)
                if f.startswith("flights_") and f.endswith(".db")
            )
            for old in existing_offsite[:-keep_last_n]:
                os.remove(os.path.join(offsite_dir, old))
            logger.info("Off-site backup written to %s", dest)
        except Exception as exc:
            logger.warning("Off-site backup failed (non-fatal): %s", exc)

    return backup_path


if __name__ == "__main__":
    import config
    from src.log_config import setup_logging

    setup_logging()
    path = backup_database(
        config.DATABASE_PATH,
        config.BACKUP_DIR,
        config.BACKUP_KEEP_LAST_N,
        offsite_dir=getattr(config, "BACKUP_OFFSITE_DIR", ""),
    )
    print(f"Backup written to {path}")
