import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import sheets


SESSION_DT = datetime(2026, 5, 12, 19, 53, tzinfo=timezone.utc)
COL_LABEL = "2026-05-12 19:53"
FILE_SUFFIX = "2026-05-12_19-53"


@pytest.fixture(autouse=True)
def _isolate_csv(tmp_path, monkeypatch):
    """Redirect CSV_DIR to a tmp path so CSVs don't leak between tests."""
    monkeypatch.setattr(sheets, "CSV_DIR", tmp_path)
    yield


# --- _col_header / _get_filename ---


def test_col_header_format():
    assert sheets._col_header(SESSION_DT) == COL_LABEL


def test_get_filename_includes_course_and_session_dt():
    assert sheets._get_filename(SESSION_DT, "OOP").endswith(
        f"attendance_OOP_{FILE_SUFFIX}.csv"
    )


def test_find_latest_session_file_picks_newest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Three sessions, two for OOP, one for an unrelated course.
    for name in (
        "attendance_OOP_2026-05-12_10-00.csv",
        "attendance_OOP_2026-05-14_13-30.csv",
        "attendance_DSA_2026-05-15_09-00.csv",
    ):
        (tmp_path / name).write_text("Student Email,Name,Timestamp\n")

    result = sheets.find_latest_session_file("OOP")
    assert result is not None
    filename, dt = result
    assert filename.endswith("attendance_OOP_2026-05-14_13-30.csv")
    assert dt.strftime("%Y-%m-%d %H:%M") == "2026-05-14 13:30"


def test_find_latest_session_file_returns_none_when_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert sheets.find_latest_session_file("OOP") is None


# --- mark_present (local CSV) ---


def test_mark_present_creates_csv_with_header():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    fname = sheets._get_filename(SESSION_DT, "OOP")
    assert os.path.isfile(fname)
    with open(fname, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[0] == "Student Email,Name,Timestamp"
    assert lines[1].startswith("alice@kse.org.ua,Alice,")


def test_mark_present_appends_without_duplicating_header():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    sheets.mark_present("bob@kse.org.ua", "Bob", "OOP", SESSION_DT)

    with open(sheets._get_filename(SESSION_DT, "OOP"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert len(lines) == 3
    assert lines[0] == "Student Email,Name,Timestamp"


def test_mark_present_does_not_hit_sheets_api():
    """Critical: mark_present must NOT call the Sheets API (quota safety)."""
    with patch.object(sheets, "_get_client") as mock_client:
        sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    mock_client.assert_not_called()


# --- list_present (local CSV) ---


def test_list_present_returns_empty_when_no_file():
    assert sheets.list_present("OOP", SESSION_DT) == []


def test_list_present_returns_emails_in_check_in_order():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    sheets.mark_present("bob@kse.org.ua", "Bob", "OOP", SESSION_DT)
    assert sheets.list_present("OOP", SESSION_DT) == [
        "alice@kse.org.ua",
        "bob@kse.org.ua",
    ]


def test_list_present_dedupes_duplicate_check_ins():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    assert sheets.list_present("OOP", SESSION_DT) == ["alice@kse.org.ua"]


def test_list_present_does_not_hit_sheets_api():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    with patch.object(sheets, "_get_client") as mock_client:
        result = sheets.list_present("OOP", SESSION_DT)
    assert result == ["alice@kse.org.ua"]
    mock_client.assert_not_called()


# --- flush_to_sheets ---


def _fake_ws(rows: list[list[str]]) -> MagicMock:
    ws = MagicMock()
    ws.id = 42
    ws.get_all_values.return_value = rows
    return ws


def _patch_client(ws: MagicMock, spreadsheet: MagicMock | None = None):
    spreadsheet = spreadsheet or MagicMock()
    spreadsheet.worksheet.return_value = ws
    client = MagicMock()
    client.open_by_key.return_value = spreadsheet
    return patch.object(sheets, "_get_client", return_value=client), spreadsheet


def test_flush_raises_when_no_csv():
    with pytest.raises(FileNotFoundError):
        sheets.flush_to_sheets("OOP", SESSION_DT)


def test_flush_creates_new_column_and_writes_attendees():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)
    sheets.mark_present("bob@kse.org.ua", "Bob", "OOP", SESSION_DT)

    ws = _fake_ws([["Student", "Name"]])
    client_patch, spreadsheet = _patch_client(ws)
    with client_patch, patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        stats = sheets.flush_to_sheets("OOP", SESSION_DT)

    assert stats == {
        "count": 2,
        "filename": sheets._get_filename(SESSION_DT, "OOP"),
        "column": COL_LABEL,
    }
    ws.update_cell.assert_called_once_with(1, 3, COL_LABEL)
    ws.batch_update.assert_called_once()
    batch = ws.batch_update.call_args[0][0]
    # New students -> A:B writes; plus per-attendee ✓
    ranges = [b["range"] for b in batch]
    assert "A2:B2" in ranges
    assert "A3:B3" in ranges
    # Two checkmark writes at col C (col_idx 3)
    assert sum(1 for b in batch if b["values"] == [["✓"]]) == 2


def test_flush_reuses_existing_column_when_present():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    ws = _fake_ws([
        ["Student", "Name", COL_LABEL],
        ["alice@kse.org.ua", "Alice", ""],
    ])
    client_patch, _ = _patch_client(ws)
    with client_patch, patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        sheets.flush_to_sheets("OOP", SESSION_DT)

    # Column already exists — no new header write
    ws.update_cell.assert_not_called()
    # No A:B row insert — Alice's row already exists
    batch = ws.batch_update.call_args[0][0]
    assert all(":B" not in b["range"] for b in batch)


def test_flush_repairs_missing_name_column():
    sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    ws = _fake_ws([["Student", "2026-05-01"]])
    # After insertDimension repair, re-read returns a fixed header.
    ws.get_all_values.side_effect = [
        [["Student", "2026-05-01"]],
        [["Student", "Name", "2026-05-01"]],
    ]
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws
    client = MagicMock()
    client.open_by_key.return_value = spreadsheet
    with patch.object(sheets, "_get_client", return_value=client), \
         patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        sheets.flush_to_sheets("OOP", SESSION_DT)

    spreadsheet.batch_update.assert_called_once()  # insertDimension call
    ws.update_cell.assert_any_call(1, 2, "Name")


def test_flush_empty_csv_makes_no_sheets_call():
    """If CSV exists but has no data rows, don't touch Sheets at all."""
    fname = sheets._get_filename(SESSION_DT, "OOP")
    with open(fname, "w", encoding="utf-8") as f:
        f.write("Student Email,Name,Timestamp\n")

    with patch.object(sheets, "_get_client") as mock_client:
        stats = sheets.flush_to_sheets("OOP", SESSION_DT)

    assert stats["count"] == 0
    mock_client.assert_not_called()
