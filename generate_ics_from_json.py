#!/usr/bin/env python3
"""
Etap 2: JSON → ICS
Wczytuje surowe dane tabeli z JSON i generuje plik ICS zgodny z RFC 5545.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Opcjonalnie: openpyxl do pliku WF
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

import sys
GROUP = sys.argv[1] if len(sys.argv) > 1 else "WEL24EL2S0"
INPUT_JSON = f"{GROUP}_lato_raw.json"
OUTPUT_ICS = f"{GROUP}_lato.ics"
WF_XLSX = "wf_details.xlsx"

# Rok semestru letniego
YEAR = 2026

# Mapa slotów godzinowych na godziny zajęć
TIME_MAP = {
    "1-2":  ("08:00", "09:35"),
    "3-4":  ("09:50", "11:25"),
    "5-6":  ("11:40", "13:15"),
    "7-8":  ("13:30", "15:05"),
    "9-10": ("16:00", "17:35"),
    "11-12":("17:50", "19:25"),
    "13-14":("19:40", "21:15"),
}

# Komórki do pominięcia (np. blokady, zajęcia innej grupy)
SKIP_KEYWORDS = {"XWF", "XFiz1", "SSW"}

# Mapa miesięcy w zapisie rzymskim
ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4,
    "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12,
}

# Dni tygodnia w planie WAT
WEEKDAYS = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]


def build_grid(rows: list[list[dict]]) -> dict:
    """
    Buduje logiczny grid uwzględniający colspan i rowspan.
    Zwraca dict: grid[row_idx][col_idx] = cell_dict
    """
    grid = {}
    # Tablica zajętości: occupied[row][col] = True
    occupied = {}

    for row_idx, row in enumerate(rows):
        col_cursor = 0
        for cell in row:
            # Przesuń kursor za zajęte miejsca
            while occupied.get((row_idx, col_cursor)):
                col_cursor += 1

            cs = cell["colspan"]
            rs = cell["rowspan"]

            # Wypełnij wszystkie pozycje objęte przez tę komórkę
            for dr in range(rs):
                for dc in range(cs):
                    r = row_idx + dr
                    c = col_cursor + dc
                    occupied[(r, c)] = True
                    if r not in grid:
                        grid[r] = {}
                    if c not in grid[r]:
                        grid[r][c] = cell

            col_cursor += cs

    return grid


def parse_roman_date(text: str) -> datetime | None:
    """
    Parsuje datę w formacie "23 II" lub "02 III" do datetime.
    """
    text = text.strip()
    # Wzorce: "23 II", "2 III", "02 III"
    match = re.match(r"(\d{1,2})\s+([IVX]+)$", text)
    if not match:
        return None
    day = int(match.group(1))
    month_roman = match.group(2)
    month = ROMAN_MONTHS.get(month_roman)
    if not month:
        return None
    try:
        return datetime(YEAR, month, day)
    except ValueError:
        return None


def find_date_row(grid: dict) -> tuple[int, dict] | tuple[None, None]:
    """
    Szuka wiersza z datami – zaczyna się od "pon." lub podobnego.
    Zwraca (row_idx, date_columns) gdzie date_columns[col_idx] = datetime.
    """
    max_row = max(grid.keys())
    for row_idx in range(max_row + 1):
        row = grid.get(row_idx, {})
        if not row:
            continue
        # Sprawdź, czy pierwsza komórka to nazwa dnia tygodnia
        first_cell = row.get(0) or row.get(min(row.keys()))
        if not first_cell:
            continue
        first_text = first_cell["text"].strip().lower()
        if not any(first_text.startswith(d.lower()) for d in WEEKDAYS):
            continue

        # Szukaj dat w kolejnych kolumnach
        date_columns = {}
        for col_idx, cell in row.items():
            parsed = parse_roman_date(cell["text"])
            if parsed:
                date_columns[col_idx] = parsed

        if date_columns:
            print(f"Znaleziono wiersz dat w wierszu {row_idx}: {len(date_columns)} dat")
            return row_idx, date_columns

    return None, None


def find_all_date_rows(grid: dict) -> list[tuple[int, dict]]:
    """
    Szuka WSZYSTKICH wierszy z datami (każdy dzień tygodnia ma swój wiersz).
    """
    max_row = max(grid.keys())
    results = []
    for row_idx in range(max_row + 1):
        row = grid.get(row_idx, {})
        if not row:
            continue
        first_cell = row.get(0) or (row.get(min(row.keys())) if row else None)
        if not first_cell:
            continue
        first_text = first_cell["text"].strip().lower()
        if not any(first_text.startswith(d.lower()) for d in WEEKDAYS):
            continue

        date_columns = {}
        for col_idx, cell in row.items():
            parsed = parse_roman_date(cell["text"])
            if parsed:
                date_columns[col_idx] = parsed

        if date_columns:
            results.append((row_idx, date_columns))

    return results


def find_time_slot(cell_text: str) -> str | None:
    """
    Szuka slotu godzinowego w tekście komórki lub wiersza.
    """
    for slot in TIME_MAP:
        if slot in cell_text:
            return slot
    return None


def parse_event_details(text: str) -> dict:
    """
    Parsuje szczegóły zajęć z tekstu komórki.
    Zwraca dict z kluczami: summary, room, teacher, notes.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return {"summary": "", "room": "", "teacher": "", "notes": ""}

    summary = lines[0]
    room = ""
    teacher = ""
    notes_lines = []

    for line in lines[1:]:
        if re.match(r"s\.\s*\w+", line, re.IGNORECASE):
            room = line
        elif re.search(r"\b(dr|mgr|prof|inż)\b", line, re.IGNORECASE):
            teacher = line
        else:
            notes_lines.append(line)

    return {
        "summary": summary,
        "room": room,
        "teacher": teacher,
        "notes": "\n".join(notes_lines),
    }


def load_wf_details(xlsx_path: str) -> dict:
    """
    Wczytuje szczegóły WF z pliku XLSX.
    Zakłada format: kolumna A = data, kolumna B = opis.
    """
    if not HAS_OPENPYXL or not Path(xlsx_path).exists():
        return {}

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    details = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1]:
            date_val = row[0]
            if isinstance(date_val, datetime):
                key = date_val.date()
            else:
                key = str(date_val)
            details[key] = str(row[1])
    print(f"Wczytano {len(details)} wpisów WF z {xlsx_path}")
    return details


def should_skip(text: str) -> bool:
    """Sprawdza, czy komórkę należy pominąć."""
    for kw in SKIP_KEYWORDS:
        if kw in text:
            return True
    return False


def make_uid(date: datetime, slot: str, col_idx: int, text: str) -> str:
    """Generuje unikalny UID dla eventu."""
    raw = f"{date.isoformat()}-{slot}-{col_idx}-{text}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{date.strftime('%Y%m%d')}-{slot.replace('-','')}-c{col_idx}-{h}@wat.edu.pl"


def format_dt(dt: datetime) -> str:
    """Formatuje datetime do formatu ICS (lokalny, bez strefy)."""
    return dt.strftime("%Y%m%dT%H%M%S")


def escape_ics(text: str) -> str:
    """Escape'uje znaki specjalne dla ICS."""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


def fold_line(line: str) -> str:
    """Składa długie linie ICS (RFC 5545: max 75 oktetów)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    result = []
    current = ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            result.append(current)
            current = " " + char
        else:
            current += char
    if current:
        result.append(current)
    return "\r\n".join(result)


def build_ics(events: list[dict]) -> str:
    """Buduje plik ICS z listy eventów."""
    now = datetime.now(__import__('datetime').timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WAT WEL Plan zajec//PL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:WAT {GROUP} Lato",
        "X-WR-TIMEZONE:Europe/Warsaw",
    ]

    for ev in events:
        lines += [
            "BEGIN:VEVENT",
            fold_line(f"UID:{ev['uid']}"),
            f"DTSTAMP:{now}",
            f"DTSTART:{ev['dtstart']}",
            f"DTEND:{ev['dtend']}",
            fold_line(f"SUMMARY:{escape_ics(ev['summary'])}"),
        ]
        if ev.get("location"):
            lines.append(fold_line(f"LOCATION:{escape_ics(ev['location'])}"))
        if ev.get("description"):
            lines.append(fold_line(f"DESCRIPTION:{escape_ics(ev['description'])}"))
        lines += [
            "STATUS:CONFIRMED",
            "SEQUENCE:0",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def process_schedule(grid: dict, wf_details: dict) -> list[dict]:
    events = []
    processed_cells = set()

    all_date_rows = find_all_date_rows(grid)
    if not all_date_rows:
        print("BŁĄD: Nie znaleziono wierszy z datami!")
        return events

    print(f"Znaleziono {len(all_date_rows)} wierszy nagłówkowych z datami.")

    date_row_indices = [r for r, _ in all_date_rows]
    max_row = max(grid.keys())

    for block_i, (date_row_idx, date_columns) in enumerate(all_date_rows):
        if block_i + 1 < len(all_date_rows):
            block_end = date_row_indices[block_i + 1]
        else:
            block_end = max_row + 1

        for row_idx in range(date_row_idx + 1, block_end):
            row = grid.get(row_idx, {})
            if not row:
                continue

            slot = None
            for check_col in sorted(row.keys())[:3]:
                slot = find_time_slot(row[check_col]["text"])
                if slot:
                    break
            if not slot:
                continue

            start_str, end_str = TIME_MAP[slot]

            for col_idx, base_date in date_columns.items():
                cell = row.get(col_idx)
                if cell is None:
                    continue

                cell_id = id(cell)
                if cell_id in processed_cells:
                    continue

                text = cell["text"].strip()
                if not text or should_skip(text):
                    continue

                rowspan = cell.get("rowspan", 1)
                sh, sm = map(int, start_str.split(":"))
                eh, em = map(int, end_str.split(":"))
                dtstart = base_date.replace(hour=sh, minute=sm)
                dtend = base_date.replace(hour=eh, minute=em)

                if rowspan > 1:
                    last_row = grid.get(row_idx + rowspan - 1, {})
                    last_slot = None
                    for check_col in sorted(last_row.keys())[:3]:
                        last_slot = find_time_slot(last_row[check_col]["text"])
                        if last_slot:
                            break
                    if last_slot:
                        _, last_end = TIME_MAP[last_slot]
                        leh, lem = map(int, last_end.split(":"))
                        dtend = base_date.replace(hour=leh, minute=lem)

                processed_cells.add(cell_id)

                details = parse_event_details(text)
                summary = details["summary"]
                room = details["room"]
                teacher = details["teacher"]
                notes = details["notes"]

                desc_parts = []
                if teacher:
                    desc_parts.append(f"Prowadzący: {teacher}")
                if notes:
                    desc_parts.append(notes)

                if "WF" in summary.upper() and wf_details:
                    wf_key = base_date.date()
                    if wf_key in wf_details:
                        desc_parts.append(f"WF: {wf_details[wf_key]}")

                description = "\n".join(desc_parts)

                ev = {
                    "uid": make_uid(base_date, slot, col_idx, text),
                    "dtstart": format_dt(dtstart),
                    "dtend": format_dt(dtend),
                    "summary": summary,
                    "location": room,
                    "description": description,
                }
                events.append(ev)

    return events


def main():
    print(f"Wczytywanie: {INPUT_JSON}")
    with open(INPUT_JSON, encoding="utf-8") as f:
        rows = json.load(f)

    grid = build_grid(rows)
    print(f"Zbudowano grid: {len(grid)} wierszy")

    wf_details = load_wf_details(WF_XLSX)

    events = process_schedule(grid, wf_details)
    print(f"Wygenerowano {len(events)} eventów")

    ics_content = build_ics(events)

    with open(OUTPUT_ICS, "w", encoding="utf-8", newline="") as f:
        f.write(ics_content)

    print(f"Zapisano: {OUTPUT_ICS}")

    # Podgląd pierwszych eventów
    print("\n--- Pierwsze 5 eventów ---")
    for ev in events[:5]:
        print(
            f"  {ev['dtstart']} | {ev['summary']!r} | {ev['location']!r}"
        )


if __name__ == "__main__":
    main()
