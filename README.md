# Presence Checker

A web tool for recording student attendance at KSE lectures.

## How it works

1. Teacher runs the server — a public URL is created via Cloudflare Tunnel (or ngrok)
2. Admin dashboard shows a QR code valid for **60 seconds**
3. Students scan the QR with their phone → sign in with `@kse.org.ua` Google account
4. Attendance is recorded in a Google Sheet (rows = students, columns = class dates)
5. Teacher manually rotates the QR via the **Rotate QR** button when needed

## Setup

### Prerequisites
- Python 3.11+
- Google Cloud project with Sheets API + Drive API enabled
- OAuth 2.0 Web Client credentials (`credentials/oauth_client.json`)
- Service Account credentials (`credentials/service_account.json`)
- The target Google Sheet shared with the service account email (Editor)
- A tunnel: **Cloudflare Tunnel** (recommended) or ngrok

### Install
```bash
pip install -r requirements.txt
```

### Configure
Copy `.env.example` to `.env` and fill in:

| Variable | Where to get it |
|----------|----------------|
| `ADMIN_KEY` | Pick any password |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GOOGLE_SPREADSHEET_ID` | From the Sheet URL |
| `COURSE_NAME` | Becomes the worksheet tab name |

#### Tunnel: Cloudflare (recommended)

Reliable on all devices including iOS Safari. Requires a domain connected to Cloudflare.

1. Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Login: `cloudflared tunnel login`
3. Create tunnel: `cloudflared tunnel create <name>`
4. Route DNS: `cloudflared tunnel route dns <name> attendance.yourdomain.com`
5. Set in `.env`:
```env
TUNNEL_MODE=cloudflare
CLOUDFLARE_PUBLIC_URL=https://attendance.yourdomain.com
CLOUDFLARE_TUNNEL_NAME=<name>
```

#### Tunnel: ngrok (fallback)

May be blocked on some mobile networks / iOS Safari.

```env
TUNNEL_MODE=ngrok
NGROK_AUTH_TOKEN=...   # from https://dashboard.ngrok.com
NGROK_DOMAIN=...       # your free static ngrok domain
```

### Run
```bash
python run.py
```

The tunnel starts automatically. Open `http://localhost:8000/admin` in your browser.

## Google Sheet layout

| Student | Name | 2026-05-12 10:00 | 2026-05-19 10:00 |
|---------|------|-----------------|-----------------|
| alice@kse.org.ua | Alice S. | ✓ | |
| bob@kse.org.ua | Bob K. | | ✓ |
