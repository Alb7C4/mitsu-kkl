# Znaczenia PID-ów ECU silnika (Eclipse 1998 2.0 4G63, ECU ID E4 3A)

Stan: 2026-09-28. Opracowane z testów na aucie: odpinania czujników, przejazdu przepustnicą 13→98%,
zimnego startu (18 → 49 °C), grzania czujnika cieczy i przepływomierza suszarką, zwarć 5 V.
Dla tego ECU nie ma publicznej dokumentacji tablicy MUT. Adresy porównane z listą EvoEcu:
w zakresie 00–7F **nie są przesunięte**, różnice opisuje sekcja „Różnice względem EvoEcu”.

Te same nazwy (po angielsku) i przeliczniki są w `pid_definicje.csv`. Niepewne mają „?”.

## Potwierdzone na aucie

| PID | znaczenie | przelicznik | na czym to opieram |
|---|---|---|---|
| 04 | kąt wyprzedzenia zapłonu | x−20 ° | 5° na postoju, 2–17° na wolnych obrotach |
| 05 | kąt wyprzedzenia wprost | ° | = 04 − 20 |
| 06 | kąt wyprzedzenia (skala jak 04) | x−20 ° | ≈ 04 |
| 07 | temperatura cieczy, surowy ADC | – | maleje przy grzaniu (135 przy 18 °C, 69 przy 49 °C); F2 = czujnik odpięty |
| 10 (12 = kopia) | temperatura cieczy | x−40 °C | 18 → 49 °C przy nagrzewaniu; 81 °C = wartość awaryjna po odpięciu czujnika |
| 11 | temperatura powietrza używana przez ECU | x−40 °C | stale 25 °C, wartość awaryjna, bo obwód IAT jest przerwany |
| 13 (3E = kopia) | przednia sonda lambda | x·0,0195 V | 0,1 → 0,45 V w miarę nagrzewania |
| 14 | napięcie akumulatora | x·0,0733 V | 12,3 V postój, 10,0 V rozruch, 14,0–14,4 V ładowanie |
| 15 (8C = kopia) | ciśnienie barometryczne | x·0,49 kPa | 99 kPa; 0 przy odpiętym przepływomierzu i zwarciu 5 V (czujnik jest w przepływomierzu) |
| 16, 25 | sterowanie biegiem jałowym (kroki / wartość) | – | spadają przy nagrzewaniu, zmieniają się przy rozruchu |
| 76 | zapotrzebowanie sterowania biegiem jałowym | – | jak 16 |
| 17 | TPS | x·100/255 % | zamknięta 33 (12,9%), pełne otwarcie 250 (98%) |
| 19 | bity kontroli rozruchu | bin | 0 → 128 przy kręceniu rozrusznikiem |
| 1A | przepływ powietrza | x·6,25 Hz | 0 na postoju, rośnie po odpaleniu i przy dodaniu gazu |
| 1C (1F = poprzednie) | obciążenie silnika | – | idzie za obrotami i gazem |
| 20 | obroty (skala biegu jałowego) | x·7,8125 obr/min | = 21, tylko dokładniej |
| 21 | obroty | x·31,25 obr/min | rozruch ok. 150, wolne obroty ok. 1000 |
| 24 | docelowe obroty biegu jałowego | x·7,8125 obr/min | 1219 → 960 przy nagrzewaniu; 20 za nimi nadąża |
| 29 (2B = kopia) | czas wtrysku (zgrubnie) | – | 158 przy rozruchu, potem 23 → 13 przy nagrzewaniu |
| 2D | korekta od napięcia akumulatora | – | 111 postój, 182 rozruch, 84–88 z ładowaniem |
| 32 | docelowy skład mieszanki | 14,7·128/x AFR | 11,8 przy rozruchu, 14,7 na wolnych obrotach |
| 33 | kąt wyprzedzenia (skorygowany) | x−20 ° | 5–14° na wolnych obrotach |
| 35 | awaryjna dawka paliwa wg TPS | – | krzywa od TPS: 89 → szczyt 153 w połowie → 145 przy pełnym otwarciu |
| 3A | temperatura powietrza IAT, surowa | – | stale 240 = przerwany obwód (grzanie przepływomierza nic nie zmienia) |
| 54 | wzbogacenie przy otwieraniu przepustnicy | – | 0 → 8 przy dodaniu gazu |
| 56 / 57 | zmiana obciążenia przy przyspieszaniu / zwalnianiu | – | 0–4 przy dodaniu gazu |
| 58 | wzbogacenie po rozruchu | – | 255 po starcie, potem opada do 132 |
| 73 | zmiana położenia przepustnicy | – | skok przy ruchu przepustnicy |
| 79 | opóźnienie wtryskiwaczy (korekta napięciowa) | – | 36 postój, 21–24 z ładowaniem |
| 8A | surowy ADC czujnika TPS | – | = 17 ±1–3 |

## Flagi (bajty bitowe, przelicznik `bin`)

| PID | bit | znaczenie |
|---|---|---|
| 00 | 7 | przepustnica zamknięta |
| AA | 6 | przepustnica zamknięta |
| 9B | 0 | przepustnica zamknięta |
| A0, A3 | 1 | przepustnica zamknięta |
| AE, B3 | 0 | przepustnica zamknięta |
| AC | 7 | przepustnica otwarta powyżej ok. 29% (TPS ok. 75) |
| 71 | 1 / 6 / 5 | błąd czujnika IAT / TPS / zapala się ok. 20 s po starcie razem z nowym kodem (41 bit 4) |
| A8 | 1, 4, 5, 6, 7 | wejścia impulsowe (migają na pracującym silniku); **bit 6 = sygnał przepływomierza** (przełącza go żarówka na pinie przepływomierza i powietrze z suszarki) |
| 23 | 4 | ? bieg jałowy (gaśnie, gdy przepustnica otwarta) |

Wszystkie flagi „przepustnica zamknięta” przełączają się przy TPS ok. 36–40 (ok. 15%).

## Kody usterek

- **40 / 41 = aktywne, 45 / 46 = zapamiętane.** Jeden bit to jeden kod, w kolejności 11, 12, 13, 14, 15, 21, 22, 23, potem 24, 25…
- Potwierdzone: bit 2 = **13** (IAT), bit 3 = **14** (TPS), bit 5 = **21** (czujnik cieczy), w drugim bajcie bit 1 = **25** (baro, po zwarciach 5 V).
- W drugim bajcie **bit 4** to nowy kod, który zapala się ok. 20 s po odpaleniu. Numer jest nieznany; w zgadywanej kolejności wychodzi 36. Do sprawdzenia z mignięć.
- Kasowanie przez MUT 0xCA na tym ECU **nie działa**: ECU odpowiada FF, ale kody zostają. Kasowanie działa przez odłączenie akumulatora, ale aktywny kod wraca.

## Prawdopodobne (ten sam adres co w EvoEcu, wartości pasują, nie udowodnione)

| PID | znaczenie | przelicznik |
|---|---|---|
| 0C, 0D, 0E | korekty paliwa długoterminowe (niska / średnia / wysoka) ? | (x−128)/5 % |
| 0F | korekta od sondy (krótkoterminowa) ? | (x−128)/5 % |
| 50 | bieżąca korekta długoterminowa ? | (x−128)/5 % |
| 1D | ? prawie równe obciążeniu 1C (w EvoEcu wzbogacenie przy przyspieszaniu, tu nie pasuje) | – |
| 26 | suma spalania stukowego ? | – |
| 27 | poziom oktanowy ? (255 = 100%) | x·100/255 % |
| 2F | prędkość pojazdu ? (nie sprawdzone w ruchu) | x·2 km/h |
| 30 | napięcie z czujnika spalania stukowego ? | x·0,0195 V |
| 3C (3D = kopia), 5C | tylna sonda lambda ? (po odpaleniu żywy sygnał ok. 0,65–0,9 V) | x·0,0195 V |
| 6A, 6B, 6D, 6E | przetwarzanie sygnału spalania stukowego ? | – |
| 85 | wypełnienie sterowania wentylatorem ? | – |

Korekty paliwa w 3-minutowym logu stały na 0%, bo przez ten czas silnik nie zdążył wejść w zamkniętą pętlę.

## Zmieniają się, znaczenie nieznane

- **09**: po odpaleniu 131 → 181.
- **2A / 2C**: skaczą po całym zakresie 0–252, raczej młodszy bajt jakiejś 16-bitowej wartości.
- **9A**: bit 7 zapala się po odpaleniu; bit 3 gaśnie na kilka sekund, kiedy ECU chwilowo uznaje IAT za sprawny.
- **AF**: bit 3 zapala się przy tym samym zdarzeniu z IAT.
- **A4**: bit 5 zapala się po odpaleniu (flaga „silnik pracuje”?).

## Różnice względem EvoEcu

- **07**: tutaj surowy ADC (maleje z temperaturą), a w EvoEcu temperatura w °C.
- **12**: kopia 10 (temperatura cieczy), a w EvoEcu temperatura EGR.
- **20**: skala x·7,8125, a w EvoEcu x·31,25.
- **Czas wtrysku**: tutaj 29/2B, w EvoEcu 2A.
- **1D**: tutaj ≈ obciążenie, w EvoEcu wzbogacenie przy przyspieszaniu.
- **Kody usterek**: tutaj 40/41 aktywne i 45/46 zapamiętane. W EvoEcu 40–45 to zapamiętane, a 47/48 aktywne; tutaj 47/48 są puste. Liczniki usterek 36/37 pokazują 0.
- **80–BF**: w większości inaczej. Wejścia impulsowe są pod A8 (w EvoEcu pod A2, na innych bitach). 94–99, A1, A2 i B4–BF zawierają wartości krążące w kółko (0/36/50/105), a nie flagi.

## Bez nazw

Pozostałe PID-y, głównie z zakresu 80–BF, zostają bez nazw, dopóki nie zobaczymy ich reakcji w teście.

Źródło porównania: [EvoEcu – MUT Requests](https://evoecu.logic.net/wiki/MUT_Requests)
