#!/usr/bin/env python3
"""
Etap 2: JSON -> ICS

Wczytuje surowe dane tabeli z JSON i generuje plik ICS zgodny z RFC 5545.

Użycie:
    python generate_ics_from_json.py [GRUPA] [SEMESTR]
    python generate_ics_from_json.py WEL24EL2S0 zima
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

DEFAULT_GROUP = "WEL24EL2S0"
DEFAULT_SEMESTER = "zima"

TIMEZONE_ID = "Europe/Warsaw"

# Mapa slotów godzinowych na godziny zajęć.
# Źródło: https://www.wel.wat.edu.pl/przydatne-informacje/siatka-godzinowa-zajec/
TIME_MAP = {
    "1-2":   ("08:00", "09:35"),
    "3-4":   ("09:50", "11:25"),
    "5-6":   ("11:40", "13:15"),
    "7-8":   ("13:30", "15:05"),
    "9-10":  ("16:00", "17:35"),
    "11-12": ("17:50", "19:25"),
    "13-14": ("19:40", "21:15"),
}

# Komórki do pominięcia: SSW to samodzielna praca, X* to przedmioty powtarzane
# przez inne grupy wpisane w ten sam rozkład.
SKIP_KEYWORDS = {"SSW"}
SKIP_PREFIX_X = True  # pomija kody zaczynające się od "X" (XWF, XFiz1, XOis1...)

ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}

WEEKDAYS = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]

# Typy zajęć w legendzie po prawej stronie tabeli (np. "w 24", "L 12", "Zp. 2")
TYPE_TOKEN_RE = re.compile(r"^(w|ć|L|S|E|r|i|P|Ep|Zp\.|Rep|Z)\s*\d*$")

# Rozwinięcia typów zajęć (OZNACZENIA z nagłówka planu)
TYPE_NAMES = {
    "w": "wykład",
    "ć": "ćwiczenia",
    "L": "laboratorium",
    "S": "seminarium",
    "P": "projekt",
    "E": "egzamin",
    "Ep": "egzamin poprawkowy",
    "Z": "zaliczenie",
    "Zp.": "zaliczenie poprawkowe",
    "Rep": "repetytorium",
}


# --------------------------------------------------------------------------
# Rok kalendarzowy
# --------------------------------------------------------------------------

def default_academic_year_start() -> int:
    """Rok startowy roku akademickiego, jeśli nie ma go w metadanych."""
    today = datetime.now()
    return today.year if today.month >= 9 else today.year - 1


def year_for_month(month: int, year_start: int) -> int:
    """Semestr zimowy przechodzi przez przełom roku: X-XII -> N, I-II -> N+1."""
    return year_start if month >= 9 else year_start + 1


# --------------------------------------------------------------------------
# Siatka tabeli
# --------------------------------------------------------------------------

def build_grid(rows: list[list[dict]]) -> dict:
    """Buduje logiczny grid uwzględniający colspan i rowspan."""
    grid: dict = {}
    occupied: dict = {}

    for row_idx, row in enumerate(rows):
        col_cursor = 0
        for cell in row:
            while occupied.get((row_idx, col_cursor)):
                col_cursor += 1

            cs = cell["colspan"]
            rs = cell["rowspan"]

            for dr in range(rs):
                for dc in range(cs):
                    r = row_idx + dr
                    c = col_cursor + dc
                    occupied[(r, c)] = True
                    grid.setdefault(r, {}).setdefault(c, cell)

            col_cursor += cs

    return grid


def parse_roman_date(text: str) -> tuple[int, int] | None:
    """Parsuje "23 II" / "02 III" do (dzień, miesiąc)."""
    match = re.match(r"(\d{1,2})\s+([IVX]+)$", text.strip())
    if not match:
        return None
    month = ROMAN_MONTHS.get(match.group(2))
    if not month:
        return None
    return int(match.group(1)), month


def find_all_date_rows(grid: dict, year_start: int) -> list[tuple[int, dict]]:
    """Znajduje wiersze nagłówkowe z datami (jeden na każdy dzień tygodnia)."""
    max_row = max(grid.keys())
    results = []

    for row_idx in range(max_row + 1):
        row = grid.get(row_idx, {})
        if not row:
            continue

        first_cell = row.get(0) or row[min(row.keys())]
        first_text = first_cell["text"].strip().lower()
        if not any(first_text.startswith(d.lower()) for d in WEEKDAYS):
            continue

        date_columns = {}
        for col_idx, cell in row.items():
            parsed = parse_roman_date(cell["text"])
            if not parsed:
                continue
            day, month = parsed
            try:
                date_columns[col_idx] = datetime(
                    year_for_month(month, year_start), month, day
                )
            except ValueError:
                print(f"  ostrzeżenie: zła data {cell['text']!r} w wierszu {row_idx}")

        if date_columns:
            results.append((row_idx, date_columns))

    return results


def build_subject_legend(grid: dict, date_columns_all: set[int]) -> dict:
    """Mapuje skróty przedmiotów na pełne nazwy z legendy po prawej stronie."""
    if not date_columns_all:
        return {}

    last_date_col = max(date_columns_all)
    legend: dict[str, str] = {}
    seen: set[int] = set()

    for row_idx in sorted(grid.keys()):
        row = grid[row_idx]
        right = [(c, row[c]) for c in sorted(row) if c > last_date_col]
        if len(right) < 2:
            continue

        code_cell, name_cell = right[0][1], right[1][1]
        if id(code_cell) in seen:
            continue
        seen.add(id(code_cell))

        code = code_cell["text"].strip()
        name = name_cell["text"].strip()

        if not code or not name:
            continue
        if TYPE_TOKEN_RE.match(code):      # "w 24", "L 12" -> to prowadzący, nie przedmiot
            continue
        if "\n" in code or len(code) > 12:
            continue
        if len(name) <= len(code) or name == code:
            continue

        legend.setdefault(code, name)

    return legend


def find_time_slot(cell_text: str) -> str | None:
    for slot in TIME_MAP:
        if slot in cell_text:
            return slot
    return None


def parse_event_details(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Adnotacja procentowa na początku (np. "50%" = połowa grupy)
    share = ""
    while lines and re.match(r"^\d+%$", lines[0]):
        share = lines[0]
        lines = lines[1:]

    if not lines:
        return {"summary": "", "room": "", "teacher": "", "notes": "", "share": share}

    summary = lines[0]
    room = ""
    teacher = ""
    notes_lines = []

    for line in lines[1:]:
        if re.search(r"\b(dr|mgr|prof|inż|kpt|ppłk|mjr|por|chor|kmdr|kpr|mł\.)\b",
                     line, re.IGNORECASE):
            teacher = line
        elif re.match(r"^(w|ć|L|S|E|r|i|P|Ep|Zp\.|Rep)$", line):
            notes_lines.append(line)
        else:
            room = f"{room}; {line}" if room else line

    return {
        "summary": summary,
        "room": room,
        "teacher": teacher,
        "notes": "\n".join(notes_lines),
        "share": share,
    }


def load_wf_details(xlsx_path: str) -> dict:
    if not HAS_OPENPYXL or not Path(xlsx_path).exists():
        return {}

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    details = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        date_val = row[0]
        opis = row[2] if len(row) > 2 else None
        if date_val and opis:
            key = date_val.date() if isinstance(date_val, datetime) else str(date_val)
            details[key] = str(opis)
    print(f"Wczytano {len(details)} wpisów WF z {xlsx_path}")
    return details


def should_skip(text: str) -> bool:
    first_line = next((l.strip() for l in text.split("\n") if l.strip()), "")
    if re.match(r"^\d+%$", first_line):
        parts = [l.strip() for l in text.split("\n") if l.strip()]
        first_line = parts[1] if len(parts) > 1 else ""

    if first_line in SKIP_KEYWORDS:
        return True
    if any(kw in text for kw in SKIP_KEYWORDS):
        return True
    if SKIP_PREFIX_X and re.match(r"^X[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]", first_line):
        return True
    return False


# --------------------------------------------------------------------------
# Budowa ICS
# --------------------------------------------------------------------------

def make_uid(date: datetime, slot: str, col_idx: int, text: str) -> str:
    raw = f"{date.isoformat()}-{slot}-{col_idx}-{text}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"{date.strftime('%Y%m%d')}-{slot.replace('-', '')}-c{col_idx}-{h}@wat.edu.pl"


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def escape_ics(text: str) -> str:
    return (text.replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n"))


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


VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    f"TZID:{TIMEZONE_ID}",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
]


def build_ics(events: list[dict], meta: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    sem_label = {"zima": "Zima", "lato": "Lato"}.get(meta.get("semester", ""), "")
    year_label = ""
    if meta.get("academic_year_start"):
        year_label = f" {meta['academic_year_start']}/{meta['academic_year_end']}"
    cal_name = f"WAT {meta.get('group', '')} {sem_label}{year_label}".strip()

    desc_bits = [f"Źródło: {meta.get('url', '')}"]
    if meta.get("source_updated"):
        desc_bits.append(f"Aktualizacja planu: {meta['source_updated']}")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WAT WEL Plan zajec//PL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold_line(f"X-WR-CALNAME:{cal_name}"),
        fold_line(f"X-WR-CALDESC:{escape_ics(' | '.join(desc_bits))}"),
        f"X-WR-TIMEZONE:{TIMEZONE_ID}",
        *VTIMEZONE,
    ]

    for ev in events:
        lines += [
            "BEGIN:VEVENT",
            fold_line(f"UID:{ev['uid']}"),
            f"DTSTAMP:{now}",
            f"DTSTART;TZID={TIMEZONE_ID}:{ev['dtstart']}",
            f"DTEND;TZID={TIMEZONE_ID}:{ev['dtend']}",
            fold_line(f"SUMMARY:{escape_ics(ev['summary'])}"),
        ]
        if ev.get("location"):
            lines.append(fold_line(f"LOCATION:{escape_ics(ev['location'])}"))
        if ev.get("description"):
            lines.append(fold_line(f"DESCRIPTION:{escape_ics(ev['description'])}"))
        lines += ["STATUS:CONFIRMED", "SEQUENCE:0", "END:VEVENT"]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# --------------------------------------------------------------------------

def process_schedule(grid: dict, wf_details: dict, year_start: int,
                     legend: dict) -> list[dict]:
    events: list[dict] = []
    processed_cells = set()

    all_date_rows = find_all_date_rows(grid, year_start)
    if not all_date_rows:
        print("BŁĄD: Nie znaleziono wierszy z datami!")
        return events

    print(f"Znaleziono {len(all_date_rows)} wierszy nagłówkowych z datami.")

    date_row_indices = [r for r, _ in all_date_rows]
    max_row = max(grid.keys())

    for block_i, (date_row_idx, date_columns) in enumerate(all_date_rows):
        block_end = (date_row_indices[block_i + 1]
                     if block_i + 1 < len(all_date_rows) else max_row + 1)

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

                cell_key = (id(cell), col_idx)
                if cell_key in processed_cells:
                    continue

                text = cell["text"].strip()
                if not text or should_skip(text):
                    continue

                processed_cells.add(cell_key)

                sh, sm = map(int, start_str.split(":"))
                eh, em = map(int, end_str.split(":"))
                dtstart = base_date.replace(hour=sh, minute=sm)
                dtend = base_date.replace(hour=eh, minute=em)

                rowspan = cell.get("rowspan", 1)
                if rowspan > 1:
                    last_row = grid.get(row_idx + rowspan - 1, {})
                    last_slot = None
                    for check_col in sorted(last_row.keys())[:3]:
                        last_slot = find_time_slot(last_row[check_col]["text"])
                        if last_slot:
                            break
                    if last_slot:
                        leh, lem = map(int, TIME_MAP[last_slot][1].split(":"))
                        dtend = base_date.replace(hour=leh, minute=lem)

                details = parse_event_details(text)
                summary = details["summary"]

                desc_parts = []
                full_name = legend.get(summary)
                if full_name:
                    desc_parts.append(full_name)
                if details["notes"]:
                    desc_parts.append(", ".join(
                        TYPE_NAMES.get(n, n) for n in details["notes"].split("\n")
                    ))
                if details["teacher"]:
                    desc_parts.append(f"Prowadzący: {details['teacher']}")
                if details["share"]:
                    desc_parts.append(f"Grupa: {details['share']}")

                wf_location = ""
                if "WF" in summary.upper() and wf_details:
                    wf_location = wf_details.get(base_date.date(), "")
                    if wf_location:
                        desc_parts.append(f"WF: {wf_location}")

                events.append({
                    "uid": make_uid(base_date, slot, col_idx, text),
                    "dtstart": format_dt(dtstart),
                    "dtend": format_dt(dtend),
                    "summary": summary,
                    "location": wf_location or details["room"],
                    "description": "\n".join(desc_parts),
                })

    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="WAT WEL: JSON rozkładu -> ICS")
    parser.add_argument("group", nargs="?", default=DEFAULT_GROUP)
    parser.add_argument("semester", nargs="?", default=DEFAULT_SEMESTER,
                        choices=["zima", "lato"])
    args = parser.parse_args()

    input_json = f"{args.group}_{args.semester}_raw.json"
    output_ics = f"{args.group}_{args.semester}.ics"

    print(f"Wczytywanie: {input_json}")
    with open(input_json, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta", {})
    rows = data.get("rows", [])
    meta.setdefault("group", args.group)
    meta.setdefault("semester", args.semester)

    year_start = meta.get("academic_year_start")
    if not year_start:
        year_start = default_academic_year_start()
        print(f"  brak roku w metadanych — przyjmuję {year_start}/{year_start + 1}")
    print(f"Rok akademicki: {year_start}/{year_start + 1}")

    grid = build_grid(rows)
    print(f"Zbudowano grid: {len(grid)} wierszy")

    date_cols: set[int] = set()
    for _, cols in find_all_date_rows(grid, year_start):
        date_cols.update(cols)
    legend = build_subject_legend(grid, date_cols)
    print(f"Legenda przedmiotów: {len(legend)} pozycji")

    wf_candidates = [f"{args.group}_{args.semester}_wf.xlsx", f"{args.group}_wf.xlsx"]
    wf_path = next((p for p in wf_candidates if Path(p).exists()), "")
    wf_details = load_wf_details(wf_path) if wf_path else {}

    events = process_schedule(grid, wf_details, year_start, legend)
    print(f"Wygenerowano {len(events)} eventów")

    with open(output_ics, "w", encoding="utf-8", newline="") as f:
        f.write(build_ics(events, meta))

    print(f"Zapisano: {output_ics}")

    print("\n--- Pierwsze 5 eventów ---")
    for ev in events[:5]:
        print(f"  {ev['dtstart']} | {ev['summary']!r} | {ev['location']!r}")


if __name__ == "__main__":
    main()
