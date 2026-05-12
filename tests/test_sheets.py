from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call
import pytest
import sheets


SESSION_DT = datetime(2026, 5, 12, 19, 53, tzinfo=timezone.utc)
COL_LABEL = "2026-05-12 19:53"


# --- _col_header ---

def test_col_header_format():
    assert sheets._col_header(SESSION_DT) == COL_LABEL


# --- list_present ---

def _make_ws(header, col_a_values, attendance_col_values):
    ws = MagicMock()
    ws.row_values.return_value = header
    ws.col_values.side_effect = lambda col: col_a_values if col == 1 else attendance_col_values
    return ws


def test_list_present_returns_emails_with_checkmark():
    header = ["Student", "Name", COL_LABEL]
    col_a = ["Student", "alice@kse.org.ua", "bob@kse.org.ua"]
    col_check = [COL_LABEL, "✓", ""]

    ws = _make_ws(header, col_a, col_check)
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws

    with patch.object(sheets, "_get_client") as mock_client:
        mock_client.return_value.open_by_key.return_value = spreadsheet
        result = sheets.list_present("OOP", SESSION_DT)

    assert result == ["alice@kse.org.ua"]


def test_list_present_returns_empty_when_column_missing():
    ws = _make_ws(["Student", "Name"], [], [])
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws

    with patch.object(sheets, "_get_client") as mock_client:
        mock_client.return_value.open_by_key.return_value = spreadsheet
        result = sheets.list_present("OOP", SESSION_DT)

    assert result == []


def test_list_present_raises_on_missing_worksheet():
    spreadsheet = MagicMock()
    spreadsheet.worksheet.side_effect = Exception("Worksheet not found")

    with patch.object(sheets, "_get_client") as mock_client:
        mock_client.return_value.open_by_key.return_value = spreadsheet
        with pytest.raises(Exception, match="Worksheet not found"):
            sheets.list_present("OOP", SESSION_DT)


def test_list_present_multiple_attendees():
    header = ["Student", "Name", COL_LABEL]
    col_a = ["Student", "alice@kse.org.ua", "bob@kse.org.ua", "carol@kse.org.ua"]
    col_check = [COL_LABEL, "✓", "✓", "✓"]

    ws = _make_ws(header, col_a, col_check)
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws

    with patch.object(sheets, "_get_client") as mock_client:
        mock_client.return_value.open_by_key.return_value = spreadsheet
        result = sheets.list_present("OOP", SESSION_DT)

    assert result == ["alice@kse.org.ua", "bob@kse.org.ua", "carol@kse.org.ua"]


# --- mark_present ---

def _make_full_ws(all_values):
    ws = MagicMock()
    ws.get_all_values.return_value = all_values
    ws.id = "fake-sheet-id"
    return ws


def test_mark_present_new_student_new_session():
    all_values = [["Student", "Name"]]
    ws = _make_full_ws(all_values)
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws

    with patch.object(sheets, "_get_client") as mock_client, \
         patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        mock_client.return_value.open_by_key.return_value = spreadsheet
        sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    # Should write email, then batch name + checkmark
    ws.update_cell.assert_any_call(2, 1, "alice@kse.org.ua")
    ws.batch_update.assert_called_once()


def test_mark_present_existing_student_idempotent():
    all_values = [
        ["Student", "Name", COL_LABEL],
        ["alice@kse.org.ua", "Alice", "✓"],
    ]
    ws = _make_full_ws(all_values)
    spreadsheet = MagicMock()
    spreadsheet.worksheet.return_value = ws

    with patch.object(sheets, "_get_client") as mock_client, \
         patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        mock_client.return_value.open_by_key.return_value = spreadsheet
        sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    # Row already exists — no new email write
    ws.update_cell.assert_not_called()
    # Still batch-writes name + checkmark (idempotent)
    ws.batch_update.assert_called_once()


def test_mark_present_inserts_name_column_when_missing():
    # Old sheet format: no Name column at col B
    all_values = [["Student", COL_LABEL], ["alice@kse.org.ua", "✓"]]
    ws = _make_full_ws(all_values)
    # After insert, re-read returns fixed header
    ws.get_all_values.side_effect = [
        all_values,
        [["Student", "Name", COL_LABEL], ["alice@kse.org.ua", "", "✓"]],
    ]
    ws.row_values.return_value = ["Student", "Name", COL_LABEL]
    spreadsheet = MagicMock()

    with patch.object(sheets, "_get_client") as mock_client, \
         patch.object(sheets, "_get_or_create_worksheet", return_value=ws):
        mock_client.return_value.open_by_key.return_value = spreadsheet
        sheets.mark_present("alice@kse.org.ua", "Alice", "OOP", SESSION_DT)

    # Should have called batch_update on spreadsheet to insert the column
    spreadsheet.batch_update.assert_called_once()
    ws.update_cell.assert_any_call(1, 2, "Name")
