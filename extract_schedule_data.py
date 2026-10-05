#!/usr/bin/env python3
"""
Etap 1: HTML planu WAT -> surowe dane tabeli + metadane.

Nie uruchamiaj tego pliku bezpośrednio — używa go aktualizuj.py.
Adresy planów są w USTAWIENIA.toml.
"""

import json
import re
from datetime import datetime, timezone

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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


def pobierz_plan(url: str) -> dict:
    """Pobiera stronę planu i zwraca {"meta": {...}, "rows": [...]}."""
    soup = BeautifulSoup(fetch_html(url), "html.parser")
    meta = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    meta.update(parse_header(soup))
    return {"meta": meta, "rows": extract_table_data(soup)}
