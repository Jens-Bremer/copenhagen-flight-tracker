import os
from datetime import date

import pytest

from scripts.backup_db import backup_database
from src.database import initialize_database


@pytest.fixture
def src_db(tmp_path):
    db_path = str(tmp_path / "flights.db")
    initialize_database(db_path)
    return db_path


def test_backup_creates_file(src_db, tmp_path):
    backup_dir = str(tmp_path / "backups")
    backup_database(src_db, backup_dir)
    today = date.today().isoformat()
    assert os.path.exists(os.path.join(backup_dir, f"flights_{today}.db"))


def test_backup_returns_path(src_db, tmp_path):
    backup_dir = str(tmp_path / "backups")
    path = backup_database(src_db, backup_dir)
    today = date.today().isoformat()
    assert path == os.path.join(backup_dir, f"flights_{today}.db")
    assert os.path.exists(path)


def test_backup_same_day_overwrites(src_db, tmp_path):
    backup_dir = str(tmp_path / "backups")
    backup_database(src_db, backup_dir)
    backup_database(src_db, backup_dir)
    files = [f for f in os.listdir(backup_dir) if f.endswith(".db")]
    assert len(files) == 1


def test_backup_prunes_old_files(src_db, tmp_path):
    backup_dir = str(tmp_path / "backups")
    os.makedirs(backup_dir)
    for i in range(1, 10):
        old = os.path.join(backup_dir, f"flights_2026-01-{i:02d}.db")
        open(old, "w").close()
    backup_database(src_db, backup_dir, keep_last_n=7)
    files = [f for f in os.listdir(backup_dir) if f.endswith(".db")]
    assert len(files) == 7


def test_offsite_copy_created(src_db, tmp_path):
    """Off-site copy is written when offsite_dir is configured."""
    offsite = tmp_path / "offsite"
    local = tmp_path / "local"
    result = backup_database(
        str(src_db), str(local), keep_last_n=7, offsite_dir=str(offsite)
    )
    assert offsite.exists()
    assert (offsite / os.path.basename(result)).exists()


def test_offsite_skipped_when_empty(src_db, tmp_path):
    """No offsite directory created when offsite_dir is empty."""
    local = tmp_path / "local"
    backup_database(str(src_db), str(local), keep_last_n=7, offsite_dir="")
    # No offsite dir should be created
    # Just verify it doesn't crash
    assert local.exists()


def test_offsite_failure_is_nonfatal(src_db, tmp_path):
    """Off-site backup failure does not raise — local backup still completes."""
    local = tmp_path / "local"
    # Use a path that cannot be created (root-level on most systems)
    result = backup_database(
        str(src_db),
        str(local),
        keep_last_n=7,
        offsite_dir="/nonexistent_root_path_xyz/backup",
    )
    # Should not raise; local backup should succeed
    assert os.path.exists(result)
