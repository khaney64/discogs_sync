"""Tests for the discogs-sync.py entry-point dependency check."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "discogs-sync.py"


def _run_script(tmp_path, *args, python_flags=()):
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    env.pop("DISCOGS_USER_TOKEN", None)
    return subprocess.run(
        [sys.executable, *python_flags, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestDependencyCheck:
    """Test the real entry point's pre-flight dependency check."""

    def test_missing_packages_report_install_command_and_exit_2(self, tmp_path):
        # -I -S: isolated mode without site-packages, so no dependency is importable
        result = _run_script(tmp_path, "--help", python_flags=("-I", "-S"))

        assert result.returncode == 2
        assert "missing required packages" in result.stderr
        assert "python3-discogs-client" in result.stderr
        assert "pip install -r" in result.stderr

    def test_packages_present_runs_cli(self, tmp_path):
        result = _run_script(tmp_path, "--help")

        assert result.returncode == 0
        assert "wantlist" in result.stdout

    def test_entry_point_does_not_spawn_or_exec(self):
        source = SCRIPT.read_text(encoding="utf-8")

        for pattern in ("subprocess", "os.exec", "os.system", "__import__"):
            assert pattern not in source


class TestConfigPermissions:
    """Test that save_config sets restrictive file permissions."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions not applicable on Windows")
    def test_config_file_gets_600_permissions(self, tmp_path, monkeypatch):
        """After save_config, the file should have 0o600 permissions."""
        import stat
        from discogs_sync import config

        fake_config = tmp_path / "config.json"
        monkeypatch.setattr(config, "get_config_path", lambda: fake_config)

        config.save_config({"auth_mode": "token", "user_token": "test123"})

        assert fake_config.exists()
        mode = fake_config.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
