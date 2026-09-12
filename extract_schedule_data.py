#!/usr/bin/env python3
"""
Etap 1: HTML -> JSON

Pobiera stronę z rozkładem zajęć WAT WEL i zapisuje surowe dane tabeli
razem z metadanymi (rok akademicki, semestr, data aktualizacji) do JSON.

Użycie:
    python extract_schedule_data.py [GRUPA] [SEMESTR]
    python extract_schedule_data.py WEL24EL2S0 zima
    python extract_schedule_data.py WEL24EL2S0 zima --from-file strona.htm
"""

import argparse
import json
import re
from datetime import datetime, timezone

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Od roku akademickiego 2026/2027 plany są na wel.wat.edu.pl.
# Stary host plany.wel.wat.edu.pl nie rozwiązuje się już w DNS.
BASE_URL = "https://wel.wat.edu.pl/planyzajec/{semester}/{group}.htm"

DEFAULT_GROUP = "WEL24EL2S0"
DEFAULT_SEMESTER = "zima"

# Serwer WEL odrzuca żądania bez przeglądarkowego User-Agenta (403).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def fetch_html(url: str) -> str:
    """Pobiera stronę i dekoduje ją zgodnie z deklarowanym kodowaniem.

    Serwer nie wysyła charset w nagłówku Content-Type, więc requests
    domyślnie przyjąłby ISO-8859-1 i rozwalił polskie znaki. Kodowanie
    odczytujemy z <meta>, z fallbackiem na utf-8.
    """
    print(f"Pobieranie strony: {url}")
    try:
        response = requests.get(url, timeout=30, headers=HEADERS)
    except requests.exceptions.SSLError as exc:
        print(f"  ostrzeżenie: problem z certyfikatem ({exc}), ponawiam bez weryfikacji")
        response = requests.get(url, timeout=30, headers=HEADERS, verify=False)
    response.raise_for_status()
    return decode_html(response.content)


def decode_html(raw: bytes) -> str:
    head = raw[:2048].decode("ascii", errors="ignore")
    match = re.search(r'charset\s*=\s*["\']?([\w-]+)', head, re.IGNORECASE)
    encoding = match.group(1).lower() if match else "utf-8"
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        print(f"  ostrzeżenie: kodowanie {encoding!r} zawiodło, próbuję utf-8")
        return raw.decode("utf-8", errors="replace")


def parse_header(soup: BeautifulSoup) -> dict:
    """Wyciąga rok akademicki, semestr i datę aktualizacji z nagłówka strony."""
    text = " ".join(soup.get_text(separator=" ").split())
    meta: dict = {}

    year = re.search(r"ROK\s+AKADEMICKI\s+(\d{4})\s*/\s*(\d{4})", text, re.IGNORECASE)
    if year:
        meta["academic_year_start"] = int(year.group(1))
        meta["academic_year_end"] = int(year.group(2))

    sem = re.search(r"SEMESTR\s+(ZIMOWY|LETNI)", text, re.IGNORECASE)
    if sem:
        meta["semester_label"] = sem.group(1).lower()

    updated = re.search(
        r"Data\s+aktualizacji:\s*([\d]{2}\.[\d]{2}\.[\d]{4}(?:\s+[\d:]{8})?)", text
    )
    if updated:
        meta["source_updated"] = updated.group(1).strip()

    return meta


def extract_table_data(soup: BeautifulSoup) -> list[list[dict]]:
    """Parsuje tabelę rozkładu do listy wierszy z komórkami."""
    table = soup.find("table")
    if not table:
        raise ValueError("Nie znaleziono tabeli na stronie!")

    rows_data = []
    for row_idx, tr in enumerate(table.find_all("tr")):
        cells = []
        for cell_idx, td in enumerate(tr.find_all(["td", "th"])):
            cells.append(
                {
                    "text": td.get_text(separator="\n", strip=True).replace("\xa0", " "),
                    "colspan": int(td.get("colspan", 1)),
                    "rowspan": int(td.get("rowspan", 1)),
                    "bgcolor": td.get("bgcolor", ""),
                    "style": td.get("style", ""),
                    "row_idx": row_idx,
                    "cell_idx": cell_idx,
                }
            )
        if cells:
            rows_data.append(cells)

    print(f"Znaleziono {len(rows_data)} wierszy w tabeli.")
    return rows_data


def main() -> None:
    parser = argparse.ArgumentParser(description="WAT WEL: HTML rozkładu -> JSON")
    parser.add_argument("group", nargs="?", default=DEFAULT_GROUP)
    parser.add_argument("semester", nargs="?", default=DEFAULT_SEMESTER,
                        choices=["zima", "lato"])
    parser.add_argument("--from-file", dest="from_file",
                        help="użyj lokalnego pliku HTML zamiast pobierania")
    args = parser.parse_args()

    url = BASE_URL.format(semester=args.semester, group=args.group)

    if args.from_file:
        print(f"Wczytywanie lokalnego pliku: {args.from_file}")
        with open(args.from_file, "rb") as f:
            html = decode_html(f.read())
    else:
        html = fetch_html(url)

    soup = BeautifulSoup(html, "html.parser")

    meta = {
        "group": args.group,
        "semester": args.semester,
        "url": url,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    meta.update(parse_header(soup))

    rows = extract_table_data(soup)

    output_file = f"{args.group}_{args.semester}_raw.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rows": rows}, f, ensure_ascii=False, indent=2)

    print(f"Zapisano dane do: {output_file}")
    print(f"  rok akademicki: {meta.get('academic_year_start', '?')}"
          f"/{meta.get('academic_year_end', '?')}")
    print(f"  semestr: {meta.get('semester_label', args.semester)}")
    print(f"  aktualizacja planu: {meta.get('source_updated', 'brak')}")

    print("\n--- Podgląd pierwszych 3 wierszy ---")
    for i, row in enumerate(rows[:3]):
        print(f"Wiersz {i}: {len(row)} komórek")
        for cell in row[:4]:
            preview = cell["text"][:50].replace("\n", " ")
            print(f"  [{cell['cell_idx']}] cs={cell['colspan']} "
                  f"rs={cell['rowspan']} | {preview!r}")


if __name__ == "__main__":
    main()
