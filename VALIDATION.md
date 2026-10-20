# Overenie novej implementácie

Overené 20. 10. 2026 na Windows, Python 3.12. Závislosti v requirements sú pripnuté
na verzie použité pri overení.

**21 testov prešlo**. Overenie zahŕňa:

- Streamlit AppTest nad demo dátami aj skutočným dodaným snapshotom.
- Všetkých osem sekcií, manuálny cieľ 150 000, nulový cieľ a nesplniteľný limit.
- Ošetrenie nedostupného BigQuery / credentials bez pádu aplikácie.
- Časové hranice, OR filter branch/názov skladu a dni s 23/25 hodinami.
- Scaling všetkých objemových metrík, kumulatívnych kriviek a backlogu.
- Minimax so známym optimom, rešpektovanie vzniku/deadline/predpick okna,
  spoločný limit, zachovanie objemu a explicitný nenaplánovaný zvyšok.
- Duplicity ID, chybné dátumy, neplatné počty a optional chýbajúce stĺpce.
- BigQuery mapovanie, parameter binding a odmietnutie neplatných identifikátorov.
- Kontrolný súčet snapshotu a presné súčty reálnych dát.

Posledný úplný testovací beh po finálnych úpravách: `21 passed in 14.09s`.

## BigQuery

SQL v src/bigquery_client.py prešiel skutočným dry runom v regióne europe-west4.
Rovnaký SELECT bol vykonaný cez read-only konektor pod billing projektom
`d-log-bi-common`. Zdrojové tabuľky ani views sa nemenili.
Job: `job_aZ4exj972nX96Rrn0-R8OmyV8m_4`, prečítané bajty 97 861 399 223.
Výsledok: 8 459 agregovaných skupín, 276 869 unikátnych joblines.

Lokálny autentifikovaný Python BigQuery klient sa proti službe nespúšťal:
credentials chatového konektora nie sú lokálne ADC. Jeho generované SQL a bound
parametre boli použité v reálnom čítacom dotaze; auth vetvy sú pripravené pre
GOOGLE_APPLICATION_CREDENTIALS, ADC a Streamlit secrets.

## Prehliadač

Aplikácia bola spustená ako skutočný Streamlit server a otvorená v prehliadači.
Vizuálne sa overilo zobrazenie reálnych súčtov, Plotly grafu potrebného výkonu,
nenaplánovaného objemu a sekcie simulácie. Interakcie s cieľom a limitom sa
automaticky overili cez AppTest. Grafy aj tabuľky pracujú nad reálnym snapshotom.

## Rozsah

Nevykonal sa push, commit, deployment ani zmena vzdialeného GitHub repozitára.
Význam cutoffu, procesné typy a pravidlá storna zostávajú obchodnými obmedzeniami
uvedenými v aplikácii, README a ANALYSIS.md. Balík obsahuje interné agregované
prevádzkové objemy, neobsahuje credentials ani individuálne jobline ID.
