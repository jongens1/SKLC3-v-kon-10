# Overenie offline dashboardu

Overené 20. 10. 2026, Python 3.12. Posledný úplný beh: **45 testov prešlo**.
Overuje sa aj spustenie Streamlit AppTest so zablokovaným sieťovým pripojením.

## Reálne dátové kontroly

- Svozová kohorta: 121 290 joblines; Standard 117 005, LC 3 013, POB 1 272.
- Práca vzniknutá pred dňom: 55 990. Celá tvorí scenárový vstupný buffer;
  historicky predpickovaných 44 421 sa podľa zadania ignoruje.
- Pickovanie pre túto kohortu v dni: 75 837.
- Celkový skutočný výkon povolených procesov v dni: 114 649.
- Skutočná špička: 16. 10. 01:00–02:00 Europe/Bratislava, 10 079 jl/h.
- Pickovanie, nevypickovaný objem a objem nedostupný v dni zachovávajú kohortu
  aj po škálovaní na 250 000. Joblines po zmeškanom termíne zostávajú na pickovanie.
- Pri cieli 250 000 je vstupný buffer 115 405 a potrebná vyrovnaná špička
  približne 10 417 jl/h; pri limite 10 000 zostane približne 9 998 vzniknutých
  joblines vo fyzickom buffri. Jeden pôvodný jobline vzniká až mimo dňa.
- Kontrolné súčty oboch priložených Parquetov sedia s manifestom.

Kohorta bola čítaná jednorazovo cez SELECT-only query
job_pxqbC0MlzPbzzcI3fsVgbDEKbV1T. Celkový výkon bol samostatne čítaný podľa
PickedDate query job_s-iQPjos83qgeQgB3aGeojcF92vm. Billing d-log-bi-common,
zdroj p-plat-datadf-l1st, región europe-west4. Zdrojové objekty sa nemenili.

## Výpočty a UI

Testy pokrývajú selection podľa cutoffu, povolené procesy, dátumové hranice,
chýbajúce časy, duplicity, carry-in, celý plánovací lookback, DST, shared capacity,
známe optimum, nemožné termíny, maximálny limit a nulový cieľ.
Nové regresie overujú nezávislosť scenárov od historického pickovania, plný vstupný
buffer, oba pickové profily a oba buffre pri nulovom, nízkom aj neobmedzenom limite.
Kumulatívny pick neprekračuje dostupnosť ani vzniky v žiadnej hodine. Auditné
pridelenia zachovávajú dostupné sloty a rozlišujú prácu v termíne a po termíne.
Následné vyrovnanie odstráni známy prípad prázdnych slotov minimax toku a pri
limite nesmie oneskorená práca vytlačiť prácu, ktorú ešte možno stihnúť v termíne.

Streamlit AppTest prešiel všetky štyri pohľady, prepočet na 250 000, zachovanie
skutočného výkonu pri zmene cieľa, explicitný demo režim, limit a exporty.
Hlavný pohľad obsahuje vzniky, dnešný profil a vyrovnaný pick, oranžový limit,
oba buffre a kumulatívnu kontrolu. Prepínač limitu mení pick aj buffer spoločne.

Aplikácia neimportuje BigQuery klienta, nečíta Google credentials a pri používaní
nevolá query. Konektor a konfigurácia zostávajú iba pre offline prípravu snapshotov.
Hodinová konzervatívna presnosť a procesné obmedzenia sú uvedené v README.
