import os
import sys

# Set test env vars before any app imports so pydantic-settings picks them up
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-padding-xx"
os.environ["ADMIN_KEY"] = "testkey"
os.environ["GOOGLE_SPREADSHEET_ID"] = "fake-sheet-id"
os.environ["NGROK_AUTH_TOKEN"] = ""
os.environ["NGROK_DOMAIN"] = ""
os.environ["COURSE_NAME"] = "TestCourse"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from itsdangerous import URLSafeSerializer


@pytest.fixture(scope="session")
def client():
    with patch("tunnel.start", return_value="https://test.ngrok.io"), \
         patch("tunnel.get_public_url", return_value="https://test.ngrok.io"):
        import main
        with TestClient(main.app) as c:
            yield c


@pytest.fixture
def anon_client(client):
    """Shared client with cookies cleared for the duration of the test."""
    saved = dict(client.cookies)
    client.cookies.clear()
    yield client
    client.cookies.update(saved)


@pytest.fixture(scope="session")
def admin_cookie(client):
    """Returns a valid signed admin session cookie value."""
    from config import settings
    signer = URLSafeSerializer(settings.secret_key, salt="admin-session")
    return signer.dumps("ok")
