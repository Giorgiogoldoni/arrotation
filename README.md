# ARRotation

Dashboard per rispondere a due domande:
1. **Dove si sta concentrando il capitale?** Osservazione delle rotazioni già in corso.
2. **Dove potrebbe spostarsi dopo?** Individuazione delle aree che stanno accelerando prima che la rotazione sia pienamente confermata.

## Motori

- **Screening BIG** (`scripts/agente.py`): candidati, uscite e verifica storica dei segnali. Non modifica il repository BIG.
- **Rotation Radar** (`scripts/rotation.py`): aggrega i rendimenti degli ETF per aree geografiche, settori e asset class; calcola forza relativa contro la mediana degli ETF azionari, ampiezza e accelerazione su 5, 20 e 60 sedute.
- **Dashboard** (`index.html`): presenta separatamente lo screening, la rotazione osservata e il radar delle possibili rotazioni successive.

## Distinzione importante: flussi e prezzi

BIG pubblica prezzi OHLC e segnali, non sottoscrizioni/rimborsi, variazioni delle quote in circolazione o flussi netti. Il Rotation Radar è quindi un **proxy di rotazione basato sui prezzi**, non una misura di flussi monetari effettivi. La pagina lo dichiara esplicitamente e non trasforma la forza relativa in un falso dato di flusso.

Per integrare i flussi effettivi serve una fonte separata con copertura, date e licenza verificabili. Una fonte pubblica da valutare è [ETFIQ Open Data](https://etfiq.com/data/): pubblica aggregati di flussi per categoria ed emittente, con attribuzione richiesta; la copertura dei flussi non coincide con l'intero universo UCITS europeo. Metodologia: [ETFIQ Fund Flows](https://etfiq.com/methodology/flows).

## Aggiornamento

Il workflow **Aggiorna arrotation** legge i dati di BIG, esegue lo screening storico, calcola il Rotation Radar scaricando gli storici degli ETF classificati e salva i file JSON in `data/` per GitHub Pages.

Schedulazione: lunedì-venerdì alle 20:30 UTC e sabato alle 11:00 UTC. È disponibile anche l'avvio manuale da Actions.

## File principali

- `data/selezione.json`: candidati e uscite dello screening.
- `data/storico.json`: esiti delle segnalazioni.
- `data/rotation.json`: dati aggregati del Rotation Radar.
- `data/regole_arrotation.pdf`: regole dello screening BIG.

## Limiti

Le categorie geografiche e settoriali del radar sono assegnate con parole chiave dei nomi degli ETF e sono quindi una tassonomia operativa da controllare. I rendimenti sono mediane di ETF disponibili nell'universo BIG, non flussi di capitale. Le serie mancanti o insufficienti sono escluse; la copertura viene mostrata. Nessuna raccomandazione automatica.


## Flussi effettivi ETFIQ

`scripts/flows.py` importa ogni run il file pubblico `https://etfiq.com/data/flows/daily/latest.json` e genera `data/flows.json`. La dashboard mostra flussi giornalieri per asset class, emittente, tema, ETF singoli e un raggruppamento geografico indicativo ricavato dai nomi dei fondi.

Il flusso è calcolato da ETFIQ sulle variazioni delle quote in circolazione e sul NAV, non da prezzo e volume. Sono esclusi i fondi trattenuti per revisione e le righe con stato diverso da `ok`. I round trip restano esposti separatamente, senza correzioni arbitrarie.

Copertura: ETF quotati negli Stati Uniti con dato giornaliero disponibile. Non equivale all'intero mercato UCITS europeo; le categorie geografiche ricavate dai nomi sono indicative, non una misura ufficiale dell'esposizione sottostante. Attribuzione obbligatoria: ETFIQ, con data del file e link a https://etfiq.com/flows/.

Se la fonte non risponde, lo script conserva l'ultimo file valido e lo marca come non aggiornato.
## Radar separati USA ed Europa UCITS

Il `scripts/rotation.py` produce anche `market_categories`: radar di forza relativa separati per ETF negoziati negli USA e ETF UCITS negoziati sulle borse europee. La sede di negoziazione viene letta dal campo borsa di BIG; il suffisso ticker è usato solo come fallback. Il benchmark è calcolato separatamente per ciascun mercato. La dashboard confronta i settori comuni su 20 e 60 sedute e segnala convergenze/divergenze.

Il radar USA dei flussi resta basato sui flussi giornalieri ETFIQ (ETF USA-listed). Il radar europeo non attribuisce flussi monetari ai prezzi: finché non è disponibile una serie UCITS omogenea e riproducibile, mostra soltanto prezzi e forza relativa. Le pubblicazioni aggregate di Amundi, EFAMA e LSEG Lipper possono essere usate come controllo esterno, ma non vengono fuse con i flussi ETFIQ perché differiscono per universo, frequenza e metodologia.
