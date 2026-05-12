from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from config import settings

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


def mark_present(email: str, name: str, course: str, session_dt: datetime) -> None:
    client = _get_client()
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    ws = _get_or_create_worksheet(spreadsheet, course)

    # Read everything once
    all_values = ws.get_all_values()
    header = all_values[0] if all_values else []

    # Fix sheet structure: ensure col A = "Student", col B = "Name"
    # If "Name" is missing at col B, insert a blank column via the Sheets API
    if len(header) < 2 or header[1] != "Name":
        spreadsheet.batch_update({"requests": [{
            "insertDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 1,  # 0-indexed: inserts at col B
                    "endIndex": 2,
                },
                "inheritFromBefore": False,
            }
        }]})
        ws.update_cell(1, 2, "Name")
        # Re-read after structural change
        all_values = ws.get_all_values()
        header = all_values[0] if all_values else []

    col_label = _col_header(session_dt)

    # Find or create date column (must be col 3+)
    if col_label in header:
        col_idx = header.index(col_label) + 1  # 1-based
    else:
        col_idx = max(len(header) + 1, 3)
        ws.update_cell(1, col_idx, col_label)

    # Find or create student row
    emails_col = [row[0] if row else "" for row in all_values]
    if email in emails_col:
        row_idx = emails_col.index(email) + 1  # 1-based
    else:
        row_idx = len(all_values) + 1
        ws.update_cell(row_idx, 1, email)

    # Write name and mark present (both idempotent)
    ws.update_cell(row_idx, 2, name)
    ws.update_cell(row_idx, col_idx, "✓")


def list_present(course: str, session_dt: datetime) -> list[str]:
    client = _get_client()
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    ws = spreadsheet.worksheet(course)
    header = ws.row_values(1)
    col_label = _col_header(session_dt)
    if col_label not in header:
        return []
    col_idx = header.index(col_label) + 1
    col_values = ws.col_values(col_idx)
    emails = ws.col_values(1)
    return [
        emails[i]
        for i, val in enumerate(col_values)
        if i > 0 and val == "✓" and i < len(emails)
    ]
