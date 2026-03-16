# WAT WEL Plan zajęć → Google Calendar

Automatyczne generowanie pliku ICS z planu zajęć WAT WEL, aktualizowanego codziennie przez GitHub Actions.

## Jak to działa

```
https://plany.wel.wat.edu.pl/lato/WEL24EL2S0.htm
          ↓
extract_schedule_data.py
          ↓
WEL24EL2S0_lato_raw.json   ← źródło prawdy do debugowania
          ↓
generate_ics_from_json.py  +  wf_details.xlsx (opcjonalnie)
          ↓
WEL24EL2S0_lato.ics
          ↓
GitHub raw URL → subskrypcja Google Calendar
```

## Użycie lokalne

```bash
pip install -r requirements.txt

# Etap 1: pobierz plan do JSON
python extract_schedule_data.py

# Etap 2: wygeneruj ICS
python generate_ics_from_json.py
```

## Subskrypcja w Google Calendar

1. Wejdź w Google Calendar → Inne kalendarze → **Dodaj z adresu URL**
2. Wklej:
   ```
   https://raw.githubusercontent.com/TWOJ_LOGIN/TWOJ_REPO/main/WEL24EL2S0_lato.ics
   ```
3. Kliknij **Dodaj kalendarz**

Google Calendar odświeża subskrybowane kalendarze automatycznie (zazwyczaj co kilka godzin).

## Opcjonalny plik WF

Umieść plik `wf_details.xlsx` w katalogu projektu z kolumnami:
- **A**: data (format daty Excel)
- **B**: opis zajęć WF

Skrypt automatycznie dołączy opisy do eventów z "WF" w nazwie.

## Automatyzacja (GitHub Actions)

Workflow `.github/workflows/update-ics.yml` uruchamia się:
- **Codziennie o 06:00 UTC** (08:00 czasu polskiego)
- **Ręcznie** przez zakładkę Actions → Run workflow

Commit pojawia się tylko wtedy, gdy plan faktycznie się zmienił.

## Struktura projektu

```
.
├── extract_schedule_data.py     # Etap 1: HTML → JSON
├── generate_ics_from_json.py    # Etap 2: JSON → ICS
├── requirements.txt
├── wf_details.xlsx              # (opcjonalnie) szczegóły WF
├── WEL24EL2S0_lato_raw.json    # (generowany) surowe dane
├── WEL24EL2S0_lato.ics         # (generowany) plik kalendarza
└── .github/
    └── workflows/
        └── update-ics.yml       # Automatyzacja
```

## Konfiguracja

W pliku `generate_ics_from_json.py` możesz dostosować:

| Zmienna | Opis |
|---------|------|
| `YEAR` | Rok semestru (domyślnie 2026) |
| `TIME_MAP` | Mapa slotów godzinowych na godziny |
| `SKIP_KEYWORDS` | Komórki do pominięcia (XWF, XFiz1, SSW) |

## Walidacja ICS

Sprawdź wygenerowany plik na: https://icalendar.org/validator.html
