"""Smoke tests for scripts/update.sh and scripts/update.ps1 (issue #30).

These tests do not execute the scripts; they verify structural properties that
guard against the two anti-patterns the issue explicitly rules out:
  - using `pkill -f` instead of the PID file mechanism.
  - silent `git stash` that would mask intentional config edits.
"""

import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_SH = REPO_ROOT / "scripts" / "update.sh"
UPDATE_PS1 = REPO_ROOT / "scripts" / "update.ps1"
PID_FILE_REF = "data/run_scheduler.pid"


def test_update_sh_exists():
    """scripts/update.sh must be present in the repository."""
    assert UPDATE_SH.exists(), f"Missing file: {UPDATE_SH}"


def test_update_sh_is_executable():
    """scripts/update.sh must have the executable bit set."""
    mode = UPDATE_SH.stat().st_mode
    assert mode & stat.S_IXUSR, (
        f"scripts/update.sh is not executable (mode={oct(mode)})"
    )


def test_update_ps1_exists():
    """scripts/update.ps1 must be present in the repository."""
    assert UPDATE_PS1.exists(), f"Missing file: {UPDATE_PS1}"


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_update_sh_references_pid_file():
    """update.sh must reference the PID file path (regression guard)."""
    content = _read_script(UPDATE_SH)
    assert PID_FILE_REF in content, (
        f"update.sh does not reference '{PID_FILE_REF}'. "
        "It must stop the scheduler via the PID file, not pkill -f."
    )


def test_update_ps1_references_pid_file():
    """update.ps1 must reference the PID file path (regression guard)."""
    content = _read_script(UPDATE_PS1)
    # Windows path separator variant
    assert "data\\run_scheduler.pid" in content or PID_FILE_REF in content, (
        "update.ps1 does not reference the PID file path. "
        "It must stop the scheduler via the PID file, not taskkill /f."
    )


def test_update_sh_does_not_use_pkill():
    """update.sh must not contain 'pkill -f' (forbidden anti-pattern)."""
    content = _read_script(UPDATE_SH)
    assert "pkill -f" not in content, (
        "update.sh contains 'pkill -f'. "
        "Use the PID file mechanism instead."
    )


def test_update_ps1_does_not_use_pkill():
    """update.ps1 must not contain 'pkill -f' (forbidden anti-pattern)."""
    content = _read_script(UPDATE_PS1)
    assert "pkill -f" not in content, (
        "update.ps1 contains 'pkill -f'. "
        "Use the PID file mechanism instead."
    )


def test_update_sh_does_not_use_git_stash():
    """update.sh must not silently git stash (forbidden anti-pattern)."""
    content = _read_script(UPDATE_SH)
    assert "git stash" not in content, (
        "update.sh contains 'git stash'. "
        "Silent stashing would mask intentional config edits — refuse instead."
    )


def test_update_ps1_does_not_use_git_stash():
    """update.ps1 must not silently git stash (forbidden anti-pattern)."""
    content = _read_script(UPDATE_PS1)
    assert "git stash" not in content, (
        "update.ps1 contains 'git stash'. "
        "Silent stashing would mask intentional config edits — refuse instead."
    )
