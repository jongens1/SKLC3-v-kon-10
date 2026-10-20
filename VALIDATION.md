# Overenie offline dashboardu

Overené 20. 10. 2026, Python 3.12. Posledný úplný beh: **52 testov prešlo**.
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
Hlavný pohľad obsahuje vzniky, pôvodný výkon a vyrovnaný pick, oranžový limit,
oba buffre a kumulatívnu kontrolu. Prepínač limitu mení vyrovnaný pick aj jeho
buffer spoločne; pôvodná referencia zostáva bez škálovania vo všetkých pohľadoch.

Presné porovnanie v pohľade Buffer a vznik používa pôvodný nameraný výkon skladu
bez škálovania ako kapacitu pre kohortu. Pri cieli 250 000 vykoná 114 649 pickov
a zostane buffer 135 349. Nový limit tento referenčný variant nemení; vyrovnaný
variant rešpektuje prepínač limitu. Nové regresie overujú bilancie oboch variantov
pri cieľoch 0, 121 290 a 250 000, pôvodnú kapacitu, zhodu piatich grafových radov
s tabuľkou a počiatočné/koncové časové hranice. AppTest overuje zmenu posuvníka
na 06:00 vrátane presných číselných kariet a nulového kumulatívneho picku.

## Audit cieľa 270 000 pri limite 15 000 jl/h

Nezávislý kontrolný výpočet overil 21 bilancií a obmedzení zdroja, hodinových
výkonov, bufferov, termínov, procesov, časových hraníc a auditných pridelení.
AppTest overil zadané nastavenie aj všetky štyri pohľady.

- Počiatočný buffer 124 637.65 + vzniky 145 360.13 = 269 997.77.
- Vyrovnaný výkon 11 249.91 jl/h; denný pick 269 997.77; buffer 0.
- Pôvodný výkon 114 649; koncový buffer 155 348.77; všetky grafy a exporty sa zhodujú.
- Dokončené v termíne 189 819.19 + po termíne 80 178.58 = celkový pick.
- Zmeškané termíny 80 180.81. Zhodujú sa denná metrika aj posledný riadok exportu.
- Rozdiel 2.23 do cieľa je jediný zdrojový jobline vzniknutý po konci dňa.
- Pri limite 10 000 kontrolný výpočet zníži pick na 240 000 a ponechá 29 997.77
  vzniknutých joblines v buffri. Neobmedzený variant je zreteľne označený.

Opravené boli dve nezhody: horný graf už neškáluje pôvodný výkon na cieľový objem
a export už nevymazáva zmeškané termíny neskorým dokončením iných joblines.
Limit je predvolene zapnutý. Hlavný hodinový export je totožný so zobrazeným
scenárom; historické referencie sú samostatne označené v úplnom audite.

Kontrola nasadenia odhalila pretrvávajúcu cache reportu z predchádzajúcej verzie
modelu. Kľúče základného aj cieľového reportu teraz obsahujú SHA-256 všetkých
výpočtových zdrojov. Regresia najprv zahreje cache, potvrdí jej opätovné použitie,
potom zmení fingerprint importovaného modelu a overí nové vykonanie výpočtu.

Aplikácia neimportuje BigQuery klienta, nečíta Google credentials a pri používaní
nevolá query. Konektor a konfigurácia zostávajú iba pre offline prípravu snapshotov.
Hodinová konzervatívna presnosť a procesné obmedzenia sú uvedené v README.
