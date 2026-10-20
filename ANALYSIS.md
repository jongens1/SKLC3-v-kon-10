# SKLC3 · logistický deň 15. 10. 2026

Výber: vznik joblines v intervale **15. 10. 06:00 až 16. 10. 06:00,
Europe/Bratislava**, `Branch_ID=6281 OR názov/ID skladu obsahuje SKLC3`.
Najnovšie verzie zdrojových ID sa vyberajú pred filtrom kohorty.

| Ukazovateľ | Joblines |
|---|---:|
| Reálny objem / unikátne ID | 276 869 |
| PickedDate vyplnený (aj po konci dňa) | 117 283 |
| Vypickované v sledovanom dni | 99 061 |
| Vypickované až po konci dňa | 18 222 |
| Bez PickedDate | 159 586 |
| Evidenčný backlog na konci dňa | 177 808 |
| Bez cutoffu | 38 738 |
| So StornoDate | 6 228 |
| PickedDate pred Created | 1 |

Hlavný sklad `10686` zastupuje 271 495 joblines. Ostatné joblines prešli požadovaným
OR filtrom branch/názvu skladu; výber sa neobmedzuje na jedno Store_ID.
Najväčší vznik bol **16. 10. 01:00–02:00: 21 748 joblines**. Najväčšie pickovanie
tejto kohorty bolo v rovnakej hodine: **10 049 joblines**.

## Model kapacity

Parametre: predstih pred cutoffom 1 hodina, predpickovanie 4 hodiny, bez hodinového
limitu, konzervatívne celé hodinové sloty. Objem s deadline po dni sa v tomto
scenári požaduje dokončiť už do konca sledovaného dňa.

| Výsledok | Reálny objem |
|---|---:|
| Plánovateľná časť | 213 027 |
| Špička baseline | 67 027 jl/h |
| Špička po vyrovnaní | približne 24 281 jl/h |
| Nenaplánovaný objem | 63 842 |

Nenaplánovaný objem pozostáva z 38 738 joblines bez cutoffu aj pickovania,
25 103 bez celej prípustnej hodiny medzi vznikom a deadline a jednej jobline
s pickovaním pred vznikom. Tieto objemy sa nestrácajú a zostávajú v hlásení rizík.
Vyhladenie rieši iba plánovateľnú časť a nepotvrdzuje splniteľnosť celého dňa.

Pri cieli **150 000** je koeficient **150000 / 276869 ≈ 0,541772**.
Ide teda o zníženie oproti tomuto reálnemu dňu. Aplikácia týmto koeficientom
prepočíta všetky počty a objemové krivky. Súbor
`data/analysis_2026-10-15_target150000.csv` obsahuje tento konkrétny scenár
s rovnakými parametrami kapacity.

## Interpretácia

Chýbajúce pickovanie, storná a rôzne procesné typy neumožňujú považovať celý
evidenčný backlog za nedokončenú fyzickú prácu. Bez potvrdenia procesných filtrov
a významu DepartureLimitTime nemožno červený výsledok interpretovať ako skutočnú
mieru meškania skladu. Žiadne dodatočné procesné filtre neboli odhadnuté potichu.

Toto je analýza kohorty vzniknutej v jednom dni, bez carry-in zo skorších dní.
Neskoršie zdrojové aktualizácie sú súčasťou snapshotu k extrakcii 20. 10. 2026;
nejde o rekonštrukciu vtedajšieho stavu databázy.

## Pôvod

Zdroj: `p-plat-datadf-l1st.L1_LogisticsViews`. Billing: `d-log-bi-common`.
Query job: `job_aZ4exj972nX96Rrn0-R8OmyV8m_4`, región `europe-west4`.
Prečítané bajty: **97 861 399 223**. Query bolo SELECT-only.
Lokálne uložených 8 459 agregovaných skupín; neexportovali sa jednotlivé ID.
Metadáta a SHA-256 sú v `data/snapshot_metadata.json`.
