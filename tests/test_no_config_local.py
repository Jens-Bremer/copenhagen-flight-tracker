"""Regression tests for issue #105.

`config_local.py` was previously gitignored and intended as an override for
`config.py`, but it was never actually imported. The owner's real ntfy topic
lived only in that file, so alerts were silently misrouted. Per CLAUDE.md
("All config in config.py. There is no config_local.py override mechanism."),
the file and any references to it must stay gone.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_config_local_file_does_not_exist():
    """`config_local.py` must not be present in the repo root."""
    assert os.path.exists(REPO_ROOT / "config_local.py") is False


def test_no_source_references_to_config_local():
    """No tracked source file (src/, scripts/, config.py) may reference config_local."""
    result = subprocess.run(
        ["grep", "-rn", "--exclude-dir=*.egg-info", "config_local", "src/", "scripts/", "config.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # grep exit code 1 means "no matches found", which is exactly what we want.
    assert result.returncode == 1, (
        f"Found stray references to config_local:\n{result.stdout}"
    )
