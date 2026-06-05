"""Project-wide pytest fixtures."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _block_ntfy():
    """Prevent real ntfy.sh notifications during the test suite.

    Patches urllib.request.urlopen to raise RuntimeError on any call so no
    test can accidentally POST to ntfy.sh.  Tests in test_notifier.py that
    need fake HTTP responses re-patch urlopen inside their own
    ``with patch(...)`` blocks, which take precedence over this fixture.
    send_alert() catches all exceptions and returns False, so callers that
    don't explicitly mock send_alert still behave correctly.
    """
    with patch(
        "urllib.request.urlopen",
        side_effect=RuntimeError("Real HTTP calls are blocked in tests"),
    ):
        yield
