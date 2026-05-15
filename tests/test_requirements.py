from pathlib import Path


def test_requirements_explicitly_include_primp() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    requirements = (
        (repo_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    )

    assert "primp>=0.15.0,<1.0" in requirements
