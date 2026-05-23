"""Tests for src/proxy_manager.py."""

import os
import tempfile

import pytest


class TestLoadProxies:
    """Tests for the load_proxies function."""

    def test_parses_standard_format(self):
        """host:port:user:pass → http://user:pass@host:port"""
        from src.proxy_manager import load_proxies

        content = "proxy1.example.com:8080:userABC:passXYZ\nproxy2.example.com:9090:user2:pass2\n"
        path = self._write_temp(content)
        try:
            result = load_proxies(path)
            assert result == [
                "http://userABC:passXYZ@proxy1.example.com:8080",
                "http://user2:pass2@proxy2.example.com:9090",
            ]
        finally:
            os.unlink(path)

    def test_skips_blank_lines_and_comments(self):
        from src.proxy_manager import load_proxies

        content = "# This is a comment\n\nhost1.com:80:u:p\n\n# Another comment\nhost2.com:80:u2:p2\n"
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


class TestProxyRotator:
    """Tests for the ProxyRotator class."""

    def test_rotates_round_robin(self):
        from src.proxy_manager import ProxyRotator

        proxies = ["http://a:a@h1:1", "http://b:b@h2:2", "http://c:c@h3:3"]
        rotator = ProxyRotator(proxies)

        # First cycle
        assert rotator.get_next() == "http://a:a@h1:1"
        assert rotator.get_next() == "http://b:b@h2:2"
        assert rotator.get_next() == "http://c:c@h3:3"
        # Wraps around
        assert rotator.get_next() == "http://a:a@h1:1"

    def test_returns_none_when_empty(self):
        from src.proxy_manager import ProxyRotator

        rotator = ProxyRotator([])
        assert rotator.get_next() is None

    def test_single_proxy_always_returns_same(self):
        from src.proxy_manager import ProxyRotator

        rotator = ProxyRotator(["http://x:x@h:1"])
        assert rotator.get_next() == "http://x:x@h:1"
        assert rotator.get_next() == "http://x:x@h:1"

    def test_len_returns_proxy_count(self):
        from src.proxy_manager import ProxyRotator

        assert len(ProxyRotator(["a", "b", "c"])) == 3
        assert len(ProxyRotator([])) == 0
