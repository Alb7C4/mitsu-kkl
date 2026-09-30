# mitsu-kkl na Raspberry Pi Pico 2 W

Pico tworzy własną sieć Wi-Fi i pokazuje tę samą stronę z odczytami na żywo co `mut_web.py` na PC.
Telefon łączy się z siecią Pico i otwiera `http://192.168.4.1/`. Z autem Pico rozmawia przez linię K
(MUT-II: inicjalizacja 5 bodów na adres 0x00, potem 15625 bodów), sam zwiera pin 1 gniazda OBD do masy
i tylko odczytuje dane: zapytania spoza 00–BF i FD–FF są odrzucane w firmware.

> **Stan:** firmware jest przetestowany na PC z symulatorem sterownika (`pc_sim/run.py`), a nie
> jeszcze na prawdziwym Pico i w aucie. **Schemat, lista części i uruchomienie układu:
> [hw/README.md](hw/README.md).**

## Pliki

| plik | co robi |
|---|---|
| `main.py` | start: ustawienia, sieć Wi-Fi, serwer, połączenie z autem |
| `kline.py` | linia K: UART 15625 bodów, inicjalizacja 5 bodów przez pin TX, zapytania MUT |
| `hub.py` | definicje PID-ów w pamięci flash, pętla odczytu, zdarzenia dla przeglądarek, dioda |
| `httpd.py` | serwer WWW: strona z `web/` i API z [../web/API.md](../web/API.md) |
| `config.json` | nazwa i hasło sieci, piny, port, automatyczne łączenie |
| `deploy.py` | wgrywa wszystko na Pico (`mpremote`) |
| `benchtest.py` | test zmontowanego układu bez auta: `mpremote run pico/benchtest.py` |
| `hw/` | schemat (`schemat.svg`), lista części, uruchomienie |
| `pc_sim/` | uruchomienie firmware na PC z symulatorem, do testów bez sprzętu |

## Wgranie

1. **MicroPython na Pico 2 W:** pobierz plik `.uf2` dla płytki **RPI_PICO2_W** ze strony
   [micropython.org/download](https://micropython.org/download/RPI_PICO2_W/). Trzymając przycisk BOOTSEL,
   podłącz Pico do USB, pojawi się dysk `RP2350`; skopiuj na niego plik `.uf2`.
2. **Narzędzie do wgrywania:** `pip install mpremote`
3. **Firmware:** z głównego folderu projektu
   ```
   python pico/deploy.py
   ```
   Kopiuje firmware, stronę, `config.json`, definicje PID-ów (z listą 10 podstawowych) i opisy kodów
   usterek, potem restartuje Pico. Przy kolejnych aktualizacjach `config.json` i definicje PID-ów
   zmienione na Pico zostają; nadpisują je dopiero `--config` i `--defs`.

## Ustawienia (`config.json`)

| klucz | domyślnie | znaczenie |
|---|---|---|
| `ssid`, `password` | `mitsu-kkl`, `mitsukkl` | sieć Wi-Fi Pico; **zmień hasło**, min. 8 znaków (krótsze = sieć otwarta) |
| `country` | `PL` | kraj dla Wi-Fi |
| `uart`, `tx_gpio`, `rx_gpio` | `0`, `0`, `1` | UART i piny do transceivera linii K |
| `invert_tx`, `invert_rx` | `true`, `false` | odwrócenie sygnałów; `true` dla TX pasuje do [schematu](hw/README.md) (tranzystor odwraca), dla L9637D oba `false` |
| `pin1_gpio`, `pin1_active_high` | `2`, `true` | pin sterujący tranzystorem, który zwiera pin 1 OBD do masy (`null` = brak) |
| `http_port` | `80` | port strony |
| `auto_connect` | `true` | łączy się z autem od razu po włączeniu |

Zmiana: `mpremote fs cp config.json :config.json`, albo edycja pliku w Thonny, potem restart Pico.

## Sprzęt

Schemat, lista części, połączenia z pinami Pico i uruchomienie krok po kroku: **[hw/README.md](hw/README.md)**.
W skrócie: GP0 → tranzystor ściągający linię K (OBD 7), GP1 ← komparator LM393 z linii K (maks. 3,3 V),
GP2 → tranzystor zwierający pin 1 do masy, VSYS ← przetwornica 12 → 5 V z pinu 16.

![Schemat](hw/schemat.svg)

## Użycie

1. Włącz zapłon; Pico wstaje w kilka sekund, dioda na płytce pokazuje stan:
   zgaszona = rozłączone, wolne miganie = łączenie, świeci = połączono, szybkie miganie = sterownik nie odpowiada.
2. W telefonie połącz się z siecią `mitsu-kkl` i otwórz **http://192.168.4.1/**.
3. Strona działa tak samo jak na PC (opis w [../INSTRUKCJA.md](../INSTRUKCJA.md), rozdział „Strona WWW”).
   Nagranie zapisuje się w telefonie.

Jeśli strona się nie otwiera, a telefon ma włączone dane komórkowe, wyłącz je: niektóre telefony
wysyłają ruch przez sieć komórkową, gdy sieć Wi-Fi nie ma internetu.

## Test bez sprzętu

```
python pico/pc_sim/run.py            # http://127.0.0.1:8766/, symulowany sterownik
python pico/pc_sim/run.py --sim none # sterownik milczy: "nie odpowiada (SILENT)", ponawianie co ok. 3 s
```

Ten sam kod co na Pico; `pc_sim/machine.py` i `pc_sim/network.py` zastępują moduły MicroPythona,
a UART i pin TX sterują symulatorem linii K z `kkl/sim.py`.
