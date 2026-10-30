"""Release boundaries: no secrets in scanner output and no unsafe evidence paths."""

import subprocess
from pathlib import Path

import pytest

from algofactory.delivery import contains_secret, safe_file, scan_history


def test_secret_detection_and_safe_reference_paths(tmp_path):
    assert contains_secret(b"prefix private-test-key suffix", (b"private-test-key",))
    assert contains_secret(b"ghp_" + b"Z" * 36)
    assert contains_secret(b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"A" * 64)
    assert not contains_secret(b"-----BEGIN OPENSSH PRIVATE KEY-----")
    assert not contains_secret(b"ALGOFACTORY_API_KEY=\n")
    with pytest.raises(ValueError):
        safe_file(tmp_path, "../hidden")
    (tmp_path / "link").symlink_to(Path("/tmp"))
    with pytest.raises(ValueError):
        safe_file(tmp_path, "link")


def test_history_scanner_finds_removed_secret_without_echoing_it(tmp_path):
    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=tmp_path)

    git("init", "--quiet")
    git("config", "user.name", "Release Test")
    git("config", "user.email", "test@example.invalid")
    path = tmp_path / "sample.txt"
    path.write_text("private-history-test-value")
    git("add", ".")
    git("commit", "--quiet", "-m", "fixture")
    path.write_text("clean current contents")
    git("add", ".")
    git("commit", "--quiet", "-m", "clean")
    result = scan_history(tmp_path, (b"private-history-test-value",))
    assert result["blobs_scanned"] == 2 and len(result["findings"]) == 1
    assert "private-history-test-value" not in str(result)
