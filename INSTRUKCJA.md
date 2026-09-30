# mitsu-KKL: sonda K-line dla Mitsubishi (MUT-II) przez kabel KKL

*Pełna instrukcja. Opis projektu: [po polsku](README.pl.md) · [in English](README.md).
Gotowe pliki .exe są w zakładce Releases, mapa PID-ów w [PID_znaczenia.md](PID_znaczenia.md).*

Narzędzie do automatycznego sprawdzania, czy i jak da się nawiązać komunikację z modułami
Mitsubishi Eclipse 1998 2.0 4G63 (wersja EU) przez kabel VAG KKL na FT232. Tło techniczne
jest w [mut2-ftdi-kkl-handoff.md](mut2-ftdi-kkl-handoff.md).

## Sprzęt (stan na 2026-09-27)

- **Potrzebny jest najtańszy kabel VAG KKL** (sprzedawany jako „VAG KKL 409.1” / „VAG-COM 409.1 KKL”):
  sam układ USB-UART i transceiver linii K, nic więcej. **Nie** kupuj kabli „HEX” / „HEX-CAN” / klonów
  VCDS, kabli K+CAN ani żadnego interfejsu z własnym mikrokontrolerem i firmware: rozmawiają one
  z komputerem własnym protokołem i nie da się nimi sterować linią K bit po bicie, więc inicjalizacja
  MUT-II przy 15625 bodach jest niemożliwa. Nie działają też interfejsy ELM327.
  - Najlepszy jest chip **FTDI FT232** (sterownik D2XX). CH340, PL2303 i CP210x działają przez port COM,
    jeśli chip obsługuje 15625 bodów i break.
- Kabel użyty w testach: FT232BM/BL, **bez EEPROM** (domyślne 0403:6001, opis "USB <-> Serial"), sterownik FTDI
  2.12.36, D2XX dostępne, COM1, latency 1 ms.
- `selftest` bez auta daje `NO_ECHO`, czyli transceiver nie ma 12 V z pinu 16. To normalne,
  dopóki kabel nie jest wpięty w gniazdo OBD.
- **Pin 1 → GND** (pin 4/5): MUT-II w silniku zwykle wymaga zwarcia pinu 1 do masy (tryb
  diagnostyczny). Kable KKL do VAG nie mają pinu 1, więc trzeba dołożyć przewód z wyłącznikiem.
  Testuj z pinem 1 wolnym i zwartym, a stan zapisuj w `--note`.

## Wyniki na aucie (2026-09-27, zapłon ON, silnik wyłączony)

| adres 5-baud | prędkość | sync | ID (FE/FF) | pin 1 = GND | pin 1 wolny |
|---|---|---|---|---|---|
| **0x00 silnik** | 15625 | `55 EF 85` | E4 3A | **działa**, 192/192 zapytań 00–BF | cisza |
| **0x04 (nieznany moduł)** | 10400 | `55 73 85` | B1 01 | **działa** | cisza |
| 0x01–0x03, 0x05–0xFF | – | – | – | cisza | nie testowano |
| ISO 9141 0x33 (OBD2), KWP fast, DSM 1953 | – | – | – | cisza | cisza |

- Pin 1 na masie jest konieczny. CEL zaczyna wtedy migać kodami, co jest normalne w trybie diagnostycznym.
- Po inicjalizacji nie trzeba wysyłać `~KB2`: ECU traktuje 0x7A jako zwykłe zapytanie (zwraca 84).
- Inicjalizacja przez break i przez bitbang działa tak samo.
- 0x14 × 0,0733 V zgadza się z ładowarką podłączoną do akumulatora (13,3–14,2 V).
- Kody usterek silnika (`python kkl_probe.py dtc`): **0x40 = aktywne, 0x45 = zapamiętane**. Każdy
  bit to jeden kod w kolejności 11, 12, 13, 14, 15, 21, 22, 23… Potwierdzone przez odpięcie TPS
  (bit 3 = 14) i czujnika cieczy (bit 5 = 21) oraz zgodność z kodami błyskowymi (13, 14, 21).
- `clear --yes` (MUT 0xCA): ECU odpowiada `FF`, ale **kodów nie kasuje**, także po cyklu zapłonu.
- Szybkie połączenie z silnikiem: `python kkl_probe.py mut --addr 00 --repeat 100`.
  Z modułem 0x04: `python kkl_probe.py mut --addr 04 --baud 10400`.

## Podgląd na żywo (GUI)

```
pythonw mut_gui.py            # okno bez konsoli; --connect łączy od razu po starcie
pythonw mut_gui.py --backend sim --sim mutlive --connect   # demo bez auta
```

Interfejs programu jest po angielsku; poniżej nazwy przycisków tak, jak są w oknie.

- **Interface** (pierwszy wiersz okna): lista wykrytych kabli.
  - „FTDI via D2XX” to obecny kabel, najszybsza droga.
  - „COMx – CH340 / PL2303 / CP210x / FTDI via COM port” to dowolny chip USB-UART przez jego port.
    Warunek: chip musi obsługiwać 15625 bodów i break.
  - „Automatic” próbuje najpierw FTDI przez D2XX, potem pierwszy port COM z chipem FTDI, CH340,
    PL2303 albo CP210x. Inne urządzenia USB (Arduino, modemy…) wybiera się tylko ręcznie.
  - Porty Bluetooth są pomijane. „Refresh” skanuje ponownie po podłączeniu kabla.
  - Wybór zapisuje się w `mut_gui.json`. Zapisany kabel, którego teraz nie ma, pokazuje się jako
    „not detected”. W czasie połączenia listy nie da się zmienić, a status pokazuje, przez który
    interfejs jest połączenie.
  - Opcje `--backend auto|d2xx|serial|sim` albo samo `--port COMx` w wierszu poleceń nadpisują wybór z okna.

- **Plik definicji** (średniki, UTF-8, otwiera się też w Excelu). Nowy plik nazywa się
  `pid_definitions.csv`; istniejący `pid_definicje.csv` jest nadal używany. Plik z polskiej wersji
  przy pierwszym wczytaniu dostaje angielski nagłówek i angielskie nazwy domyślne. Twoje własne
  nazwy i komentarze zostają bez zmian. Plik trzyma listę obserwowanych PID-ów razem z nazwami
  i przelicznikami:
  ```
  pid ; name ; conversion ; unit ; on list (1/0)
  14 ; battery voltage ; x*0.0733 ; V ; 1
  40 ; active fault codes (1) ; dtc ;  ; 1
  ```
  Przelicznik to wyrażenie z `x` (surowy bajt 0–255), np. `x*31.25`, `x-40`, `(x>>4)&15`,
  `round(x*0.49, 1)`; przecinek dziesiętny też działa. Dostępne są też słowa `dtc`/`dtc2` (kody usterek)
  i `bin` (zapis dwójkowy). Plik zapisuje się przy każdej zmianie. Jeśli edytujesz go ręcznie
  (przycisk „Edit in Notepad”), zmiany wczytają się same. PID usunięty z listy dostaje `0`,
  ale jego nazwa i przelicznik zostają w pliku. Własne komentarze (`#`) są zachowywane.
- Dodawanie: przycisk „Add PID…”, klawisz Insert albo menu pod prawym przyciskiem. Otwiera okno
  z wyszukiwarką (hex lub nazwa) i listą wszystkich dozwolonych PID-ów. Można zaznaczyć kilka
  naraz (Ctrl/Shift), a dwuklik lub Enter dodaje od razu.
- Usuwanie: prawy przycisk na wierszu → „Remove from list” (działa też na kilka zaznaczonych) albo
  klawisz Delete.
- Nazwa i przelicznik: prawy przycisk → „Edit name and conversion…” albo dwuklik na wierszu.
  Okno pokazuje podgląd przeliczenia dla bieżącej wartości.
- Pole „PIDs” + **„Show selected live Data PIDs”** (albo Enter) ustawia listę (zakresy `07,14,20-2F`).
  „Named PIDs” wybiera PID-y z nazwą w pliku, „All 00-BF” wszystkie. Zablokowane PID-y (C0–FC)
  są pomijane.
- **„Fault Codes”** przełącza na widok kodów usterek: 40/41 aktywne, 45/46 zapamiętane, z rozpisanymi
  numerami kodów. Twoja lista PID-ów, pole PID i plik definicji się nie zmieniają. W tym widoku
  pierwszy przycisk nazywa się **„Back to Live Data PID”** i wraca do poprzedniej listy. Usuwanie
  wierszy jest w widoku kodów zablokowane. Dodanie PID-u albo „Named PIDs”/„All 00-BF” wraca do
  live data.
- **Profile list PID: `pid_profiles.csv`** (`name ; PIDs`, tworzony sam z kilkoma przykładami:
  Basic, Warm-up, Throttle, Idle and ignition). Wiersz „Profile:” w oknie:
  - wybór z listy pokazuje pod tabelą, co profil zawiera; **Load** wczytuje go jako bieżącą listę
    (także z widoku Fault Codes, wtedy wraca do live data),
  - **Save** nadpisuje wybrany profil bieżącą listą (z potwierdzeniem), **Save as new…** zapisuje ją
    pod nową nazwą,
  - **Edit…** zmienia nazwę i listę PID-ów profilu (przycisk „Use the current list”, zablokowane
    i błędne PID-y są pokazywane i pomijane), **Delete** usuwa profil (z potwierdzeniem).
  Profil trzyma tylko listę; nazwy i przeliczniki są nadal w pliku definicji. Plik można też
  edytować w Notatniku, zmiany wczytają się same. Ostatnio wybrany profil jest zapamiętywany.
- **Opisy kodów usterek: `dtc_definitions.csv`** (`bit ; code ; description`, tworzony sam przy
  pierwszym uruchomieniu). Bity 0–7 to pierwszy bajt (40 aktywne / 45 zapamiętane), 8–15 drugi
  (41 / 46). Kolumna „Converted” pokazuje np. „13 intake air temperature sensor”. Przycisk
  „Edit fault code definitions” otwiera plik w Notatniku, a zmiany wczytują się same. Potwierdzone
  na tym aucie: bit 2 = 13, 3 = 14, 5 = 21, 9 = 25. Pozostałe bity to typowa kolejność Mitsubishi
  i wymagają sprawdzenia (np. przez liczenie mignięć check engine).
- Wartości w HEX albo DEC, kolumny min/max i przeliczona wartość z jednostką.
- Wiersz podświetla się na zadaną liczbę sekund, gdy wartość odejdzie o ≥ N jednostek od wartości
  z poprzedniego podświetlenia. Dzięki temu łapie zarówno skoki, jak i powolny dryf.
  Każde podświetlenie trafia do `logs/<czas>_gui_changes.csv`.
- **„● Record log”** zapisuje wszystkie odczyty do `logs/<czas>_readings_<nr>.csv` (nr rośnie z każdym
  nagraniem, np. `_readings_007.csv`, więc pliki nigdy się nie nadpisują), jeden wiersz na każdy
  pełny cykl odpytania (przy 8 PID-ach ok. 20 wierszy/s). Kolumny: czas, sekundy od startu, potem dla
  każdego PID-u wartość surowa (DEC) i przeliczona (jeśli PID ma przelicznik). Format angielski:
  przecinek jako separator, kropka dziesiętna, UTF-8 z BOM. W polskim Excelu dwuklik wrzuci wszystko
  do jednej kolumny, dlatego otwieraj przez Dane → Z tekstu/CSV (separator: przecinek). Pola
  zawierające przecinek (np. „codes: 13, 14”) są w cudzysłowie. Gdy w trakcie nagrywania zmieni się lista PID-ów
  albo definicje, zapis przechodzi do `..._readings_007_part2.csv` itd., żeby kolumny zawsze pasowały do
  nagłówka. „Logs folder” otwiera katalog `logs`.
- Klik w nagłówek kolumny sortuje (drugi klik odwraca kierunek, ▲/▼). „Live sort” utrzymuje
  kolejność co 1 s. Wiersze bez danych są zawsze na końcu.
- „Remove unchanged” zostawia tylko PID-y, których wartość choć raz się zmieniła (min ≠ max).
  Wygodny sposób szukania: wczytaj „All 00-BF”, poruszaj czymś w aucie, kliknij „Remove unchanged”.
- „Remove highlighted” usuwa wiersze podświetlone w chwili kliknięcia, np. zaszumione wartości
  (napięcie z ładowarki, liczniki), żeby nie zasłaniały zmian, których szukasz.
- „Load…” / „Save as…” przełączają się na inny plik definicji; wybrany plik staje się bieżącym.
  Wczytuje też starsze listy `.txt` (jeden PID na linię).
- Ok. 200 odczytów/s. Przy utracie sesji łączy się ponownie samo. Ustawienia zapisuje w `mut_gui.json`.
- **Aktualizacje:** przy starcie program w tle pyta GitHub, czy jest nowsze wydanie. Jeśli jest, u góry
  okna pojawia się pasek z przyciskiem „Open download page”. Pobierasz zip i podmieniasz pliki;
  ustawienia, definicje i logi zostają. Bez internetu nic się nie pokazuje. „Don't check again”
  wyłącza sprawdzanie (`"check_updates": false` w `mut_gui.json`). Wersja jest w tytule okna,
  a `kkl_probe.py info` pokazuje ją razem z tą samą podpowiedzią (`--version` wypisuje samą wersję).
- **Okno powitalne:** przy każdym starcie pokazuje krótkie wprowadzenie dla osób nietechnicznych
  (`welcome/pl.md` albo `welcome/en.md`; szczegóły techniczne zostają w README), po polsku,
  gdy Windows jest ustawiony na polski, w przeciwnym razie po angielsku. Język przełącza się w oknie.
  Zaznaczenie „Nie pokazuj więcej” ukrywa okno do następnej wersji programu (zapis
  `"welcome_hidden_version"` w `mut_gui.json`). Przycisk „About…” otwiera je w każdej chwili.

## Strona WWW (`mut_web.py`)

Te same odczyty na żywo co w GUI, ale w przeglądarce, także na telefonie.

```
python mut_web.py                                        # kabel wybrany automatycznie, otwiera przeglądarkę
python mut_web.py --lan                                  # dostępna też z innych urządzeń w sieci (adres na starcie)
python mut_web.py --backend sim --sim mutlive --connect  # demo bez auta
```

Opcje: `--backend auto|d2xx|serial|sim`, `--port COMx` (kabel przez port COM), `--connect` (łączy od razu),
`--http-port 8080`, `--lan`, `--no-browser`, `--defs plik.csv` (inny plik definicji, np. do testów).

- **Kabel** i **Połącz/Rozłącz** w nagłówku. Status mówi, co się dzieje, np. „Sterownik nie odpowiada…
  Pin 1 na masie? Zapłon włączony?”.
- **PID-y**: pole z zakresami (`07,14,20-2F`) i Enter albo „Pokaż”; „PID-y z nazwą”, „Wszystkie 00–BF”.
  Lista zapisuje się jako „na liście” w pliku definicji, wspólnym z `mut_gui`.
- **Kody usterek**: widok 40/41 (aktywne) i 45/46 (zapamiętane) z opisami; „Powrót do odczytów”
  przywraca poprzednią listę.
- **Nazwa i przelicznik**: dwuklik na wierszu (na telefonie przytrzymanie). Podgląd przeliczenia dla
  bieżącej wartości, błędne wyrażenie nie da się zapisać. Zmiany widzi od razu `mut_gui` i odwrotnie.
- **HEX/DEC**, **podświetlanie** zmian o ≥ N jednostek przez zadany czas, **min/max**, liczba podświetleń,
  czas ostatniej zmiany, sortowanie po kliknięciu nagłówka, „Usuń niezmienne”, „Zeruj min/max”.
- **● Nagrywaj** zbiera odczyty w przeglądarce (ok. 10 wierszy/s) i po zatrzymaniu pobiera plik
  `<czas>_readings.csv` (przecinki, kropka dziesiętna, liczby bez jednostek; jednostki są w nagłówkach).
  Zmiana listy PID-ów kończy nagranie i zapisuje plik.
- **PL/EN** w prawym górnym rogu; domyślnie język przeglądarki.
- Kilka przeglądarek naraz widzi to samo; lista PID-ów jest wspólna.
- Z `--lan` stronę może otworzyć każdy w tej samej sieci. Z auta może tylko czytać, ale może zmieniać
  nazwy PID-ów. Zmiany wymagają zapytań JSON, więc obca strona otwarta w przeglądarce nie może nimi sterować.
- Strona (`web/`) rozmawia z serwerem tylko przez API opisane w [web/API.md](web/API.md). Tę samą stronę
  będzie mogło serwować Raspberry Pi Pico W.

## Procedura w aucie

```
python kkl_probe.py selftest                                     # ma być OK (echo 55 AA)
python kkl_probe.py --note "pin1 open, ign ON" scan              # ~2 min
python kkl_probe.py --note "pin1 GND, ign ON" scan --full        # ~5 min
python kkl_probe.py report                                       # zestawienie wszystkich prób
```

Zapłon ON, silnik wyłączony. `scan --wait-echo 600` czeka, aż kabel zostanie wpięty, i
startuje sam.

## Komendy

| komenda | co robi |
|---|---|
| `info` | chip, sterownik, EEPROM (nic nie nadaje) |
| `selftest` | cisza na linii, echo 55 AA przy 10400/15625, pętla przez break |
| `listen --baud 15625,10400,1953` | pasywny nasłuch |
| `mut --addr 00 [--ack] [--baud 15625] [--method bitbang] [--lline rts]` | MUT-II: 5-baud + zapytania FE FF 14 07 21 17 15 |
| `mut --addr 00 --repeat 100` | po połączeniu odczyt na żywo |
| `iso [--addr 33] [--baud 10400]` | ISO 9141-2 / KWP slow init + OBD 01 00, 03 |
| `kwpfast [--target 10 --physical] [--method byte,break]` | ISO 14230 fast init |
| `dsm [--baud 1953]` | zapytania jak we wczesnych DSM, bez inicjalizacji |
| `addrscan --start 00 --end 7F [--proto mut\|iso]` | szukanie innych modułów (ABS, SRS, AT...) po adresie 5-baud |
| `scan [--full] [--lline rts]` | macierz powyższych strategii |
| `report [--last N]` | podsumowanie `logs/attempts.jsonl` |

Opcje globalne (przed komendą): `--note`, `--gap`, `--success-gap`, `--dtr on|off`,
`--rts on|off`, `--backend auto|d2xx|serial|sim`, `--port COMx`.

Interfejs (`--backend`):
- `auto` (domyślny): najpierw FTDI przez D2XX, potem pierwszy port COM z chipem FTDI, CH340,
  PL2303 albo CP210x (w tej kolejności). Inne urządzenia USB, zwykłe RS-232 i Bluetooth są
  pomijane. Wybrany kabel jest wypisywany na początku (`interface: …`) i zapisywany w logu.
- `d2xx`: kabel FTDI przez sterownik D2XX. To jedyny tryb z inicjalizacją bitbang i znacznikami
  błędów linii (`auto` wybiera go sam, gdy jest FTDI).
- `serial` albo samo `--port COMx`: dowolny chip przez wskazany port COM. Chip musi obsługiwać
  15625 bodów i break. Samo `--serial`/`--dev` oznacza `d2xx`.
- `info` pokazuje listę wszystkich wykrytych interfejsów.

## Wyniki

`NO_ECHO` < `SILENT` < `NOISE` < `SYNC` < `HANDSHAKE` < `DATA`

- `NO_ECHO`: kabel nie widzi własnych bajtów (brak zasilania z OBD).
- `SILENT`: echo jest, ale nikt nie odpowiada.
- `NOISE`: coś przyszło (bajty lub błędy ramki), ale bez 0x55. Zwykle oznacza złą prędkość.
- `SYNC` / `HANDSHAKE`: jest 0x55 / 0x55 + dwa key bytes.
- `DATA`: moduł odpowiada na zapytania.
- `lb=N`: liczba bajtów pętli zwrotnej podczas 5-baud (dowód, że linia K faktycznie spada).
  W trybie bitbang jest to odczyt poziomu K w połowie każdego bitu.
- `ALIVE-BEFORE`: sesja z poprzedniej próby jeszcze żyła, więc wynik tej próby jest niepewny.

Każde uruchomienie zapisuje pełną oś czasu bajtów w `logs/<czas>_<komenda>.jsonl`, a każda
próba trafia jako jedna linia do `logs/attempts.jsonl`.

## Bezpieczeństwo

Nadawać można wyłącznie zapytania odczytowe: MUT 0x00–0xBF oraz 0xFD–0xFF, a w OBD/KWP
tryby 01/02/03/07/09 i 81/82/3E/1A. Zakres 0xC0–0xFC jest zablokowany w kodzie (0xCA kasuje
błędy, 0xF1–0xFC uruchamiają elementy wykonawcze i odcinają wtryski), podobnie jak tryb 04.
Blokada działa, zanim cokolwiek trafi na linię.

## Źródła

Szczegóły protokołu i nazwy PID-ów zebrane z poniższych projektów i stron, a potem sprawdzone na aucie:

- [niallm90/libftdimut](https://github.com/niallm90/libftdimut) i [libftdimut-example](https://github.com/niallm90/libftdimut-example): MUT-II przez układ FTDI (inicjalizacja 5 bodów breakiem, adres 0x00, 15625 bodów, format zapytań)
- [EvoEcu wiki – MUT Protocol](https://evoecu.logic.net/wiki/MUT_Protocol): sekwencja inicjalizacji, bajty `55 EF 85`, zapytania o ID ECU
- [EvoEcu wiki – MUT Requests](https://evoecu.logic.net/wiki/MUT_Requests): lista zapytań i przeliczników, punkt odniesienia dla mapy PID-ów
- [MMCd datalogger](https://mmcdlogger.sourceforge.net/): protokół wczesnych DSM przy 1953 bodach (próba `dsm`)
- [FTDI D2XX Programmer's Guide](https://ftdichip.com/document/programming-guides/): break, bitbang, latency i status linii w FT232
- ISO 9141-2 i ISO 14230 (KWP2000): inicjalizacja wolna i szybka, key bytes, ramki OBD

## Symulator

`--backend sim --sim mut|iso|kwp|dsm|none|dead` pozwala testować logikę bez auta. Logi
symulatora trafiają do `logs/sim/`.
