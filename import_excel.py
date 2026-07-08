"""
One-time (or re-runnable) importer that reads the case-summary Excel sheet
and loads it into the SQLite database used by app.py.

Usage:
    python import_excel.py /path/to/Cases_List.xlsx [--wipe]

    --wipe   delete all existing cases before importing (otherwise it just
             adds new rows every time you run it - use --wipe if you're
             re-importing an updated sheet from scratch)
"""

import sys
import re
import argparse
from datetime import datetime

import pandas as pd

from app import app
from extensions import db
from models import Case

COLUMN_MAP = {
    "S.NO.": "s_no",
    "COURT NAME": "court_name",
    "Case Number ": "case_number",
    "Case Number": "case_number",
    "LAST DATE OF HEARING": "last_hearing_date",
    "CASE TITLE": "case_title",
    "NEXT HEARING DATE": "next_hearing_date",
    "BRIEF HISTORY": "brief_history",
    "Status of Reply/Counter affidavit ": "affidavit_status_text",
    "Status of Reply/Counter affidavit": "affidavit_status_text",
}


def parse_messy_date(value):
    """The sheet mixes real datetimes, dd-mm-yyyy strings, and cells with
    multiple comma-separated dates. Grab the first parseable date."""
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()

    text = str(value).strip()
    if not text:
        return None

    # If there are multiple dates separated by a comma, take the first.
    first_token = re.split(r"[,\n]", text)[0].strip()

    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(first_token, fmt).date()
        except ValueError:
            continue
    return None


def classify_affidavit_status(text):
    """Best-effort guess from the free-text status column. This is only a
    starting point - correct it later from the app if it guesses wrong."""
    if not text or pd.isna(text):
        return "not_filed"
    t = str(text).lower()
    if "not filed" in t or "to be filed" in t or "sent for approval" in t or "yet to" in t:
        return "not_filed"
    if "filed" in t:
        return "filed"
    return "not_filed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("excel_path")
    parser.add_argument("--wipe", action="store_true")
    args = parser.parse_args()

    df = pd.read_excel(args.excel_path, sheet_name=0, header=1)
    df = df.rename(columns=COLUMN_MAP)

    with app.app_context():
        db.create_all()

        if args.wipe:
            Case.query.delete()
            db.session.commit()
            print("Existing cases wiped.")

        count = 0
        for _, row in df.iterrows():
            case_number = str(row.get("case_number", "")).strip()
            if not case_number or case_number.lower() == "nan":
                continue  # skip blank rows

            status_text = row.get("affidavit_status_text", "")
            case = Case(
                court_name=str(row.get("court_name", "")).strip(),
                case_number=case_number,
                last_hearing_date=parse_messy_date(row.get("last_hearing_date")),
                case_title=str(row.get("case_title", "")).strip(),
                next_hearing_date=parse_messy_date(row.get("next_hearing_date")),
                brief_history=str(row.get("brief_history", "")).strip(),
                affidavit_status_text=str(status_text).strip() if not pd.isna(status_text) else "",
                affidavit_status=classify_affidavit_status(status_text),
            )
            db.session.add(case)
            count += 1

        db.session.commit()
        print(f"Imported {count} case(s) into the database.")


if __name__ == "__main__":
    main()
