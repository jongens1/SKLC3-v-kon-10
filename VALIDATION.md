# Overenie offline dashboardu

Overené 20. 10. 2026, Python 3.12. Posledný úplný beh: **37 testov prešlo**.
Overuje sa aj spustenie Streamlit AppTest so zablokovaným sieťovým pripojením.

## Reálne dátové kontroly

- Svozová kohorta: 121 290 joblines; Standard 117 005, LC 3 013, POB 1 272.
- Práca vzniknutá pred dňom: 55 990; už picknuté: 44 421; vstupný buffer: 11 569.
- Pickovanie pre túto kohortu v dni: 75 837.
- Celkový skutočný výkon povolených procesov v dni: 114 649.
- Skutočná špička: 16. 10. 01:00–02:00 Europe/Bratislava, 10 079 jl/h.
- Súčet plánovania, nenaplánovateľného objemu a práce hotovej pred začiatkom okna
  presne sedí s kohortou aj po škálovaní na 250 000.
- Kontrolné súčty oboch priložených Parquetov sedia s manifestom.

Kohorta bola čítaná jednorazovo cez SELECT-only query
job_pxqbC0MlzPbzzcI3fsVgbDEKbV1T. Celkový výkon bol samostatne čítaný podľa
PickedDate query job_s-iQPjos83qgeQgB3aGeojcF92vm. Billing d-log-bi-common,
zdroj p-plat-datadf-l1st, región europe-west4. Zdrojové objekty sa nemenili.

## Výpočty a UI

Testy pokrývajú selection podľa cutoffu, povolené procesy, dátumové hranice,
chýbajúce časy, duplicity, carry-in, celý plánovací lookback, DST, shared capacity,
známe optimum, nemožné termíny, maximálny limit a nulový cieľ.
Nové regresie overujú rozdiel medzi celkovým výkonom a kohortou, dominantnú
expedíciu, nočnú špičku, jeden vstupný buffer, vyradenie už dokončenej práce
z opakovaného plánovania a zhodu okamžitého škálovania s úplným výpočtom.

Streamlit AppTest prešiel všetky štyri pohľady, prepočet na 250 000, zachovanie
skutočného výkonu pri zmene cieľa, explicitný demo režim, limit a exporty.
Vizuálna kontrola lokálneho servera potvrdila modrú skutočnosť, zelený plán,
skompaktnené karty a hlavný graf na jednej časovej osi 06:00–06:00.

Aplikácia neimportuje BigQuery klienta, nečíta Google credentials a pri používaní
nevolá query. Konektor a konfigurácia zostávajú iba pre offline prípravu snapshotov.
Hodinová konzervatívna presnosť a procesné obmedzenia sú uvedené v README.
