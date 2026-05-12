import io
import uuid
from datetime import datetime, timezone

import qrcode
from qrcode.image.pil import PilImage

TOKEN_TTL_SECONDS = 60

_current_token: str = ""
_token_issued_at: datetime = datetime.min.replace(tzinfo=timezone.utc)
_public_url: str = ""


def set_public_url(url: str) -> None:
    global _public_url
    _public_url = url.rstrip("/")


def _rotate() -> None:
    global _current_token, _token_issued_at
    _current_token = str(uuid.uuid4())
    _token_issued_at = datetime.now(timezone.utc)


def get_token_info() -> dict:
    if not _current_token:
        _rotate()
    age = (datetime.now(timezone.utc) - _token_issued_at).total_seconds()
    return {
        "token": _current_token,
        "remaining_seconds": max(0, TOKEN_TTL_SECONDS - int(age)),
        "expired": age >= TOKEN_TTL_SECONDS,
    }


def validate_token(token: str) -> bool:
    if token != _current_token:
        return False
    age = (datetime.now(timezone.utc) - _token_issued_at).total_seconds()
    return age < TOKEN_TTL_SECONDS


def rotate_now() -> None:
    _rotate()


def generate_qr_png() -> bytes:
    info = get_token_info()
    url = f"{_public_url}/attend/{info['token']}"
    img: PilImage = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
