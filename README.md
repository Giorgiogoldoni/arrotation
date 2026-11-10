# arrotation

Screening automatico dei candidati ETF da verificare, a partire dai dati pubblici del repo `big`. Nessuna AI, nessuna chiave, nessun costo. Non è una raccomandazione.

## Struttura da caricare
- `index.html` nella radice
- `scripts/agente.py`
- `.github/workflows/agente.yml` (la cartella inizia con un punto: su GitHub usa "Add file → Create new file" e digita `.github/workflows/agente.yml`, poi incolla il contenuto)
- `data/` viene creata dall'agente al primo avvio

## Impostazioni una tantum
1. Settings → Actions → General → Workflow permissions → **Read and write permissions**
2. Settings → Pages → Source: **Deploy from a branch**, branch `main`, cartella `/ (root)`
3. Actions → "Aggiorna arrotation" → Run workflow (primo avvio manuale)

## Come funziona
Ogni giorno lavorativo alle 20:30 UTC legge `index.json` e `classifica_sintesi.json` di big, applica i criteri (vedi `data/regole_arrotation.pdf`, sempre generato dai parametri in `scripts/agente.py`), registra le nuove segnalazioni in `data/storico.json` e misura gli esiti reali a 5, 10, 20 e 60 barre.
Se i dati di big mancano o cambiano formato il workflow fallisce (GitHub ti avvisa per email), la pagina mostra l'ultimo calcolo valido con un avviso rosso.

## Parametri
Tutti in cima a `scripts/agente.py`: orizzonte della classifica, finestra dei segnali, confluenza minima, minimo di segnali storici del sistema di riferimento (`MIN_SEGNALI_STORICI`, ora 15), famiglie, soglie di vecchiaia dei dati.
