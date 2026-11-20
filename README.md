# WAT WEL plan zajęć → kalendarz

Codziennie (06:00 UTC) GitHub Actions pobiera plan grupy **WEL24EL2S0**
(zimowy i letni), dokleja szczegóły WF i publikuje kalendarz. Osobno buduje
kalendarze innych grup z `[inne_grupy]` (obecnie **WEL24EI1S0**), każdy z własnym
linkiem. Zima/lato przełącza się samo — linki do subskrypcji się nie zmieniają.

## Linki do subskrypcji

**Mój plan — WEL24EL2S0**

| Gdzie | Link |
|---|---|
| Google Calendar (*Inne kalendarze → Z adresu URL*) | `https://raw.githubusercontent.com/F3zzyy/wel-to-calendar/main/WEL24EL2S0.ics` |
| iPhone (*Ustawienia → Kalendarz → Konta → Dodaj subskrypcję*) | `webcal://f3zzyy.github.io/wel-to-calendar/WEL24EL2S0.ics` |

**WEL24EI1S0** (osobny kalendarz)

| Gdzie | Link |
|---|---|
| Google Calendar | `https://raw.githubusercontent.com/F3zzyy/wel-to-calendar/main/WEL24EI1S0.ics` |
| iPhone | `webcal://f3zzyy.github.io/wel-to-calendar/WEL24EI1S0.ics` |

Każda kolejna grupa z `[inne_grupy]` ma link tego samego kształtu, z jej nazwą.

`WEL24EL2S0_zima.ics` to identyczna kopia pod starą nazwą — dotychczasowe
subskrypcje działają dalej, nie trzeba ich ruszać.

## Co robię, gdy…

**…dostanę plan WF**
Wchodzę w `WF/<rok>_<semestr>/` (np. `WF/2026-2027_zima/`) →
*Add file → Upload files* → wrzucam `.xlsx` → *Commit changes*. Koniec.
Szczegóły: [WF/README.md](WF/README.md).

**…zacznie się nowy semestr**
Nic. Gdy WAT opublikuje plan, trafi do kalendarza sam, a w `WF/` pojawi się
folder na nowy plan WF.

**…chcę kalendarz innej grupy (albo przestać)**
`USTAWIENIA.toml` → kopiuję blok `[inne_grupy.…]` (3 linie), podmieniam nazwę
grupy w nagłówku i w obu linkach → *Commit changes*. Po ~2 minutach jest
`NAZWA.ics` z własnym linkiem (jak w tabeli wyżej). Mój kalendarz się nie
zmienia. Koniec: usuwam blok, a plik `NAZWA.ics` kasuję ręcznie.
Gdy strona planu innej grupy nie działa, w podsumowaniu jest ⚠️, jej kalendarz
zostaje w ostatniej wersji, a mój aktualizuje się normalnie.

**…WAT zmieni adres planu**
Otwieram `USTAWIENIA.toml` (na GitHubie: ikonka ołówka), wklejam nowy link
w cudzysłowie, *Commit changes*. Do tego czasu kalendarz pokazuje ostatnią
dobrą wersję planu — nic nie znika.

**…chcę sprawdzić, czy wszystko działa**
*Actions* → ostatni przebieg → podsumowanie na dole: ile zajęć, czy WF się
dopasował i ewentualne ostrzeżenia (⚠️) z instrukcją, co poprawić.
Jeśli przebieg jest czerwony, GitHub wyśle maila, a kalendarz zostaje
w ostatniej dobrej wersji.

**…chcę wymusić odświeżenie**
*Actions → Aktualizuj plan zajęć → Run workflow*.

## Pliki

```
USTAWIENIA.toml          ← jedyny plik do edycji ręcznej (grupa, linki do planów)
WF/<rok>_<semestr>/      ← tu wrzucasz plany WF (.xlsx)
aktualizuj.py            ← jedyny skrypt do uruchamiania
extract_schedule_data.py ← pobieranie i parsowanie strony WAT
generate_ics_from_json.py← budowa eventów i pliku ICS
dane/zima.json, lato.json← ostatnie dobre plany (generowane, zapas na awarię WAT)
dane/inne_grupy/<grupa>/ ← to samo dla innych grup
WEL24EL2S0.ics           ← kalendarz (generowany)
```

## Uruchomienie lokalne

```bash
python3 -m venv ~/.venvs/wel && source ~/.venvs/wel/bin/activate
pip install -r requirements.txt
python aktualizuj.py             # pobiera z WAT
python aktualizuj.py --offline   # bez sieci, z dane/
```

## Jak to działa (dla przyszłych zmian)

- Oba plany są pobierane przy każdym przebiegu. Do kalendarza trafiają tylko
  plany z **najnowszego roku akademickiego** (rok czytany z nagłówka strony),
  więc stary plan wiszący na stronie WAT nie wraca.
- Plan, którego nie da się pobrać albo który wygląda źle (brak tabeli, zły
  semestr pod linkiem), jest zastępowany ostatnią dobrą wersją z `dane/`.
  Plan letni przed publikacją (404) jest po prostu pomijany.
- 0 zajęć = błąd i brak zapisu, więc pusty kalendarz nigdy nie zostanie opublikowany.
- Inne grupy: osobny `<grupa>.ics`, najnowszy rok akademicki z ich planów,
  bez szczegółów WF z mojego pliku. UID dostaje sufiks `-<grupa>`, żeby wspólny
  wykład nie miał tego samego UID w dwóch kalendarzach. Niedostępny plan innej
  grupy = tylko ostrzeżenie, nigdy błąd.
- WF: z folderu semestru brany jest najnowszy `.xlsx` (wg daty commita).
  Rok w datach pliku jest ignorowany i liczony z roku akademickiego. Szczegóły
  trafiają do pierwszego „WF” danego dnia (późniejszy to wykład).
- UID eventów zależą od daty, slotu i treści komórki planu — zmiana WF nie
  tworzy duplikatów w kalendarzach.
- Godziny slotów: `TIME_MAP` w `generate_ics_from_json.py`
  ([siatka godzinowa WEL](https://www.wel.wat.edu.pl/przydatne-informacje/siatka-godzinowa-zajec/)).
  Commit powstaje tylko, gdy zmieni się kalendarz.
