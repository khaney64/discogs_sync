"""Tests for token configuration and the auth flow."""

import json
from unittest.mock import MagicMock, patch

import pytest

from discogs_sync import config
from discogs_sync.client_factory import build_client
from discogs_sync.exceptions import AuthenticationError


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "get_config_path", lambda: path)
    monkeypatch.delenv(config.TOKEN_ENV_VAR, raising=False)
    return path


class TestGetTokens:
    def test_env_var_takes_precedence(self, fake_config, monkeypatch):
        fake_config.write_text(json.dumps({"auth_mode": "token", "user_token": "file-token"}))
        monkeypatch.setenv(config.TOKEN_ENV_VAR, "env-token")

        assert config.get_tokens()["user_token"] == "env-token"

    def test_file_token_used_without_env(self, fake_config):
        fake_config.write_text(json.dumps({"auth_mode": "token", "user_token": "file-token", "username": "me"}))

        tokens = config.get_tokens()

        assert tokens["user_token"] == "file-token"
        assert tokens["username"] == "me"

    def test_legacy_oauth_config_is_not_used(self, fake_config):
        fake_config.write_text(json.dumps({"access_token": "a", "access_token_secret": "b"}))

        assert config.get_tokens() is None

    def test_nothing_configured(self, fake_config):
        assert config.get_tokens() is None

    def test_clear_tokens_removes_legacy_oauth_keys(self, fake_config):
        fake_config.write_text(json.dumps({"access_token": "a", "consumer_secret": "c", "cache_ttl_hours": 2}))

        config.clear_tokens()

        assert json.loads(fake_config.read_text()) == {"cache_ttl_hours": 2}


class TestBuildClient:
    def test_raises_when_not_authenticated(self, fake_config):
        with pytest.raises(AuthenticationError, match="DISCOGS_USER_TOKEN"):
            build_client()

    @patch("discogs_sync.client_factory.discogs_client.Client")
    def test_uses_env_token(self, mock_client, fake_config, monkeypatch):
        monkeypatch.setenv(config.TOKEN_ENV_VAR, "env-token")

        build_client()

        assert mock_client.call_args.kwargs == {"user_token": "env-token"}


class TestTokenAuthFlow:
    @patch("discogs_sync.auth.save_user_token")
    @patch("discogs_sync.auth.discogs_client.Client")
    @patch("discogs_sync.auth.click.prompt", return_value="secret-token")
    def test_prompt_hides_input_and_saves(self, mock_prompt, mock_client, mock_save):
        from discogs_sync.auth import run_token_auth_flow

        mock_client.return_value.identity.return_value = MagicMock(username="me")

        result = run_token_auth_flow()

        assert mock_prompt.call_args.kwargs["hide_input"] is True
        mock_save.assert_called_once_with("secret-token", "me")
        assert result["username"] == "me"

    @patch("discogs_sync.auth.save_user_token")
    @patch("discogs_sync.auth.discogs_client.Client")
    @patch("discogs_sync.auth.click.prompt", return_value="bad-token")
    def test_invalid_token_not_saved(self, _mock_prompt, mock_client, mock_save):
        from discogs_sync.auth import run_token_auth_flow

        mock_client.return_value.identity.side_effect = Exception("401")

        with pytest.raises(AuthenticationError):
            run_token_auth_flow()

        mock_save.assert_not_called()
