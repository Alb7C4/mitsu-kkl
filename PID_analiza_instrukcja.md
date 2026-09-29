# Instrukcja dla Claude: ustalanie znaczenia PID-ów (kontynuacja w nowej sesji)

Cel: rozpoznać, co oznaczają zapytania MUT-II 00–BF sterownika silnika Mitsubishi Eclipse 1998
2.0 4G63 (EU), **ECU ID E4 3A** (adres 5-baud 0x00, 15625 bodów, pin 1 OBD na masie), i zapisać
wyniki. Użytkownik pisze po polsku: odpowiadaj po polsku, zwięźle, liczby podawaj z logów.

## 1. Na początek sesji

1. Przeczytaj stan wiedzy: `PID_znaczenia.md` (znaczenia z dowodami), `pid_definicje.csv`
   (nazwy i przeliczniki używane przez GUI), `dtc_definitions.csv` (kody usterek).
2. Znajdź nowe logi: `ls -t logs | head -20`. Katalog `logs/` nie jest w gicie, istnieje tylko
   na dysku użytkownika.
3. Każdy nowy plik najpierw przez `python tools/analyze_readings.py summary <plik>`. Sprawdź:
   które PID-y są w nagłówku (lista mogła być skrócona), okres próbkowania, długość i co się ruszało.
4. **Nazwom plików i opisom użytkownika ufaj tylko luźno.** Plik `…_MAF-IAT_grzany_suszarką.csv`
   okazał się przejazdem przepustnicą i nie miał w ogóle kolumny 3A. Weryfikuj po zawartości.
5. Zapytaj, co dokładnie było robione i **o której godzinie** (pierwsza kolumna to zegar ścienny,
   `t [s]` to sekundy od startu nagrania). Bez godzin trudno powiązać zdarzenie z czynnością.

## 2. Źródła danych

| plik | format | uwagi |
|---|---|---|
| `logs/<czas>_readings_<nr>.csv` (+ `_part2`…) | GUI „● Record log”: `,` i kropka, UTF-8 z BOM, pola z przecinkiem w cudzysłowie | wiersz = pełny cykl odpytania; kolumna surowa `PID nazwa` (DEC), przeliczone `… [jedn.]` / `… (converted)`; `_part2` = zmieniona lista w trakcie |
| `logs/<czas>_odczyty*.csv` | starsza polska wersja: `;` i przecinek dziesiętny, `(przeliczona)` | ta sama zawartość |
| `logs/<czas>_gui_changes*.csv` | `time,pid,old,new,delta` | tylko skoki ≥ próg z `mut_gui.json` (było 7). Dobre do znalezienia zdarzeń, **małe zmiany są niewidoczne** |
| `logs/<czas>_mutdump.jsonl` | `kkl_probe.py mutdump` | pełny zrzut 00–BF raz; w zdarzeniu `attempt_end` → `result.table` |
| `logs/<czas>_mut.jsonl`, `attempts.jsonl` | `kkl_probe.py` | pojedyncze odczyty i próby połączenia |

Pełna lista PID-ów (ok. 170) to cykl ok. 0,8 s. Przy 8 PID-ach jest ok. 20 wierszy/s.

## 3. Narzędzie `tools/analyze_readings.py`

```
python tools/analyze_readings.py summary  <plik>            # co się zmieniało + podpowiedzi (= kopia, ~ prawie kopia, bity, bufor)
python tools/analyze_readings.py timeline <plik> 21,10,24   # punkty zmian t:wartość
python tools/analyze_readings.py window   <plik> 26 34      # tabela PID-ów zmieniających się między 26 a 34 s
python tools/analyze_readings.py bits     <plik> A8,71      # zmiany pojedynczych bitów bajtów flag
python tools/analyze_readings.py corr     <plik> 17         # PID-y skorelowane z PID-em 17
python tools/analyze_readings.py changes  <plik_gui_changes>
```

Do stanów statycznych (np. odpięty czujnik, włączone światła) lepszy jest zrzut przed i po:
`python kkl_probe.py --note "…" mutdump --addr 00` (ok. 7 s), a potem porównanie `result.table` obu plików.

## 4. Metoda

1. **Znajdź zdarzenia.** Szukaj ruchu TPS (17), startu silnika (21 > 0), zmian kodów (40/41/45/46)
   i flag. Potem `window` wokół zdarzenia: co zmienia się **jednocześnie**.
2. **Określ typ wartości:**
   - **analogowa**: płynna, dużo wartości. Surowy ADC termistora NTC **maleje**, gdy temperatura rośnie
     (07: 135 przy 18 °C, 69 przy 49 °C). Przerwa w obwodzie daje ok. 240–242.
   - **kopia**: identyczna seria jak inny PID (12=10, 1F≈1C, 2B=29, 3D=3C, 3E=13, 8C=15, 8A≈17).
   - **flagi**: zmiany o potęgi dwójki, patrz `bits`. Jeden bit = jeden warunek, często z progiem
     (zamknięta przepustnica przełącza się przy TPS ok. 36–40).
   - **zatrzask wejść impulsowych** (A8): bity migają losowo na pracującym silniku.
   - **bufor krążący**: same wartości 0/36/50/105 (83, 94–99, A1, A2, B4–BF). Ignoruj.
   - **szum pełnozakresowy** (2A, 2C): prawdopodobnie młodszy bajt wartości 16-bitowej.
3. **Sprawdź z fizyką:** kierunek i wielkość zmiany, znane skale (obroty ×31,25 w 21 i ×7,8125 w 20/24,
   akumulator ×0,0733, baro ×0,49, sonda ×0,0195 V, kąt x−20, temperatury x−40, AFR 14,7·128/x,
   TPS ×100/255) i wartości awaryjne ECU (czujnik cieczy uszkodzony → 80 °C, IAT → 25 °C).
4. **Porównaj z EvoEcu** ([MUT Requests](https://evoecu.logic.net/wiki/MUT_Requests)). W zakresie
   00–7F adresy się zgadzają, ale wzory bywają inne. Zakres 80–BF i układ kodów usterek są inne,
   tam nie zakładaj niczego.
5. **Oceń pewność:**
   - **potwierdzony**: zareagował na konkretną czynność tak, jak przewidywałeś,
   - **prawdopodobny** („?”): nazwa z EvoEcu i wiarygodne wartości, bez testu,
   - **nieznany**: zmienia się, ale brak hipotezy.
   Przy każdym wniosku zapisz dowód: plik, czas, wartości.
6. **Zaproponuj kolejny test** dla niejasnych PID-ów: jedna czynność naraz, krótka lista PID-ów,
   godzina każdej czynności.

## 5. Pułapki (poznane na tym aucie)

- Nagłówki kolumn zawierają nazwy i nawiasy, np. `07 coolant temp (raw)`. Kolumnę surową rozpoznaje
  się po dwóch cyfrach hex na początku; pomija się tylko `[…]`, `(converted)` i `(przeliczona)`.
  Wcześniej przez zbyt ostre filtrowanie zgubiłem 07 i 3A.
- Przy pełnej liście PID-y są czytane w różnych momentach cyklu 0,8 s. Krótkie zdarzenie może złapać
  flaga (71), ale nie wartość analogowa (3A). Do zdarzeń proś o nagranie 3–8 PID-ów.
- „Remove unchanged” przed testem usuwa z listy właśnie szukany PID. Sprawdzaj nagłówek.
- **Obwód IAT jest przerwany**: 3A = 240, 11 = 25 °C (wartość awaryjna), kod 13 aktywny. Grzanie
  przepływomierza nic nie pokaże, dopóki obwód nie zostanie naprawiony.
- Pin przepływomierza, który użytkownik uznał za IAT (testowany żarówką), przełącza A8 bit 6. To
  najpewniej wyjście sygnałowe samego przepływomierza, a nie IAT.
- Ładowarka na akumulatorze: 14 pokazuje do 14,2 V przy zgaszonym silniku, a 2D i 79 dryfują.
- Wiele PID-ów rusza się tylko na pracującym silniku.
- Gdy polecenia powłoki są chwilowo niedostępne, małe pliki da się przeczytać narzędziem Read.

## 6. Bezpieczeństwo

- Tylko zapytania odczytowe 00–BF i FD–FF. Zakres C0–FC (elementy wykonawcze; 0xCA i tak nie kasuje
  kodów na tym ECU) jest zablokowany w kodzie. Nie obchodź tej blokady.
- Nie proponuj zwierania linii 5 V ani żarówek jako obciążenia. Żarówka 2 W to prawie zwarcie:
  położyła zasilanie 5 V czujników, TPS i baro spadły, zapisał się kod 25. Do testów wejść używaj
  rezystora 1–3 kΩ, nigdy na linii 5 V. Nie ściągaj linii sygnałowych na pracującym silniku.
- Moduł 0x04 (10400 bodów, `55 73 85`, ID B1 01, to nie ABS): nie zrzucaj jego tablicy, bo nie znamy
  jego komend. Wolno tylko FE/FF.

## 7. Nieustalone: plan eksperymentów (od najważniejszych)

1. **Kod z bitu 12** (41/46 bit 4, razem z 71 bit 5) zapala się ok. 20 s po zimnym starcie. Poproś
   o policzenie mignięć check engine (pin 1 na masie, silnik pracował). To potwierdzi kolejność
   drugiego bajtu w `dtc_definitions.csv`.
2. **Pętla zamknięta**: nagranie rozgrzanego silnika (10 ≥ 120, czyli ≥ 80 °C, co najmniej 10 min)
   z listą 0C–0F, 50, 13, 3C, 3D, 5C, 21, 1C. Sonda 13 powinna przełączać 0,1–0,9 V, a korekty się
   ruszać. To potwierdzi korekty paliwa i tylną sondę.
3. **Prędkość**: pchnięcie auta na luzie albo jazda. Obserwuj 2F oraz A8 (czy któryś bit to impuls prędkości).
4. **Przełączniki, każdy osobno i z godziną**: klimatyzacja (silnik pracuje), światła, ogrzewanie
   szyby, dmuchawa, wspomaganie (skręt do oporu na pracującym silniku), hamulec (AA bit 7 dawał krótkie
   impulsy nieznanego pochodzenia), sprzęgło, wentylator chłodnicy (85?). Szukaj bitów w bajtach flag
   (00, 23, 49, 9A, 9B, A0–AF, B0–B3).
5. **Spalanie stukowe**: lekkie stuknięcie w blok przy czujniku spalania stukowego na biegu jałowym.
   Obserwuj 30, 26, 6A–6E.
6. **Obroty i obciążenie**: 2000 i 3000 obr/min bez obciążenia. Obserwuj 1A, 1C, 29, 2A/2C (czy to para
   16-bitowa z 29?), 32, 33, 04, 35.
7. **IAT po naprawie obwodu**: grzanie suszarką. 3A powinien spadać, a 11 pokazywać x−40.
8. **Nieznane flagi**: 09, 9A, A4, AF, 23, 71 bit 5. Obserwuj przy starcie, gaszeniu i cyklu zapłonu.

## 8. Zapis wyników

- Najpierw pokaż wnioski, a do plików dopisuj **po zgodzie użytkownika**.
- `PID_znaczenia.md` po polsku, z dowodem (plik, czas, wartości). Popraw też wcześniejsze wnioski,
  jeśli nowe dane im przeczą, i napisz o tym wprost.
- `pid_definicje.csv` edytuj przez `kkl.piddefs`: `load_defs()` zwraca **4** wartości
  (`defs, problems, keep, legacy`), zapis przez `save_defs(path, defs, keep)`, a każdy przelicznik
  sprawdzaj `compile_conversion()`. Nazwy **po angielsku** (program jest po angielsku), niepewne
  z „?”. Wypełniaj tylko puste pola i nie zmieniaj flagi „na liście”. Najpierw zrób kopię pliku.
- `dtc_definitions.csv`: w komentarzach nagłówka jest lista potwierdzonych bitów. Aktualizuj ją razem
  z opisem.
- `build_exe.ps1` pakuje `PID_znaczenia.md` i `dtc_definitions.csv` do wydania. Pisz je tak, żeby
  nadawały się dla użytkowników.
- Commity rób tylko na prośbę użytkownika.

## 9. Logi referencyjne (do sprawdzenia metody)

| plik | co naprawdę zawiera |
|---|---|
| `20260927-220728_mutdump.jsonl` / `20260927-232332_mutdump.jsonl` | zrzut bazowy / z odpiętymi TPS i czujnikiem cieczy; różnica wskazała bajty kodów 40/45 |
| `20260928-005118_gui_changes.csv` | żarówka na pinie przepływomierza (A8 bit 6) i zwarcia 5 V (TPS → 1–2, kod 14) |
| `20260928-105708_odczyty_MAF-IAT_grzany_suszarką.csv` | przejazd przepustnicą 33 → 250 → 33; flagi zamkniętej przepustnicy, AC bit 7 |
| `20260928-110238_…_CLT_suszarką.csv` | grzanie czujnika cieczy: 07 maleje, 10/12 rosną, 16/25/76/24/58 za nimi |
| `20260928-131801_readings_odpalenie_silnika.csv` | zimny start 18 → 49 °C; nowy kod na 29,6 s |
| `20260928-182336_readings_001.csv` | grzanie przepływomierza: 3A/11 stoją; 157–161 s chwilowo znika błąd IAT (71 b1, 40), zmieniają się 9A b3 i AF b3 |
