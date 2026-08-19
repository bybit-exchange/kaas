"""Tests for kb_ai._fadvise module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kb_ai._fadvise import (
    _HAS_FADVISE,
    evict_after_open_read,
    read_head_and_evict,
    read_text_and_evict,
)


class TestReadTextAndEvict:
    """Tests for read_text_and_evict."""

    def test_reads_entire_file(self, tmp_path: Path) -> None:
        p = tmp_path / "hello.txt"
        p.write_text("Hello, world!", encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == "Hello, world!"

    def test_reads_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == ""

    def test_reads_multiline(self, tmp_path: Path) -> None:
        content = "line1\nline2\nline3\n"
        p = tmp_path / "multi.txt"
        p.write_text(content, encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == content

    def test_reads_large_file_chunked(self, tmp_path: Path) -> None:
        # Create a file larger than the 64KB chunk size
        content = "x" * 100_000
        p = tmp_path / "large.txt"
        p.write_text(content, encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == content
        assert len(result) == 100_000

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        p = tmp_path / "str_path.txt"
        p.write_text("via string", encoding="utf-8")
        result = read_text_and_evict(str(p))
        assert result == "via string"

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        p = tmp_path / "path_obj.txt"
        p.write_text("via Path", encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == "via Path"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.txt"
        with pytest.raises(OSError):
            read_text_and_evict(p)

    def test_preserves_utf8_content(self, tmp_path: Path) -> None:
        content = "日本語テスト\n🎉 emoji"
        p = tmp_path / "utf8.txt"
        p.write_text(content, encoding="utf-8")
        result = read_text_and_evict(p)
        assert result == content

    def test_no_error_on_macos(self, tmp_path: Path) -> None:
        """Verify no error is raised regardless of platform."""
        p = tmp_path / "platform.txt"
        p.write_text("works", encoding="utf-8")
        # Should not raise on any platform
        result = read_text_and_evict(p)
        assert result == "works"


class TestReadHeadAndEvict:
    """Tests for read_head_and_evict."""

    def test_truncates_to_max_bytes(self, tmp_path: Path) -> None:
        content = "a" * 1000
        p = tmp_path / "long.txt"
        p.write_text(content, encoding="utf-8")
        result = read_head_and_evict(p, 100)
        assert len(result) == 100
        assert result == "a" * 100

    def test_returns_full_content_when_smaller(self, tmp_path: Path) -> None:
        content = "short"
        p = tmp_path / "short.txt"
        p.write_text(content, encoding="utf-8")
        result = read_head_and_evict(p, 1000)
        assert result == "short"

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = read_head_and_evict(p, 100)
        assert result == ""

    def test_decodes_with_replace_on_invalid_utf8(self, tmp_path: Path) -> None:
        # Write raw bytes with invalid UTF-8 sequence
        p = tmp_path / "invalid.bin"
        p.write_bytes(b"hello\xff\xfeworld")
        result = read_head_and_evict(p, 100)
        assert "hello" in result
        assert "world" in result
        assert "\ufffd" in result  # replacement character

    def test_truncation_mid_multibyte(self, tmp_path: Path) -> None:
        # UTF-8 multibyte: each CJK char is 3 bytes
        content = "日本語"  # 9 bytes
        p = tmp_path / "cjk.txt"
        p.write_text(content, encoding="utf-8")
        # Read only 5 bytes — cuts mid-character
        result = read_head_and_evict(p, 5)
        # First char "日" (3 bytes) decoded ok, then partial bytes → U+FFFD
        assert result[0] == "日"
        assert "\ufffd" in result

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        p = tmp_path / "str.txt"
        p.write_text("data", encoding="utf-8")
        result = read_head_and_evict(str(p), 100)
        assert result == "data"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nope.txt"
        with pytest.raises(OSError):
            read_head_and_evict(p, 100)

    def test_max_bytes_zero(self, tmp_path: Path) -> None:
        p = tmp_path / "file.txt"
        p.write_text("content", encoding="utf-8")
        result = read_head_and_evict(p, 0)
        assert result == ""

    def test_exact_file_size(self, tmp_path: Path) -> None:
        content = "exact"
        p = tmp_path / "exact.txt"
        p.write_text(content, encoding="utf-8")
        result = read_head_and_evict(p, 5)
        assert result == "exact"


class TestEvictAfterOpenRead:
    """Tests for evict_after_open_read."""

    def test_no_error_on_regular_file(self, tmp_path: Path) -> None:
        p = tmp_path / "file.txt"
        p.write_text("test", encoding="utf-8")
        with open(p, "rb") as f:
            f.read()
            # Should not raise on any platform
            evict_after_open_read(f)

    def test_no_error_on_text_mode_file(self, tmp_path: Path) -> None:
        p = tmp_path / "file.txt"
        p.write_text("test", encoding="utf-8")
        with open(p, "r") as f:
            f.read()
            evict_after_open_read(f)

    def test_no_error_on_macos(self, tmp_path: Path) -> None:
        """Regardless of platform, should never raise."""
        p = tmp_path / "ok.txt"
        p.write_text("ok", encoding="utf-8")
        with open(p, "rb") as f:
            f.read()
            evict_after_open_read(f)


class TestHasFadvise:
    """Tests for the _HAS_FADVISE flag."""

    def test_flag_is_boolean(self) -> None:
        assert isinstance(_HAS_FADVISE, bool)

    def test_matches_os_capability(self) -> None:
        assert _HAS_FADVISE == hasattr(os, "posix_fadvise")
