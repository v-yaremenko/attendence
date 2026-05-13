"""CLI: flush today's local attendance CSV to Google Sheets."""
from datetime import datetime

from config import settings
from sheets import TZ, flush_to_sheets


def run_merge() -> None:
    session_dt = datetime.now(TZ)
    try:
        stats = flush_to_sheets(settings.course_name, session_dt)
    except FileNotFoundError as exc:
        print(f"FAILED: {exc}")
        return
    print(
        f"Sync complete: {stats['count']} attendees -> "
        f"column '{stats['column']}' ({stats['filename']})"
    )


if __name__ == "__main__":
    run_merge()
