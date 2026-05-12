import json
from unittest.mock import patch, MagicMock
import pytest
import auth


# --- check_domain ---

def test_check_domain_valid_email():
    assert auth.check_domain({"email": "student@kse.org.ua", "hd": "kse.org.ua"})


def test_check_domain_valid_via_hd_only():
    # hd claim alone is sufficient
    assert auth.check_domain({"email": "student@kse.org.ua", "hd": "kse.org.ua"})


def test_check_domain_rejects_gmail():
    assert not auth.check_domain({"email": "student@gmail.com", "hd": "gmail.com"})


def test_check_domain_rejects_wrong_hd():
    assert not auth.check_domain({"email": "student@other.com", "hd": "other.com"})


def test_check_domain_rejects_missing_email():
    assert not auth.check_domain({})


def test_check_domain_rejects_subdomain():
    # subdomain should not pass
    assert not auth.check_domain({"email": "student@sub.kse.org.ua"})


# --- generate_state ---

def test_generate_state_is_string():
    assert isinstance(auth.generate_state(), str)


def test_generate_state_unique():
    assert auth.generate_state() != auth.generate_state()


# --- build_authorization_url ---

FAKE_CLIENT_CONFIG = {
    "web": {
        "client_id": "fake-client-id.apps.googleusercontent.com",
        "client_secret": "fake-secret",
    }
}


def test_build_authorization_url_contains_hd():
    with patch("builtins.open", MagicMock()), \
         patch("json.load", return_value=FAKE_CLIENT_CONFIG):
        url = auth.build_authorization_url("https://test.ngrok.io/auth/callback", "state123")
    assert "hd=kse.org.ua" in url
    assert "state123" in url
    assert "fake-client-id" in url


def test_build_authorization_url_contains_redirect_uri():
    with patch("builtins.open", MagicMock()), \
         patch("json.load", return_value=FAKE_CLIENT_CONFIG):
        url = auth.build_authorization_url("https://example.com/callback", "s")
    assert "example.com" in url


# --- exchange_code ---

def test_exchange_code_returns_userinfo():
    fake_tokens = {"access_token": "tok123"}
    fake_userinfo = {"email": "student@kse.org.ua", "name": "Test Student", "hd": "kse.org.ua"}

    mock_response_token = MagicMock()
    mock_response_token.json.return_value = fake_tokens
    mock_response_token.raise_for_status = MagicMock()

    mock_response_info = MagicMock()
    mock_response_info.json.return_value = fake_userinfo
    mock_response_info.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_response_token
    mock_client.get.return_value = mock_response_info

    with patch("builtins.open", MagicMock()), \
         patch("json.load", return_value=FAKE_CLIENT_CONFIG), \
         patch("httpx.Client", return_value=mock_client):
        result = auth.exchange_code("auth-code", "https://test.ngrok.io/auth/callback")

    assert result["email"] == "student@kse.org.ua"
    assert result["name"] == "Test Student"
