#!/usr/bin/env python3
"""
Etap 1: HTML → JSON
Pobiera stronę z planem WAT i zapisuje surowe dane tabeli do JSON.
"""
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import json
import requests
from bs4 import BeautifulSoup

URL = "https://plany.wel.wat.edu.pl/lato/WEL24EL2S0.htm"
OUTPUT_FILE = "WEL24EL2S0_lato_raw.json"


def extract_table_data(url: str) -> list[list[dict]]:
    """Pobiera stronę i parsuje tabelę do listy wierszy z komórkami."""
    print(f"Pobieranie strony: {url}")
    response = requests.get(url, timeout=15, verify=False)
    response.encoding = "windows-1250"
    html = response.text

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError("Nie znaleziono tabeli na stronie!")

    rows_data = []
    for row_idx, tr in enumerate(table.find_all("tr")):
        cells = []
        for cell_idx, td in enumerate(tr.find_all(["td", "th"])):
            text = td.get_text(separator="\n", strip=True)
            colspan = int(td.get("colspan", 1))
            rowspan = int(td.get("rowspan", 1))
            bgcolor = td.get("bgcolor", "")
            style = td.get("style", "")

            cells.append(
                {
                    "text": text,
                    "colspan": colspan,
                    "rowspan": rowspan,
                    "bgcolor": bgcolor,
                    "style": style,
                    "row_idx": row_idx,
                    "cell_idx": cell_idx,
                }
            )
        if cells:
            rows_data.append(cells)

    print(f"Znaleziono {len(rows_data)} wierszy w tabeli.")
    return rows_data


def main():
    rows = extract_table_data(URL)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"Zapisano dane do: {OUTPUT_FILE}")

    # Podgląd pierwszych wierszy
    print("\n--- Podgląd pierwszych 3 wierszy ---")
    for i, row in enumerate(rows[:3]):
        print(f"Wiersz {i}: {len(row)} komórek")
        for cell in row[:4]:
            preview = cell["text"][:50].replace("\n", " ")
            print(
                f"  [{cell['cell_idx']}] cs={cell['colspan']} rs={cell['rowspan']} | {preview!r}"
            )


if __name__ == "__main__":
    main()
