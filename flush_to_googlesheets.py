import csv
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config import settings


def run_merge():
    today_date = datetime.now().strftime('%Y-%m-%d')
    filename = f"attendance_{settings.course_name}_{today_date}.csv"
    col_label = datetime.now().strftime("%d-%b")

    if not os.path.exists(filename):
        print(f"❌ Local file {filename} not found.")
        return

    # Load Local Data
    attendees = {}
    with open(filename, mode='r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
        for row in rows[1:]:
            if row: attendees[row[0]] = row[1]

    # Connect to Google
    creds = Credentials.from_service_account_file(
        settings.google_service_account_json,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(settings.google_spreadsheet_id)
    ws = sh.worksheet(settings.course_name)

    all_rows = ws.get_all_values()
    header = all_rows[0] if all_rows else []

    # --- THE ADJUSTMENT LOGIC ---

    # 1. Find or create the "Total" column
    if "Total" in header:
        total_col_idx = header.index("Total") + 1
    else:
        total_col_idx = max(len(header) + 1, 5)  # Minimum position: Col E
        ws.update_cell(1, total_col_idx, "Total")
        header.append("Total")

    # 2. Find or INSERT today's date column
    if col_label in header:
        date_col_idx = header.index(col_label) + 1
    else:
        # Insert today's date right BEFORE the Total column
        date_col_idx = total_col_idx
        ws.insert_cols([[col_label]], col=date_col_idx)
        print(f"➕ Inserted new date column: {col_label}")
        # Since we inserted, Total column moved right by 1
        total_col_idx += 1
        # Refresh header for row calculations
        header = ws.row_values(1)

    # 3. Build Batch Updates
    emails_in_col_a = [r[0] for r in all_rows]
    batch_updates = []

    # Identify the range for the COUNTIF formula (Starts at Column D / Index 4)
    # This formula counts all "✓" from Column D to the column just before Total
    last_date_letter = gspread.utils.rowcol_to_a1(1, total_col_idx - 1)[0]

    for email, name in attendees.items():
        if email in emails_in_col_a:
            curr_row = emails_in_col_a.index(email) + 1
        else:
            curr_row = len(emails_in_col_a) + 1
            batch_updates.append({"range": f"A{curr_row}:B{curr_row}", "values": [[email, name]]})
            emails_in_col_a.append(email)

        # Mark attendance
        batch_updates.append({
            "range": gspread.utils.rowcol_to_a1(curr_row, date_col_idx),
            "values": [["✓"]]
        })

    # 4. Update ALL "Total" formulas in the column
    # We do this for every row that has a student email
    for row_idx in range(2, len(emails_in_col_a) + 1):
        # Formula: =COUNTIF(D2:H2, "✓") where H is the column before Total
        formula = f'=COUNTIF(D{row_idx}:{last_date_letter}{row_idx}, "✓")'
        batch_updates.append({
            "range": gspread.utils.rowcol_to_a1(row_idx, total_col_idx),
            "values": [[formula]]
        })

    if batch_updates:
        ws.batch_update(batch_updates, value_input_option='USER_ENTERED')
        print(f"🚀 Sync complete! Total column updated for {len(emails_in_col_a) - 1} students.")


if __name__ == "__main__":
    run_merge()