import csv
import glob
import os
import re
import threading
from datetime import datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

from config import settings

TZ = timezone(timedelta(hours=3))

# Matches the trailing "_YYYY-MM-DD_HH-MM.csv" suffix in attendance filenames.
_SESSION_DT_RE = re.compile(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.csv$")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_client: gspread.Client | None = None
_client_lock = threading.Lock()
_csv_lock = threading.Lock()


def init_client() -> None:
    _get_client()


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        with _client_lock:
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


def _get_filename(session_dt: datetime, course: str) -> str:
    return f"attendance_{course}_{session_dt.strftime('%Y-%m-%d_%H-%M')}.csv"


def find_latest_session_file(course: str) -> tuple[str, datetime] | None:
    """Return (filename, session_dt) for the most recent CSV for this course.

    Used by the CLI flush — the running server already knows its own
    session_dt in memory. Returns None if no matching file is found.
    """
    parsed: list[tuple[str, datetime]] = []
    for f in glob.glob(f"attendance_{course}_*.csv"):
        m = _SESSION_DT_RE.search(f)
        if not m:
            continue
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d_%H-%M").replace(tzinfo=TZ)
        except ValueError:
            continue
        parsed.append((f, dt))
    if not parsed:
        return None
    return max(parsed, key=lambda x: x[1])


def mark_present(email: str, name: str, course: str, session_dt: datetime) -> None:
    """Append attendance to a local CSV file under a thread-safe lock."""
    filename = _get_filename(session_dt, course)
    with _csv_lock:
        file_exists = os.path.isfile(filename)
        with open(filename, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Student Email", "Name", "Timestamp"])
            writer.writerow(
                [email, name, datetime.now(TZ).strftime("%H:%M:%S")]
            )


def list_present(course: str, session_dt: datetime) -> list[str]:
    """Read the local CSV (no Sheets API call) and return checked-in emails."""
    filename = _get_filename(session_dt, course)
    with _csv_lock:
        if not os.path.isfile(filename):
            return []
        with open(filename, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    seen: set[str] = set()
    result: list[str] = []
    for row in rows[1:]:
        if row and row[0] and row[0] not in seen:
            seen.add(row[0])
            result.append(row[0])
    return result


def flush_to_sheets(course: str, session_dt: datetime) -> dict:
    """Upload the local CSV for this session to Google Sheets in one batch.

    Returns {"count": N, "filename": str, "column": str}. Raises FileNotFoundError
    if the local CSV doesn't exist.
    """
    filename = _get_filename(session_dt, course)
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Local file {filename} not found")

    # Load local data — last name wins for duplicate emails.
    attendees: dict[str, str] = {}
    with _csv_lock:
        with open(filename, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    for row in rows[1:]:
        if row and len(row) >= 2 and row[0]:
            attendees[row[0]] = row[1]

    col_label = _col_header(session_dt)
    if not attendees:
        return {"count": 0, "filename": filename, "column": col_label}

    client = _get_client()
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    ws = _get_or_create_worksheet(spreadsheet, course)

    all_rows = ws.get_all_values()
    header = all_rows[0] if all_rows else []

    # Repair old sheets that have no "Name" column at B.
    if len(header) < 2 or header[1] != "Name":
        spreadsheet.batch_update({"requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 1,
                    "endIndex": 2,
                },
                "inheritFromBefore": False,
            }
        }]})
        ws.update_cell(1, 2, "Name")
        all_rows = ws.get_all_values()
        header = all_rows[0] if all_rows else []

    if col_label in header:
        col_idx = header.index(col_label) + 1
    else:
        col_idx = max(len(header) + 1, 3)
        ws.update_cell(1, col_idx, col_label)

    emails_in_col_a = [r[0] if r else "" for r in all_rows]
    batch_updates: list[dict] = []
    for email, name in attendees.items():
        if email in emails_in_col_a:
            row_idx = emails_in_col_a.index(email) + 1
        else:
            row_idx = len(emails_in_col_a) + 1
            emails_in_col_a.append(email)
            batch_updates.append({
                "range": f"A{row_idx}:B{row_idx}",
                "values": [[email, name]],
            })
        batch_updates.append({
            "range": gspread.utils.rowcol_to_a1(row_idx, col_idx),
            "values": [["✓"]],
        })

    ws.batch_update(batch_updates)

    return {"count": len(attendees), "filename": filename, "column": col_label}
