"""Tests for src/proxy_manager.py."""

import os
import tempfile

import pytest


class TestLoadProxies:
    """Tests for the load_proxies function."""

    def test_parses_standard_format(self):
        """host:port:user:pass → http://host:port (credentials ignored)"""
        from src.proxy_manager import load_proxies

        content = (
            "proxy1.example.com:8080:userABC:passXYZ\n"
            "proxy2.example.com:9090:user2:pass2\n"
        )
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == [
                "http://proxy1.example.com:8080",
                "http://proxy2.example.com:9090",
            ]
        finally:
            os.unlink(path)

    def test_skips_blank_lines_and_comments(self):
        from src.proxy_manager import load_proxies

        content = (
            "# This is a comment\n"
            "\n"
            "host1.com:80:u:p\n"
            "\n"
            "# Another comment\n"
            "host2.com:80:u2:p2\n"
        )
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert len(result) == 2
        finally:
            os.unlink(path)

    def test_skips_malformed_lines_and_logs_warning(self, caplog):
        from src.proxy_manager import load_proxies

        content = "host1.com:80:u:p\nbadline\nhost2.com:80:u2:p2\n"
        path = self._write_temp(content)
        try:
            import logging

            with caplog.at_level(logging.WARNING):
                result = load_proxies(path)
            assert len(result) == 2
            assert "Skipping malformed proxy line" in caplog.text
        finally:
            os.unlink(path)

    def test_load_proxies_two_part_format(self):
        """host:port format (no credentials) is accepted."""
        from src.proxy_manager import load_proxies

        content = "86.90.97.144:3128\n"
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == ["http://86.90.97.144:3128"]
        finally:
            os.unlink(path)

    def test_load_proxies_four_part_format_drops_credentials(self):
        """host:port:user:pass format accepted; credentials are dropped."""
        from src.proxy_manager import load_proxies

        content = "86.90.97.144:3128:user:pass\n"
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == ["http://86.90.97.144:3128"]
        finally:
            os.unlink(path)

    def test_load_proxies_malformed_line_skipped(self):
        """3-part and 1-part lines are skipped; valid lines still load."""
        from src.proxy_manager import load_proxies

        content = "badline\n86.90.97.144:3128\n"
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == ["http://86.90.97.144:3128"]
        finally:
            os.unlink(path)

    def test_load_proxies_comments_and_blanks_skipped(self):
        """Comment lines and blank lines are ignored."""
        from src.proxy_manager import load_proxies

        content = "# comment\n\n86.90.97.144:3128\n"
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == ["http://86.90.97.144:3128"]
        finally:
            os.unlink(path)

    def test_raises_file_not_found(self):
        from src.proxy_manager import load_proxies

        with pytest.raises(FileNotFoundError):
            load_proxies("/nonexistent/path/proxies.txt")

    def test_empty_file_returns_empty_list(self):
        from src.proxy_manager import load_proxies

        path = self._write_temp("# Only comments\n\n")
        try:
            result = load_proxies(path)
            assert result == []
        finally:
            os.unlink(path)

    @staticmethod
    def _write_temp(content: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            return f.name
