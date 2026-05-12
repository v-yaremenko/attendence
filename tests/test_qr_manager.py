from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
import qr_manager


@pytest.fixture(autouse=True)
def reset_state():
    """Reset qr_manager global state before each test."""
    qr_manager._current_token = ""
    qr_manager._token_issued_at = datetime.min.replace(tzinfo=timezone.utc)
    qr_manager._public_url = "https://test.ngrok.io"
    yield


def test_token_generated_on_first_call():
    info = qr_manager.get_token_info()
    assert info["token"]
    assert 0 <= info["remaining_seconds"] <= 60
    assert not info["expired"]


def test_validate_correct_token():
    token = qr_manager.get_token_info()["token"]
    assert qr_manager.validate_token(token)


def test_validate_wrong_token():
    qr_manager.get_token_info()
    assert not qr_manager.validate_token("not-the-right-token")


def test_validate_empty_token():
    qr_manager.get_token_info()
    assert not qr_manager.validate_token("")


def test_rotate_invalidates_old_token():
    old_token = qr_manager.get_token_info()["token"]
    qr_manager.rotate_now()
    assert not qr_manager.validate_token(old_token)


def test_rotate_produces_new_valid_token():
    qr_manager.get_token_info()
    qr_manager.rotate_now()
    new_token = qr_manager.get_token_info()["token"]
    assert qr_manager.validate_token(new_token)


def test_expired_token_rejected():
    token = qr_manager.get_token_info()["token"]
    past = datetime.now(timezone.utc) - timedelta(seconds=61)
    with patch.object(qr_manager, "_token_issued_at", past):
        assert not qr_manager.validate_token(token)


def test_expired_flag_in_token_info():
    qr_manager.get_token_info()
    past = datetime.now(timezone.utc) - timedelta(seconds=61)
    with patch.object(qr_manager, "_token_issued_at", past):
        info = qr_manager.get_token_info()
        assert info["expired"]
        assert info["remaining_seconds"] == 0


def test_generate_qr_png_returns_bytes():
    png = qr_manager.generate_qr_png()
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG"  # PNG magic bytes
