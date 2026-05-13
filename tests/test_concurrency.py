"""Concurrency tests for the local-CSV mark_present path."""
import threading
from datetime import datetime, timezone

import sheets

SESSION_DT = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)


def test_concurrent_mark_present_records_all_students(tmp_path, monkeypatch):
    """50 threads checking in simultaneously must all land in the CSV."""
    monkeypatch.chdir(tmp_path)

    NUM = 50
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
