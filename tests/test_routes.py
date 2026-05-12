from unittest.mock import patch, MagicMock
import pytest
import qr_manager


# --- Admin login ---

def test_admin_login_page_returns_200(client):
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "Admin" in r.text


def test_admin_login_wrong_key_returns_401(client):
    r = client.post("/admin/login", data={"key": "wrongpassword"}, follow_redirects=False)
    assert r.status_code == 401


def test_admin_login_correct_key_sets_cookie_and_redirects(client):
    r = client.post("/admin/login", data={"key": "testkey"}, follow_redirects=False)
    assert r.status_code == 303
    assert "admin_session" in r.cookies


def test_admin_dashboard_without_cookie_redirects(anon_client):
    r = anon_client.get("/admin", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/admin/login" in r.headers["location"]


def test_admin_dashboard_with_valid_cookie(client, admin_cookie):
    with patch("sheets.list_present", return_value=[]):
        r = client.get("/admin", cookies={"admin_session": admin_cookie})
    assert r.status_code == 200
    assert "QR" in r.text


# --- QR rotate ---

def test_qr_rotate_without_cookie_returns_401(anon_client):
    r = anon_client.post("/qr/rotate")
    assert r.status_code == 401


def test_qr_rotate_with_valid_cookie_returns_new_token(client, admin_cookie):
    old_token = qr_manager.get_token_info()["token"]
    r = client.post("/qr/rotate", cookies={"admin_session": admin_cookie})
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["token"] != old_token


# --- /attend/{token} ---

def test_attend_invalid_token_returns_410(client):
    r = client.get("/attend/not-a-real-token", follow_redirects=False)
    assert r.status_code == 410


def test_attend_valid_token_redirects_to_google(client):
    token = qr_manager.get_token_info()["token"]
    with patch("builtins.open", MagicMock()), \
         patch("json.load", return_value={"web": {"client_id": "fake", "client_secret": "s"}}):
        r = client.get(f"/attend/{token}", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


def test_attend_expired_token_returns_410(client):
    from datetime import datetime, timezone, timedelta
    qr_manager.get_token_info()
    past = datetime.now(timezone.utc) - timedelta(seconds=61)
    with patch.object(qr_manager, "_token_issued_at", past):
        r = client.get(f"/attend/{qr_manager._current_token}", follow_redirects=False)
    assert r.status_code == 410


# --- /auth/callback ---

def test_callback_missing_code_returns_400(client):
    r = client.get("/auth/callback?error=access_denied")
    assert r.status_code == 400


def test_callback_invalid_state_cookie_returns_400(client):
    r = client.get(
        "/auth/callback?code=abc&state=xyz",
        headers={"Cookie": "oauth_state=invalid-garbage"},
    )
    assert r.status_code == 400


def test_callback_non_kse_email_returns_403(client):
    from itsdangerous import URLSafeSerializer
    from config import settings

    token = qr_manager.get_token_info()["token"]
    state = "teststate123"
    signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")
    signed_cookie = signer.dumps({"state": state, "token": token})

    fake_userinfo = {"email": "hacker@gmail.com", "hd": "gmail.com", "name": "Hacker"}

    with patch("asyncio.to_thread", side_effect=_sync), \
         patch("auth.exchange_code", return_value=fake_userinfo):
        r = client.get(
            f"/auth/callback?code=abc&state={state}",
            headers={"Cookie": f"oauth_state={signed_cookie}"},
        )

    assert r.status_code == 403
    assert "Access denied" in r.text


def test_callback_valid_kse_email_records_and_redirects(client):
    from itsdangerous import URLSafeSerializer
    from config import settings

    token = qr_manager.get_token_info()["token"]
    state = "teststate456"
    signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")
    signed_cookie = signer.dumps({"state": state, "token": token})

    fake_userinfo = {"email": "student@kse.org.ua", "hd": "kse.org.ua", "name": "Test Student"}

    with patch("asyncio.to_thread", side_effect=_sync), \
         patch("auth.exchange_code", return_value=fake_userinfo), \
         patch("sheets.mark_present"):
        r = client.get(
            f"/auth/callback?code=abc&state={state}",
            follow_redirects=False,
            headers={"Cookie": f"oauth_state={signed_cookie}"},
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/success"


# --- /admin/attendees ---

def test_attendees_returns_list(client, admin_cookie):
    with patch("asyncio.to_thread", side_effect=_sync), \
         patch("sheets.list_present", return_value=["alice@kse.org.ua"]):
        r = client.get("/admin/attendees", cookies={"admin_session": admin_cookie})
    assert r.status_code == 200
    assert "alice@kse.org.ua" in r.json()


def test_attendees_without_cookie_returns_401(anon_client):
    r = anon_client.get("/admin/attendees")
    assert r.status_code == 401


# Helper: replaces asyncio.to_thread — must be async so `await` works
async def _sync(fn, *args, **kwargs):
    return fn(*args, **kwargs)
