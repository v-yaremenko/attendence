# Presence Checker

A web tool for recording student attendance at KSE lectures.

## How it works

1. Teacher runs the server — a public URL is created via ngrok
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
- ngrok account (free) with a static domain

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
| `NGROK_AUTH_TOKEN` | [ngrok dashboard](https://dashboard.ngrok.com) |
| `NGROK_DOMAIN` | Your free static ngrok domain |
| `COURSE_NAME` | Becomes the worksheet tab name |

### Run
```bash
python run.py
```

Open `http://localhost:8000/admin/login`, enter `ADMIN_KEY`.

## Google Sheet layout

| Student | Name | 2026-05-12 10:00 | 2026-05-19 10:00 |
|---------|------|-----------------|-----------------|
| alice@kse.org.ua | Alice S. | ✓ | |
| bob@kse.org.ua | Bob K. | | ✓ |
