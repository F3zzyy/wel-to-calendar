#!/usr/bin/env python3
"""
JEDYNY skrypt, który uruchamiasz (robi to też GitHub Actions codziennie o 06:00 UTC).

    python aktualizuj.py             # pobiera plany z WAT i buduje kalendarz
    python aktualizuj.py --offline   # bez internetu, z ostatnich planów zapisanych w dane/

Co robi, po kolei:
  1. Czyta USTAWIENIA.toml (grupa + link do planu zimowego i letniego).
  2. Pobiera OBA plany. Gdy któregoś nie da się pobrać (awaria WAT, zmiana adresu),
     bierze ostatnią dobrą wersję z dane/ — kalendarz nie traci zajęć przez chwilowy błąd.
  3. Zostawia tylko plany z najnowszego roku akademickiego, więc stary plan, który
     WAT zostawił na stronie, nie wraca do kalendarza. Zima/lato przełącza się samo.
  4. Dla każdego semestru dokleja szczegóły WF z folderu WF/<rok>_<semestr>/
     (najnowszy plik .xlsx). Folder na nowy semestr tworzy się sam.
  5. Zapisuje jeden kalendarz <grupa>.ics + identyczną kopię <grupa>_zima.ics
     (stara nazwa, żeby dotychczasowe subskrypcje dalej działały).

Ostrzeżenia widać w GitHubie: Actions → ostatni przebieg → podsumowanie.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import generate_ics_from_json as gen

ROOT = Path(__file__).resolve().parent
USTAWIENIA = ROOT / "USTAWIENIA.toml"
DANE = ROOT / "dane"
WF = ROOT / "WF"
WF_MARKER = "TUTAJ_WRZUC_PLIK_WF.txt"
WF_FOLDER_RE = re.compile(r"^\d{4}-\d{4}_(zima|lato)$")
SEMESTRY = {"zima": "zimowy", "lato": "letni"}
W_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"

podsumowanie: list[str] = []


# --------------------------------------------------------------------------
# Komunikaty (w GitHub Actions ostrzeżenia trafiają też na stronę przebiegu)
# --------------------------------------------------------------------------

def info(msg: str) -> None:
    print(msg)


def uwaga(msg: str) -> None:
    print(f"UWAGA: {msg}")
    podsumowanie.append(f"- ⚠️ {msg}")
    if W_ACTIONS:
        print(f"::warning::{msg}")


def blad(msg: str) -> None:
    print(f"\nBŁĄD: {msg}\n", file=sys.stderr)
    if W_ACTIONS:
        print(f"::error::{msg.replace(chr(10), '%0A')}")
        zapisz_podsumowanie(f"❌ {msg}")
    sys.exit(1)


def zapisz_podsumowanie(naglowek: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"### {naglowek}\n\n" + "\n".join(podsumowanie) + "\n")


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# --------------------------------------------------------------------------
# USTAWIENIA.toml
# --------------------------------------------------------------------------

def wczytaj_ustawienia() -> tuple[str, dict[str, str]]:
    if not USTAWIENIA.exists():
        blad("Brak pliku USTAWIENIA.toml w głównym folderze repo.")
    try:
        cfg = tomllib.loads(USTAWIENIA.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        blad(f"USTAWIENIA.toml ma błąd składni ({e}).\n"
             "Najczęstsza przyczyna: brak cudzysłowu na początku albo końcu linku.")

    grupa = cfg.get("grupa")
    if not isinstance(grupa, str) or not grupa.strip():
        blad('W USTAWIENIA.toml brakuje linii:  grupa = "WEL24EL2S0"')

    plany = cfg.get("plany")
    if not isinstance(plany, dict):
        blad("W USTAWIENIA.toml brakuje sekcji [plany] z liniami zima = ... i lato = ...")
    nieznane = set(plany) - set(SEMESTRY)
    if nieznane:
        blad(f"W [plany] są nieznane nazwy: {', '.join(sorted(nieznane))}. "
             "Dozwolone tylko: zima, lato.")

    linki = {}
    for sem in SEMESTRY:
        url = plany.get(sem, "")
        if not isinstance(url, str):
            blad(f'Link "{sem}" w USTAWIENIA.toml musi być w cudzysłowie.')
        url = url.strip()
        if url and not url.startswith(("https://", "http://")):
            blad(f'Link "{sem}" musi zaczynać się od https:// — jest: {url!r}')
        linki[sem] = url
    if not any(linki.values()):
        blad("Oba linki w [plany] są puste — nie ma czego pobierać.")
    return grupa.strip(), linki


# --------------------------------------------------------------------------
# Plany WAT
# --------------------------------------------------------------------------

def problem_z_planem(data: dict, sem: str) -> str | None:
    """Zwraca opis problemu albo None, jeśli plan wygląda poprawnie."""
    meta, rows = data.get("meta", {}), data.get("rows") or []
    if not rows:
        return "na stronie nie ma tabeli z planem"
    if not meta.get("academic_year_start"):
        return "na stronie nie ma nagłówka „ROK AKADEMICKI ...”"
    label = meta.get("semester_label")
    if label and label != SEMESTRY[sem]:
        return (f"to jest plan semestru {label.upper()}, a link jest wpisany jako „{sem}” "
                "— sprawdź, czy linki w USTAWIENIA.toml nie są zamienione miejscami")
    if not gen.find_all_date_rows(gen.build_grid(rows), meta["academic_year_start"]):
        return "w tabeli nie ma wierszy z datami (WAT zmienił wygląd strony?)"
    return None


def zapas(cache: Path) -> str:
    return ("Na razie używam ostatniej zapisanej wersji." if cache.exists()
            else "Zapisanej wersji brak, więc ten semestr jest pominięty.")


def wczytaj_plan(sem: str, url: str, offline: bool) -> dict | None:
    cache = DANE / f"{sem}.json"

    if not url:
        info(f"[{sem}] link w USTAWIENIA.toml jest pusty — pomijam ten semestr")
        return None

    if not offline:
        import requests  # tylko tutaj, żeby --offline działał bez sieci
        import extract_schedule_data as ext
        try:
            data = ext.pobierz_plan(url)
            problem = problem_z_planem(data, sem)
            if problem:
                raise ValueError(problem)
            DANE.mkdir(exist_ok=True)
            cache.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
            info(f"[{sem}] pobrano plan {data['meta']['academic_year_start']}/"
                 f"{data['meta']['academic_year_end']}")
            return data
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code == 404 and not cache.exists():
                info(f"[{sem}] WAT nie opublikował jeszcze tego planu (404) — pomijam")
                return None
            uwaga(f"[{sem}] strona planu zwraca błąd {code}. Jeśli WAT zmienił adres, "
                  f"wklej nowy link w USTAWIENIA.toml. {zapas(cache)}")
        except Exception as e:
            uwaga(f"[{sem}] nie udało się pobrać planu ({e}). {zapas(cache)}")

    if not cache.exists():
        info(f"[{sem}] brak zapisanej wersji planu — pomijam ten semestr")
        return None
    data = json.loads(cache.read_text(encoding="utf-8"))
    problem = problem_z_planem(data, sem)
    if problem:
        uwaga(f"[{sem}] zapisana wersja planu jest niepoprawna ({problem}) — pomijam")
        return None
    info(f"[{sem}] używam zapisanej wersji z {data['meta'].get('fetched_at', '?')}")
    return data


# --------------------------------------------------------------------------
# WF
# --------------------------------------------------------------------------

def czas_dodania(p: Path) -> tuple[int, float]:
    """Klucz „który plik jest nowszy”: data commita, a plik niescommitowany wygrywa."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", p.name],
                             cwd=p.parent, capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return (0, float(out.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return (1, p.stat().st_mtime)


def folder_wf(sem: str, year: int) -> Path:
    folder = WF / f"{year}-{year + 1}_{sem}"
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / WF_MARKER
    if not marker.exists():
        marker.write_text(
            f"Wrzuć tutaj plan WF na semestr {SEMESTRY[sem]} {year}/{year + 1} (plik .xlsx).\n"
            "Nazwa pliku jest dowolna. Gdy dostaniesz poprawioną wersję, po prostu wrzuć ją\n"
            "obok — używany jest zawsze najnowszy plik, starszy możesz usunąć.\n",
            encoding="utf-8")
    return folder


def wybierz_plik_wf(folder: Path) -> Path | None:
    pliki = [p for p in folder.iterdir() if p.is_file() and p.name != WF_MARKER
             and not p.name.startswith(("~$", "."))]
    xlsx = [p for p in pliki if p.suffix.lower() == ".xlsx"]
    for p in pliki:
        if p not in xlsx:
            uwaga(f"{rel(p)}: obsługuję tylko pliki .xlsx — otwórz go w Excelu/LibreOffice "
                  "i zapisz jako .xlsx")
    if not xlsx:
        return None
    xlsx.sort(key=czas_dodania)
    if len(xlsx) > 1:
        info(f"W {rel(folder)} jest kilka plików WF ({len(xlsx)}) — używam najnowszego: "
             f"{xlsx[-1].name} (starsze możesz usunąć)")
    return xlsx[-1]


def sprawdz_zabladzone_pliki_wf() -> None:
    if not WF.exists():
        return
    for p in WF.rglob("*"):
        if not p.is_file() or p.name in (WF_MARKER, "README.md") or p.name.startswith("."):
            continue
        if p.parent.parent != WF or not WF_FOLDER_RE.match(p.parent.name):
            uwaga(f"{rel(p)} leży poza folderem semestru, więc jest ignorowany. "
                  "Przenieś go do folderu w stylu WF/2026-2027_zima/")


# --------------------------------------------------------------------------

def eventy_semestru(sem: str, data: dict) -> list[dict]:
    meta, year = data["meta"], data["meta"]["academic_year_start"]
    grid = gen.build_grid(data["rows"])
    date_cols: set[int] = set()
    for _, cols in gen.find_all_date_rows(grid, year):
        date_cols.update(cols)
    legend = gen.build_subject_legend(grid, date_cols)

    wf_details: dict = {}
    plik = wybierz_plik_wf(folder_wf(sem, year))
    if plik:
        try:
            wf_details = gen.load_wf_details(str(plik), year)
        except Exception as e:
            uwaga(f"{rel(plik)}: nie umiem odczytać tego pliku ({e}) — pomijam WF")
        if not wf_details and plik:
            uwaga(f"{rel(plik)}: nie znalazłem w nim dat (kolumna A) — pomijam WF")

    events = gen.process_schedule(grid, wf_details, year, legend)

    opis = f"{sem} {year}/{year + 1}: {len(events)} zajęć"
    if wf_details:
        dni_wf = {e["dtstart"][:8] for e in events if e["summary"].upper() == "WF"}
        brak = sorted(d for d in wf_details if d.strftime("%Y%m%d") not in dni_wf)
        if brak:
            uwaga(f"{rel(plik)}: {len(brak)} dat z pliku WF nie ma w planie WAT jako WF "
                  f"({', '.join(d.strftime('%d.%m') for d in brak)}) — to na pewno plan Twojego plutonu?")
        opis += f", WF z pliku {plik.name} ({len(wf_details) - len(brak)}/{len(wf_details)} dopasowanych)"
    podsumowanie.append(f"- ✅ {opis}")
    info(opis)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Buduje kalendarz z planu WAT.")
    parser.add_argument("--offline", action="store_true",
                        help="nie pobieraj z WAT, użyj planów zapisanych w dane/")
    args = parser.parse_args()

    grupa, linki = wczytaj_ustawienia()

    plany = {sem: d for sem, url in linki.items()
             if (d := wczytaj_plan(sem, url, args.offline)) is not None}
    if not plany:
        blad("Nie mam żadnego planu (ani pobranego, ani zapisanego). Sprawdź linki w "
             "USTAWIENIA.toml — otwórz je w przeglądarce. Kalendarz NIE został zmieniony.")

    najnowszy = max(d["meta"]["academic_year_start"] for d in plany.values())
    for sem in list(plany):
        y = plany[sem]["meta"]["academic_year_start"]
        if y < najnowszy:
            info(f"[{sem}] plan z roku {y}/{y + 1} jest starszy niż {najnowszy}/{najnowszy + 1} — pomijam")
            del plany[sem]

    events: dict[str, dict] = {}
    for sem, data in plany.items():
        for ev in eventy_semestru(sem, data):
            events.setdefault(ev["uid"], ev)
    sprawdz_zabladzone_pliki_wf()

    if not events:
        blad("Z planów wyszło 0 zajęć — nie nadpisuję kalendarza. Otwórz linki z "
             "USTAWIENIA.toml w przeglądarce i sprawdź, czy plan tam jest.")

    lista = sorted(events.values(), key=lambda e: (e["dtstart"], e["uid"]))
    opis = " | ".join(
        f"{sem} {d['meta']['academic_year_start']}/{d['meta']['academic_year_end']}: "
        f"{d['meta'].get('url', '')} (aktualizacja {d['meta'].get('source_updated', '?')})"
        for sem, d in plany.items())
    dtstamp = max(gen.build_dtstamp(d["meta"]) for d in plany.values())
    ics = gen.build_ics(lista, f"WAT {grupa}", opis, dtstamp)

    for nazwa in (f"{grupa}.ics", f"{grupa}_zima.ics"):
        with open(ROOT / nazwa, "w", encoding="utf-8", newline="") as f:
            f.write(ics)
    info(f"Zapisano {len(lista)} zajęć do {grupa}.ics (+ kopia {grupa}_zima.ics)")
    zapisz_podsumowanie(f"Kalendarz {grupa}.ics — {len(lista)} zajęć")


if __name__ == "__main__":
    main()
