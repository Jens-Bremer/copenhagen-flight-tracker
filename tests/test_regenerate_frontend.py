import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.regenerate_frontend import main
from src.frontend_csv_builder import (
    BUILD_ALL_UNPARSEABLE,
    BUILD_HEADER_INVALID,
    BUILD_INPUT_MISSING,
    BUILD_OK,
)


def _cfg_patch(tmp_path):
    """Return a config mock pointing db at tmp_path."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.DATABASE_PATH = str(tmp_path / "flights.db")
    return mock


def test_main_all_steps_succeed_returns_0(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=100),
        patch("scripts.regenerate_frontend.build", return_value=(95, BUILD_OK)),
        patch("scripts.regenerate_frontend.generate", return_value=95),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 0


def test_main_export_exception_returns_4(tmp_path):
    with (
        patch(
            "scripts.regenerate_frontend.export_to_csv",
            side_effect=OSError("disk full"),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 4


def test_main_build_input_missing_returns_2(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=0),
        patch(
            "scripts.regenerate_frontend.build",
            return_value=(0, BUILD_INPUT_MISSING),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 2


def test_main_build_header_invalid_returns_4(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=0),
        patch(
            "scripts.regenerate_frontend.build",
            return_value=(0, BUILD_HEADER_INVALID),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 4


def test_main_build_all_unparseable_returns_4(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=0),
        patch(
            "scripts.regenerate_frontend.build",
            return_value=(0, BUILD_ALL_UNPARSEABLE),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 4


def test_main_html_input_missing_returns_2(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=100),
        patch(
            "scripts.regenerate_frontend.build", return_value=(95, BUILD_OK)
        ),
        patch(
            "scripts.regenerate_frontend.generate",
            side_effect=FileNotFoundError("input file not found: x.csv"),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 2


def test_main_html_asset_missing_returns_3(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=100),
        patch(
            "scripts.regenerate_frontend.build", return_value=(95, BUILD_OK)
        ),
        patch(
            "scripts.regenerate_frontend.generate",
            side_effect=FileNotFoundError(
                "required frontend asset missing: styles.css"
            ),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 3


def test_main_html_runtime_error_returns_4(tmp_path):
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=100),
        patch(
            "scripts.regenerate_frontend.build", return_value=(95, BUILD_OK)
        ),
        patch(
            "scripts.regenerate_frontend.generate",
            side_effect=RuntimeError("boom"),
        ),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        assert main(["--data-dir", str(tmp_path)]) == 4


def test_main_calls_steps_in_order(tmp_path):
    """Pipeline steps run export → build → generate, in that order."""
    call_order = []

    def mock_export(*a, **kw):
        call_order.append("export")
        return 10

    def mock_build(*a, **kw):
        call_order.append("build")
        return (10, BUILD_OK)

    def mock_generate(*a, **kw):
        call_order.append("generate")
        return 10

    with (
        patch("scripts.regenerate_frontend.export_to_csv", side_effect=mock_export),
        patch("scripts.regenerate_frontend.build", side_effect=mock_build),
        patch("scripts.regenerate_frontend.generate", side_effect=mock_generate),
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        main(["--data-dir", str(tmp_path)])

    assert call_order == ["export", "build", "generate"]


def test_main_generate_not_called_if_build_fails(tmp_path):
    """generate must not be called when build returns a failure status."""
    with (
        patch("scripts.regenerate_frontend.export_to_csv", return_value=0),
        patch(
            "scripts.regenerate_frontend.build",
            return_value=(0, BUILD_INPUT_MISSING),
        ),
        patch(
            "scripts.regenerate_frontend.generate"
        ) as mock_generate,
        patch("scripts.regenerate_frontend.config", _cfg_patch(tmp_path)),
    ):
        main(["--data-dir", str(tmp_path)])
    mock_generate.assert_not_called()
