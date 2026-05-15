from pathlib import Path


def test_requirements_explicitly_include_primp() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    requirement_lines = (
        (repo_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    )

    normalized_lines = [
        line.split("#", maxsplit=1)[0].strip().replace(" ", "").lower()
        for line in requirement_lines
    ]

    primp_line = next(
        (line for line in normalized_lines if line.startswith("primp")), None
    )

    assert primp_line is not None
    assert ">=0.15.0" in primp_line
    assert "<1.0" in primp_line
