"""CLI: flush the most recent local attendance CSV to Google Sheets."""
from config import settings
from sheets import find_latest_session_file, flush_to_sheets


def run_merge() -> None:
    latest = find_latest_session_file(settings.course_name)
    if latest is None:
        print(f"No attendance CSV found for course '{settings.course_name}'.")
        return
    filename, session_dt = latest
    print(f"Flushing {filename} (session {session_dt:%Y-%m-%d %H:%M})...")
    try:
        stats = flush_to_sheets(settings.course_name, session_dt)
    except FileNotFoundError as exc:
        print(f"FAILED: {exc}")
        return
    print(
        f"Sync complete: {stats['count']} attendees -> "
        f"column '{stats['column']}'"
    )


if __name__ == "__main__":
    run_merge()
