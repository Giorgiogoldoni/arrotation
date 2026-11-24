"""Importa i flussi ETF effettivi pubblicati da ETFIQ.
I flussi giornalieri sono calcolati da variazioni delle quote in circolazione x NAV,
non da prezzo/volume. La copertura è USA-listed e non rappresenta l'intero mercato UCITS.
"""
import datetime as dt
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
URL = "https://etfiq.com/data/flows/daily/latest.json"
UA = "ARRotation/1.0 (ETFIQ attribution: https://etfiq.com/flows/)"

def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))

def clean_rows(rows):
    return [r for r in rows if isinstance(r, dict)]

def main():
    DATA.mkdir(exist_ok=True)
    raw = fetch()
    if raw.get("schemaVersion") != 1 or raw.get("basis") != "daily":
        raise RuntimeError("Schema ETFIQ inatteso: nessun dato aggiornato pubblicato")
    funds = clean_rows(raw.get("funds", []))
    # Non sommare i fondi trattenuti per revisione o senza flusso verificato.
    valid = [r for r in funds if not r.get("held") and r.get("status") == "ok" and isinstance(r.get("flowUsd"), (int, float))]
    themes = {}
    for row in valid:
        theme = row.get("theme")
        if not theme:
            continue
        g = themes.setdefault(theme, {"name": theme, "funds": 0, "flowUsd": 0, "roundTripUsd": 0, "tickers": []})
        g["funds"] += 1
        g["flowUsd"] += row["flowUsd"]
        g["roundTripUsd"] += row.get("roundTripUsd") or 0
        if len(g["tickers"]) < 8:
            g["tickers"].append(row.get("ticker"))
    theme_rows = sorted(themes.values(), key=lambda x: x["flowUsd"], reverse=True)
    # Paesi/regioni: solo strumenti con esposizione geografica riconoscibile dal nome.
    geo_terms = {
        "Cina": ["china", "chinese", "hang seng", "csi 300"],
        "Giappone": ["japan", "japanese", "nikkei", "topix"],
        "India": ["india", "indian", "nifty"],
        "Europa": ["europe", "european", "euro stoxx", "stoxx europe"],
        "Regno Unito": ["united kingdom", "uk equity", "ftse 100"],
        "Germania": ["germany", "dax"],
        "Francia": ["france", "cac 40"],
        "Italia": ["italy", "italian"],
        "Brasile": ["brazil", "brazilian", "bovespa"],
        "Messico": ["mexico", "mexican"],
        "Corea del Sud": ["south korea", "korea", "kospi"],
        "Taiwan": ["taiwan"],
    }
    geos = {}
    for row in valid:
        name = str(row.get("name") or "").lower()
        for label, terms in geo_terms.items():
            if any(term in name for term in terms):
                g = geos.setdefault(label, {"name": label, "funds": 0, "flowUsd": 0, "tickers": []})
                g["funds"] += 1
                g["flowUsd"] += row["flowUsd"]
                if len(g["tickers"]) < 8:
                    g["tickers"].append(row.get("ticker"))
                break
    result = {
        "source": "ETFIQ",
        "source_url": "https://etfiq.com/flows/",
        "data_url": URL,
        "methodology_url": "https://etfiq.com/methodology/flows",
        "license_note": "Dati calcolati da ETFIQ, riutilizzati con attribuzione. Dati as of nel file sorgente.",
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "asOf": raw.get("asOf"),
        "basis": "daily",
        "coverage": {
            "funds_published": raw.get("fundsPublished"),
            "funds_not_read": raw.get("fundsNotRead"),
            "funds_with_daily_flow": raw.get("total", {}).get("funds"),
            "held_funds": raw.get("total", {}).get("heldFunds"),
            "funds_valid_rows": len(valid)
        },
        "total": raw.get("total", {}),
        "categories": clean_rows(raw.get("categories", [])),
        "issuers": clean_rows(raw.get("issuers", [])),
        "themes": theme_rows,
        "geographies": sorted(geos.values(), key=lambda x: x["flowUsd"], reverse=True),
        "top_inflows": sorted(valid, key=lambda x: x["flowUsd"], reverse=True)[:15],
        "top_outflows": sorted(valid, key=lambda x: x["flowUsd"])[:15],
        "round_trip_note": "flowUsd include i round trip segnalati separatamente in roundTripUsd. Mostrare entrambi; non sottrarre il secondo senza seguire la metodologia ETFIQ.",
        "limitations": "Flussi ETF giornalieri USA-listed; non coprono l'intero universo UCITS europeo. I flussi misurano creazioni/rimborsi nette degli ETF, non l'identità o la direzione di ogni investitore."
    }
    target = DATA / "flows.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)
    print("ETFIQ flows:", result["asOf"], "| valid fund rows", len(valid), "| categories", len(result["categories"]), "| issuers", len(result["issuers"]), "| themes", len(theme_rows))

if __name__ == "__main__":
    main()
