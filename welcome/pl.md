# Witaj w mitsu-kkl

Program odczytuje dane z komputera silnika starszych Mitsubishi z lat 90. (sprawdzony na Eclipse 1998 2.0).
Pokazuje na żywo odczyty czujników, na przykład obroty, temperaturę silnika, napięcie akumulatora
i położenie pedału gazu, oraz kody usterek.

**Szczególnie przydatny dla roczników 1998–1999**, z którymi większość zwykłych testerów diagnostycznych się nie łączy.
Łączy się też z europejskimi sterownikami, z którymi nie łączy się program EvoScan.

**Program tylko odczytuje dane. Niczego nie zmienia w samochodzie.**

## Czego potrzebujesz

- Laptopa z Windows.
- **Najtańszego kabla „VAG KKL 409.1”** (z jednej strony USB, z drugiej wtyczka do gniazda diagnostycznego w aucie).
  Nie kupuj droższych kabli „HEX”, „VCDS” ani przejściówek „ELM327”: z tym samochodem nie działają.
- **Kawałka przewodu**, który w gnieździe diagnostycznym połączy **styk 1** ze **stykiem 4 albo 5**.
  Bez tego komputer samochodu nie odpowiada. Najwygodniej z małym wyłącznikiem.
  Patrząc na gniazdo w aucie szerszym bokiem do góry: styk 1 jest skrajnie z lewej w górnym rzędzie,
  styki 4 i 5 to czwarty i piąty w tym samym rzędzie.

## Jak zacząć

1. Włóż kabel do gniazda diagnostycznego pod deską rozdzielczą i do USB laptopa.
2. Połącz przewodem styk 1 ze stykiem 4 albo 5.
3. Przekręć kluczyk na zapłon. Silnika nie trzeba uruchamiać.
4. W programie kliknij **Connect**. Po kilku sekundach wartości na liście zaczną się zmieniać.

Lista **ECU init** obok wyboru kabla mówi, jak program zagaduje komputer samochodu. Zostaw **Auto**:
program sam próbuje na zmianę sposobu europejskiego (0x00) i amerykańskiego (0x33, tak jak EvoScan),
aż samochód odpowie.

Lampka „check engine” może wtedy migać. To normalne: komputer samochodu pokazuje w ten sposób kody usterek.

## Gdy coś nie działa

- **Na górze okna pojawia się „ECU not responding”:** sprawdź przewód na styku 1 i czy zapłon jest włączony.
- **Program nie widzi kabla:** podłącz kabel jeszcze raz i kliknij **Refresh**. Może być potrzebny sterownik ze strony [ftdichip.com](https://ftdichip.com/drivers/).
- **Windows przy pierwszym uruchomieniu ostrzega przed programem:** kliknij „Więcej informacji”, potem „Uruchom mimo to”.

## Przydatne przyciski

- **Fault Codes:** kody usterek, te same, które miga lampka „check engine”.
- **● Record log:** zapisuje odczyty do pliku, który otworzysz w Excelu.
- Gdy pojawi się nowa wersja programu, na górze okna zobaczysz pasek z przyciskiem do pobrania.

Szczegóły techniczne i pełna instrukcja są na [stronie projektu](https://github.com/Alb7C4/mitsu-kkl).

Używasz na własne ryzyko. Program nie jest związany z Mitsubishi Motors.
