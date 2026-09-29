# mitsu-KKL: wskazówki dla Claude

- Użytkownik pisze po polsku, więc odpowiadaj po polsku.
- Przed analizą znaczenia PID-ów przeczytaj `PID_analiza_instrukcja.md`: metoda, formaty logów,
  pułapki i plan eksperymentów. Stan wiedzy jest w `PID_znaczenia.md`, `pid_definicje.csv`
  i `dtc_definitions.csv`.
- Logi są w `logs/` (poza gitem). Do ich analizy służy `tools/analyze_readings.py`.
- Na linię K wysyłaj wyłącznie zapytania odczytowe MUT 00–BF i FD–FF. Nie obchodź blokady zakresu C0–FC.
