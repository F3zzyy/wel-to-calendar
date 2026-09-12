# WAT WEL Plan zajęć → Google Calendar

Automatyczne generowanie pliku ICS z rozkładu zajęć WAT WEL dla grupy
**WEL24EL2S0**, aktualizowanego codziennie przez GitHub Actions.

Aktualny semestr: **zimowy 2026/2027**.

## Jak to działa

```
https://wel.wat.edu.pl/planyzajec/zima/WEL24EL2S0.htm
          ↓
extract_schedule_data.py
          ↓
WEL24EL2S0_zima_raw.json   ← źródło prawdy do debugowania (meta + surowa tabela)
          ↓
generate_ics_from_json.py  +  WEL24EL2S0_zima_wf.xlsx (opcjonalnie)
          ↓
WEL24EL2S0_zima.ics
          ↓
GitHub raw URL → subskrypcja Google Calendar
```

## Użycie lokalne

```bash
pip install -r requirements.txt

# Etap 1: pobierz plan do JSON
python extract_schedule_data.py WEL24EL2S0 zima

# Etap 2: wygeneruj ICS
python generate_ics_from_json.py WEL24EL2S0 zima
```

Oba skrypty domyślnie przyjmują `WEL24EL2S0 zima`, więc można je uruchomić
bez argumentów. Do debugowania parsera bez sieci:

```bash
python extract_schedule_data.py WEL24EL2S0 zima --from-file zapisana_strona.htm
```

## Zmiana semestru

Semestr jest argumentem, nie stałą w kodzie. Po zakończeniu zimowego:

1. W `.github/workflows/update-ics.yml` zmień `SEMESTER` na `lato`.
2. Uruchom workflow ręcznie (Actions → Run workflow) albo poczekaj na cron.
3. Zaktualizuj URL subskrypcji w Google Calendar na `..._lato.ics`.

Rok kalendarzowy **nie jest** nigdzie wpisany na sztywno — skrypt czyta
`ROK AKADEMICKI 2026/2027` z nagłówka strony i sam rozstrzyga przełom roku
(październik–grudzień → 2026, styczeń–luty → 2027).

## Subskrypcja w Google Calendar

1. Google Calendar → Inne kalendarze → **Dodaj z adresu URL**
2. Wklej:
   ```
   https://raw.githubusercontent.com/F3zzyy/wel-to-calendar/main/WEL24EL2S0_zima.ics
   ```
3. Kliknij **Dodaj kalendarz**

Google odświeża subskrybowane kalendarze automatycznie (zwykle co kilka godzin,
czasem rzadziej — to ograniczenie Google, nie tego repo).

## Opcjonalny plik WF

Umieść `WEL24EL2S0_zima_wf.xlsx` (albo `WEL24EL2S0_wf.xlsx`) w katalogu projektu:

- **kolumna A**: data (format daty Excel)
- **kolumna C**: opis zajęć WF wraz z salą

Opisy trafiają do pola LOCATION i DESCRIPTION eventów z „WF" w nazwie.

## Automatyzacja (GitHub Actions)

Workflow `.github/workflows/update-ics.yml`:

- **codziennie o 06:00 UTC** (08:00 czasu polskiego)
- **ręcznie** przez Actions → Run workflow (można podać inną grupę/semestr)

Commit powstaje tylko wtedy, gdy zmienił się plik `.ics` — samo odpytanie
serwera nie generuje szumu w historii.

## Struktura projektu

```
.
├── extract_schedule_data.py        # Etap 1: HTML → JSON
├── generate_ics_from_json.py       # Etap 2: JSON → ICS
├── requirements.txt
├── WEL24EL2S0_zima_wf.xlsx         # (opcjonalnie) szczegóły WF
├── WEL24EL2S0_zima_raw.json        # (generowany) meta + surowa tabela
├── WEL24EL2S0_zima.ics             # (generowany) plik kalendarza
└── .github/
    └── workflows/
        └── update-ics.yml          # Automatyzacja
```

## Konfiguracja

W `generate_ics_from_json.py`:

| Zmienna | Opis |
|---------|------|
| `TIME_MAP` | Mapa slotów godzinowych na godziny — sprawdź z [siatką godzinową WEL](https://www.wel.wat.edu.pl/przydatne-informacje/siatka-godzinowa-zajec/) |
| `SKIP_KEYWORDS` | Komórki pomijane w całości (domyślnie `SSW`) |
| `SKIP_PREFIX_X` | Pomija przedmioty powtarzane (`XWF`, `XFiz1`, …) |
| `TYPE_NAMES` | Rozwinięcia skrótów typu zajęć (w → wykład itd.) |
| `TIMEZONE_ID` | Strefa czasowa eventów (`Europe/Warsaw`) |

Eventy mają jawny `TZID=Europe/Warsaw` i blok `VTIMEZONE`, więc zmiana czasu
pod koniec października nie przesuwa zajęć.

## Uwagi o danych źródłowych

- Kolumny lutego bywają puste do czasu ogłoszenia sesji — wtedy ICS po prostu
  kończy się na styczniu i uzupełni się sam przy kolejnym przebiegu.
- Strona podaje `Data aktualizacji` — trafia ona do `X-WR-CALDESC` w ICS.
- Stary host `plany.wel.wat.edu.pl` już nie działa (brak wpisu DNS).

## Walidacja ICS

https://icalendar.org/validator.html
