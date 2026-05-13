import hmac
import logging
from contextlib import asynccontextmanager
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))
# Default asyncio executor is min(32, cpu+4) workers — too small for 70+
# concurrent OAuth callbacks (each runs httpx.exchange_code in a thread).
THREAD_POOL_SIZE = 100


class _AccessLogFilter(logging.Filter):
    """Drop uvicorn access logs for dashboard-polled endpoints."""

    QUIET_PATHS = ("/admin/attendees",)

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self.QUIET_PATHS)


logging.getLogger("uvicorn.access").addFilter(_AccessLogFilter())

from fastapi import Cookie, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadData, BadSignature, URLSafeSerializer

import auth
import qr_manager
import sheets
import tunnel
from config import settings

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_session_dt: datetime = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _session_dt
    _session_dt = datetime.now(TZ)
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE, thread_name_prefix="pc")
    )
    sheets.init_client()
    public_url = tunnel.start()
    qr_manager.set_public_url(public_url)
    print(f"\n  Public URL: {public_url}")
    print(f"  Admin:      http://localhost:8000/admin/login\n")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_signer = URLSafeSerializer(settings.secret_key, salt="admin-session")

# ---------------------------------------------------------------------------
# Admin auth helpers
# ---------------------------------------------------------------------------


def _sign_admin_cookie() -> str:
    return _signer.dumps("ok")


def _verify_admin_cookie(value: str | None) -> bool:
    if not value:
        return False
    try:
        return _signer.loads(value) == "ok"
    except BadSignature:
        return False


def _check_admin(admin_session: str | None) -> bool:
    return _verify_admin_cookie(admin_session)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_login.html")


@app.post("/admin/login")
async def admin_login(response: Response, key: str = Form(...)):
    if not hmac.compare_digest(key, settings.admin_key):
        return HTMLResponse("<p>Wrong key. <a href='/admin/login'>Try again</a></p>", status_code=401)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("admin_session", _sign_admin_cookie(), httponly=True, samesite="lax")
    return resp


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return RedirectResponse("/admin/login")
    attendees = sheets.list_present(settings.course_name, _session_dt)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "course": settings.course_name,
            "session_dt": _session_dt.strftime("%Y-%m-%d %H:%M UTC+3"),
            "attendees": attendees,
            "public_url": tunnel.get_public_url(),
        },
    )


# ---------------------------------------------------------------------------
# Attendees poll endpoint (called by admin dashboard JS every 5s)
# ---------------------------------------------------------------------------


@app.get("/admin/attendees")
async def admin_attendees(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        result = await asyncio.to_thread(sheets.list_present, settings.course_name, _session_dt)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/admin/flush")
async def admin_flush(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        stats = await asyncio.to_thread(
            sheets.flush_to_sheets, settings.course_name, _session_dt
        )
        return JSONResponse(stats)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# QR endpoints
# ---------------------------------------------------------------------------


@app.get("/qr.png")
async def qr_image(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return Response(status_code=401)
    png = qr_manager.generate_qr_png()
    return StreamingResponse(iter([png]), media_type="image/png")


@app.get("/qr/token")
async def qr_token_info(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(qr_manager.get_token_info())


@app.post("/qr/rotate")
async def qr_rotate(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    qr_manager.rotate_now()
    return JSONResponse(qr_manager.get_token_info())



# ---------------------------------------------------------------------------
# Student attendance routes
# ---------------------------------------------------------------------------


@app.get("/attend/{token}")
async def attend(token: str, request: Request, response: Response):
    if not qr_manager.validate_token(token):
        return HTMLResponse(
            "<h2>QR code expired or invalid.</h2><p>Ask your teacher to show a fresh QR.</p>",
            status_code=410,
        )
    state = auth.generate_state()
    redirect_uri = _callback_uri(request)
    auth_url = auth.build_authorization_url(redirect_uri, state)

    resp = RedirectResponse(auth_url)
    # Store token + state in a short-lived cookie so callback can validate
    _state_signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")
    resp.set_cookie(
        "oauth_state",
        _state_signer.dumps({"state": state, "token": token}),
        httponly=True,
        max_age=120,
        samesite="lax",
    )
    return resp


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
):
    if error or not code:
        return HTMLResponse(f"<h2>Sign-in cancelled or failed: {error}</h2>", status_code=400)

    import traceback
    try:
        return await _auth_callback_inner(request, code, state, oauth_state)
    except Exception as exc:
        return HTMLResponse(f"<h2>Unexpected error</h2><pre>{traceback.format_exc()}</pre>", status_code=500)

    return None  # handled by _auth_callback_inner above


async def _auth_callback_inner(
    request: Request,
    code: str,
    state: str | None,
    oauth_state: str | None,
):
    _state_signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")
    try:
        saved = _state_signer.loads(oauth_state or "")
    except (BadSignature, BadData, Exception) as exc:
        return HTMLResponse(f"<h2>Invalid session: {exc}</h2><p>Please scan the QR again.</p>", status_code=400)

    if saved.get("state") != state:
        return HTMLResponse("<h2>CSRF check failed. Please scan the QR again.</h2>", status_code=400)

    # The signed cookie proves the QR was valid when scanned (we only set it
    # after qr_manager.validate_token passed in /attend). The browser-enforced
    # max_age=120s on that cookie bounds replay. Re-checking the token here
    # would fail any student who takes >60s to finish Google OAuth.

    redirect_uri = _callback_uri(request)
    try:
        userinfo = await asyncio.to_thread(auth.exchange_code, code, redirect_uri)
    except Exception as exc:
        return HTMLResponse(f"<h2>Token exchange failed: {exc}</h2>", status_code=500)

    if not auth.check_domain(userinfo):
        email = userinfo.get("email", "unknown")
        return HTMLResponse(
            f"<h2>Access denied.</h2><p>{email} is not a @kse.org.ua account.</p>",
            status_code=403,
        )

    email = userinfo["email"]
    name = userinfo.get("name", email)
    try:
        await asyncio.to_thread(sheets.mark_present, email, name, settings.course_name, _session_dt)
    except Exception as exc:
        return HTMLResponse(f"<h2>Could not record attendance: {exc}</h2>", status_code=500)

    resp = RedirectResponse("/success", status_code=303)
    resp.delete_cookie("oauth_state")
    _name_signer = URLSafeSerializer(settings.secret_key, salt="student-name")
    resp.set_cookie(
        "student_name",
        _name_signer.dumps(userinfo.get("name", email)),
        httponly=True,
        max_age=60,
        samesite="lax",
    )
    return resp


@app.get("/success", response_class=HTMLResponse)
async def success(request: Request, student_name: str | None = Cookie(default=None)):
    name = "Student"
    if student_name:
        _name_signer = URLSafeSerializer(settings.secret_key, salt="student-name")
        try:
            name = _name_signer.loads(student_name)
        except BadSignature:
            pass
    return templates.TemplateResponse(
        request=request,
        name="success.html",
        context={"name": name, "course": settings.course_name},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _callback_uri(request: Request) -> str:
    public = tunnel.get_public_url()
    if public:
        return f"{public}/auth/callback"
    return str(request.url_for("auth_callback"))
