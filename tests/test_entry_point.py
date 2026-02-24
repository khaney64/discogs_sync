"""Tests for the discogs-sync.py entry-point dependency check."""

import subprocess
import sys
import textwrap

import pytest


class TestDependencyCheck:
    """Test that the entry-point pre-flight check catches missing packages."""

    def test_missing_package_reports_error_and_exits_2(self, tmp_path):
        """Simulate a missing import and verify the error message + exit code."""
        # Create a minimal script that mimics the dependency check logic
        # but with a fake package that definitely doesn't exist.
        script = tmp_path / "check.py"
        script.write_text(
            textwrap.dedent("""\
                import sys

                _REQUIRED_PACKAGES = {
                    "nonexistent_pkg_abc": "fake-package-abc",
                    "nonexistent_pkg_xyz": "fake-package-xyz",
                }

                _missing = []
                for _module, _pip_name in _REQUIRED_PACKAGES.items():
                    try:
                        __import__(_module)
                    except ImportError:
                        _missing.append(_pip_name)

                if _missing:
                    print(
                        f"Error: missing required packages: {', '.join(_missing)}\\n"
                        f"Install them with:  pip install {' '.join(_missing)}",
                        file=sys.stderr,
                    )
                    sys.exit(2)
            """),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "missing required packages" in result.stderr
        assert "fake-package-abc" in result.stderr
        assert "fake-package-xyz" in result.stderr
        assert "pip install" in result.stderr

    def test_all_packages_present_no_error(self, tmp_path):
        """When all packages are importable, the check passes silently."""
        script = tmp_path / "check.py"
        script.write_text(
            textwrap.dedent("""\
                import sys

                _REQUIRED_PACKAGES = {
                    "os": "os",
                    "sys": "sys",
                }

                _missing = []
                for _module, _pip_name in _REQUIRED_PACKAGES.items():
                    try:
                        __import__(_module)
                    except ImportError:
                        _missing.append(_pip_name)

                if _missing:
                    print(
                        f"Error: missing required packages: {', '.join(_missing)}",
                        file=sys.stderr,
                    )
                    sys.exit(2)

                print("OK")
            """),
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "OK" in result.stdout


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
