import json
import secrets
from urllib.parse import urlencode

import httpx

from config import settings

ALLOWED_DOMAIN = "kse.org.ua"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _load_client_config() -> dict:
    with open(settings.google_oauth_client_json) as f:
        data = json.load(f)
    return data.get("web", data)


def build_authorization_url(redirect_uri: str, state: str) -> str:
    cfg = _load_client_config()
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "hd": ALLOWED_DOMAIN,  # hint — Google shows only @kse.org.ua accounts
        "access_type": "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange auth code for tokens; returns userinfo dict."""
    cfg = _load_client_config()
    with httpx.Client() as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        info_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        info_resp.raise_for_status()
        return info_resp.json()


def check_domain(userinfo: dict) -> bool:
    email: str = userinfo.get("email", "")
    hd: str = userinfo.get("hd", "")
    return email.endswith(f"@{ALLOWED_DOMAIN}") or hd == ALLOWED_DOMAIN
