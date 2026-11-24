"""ARRotation: misura la rotazione relativa usando i prezzi giornalieri pubblicati da BIG.
Non misura flussi monetari effettivi: BIG pubblica OHLC, non sottoscrizioni/rimborsi né AUM.
Produce un radar trasparente di forza relativa, ampiezza e accelerazione per aree, settori e asset class.
"""
import concurrent.futures as cf
import datetime as dt
import json
import statistics
import time
import urllib.request
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BIG = "https://giorgiogoldoni.github.io/big/data/"
UA = "ARRotation/2.0 (public ETF rotation monitor)"

# Tassonomia per parole chiave nei nomi ufficiali degli ETF. Le categorie sono proxy:
# non sono classificazioni ufficiali e un ETF può appartenere a più di una categoria.
REGIONS = {
    "USA": ["usa", "united states", "s&p 500", "s&p500", "nasdaq 100", "nasdaq-100", "russell 2000", "msci usa", "dow jones", "us equity", "u.s. equity"],
    "Europa": ["europe", "euro stoxx", "stoxx europe", "msci emu", "dax", "ftse 100", "cac 40", "msci france", "msci germany", "msci italy", "msci spain", "msci switzerland", "uk equity", "eurozone"],
    "Cina": ["china", "msci china", "hang seng", "hscei", "csi 300", "china a"],
    "Giappone": ["japan", "msci japan", "nikkei", "topix"],
    "India": ["india", "msci india", "nifty", "sensex"],
    "Mercati emergenti": ["emerging markets", "em markets", "msci em ", "msci emerging", "em equity", "em ex"],
    "Azionario globale": ["world", "msci acwi", "acwi", "all country", "global equity", "global stock"],
}
SECTORS = {
    "Tecnologia": ["technology", "tech sector", "information technology", "digitalisation", "digitalization"],
    "Energia": ["energy", "oil & gas", "oil and gas"],
    "Finanziari": ["financial", "banks", "banking", "insurance"],
    "Salute": ["health care", "healthcare", "pharma"],
    "Industria": ["industrials", "industrial", "transport"],
    "Consumi ciclici": ["consumer discretionary", "consumer cyclical"],
    "Consumi difensivi": ["consumer staples", "consumer defensive"],
    "Comunicazioni": ["communication services", "telecommunications", "telecom", "media"],
    "Materiali": ["materials", "metals & mining", "mining", "basic resources"],
    "Utilities": ["utilities"],
    "Immobiliare": ["real estate", "property"],
}
THEMES = {
    "Semiconduttori": ["semiconductor", "semiconductors", "chip"],
    "Intelligenza artificiale": ["artificial intelligence", "machine learning"],
    "Cybersecurity": ["cybersecurity", "cyber security"],
    "Difesa": ["defence", "defense", "aerospace & defense", "aerospace and defense"],
    "Energia pulita": ["clean energy", "renewable energy", "solar energy", "wind energy"],
    "Robotica": ["robotics", "automation"],
    "Biotech": ["biotech", "biotechnology"],
    "Cloud": ["cloud computing", "cloud technology"],
    "Infrastrutture": ["infrastructure", "infrastructures"],
    "Acqua": ["water"],
    "Spazio": ["space exploration", "space economy"],
}

ASSETS = {
    "Obbligazionario": ("bond", ["bond", "bonds", "treasury", "government", "corporate", "high yield", "aggregate", "gilts"]),
    "Materie prime": ("commodity", ["commodity", "commodities", "broad basket", "natural resources"]),
    "Oro": (None, ["gold", "physical gold", "gold miners"]),
    "Cripto": ("crypto", ["bitcoin", "ethereum", "crypto", "blockchain"]),
}

def get_json(url, timeout=35):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def med(values):
    return round(statistics.median(values), 2) if values else None

def classify(row):
    name = str(row.get("n") or "").lower()
    ac = str(row.get("ac") or "").lower()
    found = []
    for label, words in REGIONS.items():
        if ac in ("equity", "stock", "stocks") and any(w in name for w in words):
            found.append(("Geografia", label))
    if ac in ("equity", "stock", "stocks"):
        for label, words in SECTORS.items():
            if any(w in name for w in words):
                found.append(("Settori", label))
        for label, words in THEMES.items():
            if any(w in name for w in words):
                found.append(("Temi", label))
    for label, (asset, words) in ASSETS.items():
        if (asset is None and any(w in name for w in words)) or (asset is not None and (ac == asset or any(w in name for w in words))):
            found.append(("Asset class", label))
    if ac in ("equity", "stock", "stocks") and not any(g == "Asset class" for g, _ in found):
        found.append(("Asset class", "Azionario"))
    return found

def load_chart(ticker):
    url = BIG + "charts/" + ticker.replace(".", "_") + ".json"
    try:
        obj = get_json(url)
        bars = obj.get("d") or []
        closes = [float(x[4]) for x in bars if isinstance(x, list) and len(x) >= 5 and x[4] not in (None, 0)]
        dates = [x[0] for x in bars if isinstance(x, list) and len(x) >= 5 and x[4] not in (None, 0)]
        if len(closes) < 61:
            return ticker, None
        last = closes[-1]
        ret = {n: (last / closes[-1-n] - 1) * 100 for n in (5, 20, 60)}
        return ticker, {"date": dates[-1], "ret": ret}
    except Exception:
        return ticker, None


def market_of(row):
    """Mercato di quotazione; UCITS Europa richiede anche ISIN con domicilio riconosciuto."""
    exchange = str(row.get("b") or "").strip().lower().replace(" ", "")
    ticker = str(row.get("t") or "").upper()
    isin = str(row.get("i") or "").upper()
    us_codes = ("nyse", "nasdaq", "arca", "arcx", "bats", "cboe", "amex", "nysearca", "xnas", "xnys")
    eu_codes = ("mil", "milan", "borsaitaliana", "xmil", "xetra", "xetr", "frankfurt", "gettex", "london", "lse", "xlon", "euronext", "paris", "xpar", "amsterdam", "xams", "brussels", "xbru", "lisbon", "xlis", "madrid", "xmad", "swiss", "six", "zurich", "xswx", "stockholm", "xsto", "oslo", "xosl", "copenhagen", "xcse", "helsinki", "xhel", "vienna", "xvie", "dublin", "xdub", "stuttgart", "tradegate", "borsa")
    if any(code in exchange for code in us_codes):
        return "USA"
    suffix = ticker.rsplit(".", 1)[-1] if "." in ticker else ""
    eu_suffixes = {"MI", "DE", "AS", "PA", "L", "SW", "MC", "BR", "ST", "OL", "CO", "HE", "IR", "VI", "F", "SG", "BE", "DU", "HM", "HA", "ETR", "MU", "PR", "AT", "LS"}
    is_eu_venue = any(code in exchange for code in eu_codes) or suffix in eu_suffixes
    ucits_domiciles = {"IE", "LU", "DE", "FR", "NL", "BE", "ES", "IT", "SE", "DK", "FI", "AT", "PT", "PL", "CZ", "HU", "GR", "RO", "SK", "SI", "BG", "HR", "LT", "LV", "EE", "MT", "CY", "GB"}
    if is_eu_venue and len(isin) == 12 and isin[:2] in ucits_domiciles:
        return "UCITS Europa"
    return None

def main():
    DATA.mkdir(exist_ok=True)
    previous = DATA / "rotation.json"
    try:
        idx = get_json(BIG + "index.json")
        rows = idx.get("righe") or []
        if not rows:
            raise RuntimeError("BIG index.json senza righe")
        eligible = [r for r in rows if not r.get("lv") and not r.get("inv")]
        groups = defaultdict(set)
        ticker_rows = {}
        for r in eligible:
            ticker = r.get("t")
            if not ticker:
                continue
            cats = classify(r)
            if not cats:
                continue
            ticker_rows[ticker] = r
            for group, category in cats:
                groups[(group, category)].add(ticker)

        tickers = sorted({t for members in groups.values() for t in members})
        cache = {}
        with cf.ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(load_chart, t) for t in tickers]
            for future in cf.as_completed(futures):
                t, value = future.result()
                if value:
                    cache[t] = value

        equity = [r for r in eligible if str(r.get("ac") or "").lower() in ("equity", "stock", "stocks") and r.get("t") in cache]
        benchmark = {n: med([cache[r["t"]]["ret"][n] for r in equity]) for n in (5, 20, 60)}
        out = []
        for (group, category), members in groups.items():
            valid = [cache[t] for t in members if t in cache]
            if len(valid) < 3:
                continue
            returns = {n: [x["ret"][n] for x in valid] for n in (5, 20, 60)}
            breadth = round(100 * sum(1 for x in returns[20] if x > 0) / len(valid), 1)
            r5, r20, r60 = med(returns[5]), med(returns[20]), med(returns[60])
            rel20 = round(r20 - benchmark[20], 2) if benchmark[20] is not None else None
            rel60 = round(r60 - benchmark[60], 2) if benchmark[60] is not None else None
            acceleration = round(r20 - r60 / 3, 2) if r20 is not None and r60 is not None else None
            # Score di rotazione: forza relativa, conferma a 60 barre, accelerazione e ampiezza.
            score = round(0.40 * (rel20 or 0) + 0.25 * (rel60 or 0) + 0.20 * (acceleration or 0) + 0.10 * ((breadth - 50) / 5), 2)
            if rel20 is not None and rel20 > 0 and breadth >= 60 and (acceleration or 0) > 0:
                status = "Forza diffusa"
            elif (acceleration or 0) > 0 and breadth >= 50:
                status = "In miglioramento"
            elif rel20 is not None and rel20 < 0 and breadth < 40:
                status = "Perdita di forza"
            else:
                status = "Neutrale"
            dates = [cache[t]["date"] for t in members if t in cache]
            out.append({
                "group": group, "category": category, "n": len(valid), "coverage": round(100 * len(valid) / len(members), 1),
                "date": max(dates) if dates else None, "ret5": r5, "ret20": r20, "ret60": r60,
                "benchmark20": benchmark[20], "benchmark60": benchmark[60], "rel20": rel20, "rel60": rel60,
                "breadth20": breadth, "acceleration": acceleration, "score": score, "status": status,
                "tickers": sorted([t for t in members if t in cache])[:12]
            })
        out.sort(key=lambda x: (x["score"], x["rel20"] or -999), reverse=True)
        # Due universi separati per mercato di quotazione: USA-listed e UCITS negoziati in Europa.
        market_groups = defaultdict(set)
        market_rows = defaultdict(dict)
        for r in eligible:
            market = market_of(r)
            ticker = r.get("t")
            if not market or not ticker or ticker not in cache:
                continue
            market_rows[market][ticker] = r
            for group, category in classify(r):
                market_groups[(market, group, category)].add(ticker)
        market_equity = defaultdict(list)
        for market, rows_by_ticker in market_rows.items():
            market_equity[market] = [cache[t]["ret"] for t, r in rows_by_ticker.items()
                if str(r.get("ac") or "").lower() in ("equity", "stock", "stocks") and t in cache]
        market_benchmarks = {m: {n: med([x[n] for x in vals]) for n in (5, 20, 60)}
            for m, vals in market_equity.items()}
        split_out = []
        for (market, group, category), members in market_groups.items():
            valid = [cache[t] for t in members if t in cache]
            if len(valid) < 3:
                continue
            returns = {n: [x["ret"][n] for x in valid] for n in (5, 20, 60)}
            breadth = round(100 * sum(1 for x in returns[20] if x > 0) / len(valid), 1)
            r5, r20, r60 = med(returns[5]), med(returns[20]), med(returns[60])
            bench = market_benchmarks.get(market, {})
            rel20 = round(r20 - bench[20], 2) if bench.get(20) is not None else None
            rel60 = round(r60 - bench[60], 2) if bench.get(60) is not None else None
            acceleration = round(r20 - r60 / 3, 2) if r20 is not None and r60 is not None else None
            score = round(0.40 * (rel20 or 0) + 0.25 * (rel60 or 0) + 0.20 * (acceleration or 0) + 0.10 * ((breadth - 50) / 5), 2)
            if rel20 is not None and rel20 > 0 and breadth >= 60 and (acceleration or 0) > 0:
                status = "Forza diffusa"
            elif (acceleration or 0) > 0 and breadth >= 50:
                status = "In miglioramento"
            elif rel20 is not None and rel20 < 0 and breadth < 40:
                status = "Perdita di forza"
            else:
                status = "Neutrale"
            dates = [cache[t]["date"] for t in members if t in cache]
            split_out.append({"market": market, "group": group, "category": category, "n": len(valid),
                "coverage": round(100 * len(valid) / len(members), 1), "date": max(dates) if dates else None,
                "ret5": r5, "ret20": r20, "ret60": r60, "benchmark20": bench.get(20), "benchmark60": bench.get(60),
                "rel20": rel20, "rel60": rel60, "breadth20": breadth, "acceleration": acceleration,
                "score": score, "status": status, "tickers": sorted(members)[:12]})
        split_out.sort(key=lambda x: (x["market"], x["score"]), reverse=False)
        market_coverage = {m: {"tickers": len(v), "equity": len(market_equity.get(m, []))} for m, v in market_rows.items()}
        data = {
            "version": 1, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "big_generated": idx.get("gen"), "latest_bar": max((x["date"] for x in cache.values()), default=None),
            "universe": len(rows), "eligible": len(eligible), "tickers_requested": len(tickers), "tickers_loaded": len(cache),
            "benchmark": benchmark, "actual_flows_available": False,
            "flow_note": "BIG pubblica prezzi OHLC e segnali, non flussi netti, sottoscrizioni/rimborsi o AUM. I valori sotto sono proxy di rotazione basati sui prezzi, non flussi monetari misurati.",
            "method": "Mediana dei rendimenti ETF per categoria su 5/20/60 sedute; forza relativa contro la mediana degli ETF azionari BIG; ampiezza = quota con rendimento positivo a 20 sedute; accelerazione = rendimento 20 sedute meno un terzo del rendimento 60 sedute.",
            "categories": out,
            "market_categories": split_out, "market_coverage": market_coverage,
            "market_method": "Mercato identificato dalla borsa dichiarata da BIG; suffissi ticker solo come fallback. USA e UCITS Europa sono classificati per sede di negoziazione, non per esposizione geografica. Benchmark calcolato separatamente in ciascun mercato."
        }
        tmp = previous.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(previous)
        print("rotation: universe", len(rows), "| eligible", len(eligible), "| charts", len(cache), "/", len(tickers), "| categories", len(out))
    except Exception as exc:
        if previous.exists():
            try:
                old = json.loads(previous.read_text(encoding="utf-8"))
                old["stale"] = True
                old["error"] = str(exc)[:300]
                previous.write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            except Exception:
                pass
        raise

if __name__ == "__main__":
    main()
