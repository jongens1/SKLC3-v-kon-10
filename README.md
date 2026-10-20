# SKLC3 · Výkon a plán

Streamlit aplikácia s **pripravenými reálnymi agregátmi z BigQuery**. Pri otvorení,
prepínaní grafov ani prepočte cieľového objemu sa do BigQuery nepripája.
**V Streamlit Cloud netreba nastavovať Google credentials.**

## Spustenie

Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Na Linuxe/macOS aktivuj prostredie cez `source .venv/bin/activate`.
Nahraj celý repozitár **vrátane data/**. Predvolený zdroj je reálny snapshot,
DEMO je samostatná explicitná voľba. Nepoužíva sa tichý prechod na demo.

## Čo vidíš

- **Výkon a plán:** modrá je skutočne vypickovaný objem celého skladu po hodinách;
  zelená je vyrovnaný plán pre cieľový objem vybraných svozov.
- **Buffer a vznik:** staršia nevypickovaná práca je jeden vstupný buffer o 06:00,
  potom nasledujú vzniky a buffer počas logistického dňa.
- **Svozy:** hodinové cutoffy a skutočné podiely Expedícia Standard / LC / POB.
- **Dáta a export:** technické údaje, kvalita, pôvod dát a CSV sú schované tu.

Hlavný graf ukazuje iba skutočný výkon a potrebný plán. Rozbaliteľné detaily
ukazujú výkon pre konkrétne svozy, historický profil prepočítaný koeficientom
a splatný objem pred cutoffmi. Čiary spájajú skutočné hodinové hodnoty; nepoužíva
sa spline s vymyslenými špičkami ani zmenou počtov. Os výkonu začína na nule.

## Reálne dáta pre 15. 10. 2026

Logistický deň: **15. 10. 06:00 – 16. 10. 06:00, Europe/Bratislava**.
Kohorta sa vyberá podľa `DepartureLimitTime`, nie podľa vzniku.

| Proces | Joblines pre svozy |
|---|---:|
| Expedícia - Standard | 117 005 |
| Distribúcia - LC | 3 013 |
| Distribúcia - POB | 1 272 |
| Spolu | 121 290 |

Filter skladu: Branch_ID=6281 alebo názov skladu obsahuje SKLC3.
Native mapovanie z číselníkov LookupLists:

| Proces | JobType_ID | JobSubType_ID | JobDirection_ID |
|---|---:|---:|---:|
| Expedícia - Standard | 1 | 1 | -1 |
| Distribúcia - LC | 2 | 7 | -1 |
| Distribúcia - POB | 2 | 8 | -1 |

Balíkové sledovacie záznamy a príjem sú vylúčené. Storná sa vykazujú, ale bez
obchodného pravidla sa automaticky neodstraňujú.

### Dva rozdielne pohľady na pickovanie

**Skutočný výkon skladu** je všetkých **114 649** povolených joblines picknutých
počas logistického dňa, aj keď patria do iných svozových dní. Jeho špička je
**16. 10. 01:00–02:00, 10 079 jl/h**. Tento rad sa nemení pri zmene cieľa.

**Pickovanie pre vybrané svozy** má v tomto dni **75 837** joblines. Ide o časť
celkového výkonu, nie o celý výkon skladu. Je dostupné ako doplnková čiara.
Rozdiel nie je chyba sumy: rady majú rôzny dátový výber.

### Vstupný buffer

Pred 15. 10. 06:00 vzniklo 55 990 joblines tejto kohorty. Už picknutých bolo
44 421, preto otvorený vstupný buffer je **11 569**. Historicky dokončená práca sa
nepočíta ako ďalšia čakajúca práca. Úplná staršia história je dostupná v detaile,
na hlavnej osi sa zoskupí do jednej hodnoty.

## Cieľový objem a plánovanie

```text
koeficient = cieľový objem / objem svozovej kohorty
prepočítaný počet = pôvodný počet × koeficient
pick deadline = cutoff − bezpečnostný predstih
začiatok plánovania = začiatok dňa − lookback
```

Defaultný lookback je 24 h, rozsah 0–168 h. Práca už historicky dokončená pred
začiatkom plánovacieho okna sa znovu neplánuje. Zostávajúca staršia práca je
dostupná od začiatku okna. Model nikdy neplánuje pred vznikom ani po deadline.

Využívajú sa celé hodinové sloty: vznik 06:10 umožní prvý slot 07:00–08:00.
Cutoff 14:30 a predstih 1 h znamená deadline 13:30, posledný celý slot 12–13.
To je konzervatívne. Objem s deadline pred vznikom alebo bez celého slotu zostáva
explicitne nenaplánovateľný, nestráca sa z bilancie.

Maximálny tok a bisekcia minimalizujú spoločnú špičku výkonu. Voliteľný limit
platí pre celý sklad naraz. Cieľový objem bez limitu sa prepočíta okamžite zo
základného plánu; nemusí sa opakovať optimalizácia ani čítanie dát.
Pri zadanom limite sa kontroluje maximálny realizovateľný objem a zvyšok.

Historické počty, backlog, svozy, potrebný a simulovaný výkon majú prepočítané
stĺpce v exportoch. **Nameraná modrá čiara skladu zostáva skutočnosťou.** Scaled
historická čiara je v detaile samostatne označená.

## Obsah snapshotu

`data/manifest.json` eviduje dátum, pôvod, query joby a SHA-256 súborov.
Parquet kohorty obsahuje iba agregované časové skupiny a počty, nie individuálne
jobline ID. Druhý Parquet je hodinový skutočný výkon skladu podľa procesu.
Kontrolné súčty sa overujú pri načítaní. Dáta sú stav zdroja k 20. 10. 2026,
nie priebežne aktualizovaný zdroj. Iný deň musí byť najprv pripravený.

## Jednorazová príprava ďalšieho dňa

Táto časť je určená správcovi dát, nie nasadenej aplikácii:

```powershell
python scripts/refresh_snapshot.py --date 2026-10-15 --start 06:00
```

Skript číta kohortu podľa cutoffu a samostatne výkon podľa PickedDate. Používa
source project `p-plat-datadf-l1st`, billing **d-log-bi-common**, europe-west4.
Vykonáva iba SELECT. Query hodnoty sú viazané parametre a identifikátory validované.

Pre tento offline skript podporujeme GOOGLE_APPLICATION_CREDENTIALS, ADC alebo
Streamlit service-account secrets. Príklady sú v `.env.example` a
`.streamlit/secrets.toml.example`. Skutočné kľúče sa necommitujú.
Názvy polí nastavujú `*_COLUMN`; povolené procesy `ALLOWED_JOB_TYPES`.
Joined režim používa logistické views; flat režim jednu namapovanú tabuľku.
Po kontrole nového snapshotu treba pridať data/ do commitu a aktualizovať appku.

## Testy

```powershell
pip install -r requirements-dev.txt
pytest -q
```

Testy kontrolujú reálny procesný mix, nočnú špičku, rozdiel celkového výkonu a
svozovej kohorty, vstupný buffer, zachovanie objemu, prepočet cieľa, limity,
celé sloty, DST, offline načítanie a všetky štyri pohľady aplikácie.

## Obmedzenia

- Celkový výkon zahŕňa aj iné svozy. Sám osebe nedokazuje splnenie konkrétneho cutoffu.
- Zelená čiara je plán známej kohorty, nie forecast budúcich objednávok.
- Výkon vyjadrujeme v joblines, nie kusoch alebo normovanom čase SKU.
- Prestávky, dochádzka, zásoby ani samostatný výkon balenia sa nemodelujú.
- Chýbajúci PickedDate nemusí znamenať otvorenú fyzickú prácu. Procesné výnimky
  a storná treba vyhodnotiť s vlastníkom skladu.
- Snapshot obsahuje interné agregované objemy pre používateľom požadovanú aplikáciu.
