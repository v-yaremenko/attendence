import gspread
from google.oauth2.service_account import Credentials
import csv
import os
import threading
from datetime import datetime
from config import settings  #

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            settings.google_service_account_json, scopes=_SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _get_or_create_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=200, cols=50)
        ws.update("A1:B1", [["Student", "Name"]])
        return ws


def _col_header(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")

# A lock to prevent race conditions when 50 students write at the same time
_lock = threading.Lock()


def _get_filename(session_dt: datetime, course: str) -> str:
    # Generates: attendance_OOP_2026-05-13.csv
    return f"attendance_{course}_{session_dt.strftime('%Y-%m-%d')}.csv"


def mark_present(email: str, name: str, course: str, session_dt: datetime) -> None:
    """Saves attendance to a local CSV file using a thread-safe lock."""
    filename = _get_filename(session_dt, course)
    file_exists = os.path.isfile(filename)

    with _lock:
        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Write headers if it's a brand new file
            if not file_exists:
                writer.writerow(["Student Email", "Name", "Timestamp"])

            # Record the student
            writer.writerow([email, name, datetime.now().strftime("%H:%M:%S")])


def list_present(course: str, session_dt: datetime) -> list[str]:
    """Reads the local CSV to update the admin dashboard count."""
    filename = _get_filename(session_dt, course)
    if not os.path.isfile(filename):
        return []

    with _lock:
        with open(filename, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
            return [row[0] for row in rows[1:] if row]