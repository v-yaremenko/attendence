"""Concurrency / high-load tests.

Two layers:
 * Unit: 100 threads call sheets.mark_present directly — verifies the CSV
   lock holds under contention without going through HTTP.
 * HTTP: 70 threads hit /auth/callback simultaneously — verifies the full
   stack (FastAPI routing, asyncio.to_thread → custom thread pool, signed
   cookie path, sheets.mark_present) survives a real check-in storm.
"""
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

from itsdangerous import URLSafeSerializer

import sheets
from config import settings

SESSION_DT = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)


# --- Unit-level: lock under contention ---


def test_concurrent_mark_present_records_all_students(tmp_path, monkeypatch):
    """100 threads checking in simultaneously must all land in the CSV."""
    monkeypatch.chdir(tmp_path)

    NUM = 100
    barrier = threading.Barrier(NUM)

    def check_in(i: int) -> None:
        barrier.wait()
        sheets.mark_present(
            f"student{i}@kse.org.ua", f"Student {i}", "OOP", SESSION_DT
        )

    threads = [threading.Thread(target=check_in, args=(i,)) for i in range(NUM)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    emails = sheets.list_present("OOP", SESSION_DT)
    assert len(emails) == NUM
    assert set(emails) == {f"student{i}@kse.org.ua" for i in range(NUM)}


def test_concurrent_reads_and_writes_are_safe(tmp_path, monkeypatch):
    """list_present must not raise while mark_present is appending."""
    monkeypatch.chdir(tmp_path)

    NUM_WRITERS = 20
    NUM_READERS = 20
    errors: list[BaseException] = []
    barrier = threading.Barrier(NUM_WRITERS + NUM_READERS)

    def writer(i: int) -> None:
        barrier.wait()
        try:
            sheets.mark_present(
                f"w{i}@kse.org.ua", f"W{i}", "OOP", SESSION_DT
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        barrier.wait()
        try:
            sheets.list_present("OOP", SESSION_DT)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = (
        [threading.Thread(target=writer, args=(i,)) for i in range(NUM_WRITERS)]
        + [threading.Thread(target=reader) for _ in range(NUM_READERS)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(sheets.list_present("OOP", SESSION_DT)) == NUM_WRITERS


# --- HTTP-level: 70 concurrent /auth/callback through the full stack ---


def test_70_concurrent_callbacks_all_succeed(client, tmp_path, monkeypatch, request):
    """70 concurrent /auth/callback requests must all return 303 and the
    server's CSV must contain 70 unique emails. Exercises FastAPI routing,
    the custom 100-worker thread pool, cookie/state validation, and
    sheets.mark_present end-to-end.
    """
    monkeypatch.chdir(tmp_path)
    # Each successful callback sets a student_name cookie on the shared
    # session client; 70 duplicates would break the anon_client fixture in
    # later tests. Clear them unconditionally at test exit.
    request.addfinalizer(client.cookies.clear)

    NUM = 70
    signer = URLSafeSerializer(settings.secret_key, salt="oauth-state")

    # Every call to auth.exchange_code returns a unique student. A small lock
    # protects the counter (it's the only shared state inside the side-effect).
    counter = {"n": 0}
    counter_lock = threading.Lock()

    def fake_exchange(code, redirect_uri):
        with counter_lock:
            n = counter["n"]
            counter["n"] += 1
        return {
            "email": f"student{n}@kse.org.ua",
            "name": f"Student {n}",
            "hd": "kse.org.ua",
        }

    statuses: list[int] = []
    statuses_lock = threading.Lock()
    barrier = threading.Barrier(NUM)

    def make_request(i: int) -> None:
        state = f"state_{i}"
        cookie_val = signer.dumps({"state": state, "token": "fake_token"})
        barrier.wait()
        r = client.get(
            f"/auth/callback?code=c{i}&state={state}",
            cookies={"oauth_state": cookie_val},
            follow_redirects=False,
        )
        with statuses_lock:
            statuses.append(r.status_code)

    with patch("auth.exchange_code", side_effect=fake_exchange):
        start = time.perf_counter()
        threads = [threading.Thread(target=make_request, args=(i,)) for i in range(NUM)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

    assert statuses.count(303) == NUM, (
        f"Expected {NUM} redirects, got {statuses.count(303)}. "
        f"Status distribution: {sorted(set((s, statuses.count(s)) for s in statuses))}"
    )
    assert counter["n"] == NUM

    # Verify the server's CSV — uses the server's actual _session_dt.
    import main
    emails = sheets.list_present(settings.course_name, main._session_dt)
    assert len(emails) == NUM, f"CSV has {len(emails)} students, expected {NUM}"
    assert set(emails) == {f"student{i}@kse.org.ua" for i in range(NUM)}

    # Soft perf assertion — should comfortably finish in a few seconds even on
    # CI. If this regresses dramatically, the thread pool or lock is the
    # likely suspect.
    assert elapsed < 10, f"70 concurrent callbacks took {elapsed:.1f}s (>10s)"
