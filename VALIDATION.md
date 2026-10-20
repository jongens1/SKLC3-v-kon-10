# Overenie collection-day implementácie

Overené 20. 10. 2026, Windows, Python 3.12. Priame závislosti sú pripnuté
v requirements.txt. Automatický GitHub Actions workflow nie je súčasťou tejto verzie.

Posledný úplný lokálny beh: **29 testov prešlo za 20,28 s**.

Testy pokrývajú:

- Zaradenie podľa svozu aj pri vzniku niekoľko dní pred sledovaným dňom.
- Vyradenie svozu mimo intervalu, hoci jobline vznikla v sledovanom dni.
- Tri povolené typy; ostatné procesy sa vyradia.
- Deadline ako collection čas mínus bezpečnostný predstih.
- Zákaz simulovaného pickovania pred dostupnosťou alebo po deadline.
- Scaling 124 000 → 150 000 vrátane všetkých objemových kriviek.
- Globálne predĺženie planning okna, carry-in, 0–168 h lookback a DST.
- Hodinové bucketovanie aj pri polhodinovom UTC offsete a opakovanej DST hodine.
- Známe optimum vyrovnávania, spoločný limit a zachovanie nenaplánovaného objemu.
- Chýbajúce dátumy, duplicity ID, neplatné počty a chýbajúce optional stĺpce.
- Konfiguráciu z env/secrets, validáciu identifikátorov a ARRAY query parametre.
- Deväť Streamlit sekcií, hour/day grafy, cieľ 150 000, nulový cieľ,
  168 h lookback, nedostatočný limit a chybu BigQuery credentials.
- CSV UTF-8 BOM a neutralizáciu textov začínajúcich vzorcom.

## BigQuery

Nový SQL prešiel skutočným dry runom a následným SELECT-only čítaním
v europe-west4 pod billing projektom d-log-bi-common.
Overilo sa, že kohorta obsahuje iba povolené výdajové procesy a zachováva staršie
vzniky aj všetky neskoršie pickovania. Nad reálnym výsledkom sa overili súčty
časových radov, kapacitné zachovanie objemu a nezáporný dostupný simulovaný buffer.
Zdrojové objekty sa nemenili. Produkčné výsledky nie sú uložené v repozitári.

Lokálny Python klient používa vlastné credentials. Jeho generované SQL a REST
parametre boli použité pri overení cez pripojený read-only konektor; samotné
lokálne service-account credentials neboli potrebné na toto overenie.
Python parameter binding bol samostatne overený testom s fake klientom.

## Rozsah a obmedzenia

Interakcie UI overuje Streamlit AppTest, aplikácia bola zároveň spustená
ako skutočný lokálny server. Obchodný význam cutoffu, storná a procesné výnimky
zostávajú uvedenými obmedzeniami modelu. Celé hodinové sloty sú konzervatívne;
nejde o presný minútový plán ani dochádzkový model.
