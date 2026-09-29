# mitsu-kkl

**Diagnostyka MUT-II sterowników silnika Mitsubishi z lat 90. przez tani kabel USB „KKL” do VAG.**

*[English](README.md) · pełna instrukcja: [INSTRUKCJA.md](INSTRUKCJA.md)*

Wiele Mitsubishi z końca lat 90. rozmawia wyłącznie własnym protokołem Mitsubishi MUT-II: inicjalizacja
5 bodów na adres 0x00, potem 15625 bodów, i tylko wtedy, gdy pin 1 gniazda OBD jest zwarty do masy.
Większość uniwersalnych diagnoskopów nie dostaje żadnej odpowiedzi. Ten projekt łączy się z takim
sterownikiem z komputera przez najprostszy kabel USB–linia K. Ma też sondę, która próbuje wielu
sposobów inicjalizacji, prędkości i adresów i zapisuje każdy bajt, dla aut, o których nikt nie wie, co działa.

**Szczególnie przydatny dla roczników 1998–1999**, z których sterownikiem silnika większość diagnoskopów się nie łączy.
Powstał i był testowany na **Mitsubishi Eclipse 1998 2.0 16V 4G63 (wersja EU)**, ID sterownika silnika `E4 3A`.

## Co jest w środku

| narzędzie | co robi |
|---|---|
| **`mut_gui`** | Podgląd na żywo: dowolne ze 190+ odczytywalnych PID-ów z własnymi nazwami i przelicznikami, podświetlanie zmian, min/max, zapis do CSV, widok kodów usterek, profile list PID-ów, automatyczne ponowne łączenie. |
| **`kkl_probe`** | Sonda w wierszu poleceń: test kabla, MUT-II / ISO 9141-2 / KWP2000 (inicjalizacja wolna i szybka) / DSM 1953 bodów, skanowanie adresów, pełna macierz testów, odczyt kodów usterek. Każde uruchomienie jest zapisywane bajt po bajcie ze znacznikami czasu. |

Oba narzędzia **z założenia tylko odczytują** (zob. [Bezpieczeństwo](#bezpieczeństwo)).

## Sprzęt

- **Najtańszy kabel VAG KKL** (sprzedawany jako „VAG KKL 409.1” / „VAG-COM 409.1 KKL”): tylko układ USB-UART i transceiver linii K, nic więcej.
  **Nie** kupuj kabla „HEX” / „HEX-CAN” / klona VCDS, kabla K+CAN ani żadnego interfejsu z własnym mikrokontrolerem albo firmware:
  rozmawiają one z komputerem własnym protokołem i nie da się nimi sterować bit po bicie, więc inicjalizacja MUT-II przy 15625 bodach jest niemożliwa.
  - Najlepiej działa **FTDI FT232** (przez sterownik FTDI D2XX; tylko w tym trybie jest inicjalizacja bitbang i znaczniki błędów linii).
  - CH340, PL2303 i CP210x działają przez swój port COM, **jeśli układ obsługuje 15625 bodów i wysyła break**. Wiele starych albo podrobionych PL2303 obsługuje tylko standardowe prędkości.
  - **Interfejsy ELM327 nie działają**: nie potrafią zrobić inicjalizacji MUT-II przy 15625 bodach.
- **Pin 1 OBD → masa (pin 4 albo 5).** Kable do VAG nie mają pinu 1, więc trzeba dołożyć przewód, najlepiej z wyłącznikiem.
  Gdy pin 1 jest na masie, a zapłon włączony, kontrolka check engine zaczyna migać kodami usterek. To normalne: sterownik jest w trybie diagnostycznym.

Używane piny OBD: 7 = linia K, 16 = +12 V, 4/5 = masa, 1 = tryb diagnostyczny.

## Pobieranie i uruchomienie (Windows)

1. Pobierz `mitsu-kkl-<wersja>-windows.zip` z **[Releases](../../releases)** i rozpakuj w dowolnym miejscu.
2. Do kabla z układem FTDI zainstaluj sterownik FTDI (VCP + D2XX) ze strony [ftdichip.com](https://ftdichip.com/drivers/). Windows często instaluje go sam.
3. Podłącz kabel do auta, zewrzyj pin 1 do masy, włącz zapłon (silnik może być wyłączony).
4. Uruchom **`mut_gui.exe`**, wybierz kabel z listy *Interface* (albo zostaw *Automatic*) i kliknij *Connect*.

Pliki .exe nie są podpisane, więc przy pierwszym uruchomieniu Windows SmartScreen może ostrzec („Więcej informacji” → „Uruchom mimo to”).
Ustawienia, definicje PID-ów i logi są zapisywane obok pliku .exe.

Nie masz auta pod ręką? `mut_gui.exe --backend sim --sim mutlive --connect` uruchamia symulowany sterownik.

**Aktualizacje:** przy starcie `mut_gui` pyta w tle GitHub, czy jest nowsze wydanie, i jeśli jest, pokazuje
pasek z odnośnikiem do strony pobierania (pobierasz zip i podmieniasz pliki; ustawienia, definicje i logi
zostają). Bez internetu nic się nie pokazuje. „Don't check again” wyłącza sprawdzanie
(`"check_updates": false` w `mut_gui.json`). `kkl_probe info` wypisuje wersję i tę samą podpowiedź.

**Okno powitalne:** `mut_gui` przy każdym starcie pokazuje krótkie wprowadzenie prostym językiem
(`welcome/pl.md`, `welcome/en.md`), po polsku, gdy Windows jest ustawiony na polski, w przeciwnym razie
po angielsku (język przełącza się w oknie). „Nie pokazuj więcej” ukrywa je
do następnej wersji; przycisk *About…* otwiera je w każdej chwili.

## Uruchomienie ze źródeł

Testowane z Pythonem 3.14 na Windows 10.

```
pip install pyserial
pythonw mut_gui.py
python kkl_probe.py selftest
```

`build_exe.ps1` buduje oba pliki .exe i zip z wydaniem przy pomocy PyInstallera.

## kkl_probe w skrócie

```
python kkl_probe.py info                     # układ kabla, sterownik, wszystkie wykryte interfejsy (nic nie wysyła)
python kkl_probe.py selftest                 # czy kabel ma zasilanie z gniazda OBD i słyszy własne echo?
python kkl_probe.py scan [--full]            # próba wszystkich inicjalizacji / prędkości / adresów, ok. 2-5 min
python kkl_probe.py mut --addr 00 --repeat 100   # połączenie ze sterownikiem silnika i odczyt na żywo
python kkl_probe.py dtc                      # odczyt bajtów kodów usterek
python kkl_probe.py report                   # podsumowanie wszystkich dotychczasowych prób
```

Pozostałe komendy: `listen`, `mutdump`, `iso`, `kwpfast`, `dsm`, `addrscan`, `clear`. Każda ma `--help`.
Wyniki mają ranking `NO_ECHO` < `SILENT` < `NOISE` < `SYNC` < `HANDSHAKE` < `DATA`; logi trafiają do `logs/`.

## Co ustalono na testowym aucie

| adres 5-baud | prędkość | bajty sync | ID (FE/FF) | pin 1 na masie | pin 1 wolny |
|---|---|---|---|---|---|
| **0x00 silnik** | 15625 | `55 EF 85` | `E4 3A` | odpowiada na wszystkie 192 zapytania odczytu 00–BF | cisza |
| **0x04 nieznany moduł** | 10400 | `55 73 85` | `B1 01` | odpowiada | cisza |
| 0x01–0x03, 0x05–0xFF | – | – | – | cisza | – |
| ISO 9141-2 (0x33), KWP2000 szybka inicjalizacja, DSM 1953 | – | – | – | cisza | cisza |

- Po bajtach sync nie trzeba odsyłać `~KB2`; każde zapytanie to 1 bajt, odpowiedź to echo + 1 bajt.
- Kody usterek: PID `40/41` = aktywne, `45/46` = zapamiętane, jeden bit na kod Mitsubishi (potwierdzone: bit 2 = 13, bit 3 = 14, bit 5 = 21, bit 9 = 25).
- Kasowanie kodów komendą MUT `0xCA` na tym sterowniku **nie działa**; działa odłączenie akumulatora.
- Dotychczasowa mapa PID-ów (temperatura cieczy i powietrza, kąt wyprzedzenia, docelowe obroty biegu jałowego, czas wtrysku, korekty paliwa, flagi przepustnicy…) jest w [PID_znaczenia.md](PID_znaczenia.md) i trafia do pliku definicji PID-ów jako nazwy i przeliczniki.
- Adresy 00–7F zgadzają się z [listą zapytań MUT z EvoEcu](https://evoecu.logic.net/wiki/MUT_Requests) (nie są przesunięte); układ kodów usterek i zakres 80–BF są inne.

Inne modele Mitsubishi z tych lat mogą używać tej samej inicjalizacji; wyniki i znaczenia PID-ów będą się różnić między sterownikami.

## Bezpieczeństwo

Wysyłać można wyłącznie zapytania odczytowe: MUT `0x00–0xBF` i `0xFD–0xFF`, usługi OBD/KWP 01, 02, 03, 07, 09
oraz sterowanie sesją. MUT `0xC0–0xFC` jest zablokowane w kodzie, zanim cokolwiek trafi na linię K: w sterownikach
MUT-II `0xCA` kasuje kody usterek, a `0xF1–0xFC` uruchamiają elementy wykonawcze albo odcinają wtryski. Jedynym
wyjątkiem jest `kkl_probe.py clear --yes`, które wysyła `0xCA` do sterownika silnika przy wyłączonym silniku.

Używasz na własne ryzyko. Projekt nie jest związany z Mitsubishi Motors.

## Więcej dokumentacji

- [README.md](README.md): ten opis po angielsku
- [INSTRUKCJA.md](INSTRUKCJA.md): pełna instrukcja po polsku (wszystkie funkcje GUI, wszystkie komendy, procedura testu)
- [PID_znaczenia.md](PID_znaczenia.md): znaczenia PID-ów ustalone na testowym aucie
- [mut2-ftdi-kkl-handoff.md](mut2-ftdi-kkl-handoff.md): notatki techniczne o MUT-II i kablu FTDI (po angielsku)

## Źródła

Szczegóły protokołu i nazwy PID-ów zebrane z poniższych projektów i stron, a potem sprawdzone na aucie:

- [niallm90/libftdimut](https://github.com/niallm90/libftdimut) i [libftdimut-example](https://github.com/niallm90/libftdimut-example): MUT-II przez układ FTDI (inicjalizacja 5 bodów breakiem na adres 0x00, 15625 bodów, format zapytań)
- [EvoEcu wiki – MUT Protocol](https://evoecu.logic.net/wiki/MUT_Protocol): sekwencja inicjalizacji, bajty `55 EF 85`, zapytania o ID sterownika
- [EvoEcu wiki – MUT Requests](https://evoecu.logic.net/wiki/MUT_Requests): lista zapytań i przeliczników, punkt odniesienia dla mapy PID-ów
- [MMCd datalogger](https://mmcdlogger.sourceforge.net/): protokół wczesnych DSM przy 1953 bodach (próba `dsm`)
- [FTDI D2XX Programmer's Guide](https://ftdichip.com/document/programming-guides/): break, bitbang, latency i status linii w układach FT232
- ISO 9141-2 i ISO 14230 (KWP2000): inicjalizacja wolna i szybka, key bytes, ramki OBD

## Licencja

[MIT](LICENSE)
