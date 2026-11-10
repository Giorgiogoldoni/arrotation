"""arrotation: legge i dati pubblici di big, applica criteri fissi, tiene lo storico delle segnalazioni e misura gli esiti reali.
Nessuna AI, nessuna chiave. Non modifica big. E' uno screening, non una raccomandazione.
Scrive in data/: selezione.json, storico.json, regole_arrotation.pdf. Se i dati di big mancano o hanno cambiato formato,
mantiene l'ultima selezione valida, la marca come non aggiornata e termina con errore (il workflow risulta fallito)."""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITO_BIG = "https://giorgiogoldoni.github.io/big/"
BIG = os.environ.get("BIG_BASE", SITO_BIG + "data/").rstrip("/") + "/"
OGGI = dt.date.fromisoformat(os.environ["ARROTATION_OGGI"]) if os.environ.get("ARROTATION_OGGI") else dt.datetime.now(dt.timezone.utc).date()

# ---------------- Parametri (modificabili: PDF e pagina si aggiornano da soli) ----------------
ORIZZONTE_CLASSIFICA = "20"                 # orizzonte (barre) della classifica di big usato per il giudizio "affidabile"
FINESTRA_GG = 5                             # giorni di calendario, rispetto all'ultima barra dell'ETF
CONFLUENZA_MIN = 2                          # famiglie coerenti con un segnale nella finestra
MAX_VECCHIAIA_GG_LAV = 3                    # giorni lavorativi: oltre, i dati dell'ETF (o di big) sono considerati vecchi
MAX_VECCHIAIA_CLASSIFICA_GG = 9             # giorni di calendario: la classifica di big si aggiorna il sabato
ORIZZONTI_ESITO = (5, 10, 20, 60)           # barre dopo il segnale su cui si misura l'esito reale
CASO_AFFIDABILI_PCT = 2.0                   # % di "affidabili" attesa per solo caso a +20 barre (calibrazione dichiarata da big, 150 serie casuali)
MIN_SEGNALI_STORICI = 15                    # segnali storici minimi del sistema di riferimento su quell'ETF (da classifica di big): sotto, il giudizio "affidabile" poggia su troppo pochi casi
MIN_BASE = 30                               # osservazioni minime per la mediana di riferimento dell'ETF
SCADENZA_APERTE_GG = 400                    # segnalazioni mai risolte oltre questo limite passano in archivio
FAMIGLIE = {"Trend": ["core", "azb", "sbb", "psar", "adx", "ema"], "Momentum": ["mom"], "Indicatori": ["cd"]}
FAM_ESCLUSA = {"Inversione": ["inv", "mr", "smr"]}   # compra in controtendenza: non entra nella confluenza e non puo' essere il sistema di riferimento
SISTEMI_ATTESI = {i for f in (FAMIGLIE, FAM_ESCLUSA) for ids in f.values() for i in ids}
FAM_DI = {i: n for n, ids in FAMIGLIE.items() for i in ids}


def scarica(url, tentativi=3):
    ultimo = None
    for k in range(tentativi):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arrotation/1.0"})
            with urllib.request.urlopen(req, timeout=60) as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception as e:
            ultimo = e; time.sleep(3 * (k + 1))
    raise RuntimeError("%s: %s" % (url, repr(ultimo)[:120]))


def carica(p, default=None):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return default


def lav(a, b):
    """Giorni lavorativi tra due date ISO (0 se b precede a)."""
    try: return max(0, int(np.busday_count(np.datetime64(a[:10]), np.datetime64(b[:10]))))
    except Exception: return 10**6


def cal(a, b):
    return (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days


def data_gen(s):
    try: return dt.datetime.strptime(s, "%Y-%m-%d %H:%M UTC").date().isoformat()
    except Exception: return None


def valida(idx, sint):
    err, avv = [], []
    if not isinstance(idx, dict) or not isinstance(idx.get("righe"), list) or not idx["righe"]:
        return ["index.json di big: manca l'elenco righe o è vuoto"], avv
    for k in ("gen", "sistemi"):
        if k not in idx: err.append("index.json di big: manca il campo %s" % k)
    for r in idx["righe"][:100]:
        manc = [k for k in ("t", "s", "u", "sta", "lv", "inv", "p") if k not in r]
        if manc: err.append("index.json di big: campi mancanti nelle righe (%s)" % ", ".join(manc)); break
    if not isinstance(sint, dict) or not isinstance(sint.get("mig"), dict) or not sint["mig"]:
        err.append("classifica_sintesi.json di big: manca mig o è vuoto")
    else:
        v = next(iter(sint["mig"].values()))
        if not isinstance(v, dict) or ORIZZONTE_CLASSIFICA not in v: err.append("classifica_sintesi.json di big: manca l'orizzonte +%s barre" % ORIZZONTE_CLASSIFICA)
    if not err:
        ids = {s.get("id") for s in idx["sistemi"]}
        if ids != SISTEMI_ATTESI:
            avv.append("L'elenco dei sistemi di big è cambiato (nuovi: %s; spariti: %s): aggiornare le famiglie in scripts/agente.py. I sistemi non riconosciuti sono ignorati." % (sorted(ids - SISTEMI_ATTESI) or "-", sorted(SISTEMI_ATTESI - ids) or "-"))
    return err, avv


def seleziona(idx, sint, avvisi):
    nomi = {s["id"]: s for s in idx["sistemi"]}
    ori = ORIZZONTE_CLASSIFICA
    cand, uscite, sc = [], [], Counter()
    normali = misurabili = affidabili = 0
    for r in idx["righe"]:
        if r.get("lv") or r.get("inv"): sc["leva_inversi"] += 1; continue
        normali += 1
        m = (sint["mig"].get(r["t"]) or {}).get(ori)
        if m and m[1] in ("ok", "nv", "no"): misurabili += 1
        if m and m[1] == "ok": affidabili += 1
        vecchia = lav(r["u"], OGGI.isoformat()) > MAX_VECCHIAIA_GG_LAV
        sta = r.get("sta") or ["FUORI", None, None, None, 0]
        if sta[0] == "ESCI":
            if vecchia: sc["dati_vecchi"] += 1
            else: uscite.append(dict(t=r["t"], nome=r["n"], emittente=r["e"], ingresso=sta[2], uscita=sta[3], guadagno=sta[1], prezzo=r["p"], ultima_barra=r["u"]))
        if not (m and m[1] == "ok" and m[0]): continue
        sid = m[0]
        if sid not in FAM_DI: sc["sistema_inversione_o_ignoto"] += 1; continue
        if vecchia: sc["dati_vecchi"] += 1; continue
        d = r["s"].get(sid)
        if not d or cal(d, r["u"]) > FINESTRA_GG: continue
        fam = [n for n, ids in FAMIGLIE.items() if any(r["s"].get(i) and cal(r["s"][i], r["u"]) <= FINESTRA_GG for i in ids)]
        if len(fam) < CONFLUENZA_MIN: sc["confluenza_bassa"] += 1; continue
        if (m[3] or 0) < MIN_SEGNALI_STORICI: sc["storia_breve"] += 1; continue   # conta solo chi avrebbe superato tutti gli altri criteri
        cand.append(dict(t=r["t"], nome=r["n"], isin=r["i"], emittente=r["e"], tipo=r.get("tp"), borsa=r["b"], prezzo=r["p"], var=r["v"], ultima_barra=r["u"],
                         sistema=sid, sistema_nome=nomi.get(sid, {}).get("nome", sid), colore=nomi.get(sid, {}).get("colore", "#666"), data_segnale=d,
                         famiglie=fam, confluenza=len(fam), stato=sta[0], eccesso=m[2], n_segnali=m[3], positivi=m[4],
                         grafico=SITO_BIG + "grafico.html?t=" + urllib.parse.quote(r["t"])))
    cand.sort(key=lambda c: c["t"])                                   # ordine: confluenza alta, segnale piu' recente, poi ticker
    cand.sort(key=lambda c: c["data_segnale"], reverse=True)          # (non si ordina per eccesso storico: eviterebbe di premiare il caso)
    cand.sort(key=lambda c: c["confluenza"], reverse=True)
    uscite.sort(key=lambda u: (u["uscita"] or "", u["t"]), reverse=True)
    for u in uscite: u["grafico"] = SITO_BIG + "grafico.html?t=" + urllib.parse.quote(u["t"])
    riep = dict(etf_normali=normali, misurabili=misurabili, affidabili=affidabili, attesi_per_caso=round(misurabili * CASO_AFFIDABILI_PCT / 100, 1),
                candidati=len(cand), uscite=len(uscite), scartati=dict(sc))
    if normali and sc["dati_vecchi"] / normali > 0.30:
        avvisi.append("Più del 30% degli ETF ha l'ultima barra vecchia (oltre %d giorni lavorativi): possibile problema di download in big." % MAX_VECCHIAIA_GG_LAV)
    return cand, uscite, riep


def dal_segnale(cand):
    """Informazione, non criterio: variazione % dall'apertura della barra successiva al segnale (primo prezzo eseguibile) all'ultima chiusura
    del grafico di big. Stessa serie di prezzi per entrambi i punti. None se non calcolabile. Ritorna quanti grafici non erano scaricabili."""
    cache, falliti = {}, 0
    for c in cand:
        c["dal_segnale"] = None; c["dal_segnale_al"] = None
        t = c["t"]
        if t not in cache:
            try: cache[t] = scarica(BIG + "charts/" + t.replace(".", "_") + ".json")["d"]
            except Exception: cache[t] = None; falliti += 1
        d = cache[t]
        if not d: continue
        try:
            i = [x[0] for x in d].index(c["data_segnale"])
            if i + 1 >= len(d): continue                      # segnale sull'ultima barra: l'ingresso non c'e' ancora
            p0, p1 = d[i + 1][1], d[-1][4]
            if p0 and p0 > 0 and p1 and p1 > 0:
                c["dal_segnale"] = round((p1 / p0 - 1) * 100, 2); c["dal_segnale_al"] = d[-1][0]
        except (ValueError, IndexError, TypeError):
            pass
    return falliti


# ---------------- Storico ed esiti reali ----------------
def registra(storico, cand):
    noti = {e["k"] for e in storico["segnalazioni"]} | {c["k"] for c in storico["chiuse"]}
    nuove = 0
    for c in cand:
        k = "%s|%s|%s" % (c["t"], c["sistema"], c["data_segnale"])
        if k in noti: continue
        storico["segnalazioni"].append(dict(k=k, t=c["t"], nome=c["nome"], sistema=c["sistema"], sistema_nome=c["sistema_nome"], data_segnale=c["data_segnale"],
                                            registrata=OGGI.isoformat(), famiglie=c["famiglie"], confluenza=c["confluenza"],
                                            classifica=dict(orizzonte=ORIZZONTE_CLASSIFICA, eccesso=c["eccesso"], n=c["n_segnali"], positivi=c["positivi"]),
                                            ingresso=None, esiti={}))
        nuove += 1
    return nuove


def aggiorna_esiti(storico, avvisi):
    """Esito = chiusura N barre dopo il segnale rispetto all'apertura della barra successiva (primo prezzo eseguibile). Eccesso = esito meno la
    mediana dello stesso calcolo su tutte le barre dell'ETF nel grafico di big (ultimi 2 anni). Rendimenti lordi, costi ignorati."""
    cache, aperte = {}, []
    for e in storico["segnalazioni"]:
        t = e["t"]
        if t not in cache:
            try: cache[t] = scarica(BIG + "charts/" + t.replace(".", "_") + ".json")["d"]
            except Exception: cache[t] = None; avvisi.append("Grafico di big non disponibile per %s: esiti non aggiornati in questo giro." % t)
        d = cache[t]
        if d:
            try: i = [x[0] for x in d].index(e["data_segnale"])
            except ValueError: e["nota"] = "Barra del segnale non trovata nel grafico di big"; i = None
            if i is not None:
                e.pop("nota", None)
                if not e.get("ingresso") and i + 1 < len(d) and d[i + 1][1] and d[i + 1][1] > 0: e["ingresso"] = dict(data=d[i + 1][0], prezzo=d[i + 1][1])
                if e.get("ingresso"):
                    p0 = e["ingresso"]["prezzo"]
                    for N in ORIZZONTI_ESITO:
                        k = str(N)
                        if k in e["esiti"] or i + N >= len(d): continue
                        ret = d[i + N][4] / p0 - 1
                        base = [d[j + N][4] / d[j + 1][1] - 1 for j in range(len(d) - N) if d[j + 1][1] and d[j + 1][1] > 0]
                        b = float(np.median(base)) if len(base) >= MIN_BASE else None
                        e["esiti"][k] = dict(data=d[i + N][0], ret=round(ret * 100, 2), base=None if b is None else round(b * 100, 2), eccesso=None if b is None else round((ret - b) * 100, 2))
        completa = all(str(N) in e["esiti"] for N in ORIZZONTI_ESITO)
        scaduta = cal(e["registrata"], OGGI.isoformat()) > SCADENZA_APERTE_GG
        if completa or scaduta:
            storico["chiuse"].append(dict(k=e["k"], t=e["t"], sistema=e["sistema"], data_segnale=e["data_segnale"], completa=completa,
                                          ret={k: v["ret"] for k, v in e["esiti"].items()}, eccesso={k: v["eccesso"] for k, v in e["esiti"].items() if v["eccesso"] is not None}))
        else: aperte.append(e)
    storico["segnalazioni"] = aperte


def statistiche(storico):
    out = {}
    for N in ORIZZONTI_ESITO:
        k = str(N); rets, exs = [], []
        for e in storico["segnalazioni"]:
            x = e["esiti"].get(k)
            if x:
                rets.append(x["ret"])
                if x["eccesso"] is not None: exs.append(x["eccesso"])
        for c in storico["chiuse"]:
            if k in c["ret"]:
                rets.append(c["ret"][k])
                if k in c["eccesso"]: exs.append(c["eccesso"][k])
        med = lambda a: round(float(np.median(a)), 2) if a else None
        out[k] = dict(n=len(rets), positivi=round(100 * sum(1 for x in rets if x > 0) / len(rets)) if rets else None, mediana=med(rets), eccesso_mediano=med(exs))
    return out


# ---------------- PDF delle regole (generato dagli stessi parametri usati dalla selezione) ----------------
def testo_regole():
    fam = "; ".join("%s (%s)" % (n, ", ".join(ids)) for n, ids in FAMIGLIE.items())
    return [
        ("Cos'è e cosa non è", [
            "arrotation è uno screening automatico che legge i dati pubblici del repository big e applica criteri fissi. Non è una raccomandazione di investimento, non è consulenza e non tiene conto di obiettivi, costi, tasse o liquidità di nessun investitore. Le liste sono candidati da verificare.",
            "Nessuna intelligenza artificiale: stessi dati e stessi criteri producono sempre lo stesso risultato."]),
        ("Fonte dei dati", [
            "index.json (segnali, stato, prezzi) e classifica_sintesi.json (miglior sistema per ETF) di big, più i grafici giornalieri di big per misurare gli esiti. Se i dati mancano o cambiano formato, la pagina mostra l'ultimo calcolo valido con un avviso e non presenta numeri come attuali."]),
        ("Criteri dei candidati (tutti obbligatori)", [
            "1. Solo ETF normali: esclusi leva e inversi (riconosciuti da big, la distinzione sugli inversi si basa sul nome e può sbagliare).",
            "2. Il miglior sistema dell'ETF nella classifica di big a +%s barre deve avere esito 'affidabile'. Il sistema non può appartenere alla famiglia Inversione (compra in controtendenza). Deve inoltre aver dato almeno %d segnali storici su quell'ETF: con meno, il giudizio 'affidabile' poggia su troppo pochi casi." % (ORIZZONTE_CLASSIFICA, MIN_SEGNALI_STORICI),
            "3. Quel sistema deve aver dato un segnale negli ultimi %d giorni di calendario rispetto all'ultima barra dell'ETF." % FINESTRA_GG,
            "4. Confluenza: almeno %d famiglie coerenti con un segnale nella stessa finestra. Famiglie contate: %s. Inversione non è contata." % (CONFLUENZA_MIN, fam),
            "5. Dati freschi: l'ultima barra dell'ETF non più vecchia di %d giorni lavorativi." % MAX_VECCHIAIA_GG_LAV,
            "Ordine della lista: confluenza, poi segnale più recente, poi ticker. Non si ordina per eccesso storico: premierebbe il caso. La lista può essere vuota: è un risultato valido.",
            "La colonna '% dal segnale' è solo informativa e non esclude nessun candidato: mostra di quanto è variato il prezzo dall'apertura della barra successiva al segnale (primo prezzo eseguibile) all'ultima chiusura disponibile. Un valore alto indica un ingresso già in ritardo. Non è calcolata (n.d.) se il segnale è sull'ultima barra o il grafico di big non è disponibile."]),
        ("Uscite recenti", [
            "ETF normali in stato ESCI secondo big: una posizione della famiglia Trend si è chiusa negli ultimi 5 giorni di calendario. Big non ha segnali short: ESCI significa solo che un sistema ha chiuso la sua posizione long, non è un invito a vendere."]),
        ("Storico ed esiti reali", [
            "Ogni candidato nuovo viene registrato con data e sistema (una sola volta). Per ogni segnalazione si misura, a %s barre dopo il segnale, la chiusura rispetto all'apertura della barra successiva al segnale (primo prezzo eseguibile). Rendimenti lordi, costi ignorati." % ", ".join(str(n) for n in ORIZZONTI_ESITO),
            "Eccesso = esito meno la mediana dello stesso calcolo su tutte le barre dell'ETF negli ultimi 2 anni di big. Le statistiche aggregate sono la sola misura fuori campione: valgono solo con molte segnalazioni e molti mesi di storia."]),
        ("Limiti noti", [
            "Il giudizio 'affidabile' di big si basa sulla stessa storia usata per scegliere il sistema, tra 11 sistemi per ETF: con migliaia di ETF alcuni risultano affidabili per solo caso. Per questo la pagina riporta quanti ne risultano e quanti se ne attenderebbero per caso (circa %.0f%% dei misurabili a +20 barre, stima grezza dalla calibrazione di big su 150 serie casuali)." % CASO_AFFIDABILI_PCT,
            "L'universo contiene solo ETF oggi quotati: i chiusi mancano e i risultati tendono a essere ottimistici. Nessun filtro di liquidità: un segnale su un ETF poco scambiato può non essere eseguibile. I volumi di Yahoo sugli ETF europei sono poco affidabili.",
            "Le segnalazioni registrate prima dell'introduzione del minimo di segnali storici restano nelle statistiche anche se non lo rispettano.",
            "Le posizioni di big usano finestre di dati diverse tra run giornaliero (2 anni) e classifica (5 anni). I rendimenti passati non sono una previsione."]),
        ("Aggiornamento", [
            "Lunedì-venerdì alle 20:30 UTC (dopo il run di big delle 17:30) e il sabato alle 11:00 UTC (dopo la classifica di big). Ogni file porta la data di generazione e la data dei dati di big."]),
    ]


def genera_pdf(path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except Exception as e:
        print("PDF non generato (reportlab mancante):", repr(e)[:80]); return False
    st = getSampleStyleSheet(); corpo = ParagraphStyle("c", parent=st["Normal"], fontSize=9.5, leading=13, spaceAfter=4)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm, title="arrotation - regole", author="arrotation")
    story = [Paragraph("arrotation - regole di selezione", st["Title"]), Paragraph("Generato il %s dai parametri in uso." % OGGI.isoformat(), corpo), Spacer(1, 8)]
    for tit, pars in testo_regole():
        story.append(Paragraph(escape(tit), st["Heading2"]))
        story += [Paragraph(escape(p), corpo) for p in pars]
    doc.build(story); return True


def scrivi_json(p, obj, compatto=True):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compatto else None, indent=None if compatto else 1), encoding="utf-8")


def esci_con_errore(prev, messaggi):
    out = prev if isinstance(prev, dict) else dict(candidati=[], uscite=[], riepilogo={}, statistiche={})
    out.update(stato="errore", generato=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), avvisi=messaggi + ["Le liste qui sotto sono l'ultimo calcolo valido e NON sono aggiornate."])
    scrivi_json(DATA / "selezione.json", out); genera_pdf(DATA / "regole_arrotation.pdf")
    print("ERRORE:", " | ".join(messaggi)); sys.exit(1)


def main():
    DATA.mkdir(exist_ok=True)
    prev = carica(DATA / "selezione.json")
    try:
        idx = scarica(BIG + "index.json"); sint = scarica(BIG + "classifica_sintesi.json")
    except Exception as e:
        esci_con_errore(prev, ["Impossibile leggere i dati di big: %s" % e])
    err, avvisi = valida(idx, sint)
    if err: esci_con_errore(prev, err)
    gen = data_gen(idx["gen"]); gen_c = data_gen(sint.get("gen", ""))
    stato = "ok"
    if gen is None or lav(gen, OGGI.isoformat()) > MAX_VECCHIAIA_GG_LAV:
        stato = "dati_vecchi"; avvisi.append("I dati di big sono vecchi (generati il %s): nessun candidato nuovo." % (idx["gen"]))
    if gen_c is None or cal(gen_c, OGGI.isoformat()) > MAX_VECCHIAIA_CLASSIFICA_GG:
        avvisi.append("La classifica dei sistemi di big non è recente (calcolata il %s): il giudizio 'affidabile' può essere superato." % sint.get("gen", "n.d."))
    cand, uscite, riep = seleziona(idx, sint, avvisi)
    if stato == "dati_vecchi": cand = []; riep["candidati"] = 0
    falliti = dal_segnale(cand)
    if falliti: avvisi.append("Variazione dal segnale non calcolata per alcuni candidati: grafico di big non scaricabile (%d)." % falliti)
    storico = carica(DATA / "storico.json") or {}
    storico.setdefault("segnalazioni", []); storico.setdefault("chiuse", []); storico["versione"] = 1
    nuove = registra(storico, cand)
    aggiorna_esiti(storico, avvisi)
    stat = statistiche(storico); storico["aggiornato"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    scrivi_json(DATA / "storico.json", storico, compatto=False)
    riep["nuove_segnalazioni"] = nuove; riep["segnalazioni_aperte"] = len(storico["segnalazioni"]); riep["segnalazioni_chiuse"] = len(storico["chiuse"])
    criteri = dict(orizzonte_classifica=int(ORIZZONTE_CLASSIFICA), finestra_gg=FINESTRA_GG, confluenza_min=CONFLUENZA_MIN, min_segnali_storici=MIN_SEGNALI_STORICI, max_vecchiaia_gg_lav=MAX_VECCHIAIA_GG_LAV, famiglie=FAMIGLIE, esclusa=FAM_ESCLUSA)
    scrivi_json(DATA / "selezione.json", dict(versione=1, stato=stato, generato=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), big_gen=idx["gen"], classifica_gen=sint.get("gen"),
                                              avvisi=avvisi, criteri=criteri, riepilogo=riep, candidati=cand, uscite=uscite, statistiche=stat))
    genera_pdf(DATA / "regole_arrotation.pdf")
    print("stato %s | candidati %d | uscite %d | nuove %d | aperte %d | chiuse %d | avvisi %d" % (stato, len(cand), len(uscite), nuove, len(storico["segnalazioni"]), len(storico["chiuse"]), len(avvisi)))


if __name__ == "__main__":
    main()
