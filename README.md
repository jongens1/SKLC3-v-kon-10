# SKLC3 Warehouse Picking Performance

Python / Streamlit aplikácia pre vznik joblines, pickovanie, backlog, cutoffy,
škálovanie objemu a vyrovnávanie pickovacieho výkonu. Predvolený logistický deň je
**15. 10. 2026 06:00 – 16. 10. 2026 06:00, Europe/Bratislava**.

## Spustenie

Odporúčaný Python: **3.12+**, overenie je zaznamenané v `VALIDATION.md`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Na Linuxe/macOS aktivuj prostredie cez `source .venv/bin/activate`.
Aplikácia ponúka BigQuery a explicitný **DEMO** režim. Ak je priložený overený
snapshot v `data/`, je predvoleným zdrojom a funguje bez credentials aj internetu.
DEMO vytvorí presne 124 000 syntetických joblines s oneskoreným pickovaním a
viacerými cutoffmi. Pri chybe BigQuery aplikácia zobrazí hlášku a umožní prepnúť
zdroj na DEMO; neprepne sa na syntetické dáta potichu.

## BigQuery a autentifikácia

Zdrojový projekt: `p-plat-datadf-l1st`, dataset `L1_LogisticsViews`, región
`europe-west4`. **Query/billing projekt je `d-log-bi-common`.** Konektor používa
iba SELECT, nevytvára cieľové tabuľky ani nemení zdrojové objekty.
Dotazy sa cacheujú 15 minút; tlačidlo v sidebare vyčistí query cache.

Skopíruj `.env.example` na `.env` alebo `.streamlit/secrets.toml.example` na
`.streamlit/secrets.toml`. Tieto lokálne súbory sú v `.gitignore`.
Poradie konfigurácie: environment / `.env` > Streamlit secrets > predvolené hodnoty.

Podporované credentials:

1. `GOOGLE_APPLICATION_CREDENTIALS` s cestou k servisnému JSON kľúču.
2. `[gcp_service_account]` v Streamlit secrets; príklad je v súbore secrets.
3. Application Default Credentials, napríklad existujúce lokálne ADC.

Pri explicitných Streamlit service-account secrets majú tieto credentials prednosť
pred ADC a premennou `GOOGLE_APPLICATION_CREDENTIALS`. Prístup konektora v chate sa
automaticky neprenáša do lokálnej Streamlit aplikácie. Service account potrebuje
čítanie zdrojových views a spustenie query jobov v billing projekte. Žiadne skutočné
credentials nie sú súčasťou projektu.

### Skutočná logistická schéma (`BQ_MODE=joined`)

| Zdroj | Použitie |
|---|---|
| `v_StoreJobLines` | StoreJobLine_ID, StoreJob_ID, Store_ID, Created |
| `v_StoreJobs` | Branch_ID, DepartureLimitTime |
| `v_StoreJobLineStates` | PickedDate, StornoDate |
| `v_Stores` | číselné Store_ID → textový názov Store |

Najnovšia verzia podľa `load_timestamp` sa vyberá **pred** filtrom logistického dňa.
Existujúce views už filtrujú `is_deleted=false`. Pri rovnakom ID a rovnakom
`load_timestamp` treba v zdroji zabezpečiť deterministické verzie.

Výber kohorty:

```sql
created_at >= @start AND created_at < @end
AND (branch_id = @branch_id
     OR STRPOS(UPPER(store_name), @store_pattern) > 0
     OR STRPOS(UPPER(store_id), @store_pattern) > 0)
```

Parametre sú `6281` a `SKLC3`. V tejto schéme je `Store_ID` číslo; textové hľadanie
preto zahŕňa názov cez `v_Stores`. Neobmedzujeme sa iba na hlavný Store_ID 10686:
podmienka zámerne zahŕňa celú požadovanú branch alebo ďalšie názvy SKLC3.
Nevylučujeme storná ani procesné typy bez obchodného pravidla. Počet so StornoDate
sa uvádza v kvalite dát.

`DepartureLimitTime` je nakonfigurovaný zdroj cutoffu. Jeho obchodný význam treba
potvrdiť s vlastníkom procesu; aplikácia z neho nevytvára skutočný čas odjazdu.

### Jedna tabuľka s mapovaním (`BQ_MODE=flat`)

Nastav project, dataset, table a `BQ_COLUMN_MAP_JSON`, napríklad:

```dotenv
BQ_MODE=flat
BQ_TABLE=Joblines
BQ_COLUMN_MAP_JSON={"id":"JobLine_ID","created":"Created_At","picked":"Picked_At","branch":"Branch_ID","store":"Store_Name","cutoff":"Cutoff_At","version":"load_timestamp"}
```

Mapovanie možno upraviť aj v sidebare. Identifikátory sa validujú a iba potom
vkladajú do SQL; dátumy, časové pásmo a hodnoty filtrov sú viazané parametre.
Chýbajúci optional stĺpec nastav na `null` v JSON alebo prázdny reťazec v secrets.
Povinné sú `id`, `created` a aspoň jedno z `branch`/`store`. `picked`, `cutoff` a
`version` sú voliteľné. Bez version sa duplicity ID odhalia a výpočet sa zablokuje.
Ak je store číselné ID, flat zdroj musí poskytovať branch alebo textový názov
skladu cez pripravený view. Mapovanie časov predpokladá TIMESTAMP alebo jednoznačne
konvertovateľný timestamp; nejednoznačný lokálny DATETIME treba previesť vo view.

Konektor vracia agregované skupiny, nie detailné ID. Unikátnosť sa overuje pred
agregáciou. Zachováva hodinu vzniku/pickovania, konzervatívny čas pripravenosti,
presný cutoff, počet a príznaky kvality. SQL vie čítať rozsiahlu históriu pri výbere
latest verzií; zmena dátumu spúšťa nový dotaz. Query size je uvedená v pôvode dát.

## Kohorta a hodinové metriky

Kohorta sú joblines **vzniknuté** v zvolenom dni, nie všetky joblines so zvozom v dni.
Časy ich pickovania a cutoffy môžu ležať po konci dňa a zostávajú vo vstupoch.
Graf pickovania dňa zobrazuje iba pickovanie tejto kohorty vo vybranom intervale.
Neobsahuje carry-in z predchádzajúcich dní; nejde teda o celkový výkon celého skladu
zo všetkých historických kohort. Počet pickov po konci dňa je v Dataset overview.

Hodina znamená interval `[H, H+1)`; kumulatívny stav je na jeho konci.
`operational_hour=0` označuje prvú hodinu logistického dňa. Pri zmene letného času
môže mať deň 23 alebo 25 hodín; offset časovej osi rozlišuje opakované hodiny.

```text
cumulative_created = priebežný súčet created_count
cumulative_picked  = priebežný súčet picked_count
backlog            = cumulative_created − cumulative_picked
```

Chýbajúce alebo neplatné povinné hodnoty, nekladné/neceločíselné počty a duplicitné ID
blokujú výpočet. Časové rozpory sa reportujú; počty sa nestrácajú. Joblines s pickom
pred vznikom sú vo výpočte historických metrík, ale zostanú nenaplánované.

## Prepočet na cieľový objem

Predvolený cieľ je reálny objem po načítaní. Manuálne ho možno zmeniť:

```text
koeficient = cieľový_objem / reálny_objem
prepočítaná_hodnota = reálna_hodnota × koeficient
```

Rovnaký koeficient sa používa pre vznik, pickovanie, kumulatívne krivky, backlog,
cutoffy a potrebný výkon. Príklad: `150000 / 124000 = 1.209677419…`.
Výsledky sú desatinné objemové odhady, priebežne sa nezaokrúhľujú na celé joblines.
Nulový cieľ dá nuly; pri prázdnom dni sa škálovanie a plánovanie nespustí.
Scaling predpokladá rovnaký časový profil a mix ako reálny deň.

## Potrebný výkon a predpickovanie

Presný pick deadline = cutoff mínus používateľský bezpečnostný predstih.
Baseline priradí každú jobline do **poslednej celej hodiny**, ktorá sa končí pred
alebo presne na deadline a začína najskôr pri jej pripravenosti.
Jobline vzniknutá 06:10 môže využiť až slot 07:00–08:00; cutoff 09:30 s predstihom
1 h má deadline 08:30 a posledný celý slot je 07:00–08:00.
Toto je konzervatívny hodinový plán, nie optimalizácia čiastočných hodín.

Pri cutoffe po konci dňa model explicitne požaduje dokončiť kohortu už do konca
sledovaného dňa a zobrazí upozornenie. Ak platný celý slot neexistuje, objem zostáva
v tabuľke nenaplánovaných. Nie je odhodený ani presunutý za deadline.

Chýbajúci cutoff používa **označený fallback** podľa skutočnej hodiny pickovania.
Bez cutoffu aj pickovania nemožno termín odhadnúť a objem zostane nenaplánovaný.
Pri čiastočne chýbajúcich cutoffoch sa fallback použije len pre príslušnú časť.
Historická hodina pickovania nie je potvrdený deadline expedície.

Predpickovanie dovolí posun maximálne N hodín pred baseline, stále až po vzniku.
Praktický algoritmus s maximálnym tokom a bisekciou minimalizuje špičkový výkon
pri zachovaní objemu a spoločnej hodinovej kapacity. Pracuje nad skupinami rovnakých
prípustných slotov, nie rozbalením počtov na stovky tisíc joblines.

Ak je zadaný maximálny výkon, platí pre **cieľový objem**. Algoritmus najprv zistí
maximálny objem, ktorý sa zmestí pod limit, a minimalizuje jeho špičku. Zvyšok sa
vykáže ako nenaplánovaný. Čiastočne naplánovaná hladká krivka sa neoznačí za úspech.
`prepick_smoothed_count` je optimalizácia reálneho objemu bez limitu a
`prepick_smoothed_scaled` optimalizácia cieľového scenára s prípadným limitom.
Bez limitu sú navzájom škálované; s limitom ide o samostatný scenár.

## Sekcie a export

Dataset overview; Hourly created vs picked; Cumulative curves; Backlog / buffer;
Distribution by cutoff; Required picking performance; Pre-picking simulation;
Tables and export. Plotly grafy majú interaktívny hover a legendu.

CSV UTF-8 BOM exporty obsahujú hodinové metriky, cutoff distribúciu, audit
pridelenia do hodín a parametre/výsledok scenára. Textové bunky začínajúce znakmi
vzorcov sú chránené apostrofom. Audit má release/latest/earliest/hour a počet,
takže rešpektovanie okna možno skontrolovať.

## Štruktúra

```text
app.py
src/config.py              env / secrets / bezpečné mapovanie
src/bigquery_client.py     parameterized SELECT a autentifikácia
src/data_processing.py     kohorta, čas, hodinové počty, demo
src/performance.py         baseline, scaling, nenaplánovaná práca
src/prepicking.py          minimax plánovanie so spoločným limitom
src/plots.py               Plotly
src/utils.py               CSV a kontrolný súčet snapshotu
tests/                     výpočty, query contract, Streamlit AppTest
data/                      lokálny snapshot a jeho pôvod, ak je priložený
.env.example
.streamlit/secrets.toml.example
requirements.txt
requirements-dev.txt
```

## Obnovenie lokálneho snapshotu

S nakonfigurovanými credentials možno explicitne spustiť:

```powershell
python scripts/refresh_snapshot.py --date 2026-10-15 --start 06:00
```

Skript vykoná čítací SELECT, overí výsledok a uloží CSV, metadáta, kontrolný súčet
a SQL do `data/`. Nemení zdrojové tabuľky. Každé obnovenie môže čítať rozsiahlu
históriu, preto nie je súčasťou bežného otvorenia lokálneho snapshotu.
Konkrétna analýza dodaného dňa je v `ANALYSIS.md`.

## Automatické overenie

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Testuje sa scaling, zachovanie objemu, vznik/cutoff/predpick okno, známe optimum,
nesplniteľný limit, nulový cieľ, chýbajúce časy, duplicitné ID, filter OR, hranice
intervalu, DST, query parametre a Streamlit app vrátane chyby credentials.

## Známe obmedzenia

- Jobline je jednotka práce, nie počet kusov (`Amount`) ani normovaný čas SKU.
- Bez typov procesov a pravidiel storna nemožno MissingPicked interpretovať ako
  skutočnú nedokončenú prácu ani merať výkon pracovníkov.
- Model predpokladá spoločný fond kapacity a celodennú dostupnosť hodinových slotov.
  Zmeny, prestávky, dostupnosť zásob a samostatný výkon balenia sa nemodelujú.
- Bezpečnostný predstih je čas, nie percentuálna rezerva kapacity.
- Optimalizácia je offline scenár známej kohorty; nie forecast budúcich objednávok.
- Snapshot je stav zdrojov v čase extrakcie, nie historický stav databázy o 06:00.
- Agregované interné prevádzkové dáta treba zdieľať podľa interných pravidiel.
  Dodaný balík je lokálny; upload do GitHub nebol vykonaný automaticky.
