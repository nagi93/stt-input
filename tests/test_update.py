"""Pure helpers of tools/update.py (the orchestration itself is Windows-
and network-bound and is verified on a real install instead)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from update import needs_update, parse_pids  # noqa: E402


def test_parse_pids_plain_lines():
    assert parse_pids("1234\n5678\n") == [1234, 5678]


def test_parse_pids_crlf_and_blank_lines():
    assert parse_pids("\r\n 42 \r\n\r\n") == [42]


def test_parse_pids_ignores_noise():
    assert parse_pids("PID\nabc\n12x\n") == []


def test_parse_pids_empty():
    assert parse_pids("") == []


def test_needs_update_same_and_clean():
    assert needs_update("abc", "abc", False) is False


def test_needs_update_new_commit():
    assert needs_update("abc", "def", False) is True


def test_needs_update_dirty_tree():
    assert needs_update("abc", "abc", True) is True
