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

- **Výkon a plán:** stĺpce sú nové vzniky, modrá je simulovaný pick podľa dnešného
  hodinového profilu, zelená vyrovnaný pick. Oba scenáre majú rovnaký cieľový objem.
- **Buffer a vznik:** oba priebehy bufferu a kumulatívna kontrola vznikov/pickov
  s presnými hodnotami pre vybraný čas sú tu hneď hore. Porovnanie je dostupné
  aj na hlavnom pohľade; rozbaliteľný detail obsahuje jeden stĺpec vstupného bufferu.
- **Svozy:** hodinové cutoffy a skutočné podiely Expedícia Standard / LC / POB.
- **Dáta a export:** technické údaje, kvalita, pôvod dát a CSV sú schované tu.

Hlavný graf ukazuje vzniky, dva scenáre a oranžový limit skladu. Rozbaliteľné detaily
ukazujú nameranú históriu a hodinové prekročenia limitu. Čiary spájajú hodinové hodnoty; nepoužíva
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

### Nameraná referencia a simulácia podľa dnešného profilu

**Skutočný výkon skladu** je všetkých **114 649** povolených joblines picknutých
počas logistického dňa, aj keď patria do iných svozových dní. Jeho špička je
**16. 10. 01:00–02:00, 10 079 jl/h**. Tento rad sa nemení pri zmene cieľa.

**Pickovanie pre vybrané svozy** má v tomto dni **75 837** joblines. Ide o časť
celkového výkonu, nie o celý výkon skladu. Je dostupné v rozbalenej referencii.
Rozdiel nie je chyba sumy: rady majú rôzny dátový výber.

Modrá hlavná krivka je **scenár**, nie nameraná história:
`požadovaný pick[h] = cieľ × nameraný výkon[h] / súčet nameraného výkonu dňa`.
Vykonaný pick sa obmedzí dostupnou prácou; nevyužitá kapacita sa neprenáša.
Nevypickované joblines zostávajú v rade. Pri zapnutí limitu sa každá hodina
navyše obmedzí jeho hodnotou. Bez nameraného profilu sa použije rovnomerný profil.

### Presné porovnanie vznikov, pickov a bufferu

Dva grafy majú spoločný posuvník **Stav k času**, číselné karty a hodinovú tabuľku
s CSV exportom. Prvý ukazuje všetky dovtedy vzniknuté joblines a kumulatívny pick
oboch variantov, druhý zostávajúci buffer každého variantu. Počiatočné vzniky sú
už v prvom bode o 06:00; oba pickové rady začínajú nulou. Časy označujú stav na
hranici hodiny, nie začiatok hodinového výkonu. Vybraný čas je biela zvislá čiara.

**Aktuálny výkon bez úprav** v tomto porovnaní používa pôvodné namerané jl/h
celého skladu ako dostupnú kapacitu pre vybranú kohortu. Neškáluje sa na cieľ
a nemení ho nový limit skladu. Skutočný simulovaný pick sa zastaví pri nedostatku
vzniknutej a dostupnej práce. Nejde o tvrdenie, že sklad historicky pickoval iba
túto kohortu. Vyrovnaný variant rešpektuje prepínač uplatnenia limitu.

Tento rad je zámerne odlišný od horného hodinového grafu, ktorý porovnáva
dnešný profil prepočítaný na rovnaký cieľový objem. Napríklad pri cieli 250 000
je v novom porovnaní pôvodný denný výkon 114 649 a koncový buffer 135 349 jl;
všetka dostupná pôvodná kapacita sa v tomto prípade využije.

### Vstupný buffer

Pred 15. 10. 06:00 vzniklo **55 990** joblines tejto kohorty. Scenár predpokladá,
že sa **nič nepredpickovalo**: celý tento objem je vstupný buffer. Historicky
picknutých 44 421 sa neodpočítava. Pri cieli 250 000 je vstupný buffer 115 405.
Oba scenáre začínajú o 06:00 s nulovým kumulatívnym pickom.

`buffer = vstupný buffer + nové vzniky od 06:00 − vykonaný pick od 06:00`.
V kumulatívnom grafe je explicitný počiatočný bod aj koniec o 06:00 nasledujúci deň.
Vykonaný pick nikdy neprekročí kumulatívne dostupné joblines.

## Cieľový objem a plánovanie

```text
koeficient = cieľový objem / objem svozovej kohorty
prepočítaný počet = pôvodný počet × koeficient
pick deadline = cutoff − bezpečnostný predstih
začiatok plánovania = začiatok dňa o 06:00
```

Plánovanie má presne jeden logistický deň. Všetka staršia vzniknutá práca je
dostupná od začiatku dňa bez ohľadu na historický pick. Model neplánuje pred
dostupnosťou. Splniteľné termíny sa dodržiavajú. Práca, ktorá už od 06:00 nemá
žiadny platný slot pred termínom, sa ponechá na pickovanie do konca dňa a
vykáže sa ako oneskorená. Zmeškaný svoz nesmie vymazať fyzický buffer.

Využívajú sa celé hodinové sloty: vznik 06:10 umožní prvý slot 07:00–08:00.
Cutoff 14:30 a predstih 1 h znamená deadline 13:30, posledný celý slot 12–13.
To je konzervatívne. Objem s deadline pred vznikom alebo bez celého slotu je
explicitne nesplniteľný v termíne, ale zostáva v rade na pickovanie. Jeden reálny
jobline vzniká až mimo sledovaného dňa; v tom dni ho nemožno pickovať.

Maximálny tok a bisekcia minimalizujú spoločnú špičku výkonu. Následné vyrovnanie
minimalizuje súčet štvorcov hodinového zaťaženia pri zachovaní prideleného objemu
každej skupiny a jej dostupných slotov. Odstraňuje ľubovoľné prázdne sloty
rovnocenných riešení toku. Pri limite sa najprv maximalizuje realizovateľný objem.
Pri cieli 250 000 vychádza potrebný rovnomerný výkon približne **10 417 jl/h**.

**Limit skladu** je viditeľný vľavo. Predvolene je referenčnou čiarou, aby bolo
vidieť, kde ho potrebné výkony prekračujú. Voľba **Uplatniť limit v krivkách**
prepne oba pickové priebehy aj oba buffre na realizovateľný variant pri tomto
limite. Počty hodín nad limitom vždy vychádzajú z potrieb bez limitu. Metrika
nesplnených termínov je odlišná od zostávajúceho bufferu: oneskorená práca môže
byť ešte v daný deň vypickovaná. Audit označuje tieto pridelenia `on_time=False`.

Hodinový export obsahuje oba scenáre bez limitu aj s limitom, kumulatívne
vzniky, pick a buffre. Namerané stĺpce sú iba auditná referencia a nemenia
scenárový vstupný buffer.

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
