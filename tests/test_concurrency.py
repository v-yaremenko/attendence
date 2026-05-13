import asyncio
from datetime import datetime
from unittest.mock import patch

import gspread
import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import URLSafeSerializer

import auth
import qr_manager
import sheets
from config import settings
from main import app


class FakeWorksheet:
    def __init__(self, title):
        self.title = title
        self.id = 123
        self.rows = [["Student", "Name"]]
        self.updates = []

    def get_all_values(self):
        # We need to copy to simulate multiple threads reading the exact state 
        # simultaneously if there was no lock. With lock, it's just a normal read.
        # Introduce a tiny delay to ensure a race condition would trigger without locks.
        # But wait, asyncio.sleep doesn't work inside synchronous get_all_values.
        # We can use time.sleep(0.001) but let's just return a copy.
        import time
        time.sleep(0.01) # This forces the thread to yield, triggering TOCTOU without a lock
        return [list(r) for r in self.rows]

    def update_cell(self, row, col, value):
        while len(self.rows) < row:
            self.rows.append([""])
        while len(self.rows[row - 1]) < col:
            self.rows[row - 1].append("")
        self.rows[row - 1][col - 1] = value
        self.updates.append((row, col, value))

    def batch_update(self, data):
        # handle list of updates for mark_present
        if isinstance(data, list):
            import gspread.utils
            for req in data:
                if "range" in req and "values" in req:
                    row, col = gspread.utils.a1_to_rowcol(req["range"])
                    val = req["values"][0][0]
                    self.update_cell(row, col, val)


class FakeSpreadsheet:
    def __init__(self):
        self.worksheets_dict = {}

    def worksheet(self, title):
        if title not in self.worksheets_dict:
            raise gspread.WorksheetNotFound()
        return self.worksheets_dict[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title)
        self.worksheets_dict[title] = ws
        return ws

    def batch_update(self, body):
        # Mocking the insert column structure fix
        if "requests" in body:
            pass


class FakeClient:
    def __init__(self):
        self.spreadsheets = {}

    def open_by_key(self, key):
        if key not in self.spreadsheets:
            self.spreadsheets[key] = FakeSpreadsheet()
        return self.spreadsheets[key]


@pytest.mark.asyncio
async def test_concurrency_mark_present():
    fake_client = FakeClient()
    fake_ss = fake_client.open_by_key(settings.google_spreadsheet_id)
    fake_ws = fake_ss.add_worksheet(settings.course_name, 200, 50)
    fake_ws.update_cell(1, 3, "2026-05-13 18:00") # Setup date header

    # Mock `sheets._get_client` directly since authorize is already called 
    # and client initialization is locked. 
    # Or mock `gspread.authorize`
    with patch("gspread.authorize", return_value=fake_client), \
         patch("sheets.Credentials.from_service_account_file", return_value=None), \
         patch("auth.exchange_code") as mock_exchange, \
         patch("qr_manager.validate_token", return_value=True), \
         patch("auth.check_domain", return_value=True):
         
        # Reset the client so _get_client() calls gspread.authorize again
        sheets._client = None
        sheets.init_client()

        call_count = 0

        def fake_exchange(code, redirect_uri):
            nonlocal call_count
            call_count += 1
            return {"email": f"student{call_count}@kse.org.ua", "name": f"Student {call_count}"}

        mock_exchange.side_effect = fake_exchange

        NUM_REQUESTS = 10

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            state = "test_state"
            token = "test_token"

            _state_signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")
            cookie_val = _state_signer.dumps({"state": state, "token": token})

            async def make_request(i):
                # add a tiny sleep to force context switching
                await asyncio.sleep(0.01)
                response = await ac.get(
                    "/auth/callback",
                    params={"code": f"code_{i}", "state": state},
                    cookies={"oauth_state": cookie_val}
                )
                return response

            # Execute 10 concurrent requests
            responses = await asyncio.gather(*[make_request(i) for i in range(NUM_REQUESTS)])

            for r in responses:
                assert r.status_code == 303  # Expect Redirect to /success

            # Verify no data loss: 1 header row + 10 students
            assert len(fake_ws.rows) == NUM_REQUESTS + 1
            
            emails = [row[0] for row in fake_ws.rows if row and row[0] and row[0] != "Student"]
            assert len(emails) == NUM_REQUESTS
            assert len(set(emails)) == NUM_REQUESTS
