# SKLC3 Warehouse Picking Performance

Streamlit aplikácia pre plánovanie hodinového pickovania skladu SKLC3. Vyberá
**svozovú kohortu podľa collection/cutoff/dispatch času**, zobrazuje celú históriu
vzniku a pickovania, počíta buffer, potrebný výkon a vyrovnaný plán predpickovania.

Predvolený deň: **15. 10. 2026 06:00 – 16. 10. 2026 06:00**,
`Europe/Bratislava`. Predvolený planning lookback: **24 h**.

## Inštalácia a spustenie

Odporúčaný Python: **3.12**. Priame závislosti sú pripnuté na overené verzie.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Linux/macOS: aktivácia `source .venv/bin/activate`. Server sa štandardne viaže na
`127.0.0.1`, nie na verejné rozhranie. Pri hostovaní nastav server address podľa
hostovacej platformy. Bez explicitných credentials sa predvolí viditeľne označený
DEMO režim. S lokálnym ADC možno BigQuery zvoliť manuálne v sidebare.

## Hlavné pravidlá

- Hlavný dátumový filter je `collection_at >= start AND collection_at < end`.
- **Created_At nie je filter dňa.** Vybraná jobline mohla vzniknúť aj niekoľko dní
  pred svozovým dňom alebo, pri nekonzistentnom zdroji, až po deadline.
- Celé created a picked timeline sa zobrazujú od minima po maximum príslušnej
  udalosti vo vybranej kohorte, s granularitou hour/day a nulovými medzerami.
- Filter skladu je `Branch_ID=6281 OR Store LIKE '%SKLC3%'`.
- Povolené procesy: **Expedícia - Standard, Distribúcia - LC, Distribúcia - POB**.
- Príjem, expedičný podtyp Balíkový a ostatné procesy sú z predvoleného výberu
  vyradené. Balíkové sledovacie záznamy sa nepovažujú za ďalšiu pickovaciu prácu.

## BigQuery konfigurácia

Skopíruj `.env.example` na `.env` alebo
`.streamlit/secrets.toml.example` na `.streamlit/secrets.toml`. Obe konfigurácie
obsahujú rovnaké nastavenia. Environment/.env má prednosť pred secrets.

```dotenv
GCP_PROJECT_ID=p-plat-datadf-l1st
BQ_BILLING_PROJECT=d-log-bi-common
BQ_DATASET=L1_LogisticsViews
BQ_TABLE=v_StoreJobLines
BQ_MODE=joined
BQ_LOCATION=europe-west4
BRANCH_ID=6281
STORE_PATTERN=%SKLC3%
ALLOWED_JOB_TYPES=Expedícia - Standard,Distribúcia - LC,Distribúcia - POB
TIMEZONE=Europe/Bratislava
DEFAULT_LOGISTIC_START_TIME=06:00
```

`GCP_PROJECT_ID` označuje zdroj. **Query/billing projekt je d-log-bi-common.**
Konektor vykonáva iba SELECT; nepíše do zdrojových ani cieľových tabuliek.
Najnovšie verzie podľa `load_timestamp` vyberá pred filtrom dňa a typov.
Veľké historické zdroje môžu vyžadovať rozsiahly scan. Query výsledky sa cacheujú
15 minút; tlačidlo v sidebare cache vyčistí.

### Autentifikácia

Podporované sú:

1. `GOOGLE_APPLICATION_CREDENTIALS` s cestou k servisnému JSON súboru.
2. Streamlit secrets s `[gcp_service_account]` podľa priloženého príkladu.
3. Application Default Credentials, napr. už nakonfigurované lokálne ADC.

Explicitné service-account secrets majú prednosť pred ADC. Skutočné kľúče,
`.env` ani `secrets.toml` nepatria do GitHubu. Service account musí vedieť čítať
views a spúšťať joby v billing projekte. Prístup konektora v chate sa automaticky
neprenáša do lokálnej Streamlit aplikácie.

Pri chybe credentials, regiónu alebo schémy sa zobrazí hláška a zostane dostupný
DEMO režim. Aplikácia sa neprepne potichu na syntetické dáta.

### Joined režim pre skutočné logistické views

| Zdroj | Úloha |
|---|---|
| v_StoreJobLines | ID jobline, vznik, Store_ID a StoreJob_ID |
| v_StoreJobs | Branch_ID, DepartureLimitTime, JobType/SubType/Direction |
| v_StoreJobLineStates | PickedDate a príznak StornoDate |
| v_Stores | číselné Store_ID → textový názov skladu |

Názvy doplnkových tabuliek sa nastavujú cez BQ_JOBS_TABLE, BQ_STATES_TABLE a
BQ_STORES_TABLE. Store_ID je v skutočnej schéme číslo, preto sa textová podmienka
SKLC3 vyhodnocuje aj nad názvom Store.

Mapovanie procesov, overené oproti LookupLists (skupiny 29, 915, 32):

| Názov | JobType_ID | JobSubType_ID | JobDirection_ID |
|---|---:|---:|---:|
| Expedícia - Standard | 1 | 1 | -1 |
| Distribúcia - LC | 2 | 7 | -1 |
| Distribúcia - POB | 2 | 8 | -1 |

V joined režime sa textový job_type odvodí týmto mapovaním; JOB_TYPE_COLUMN je
zdrojový stĺpec iba vo flat režime. Jednotlivé smery a podtypy sa nezlievajú.
Storná sa automaticky nevylučujú; ich počet sa uvádza v kvalite dát.
`DepartureLimitTime` je použitý cutoff. Jeho význam treba potvrdiť s vlastníkom
procesu; nie je automaticky skutočným odjazdom vozidla.

### Flat režim a mapovanie názvov stĺpcov

Pre jednu pripravenú tabuľku alebo view nastav napríklad:

```dotenv
BQ_MODE=flat
BQ_TABLE=your_joblines_table
JOBLINE_ID_COLUMN=JobLine_ID
CREATED_TIME_COLUMN=Created_At
PICKED_TIME_COLUMN=Picked_At
COLLECTION_TIME_COLUMN=Collection_At
BRANCH_ID_COLUMN=Branch_ID
STORE_ID_COLUMN=Store_ID
JOB_TYPE_COLUMN=Job_Type
VERSION_COLUMN=load_timestamp
```

COLLECTION_TIME_COLUMN možno zmeniť na Cutoff_At alebo Dispatch_At. JOB_TYPE_COLUMN
možno zmeniť na Process_Type, Operation_Type alebo iný názov. Hodnoty typu sa musia
zhodovať s ALLOWED_JOB_TYPES; zoznam je nastaviteľný v env, secrets aj sidebare.

Mapovanie možno upraviť v sidebare cez JSON s kľúčmi id, created, picked,
collection, branch, store, job_type, version. Bez dostupného Picked_At nastav picked
na null (v env prázdnu hodnotu); vzniká warning a graf pickovania sa vynechá.
Bez version sa duplicity ID kontrolujú a blokujú výpočet. Collection a job_type
sú povinné pre výber kohorty. Chýbajúce hodnoty Created_At zostávajú v kohorte,
ale bez známej dostupnosti sa nenaplánujú.

Identifikátory sa validujú. Hodnoty sú viazané parametre: collection_start/end,
branch_id, store_pattern, allowed_job_types (ARRAY<STRING>) a timezone.
Query obsahuje `job_type IN UNNEST(@allowed_job_types)` a nemá created-date filter.
Flat zdroj s číselným Store_ID musí poskytovať branch alebo textový názov skladu
v namapovanom store stĺpci. Časové polia musia byť TIMESTAMP alebo jednoznačne
konvertovateľné; nejednoznačný lokálny DATETIME preveď vo zdrojovom view.

## Safety buffer a planning lookback

```text
pick deadline = collection_at − safety_buffer_hours
planning start = collection day start − lookback_hours
planning end = collection day end
```

Default: safety 1 h a lookback 24 h. Pre 15. 10. je planning okno od
**14. 10. 06:00 do 16. 10. 06:00**. Lookback možno nastaviť od 0 do 168 h.
Predlžuje celé plánovacie okno, nie len posledných N hodín každej jobline.
Staršia práca je na začiatku okna dostupný carry-in. Pri práci vzniknutej v okne
sa rešpektuje jej skutočný vznik.

Model používa **iba celé hodinové sloty**. Vznik 06:10 umožní prvý slot 07–08;
cutoff 14:30 a safety 1 h znamená deadline 13:30 a posledný slot 12–13.
To je konzervatívne: model nevyužíva časť hodiny, ale nikdy neplánuje pred vznikom
ani po presnom deadline. Zmena letného času zachová skutočné uplynuté hodiny.

Required baseline priradí celý splatný objem do posledného celého slotu pred
deadline. Zahŕňa aj dopyt, ktorý nie je možné splniť. Objem s deadline pred planning
oknom sa zobrazí osobitne a vstupuje do kumulatívnej potreby. Chýbajúci vznik,
deadline pred vznikom alebo absencia celého slotu sa vykazujú ako infeasible.

Simulácia používa maximálny tok a bisekciu pre minimum spoločnej hodinovej špičky.
Pracuje nad agregovanými skupinami rovnakých prípustných hodín, nerozbaľuje váhy na
individuálne joblines. S maximálnym hodinovým limitom najprv nájde najväčší
naplánovateľný objem; zvyšok zostane viditeľný ako unmet volume.
Objem sa neodhaduje podľa historických pickov a neposúva sa za deadline.

## Scaling a backlog

```text
scaling_factor = target_volume / real_volume
scaled_value = real_value × scaling_factor
```

Real volume je počet po filtroch collection dňa, skladu a procesov. Príklad:
150000 / 124000 ≈ 1.209677. Rovnaký koeficient sa aplikuje na created/picked
timeline, svozy, required výkon, kumulatívne krivky a buffer. Cieľ je defaultne
reálny objem; nula je platný cieľ. Prázdna kohorta sa zobrazí bez delenia nulou.

Historický backlog = kumulatívne vzniknuté mínus kumulatívne picknuté v planning
okne vrátane carry-in. Simulovaný buffer = kumulatívne dostupné mínus kumulatívne
simulované. Required curve vychádza zo svozov. Simulácia je scenár celej kohorty,
nie simulácia zostávajúceho objemu po odpočítaní historických pickov.
Pri zadanom maxime sa cieľový scenár optimalizuje samostatne; jeho krivka preto
nemusí byť jednoduchým násobkom nelimitovanej reálnej simulácie.

## Sekcie a exporty

1. Dataset overview: interval, mapovanie, procesy, unikátne ID, chýbajúce časy,
   min/max udalostí, počty podľa typu a scaling.
2. Created timeline: celá história, hour/day, reálne a cieľové počty.
3. Picked timeline: celá história a explicitne chýbajúce pickovanie.
4. Collection distribution: hlavný deň a rozdelenie podľa typu.
5. Cumulative curves: dostupnosť, required a simulované pickovanie.
6. Backlog: historický a simulovaný stav, rast a rizikové hodiny.
7. Required picking performance: baseline a nenaplánovateľný dopyt.
8. Pre-picking simulation: zníženie špičky, priemer, limit a unmet volume.
9. Tables and export: samostatné CSV časových radov, svozov, required, simulácie,
   backlogu, auditu rozdelenia do slotov a parametrov scenára.

CSV je UTF-8 BOM, textové bunky so začiatkom vzorca sú chránené apostrofom.
Časy v audite majú offset, takže opakovaná hodina pri DST je rozlíšená.

## Demo a lokálny export

DEMO obsahuje presne 124 000 vážených joblines pred používateľskými filtrami.
Collection leží vo zvolenom dni, vznik je do 72 h pred svozom, pickovanie medzi
vznikom a svozom. Obsahuje iba tri povolené typy.

S vlastnými credentials možno explicitne exportovať lokálny snapshot:

```powershell
python scripts/refresh_snapshot.py --date 2026-10-15 --start 06:00
```

Snapshot aj exporty sa ukladajú do ignorovaných priečinkov. Produkčné agregáty
ani kľúče nie sú súčasťou novej verzie repozitára. Aplikácia číta BigQuery alebo
generuje DEMO; starý created-day snapshot sa už nenačítava.

## Testy a štruktúra

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Testy pokrývajú všetkých šesť požadovaných pravidiel, carry-in, DST, nulový cieľ,
nesplniteľný limit, známe optimum simulácie, parameter binding, konfigurovateľnú
schému a Streamlit UI. Testy sa spúšťajú lokálne na Python 3.12.

```text
app.py
src/config.py              env, secrets, typy, mapovanie
src/bigquery_client.py     collection-day SELECT, auth a parametre
src/data_processing.py     kohorta, timeline a carry-in
src/performance.py         deadline, required, scaling
src/prepicking.py          vyrovnávanie a spoločný limit
src/plots.py               Plotly grafy
src/demo_data.py           syntetická svozová kohorta
src/utils.py               bezpečný CSV export
scripts/refresh_snapshot.py
tests/
```

## Známe obmedzenia

- Chýbajúci collection čas nemožno priradiť k dňu, preto sa vyradí dátumovým filtrom.
  Nulový počet chýbajúcich cutoffov po filtroch neznamená úplný celý zdroj.
- Jobline je jednotka práce, nie počet kusov ani normovaný čas konkrétneho SKU.
- Bez procesného pravidla sa storná automaticky nevylučujú. Chýbajúce pickovanie
  samo osebe nie je dôkaz nedokončenej fyzickej práce.
- Model predpokladá spoločný fond kapacity a nepočíta prestávky, zmeny, zásoby ani
  samostatný výkon balenia. Safety buffer je čas, nie percentuálna kapacitná rezerva.
- Ide o offline scenár známej kohorty. Nie je to forecast budúcich objednávok.
- Agregované SQL zachová presné min/max event časov, presný cutoff a konzervatívny
  release; samotné created/picked grafy sú hodinové alebo denné.
- Latest zdrojové verzie nie sú rekonštrukciou historického stavu databázy.
  Pri rovnakom ID a load_timestamp musí zdroj zabezpečiť jednoznačnosť verzie.
