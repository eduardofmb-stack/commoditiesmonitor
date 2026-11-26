#!/usr/bin/env python3
"""Coleta diária de preços para o Monitor de Commodities (Arar Capital).
Grava CSVs em data/ e um data/status.json dizendo o que funcionou.
Cada fonte roda isolada: a falha de uma não derruba as outras.
Fontes: Yahoo Finance (futuros CBOT e ICE por contrato e série contínua),
Banco Central (PTAX venda, série SGS 1) e CFTC (posição dos fundos)."""
import csv, datetime as dt, json, os, time, urllib.parse, urllib.request

HOJE = dt.date.today()
OUT = "data"
UA = {"User-Agent": "Mozilla/5.0 (monitor-commodities)"}
MES = {"F": "Jan", "G": "Fev", "H": "Mar", "J": "Abr", "K": "Mai", "M": "Jun",
       "N": "Jul", "Q": "Ago", "U": "Set", "V": "Out", "X": "Nov", "Z": "Dez"}
NUM = {c: i + 1 for i, c in enumerate("FGHJKMNQUVXZ")}
PRODUTOS = {  # raiz, sufixo Yahoo, meses negociados, quantos vencimentos gravar
    "Soja": ("ZS", "CBT", "FHKNQUX", 6),
    "Milho": ("ZC", "CBT", "HKNUZ", 5),
    "Algodão": ("CT", "NYB", "HKNVZ", 5),
}
CONTINUO = {"Soja": "ZS=F", "Milho": "ZC=F", "Algodão": "CT=F"}
CFTC = {"Soja": "005602", "Milho": "002602", "Algodão": "033661"}

def baixar(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))

def yahoo(simbolo, periodo):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(simbolo)
           + "?range=" + periodo + "&interval=1d")
    res = baixar(url)["chart"]["result"][0]
    datas = res.get("timestamp") or []
    fech = res["indicators"]["quote"][0]["close"]
    linhas = []
    for t, c in zip(datas, fech):
        if c is not None:
            linhas.append((dt.datetime.utcfromtimestamp(t).date().isoformat(), round(c, 4)))
    return linhas

def proximos(meses, n):
    """Próximos n vencimentos a partir do mês atual."""
    lista, ano = [], HOJE.year
    while len(lista) < n:
        for c in meses:
            if (ano, NUM[c]) >= (HOJE.year, HOJE.month) and len(lista) < n:
                lista.append((c, ano))
        ano += 1
    return lista

def gravar(nome, cabecalho, linhas):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, nome), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cabecalho)
        w.writerows(linhas)

def futuros():
    linhas, falhas = [], []
    for produto, (raiz, bolsa, meses, n) in PRODUTOS.items():
        for cod, ano in proximos(meses, n):
            simbolo = "%s%s%02d.%s" % (raiz, cod, ano % 100, bolsa)
            contrato = "%s/%02d" % (MES[cod], ano % 100)
            try:
                for d, c in yahoo(simbolo, "1y"):
                    linhas.append((d, produto, contrato, simbolo, c))
            except Exception as e:
                falhas.append("%s: %s" % (simbolo, e))
            time.sleep(1)
    gravar("futuros.csv", ["data", "produto", "contrato", "simbolo", "fechamento"], sorted(linhas))
    return len(linhas), falhas

def continuo():
    linhas, falhas = [], []
    for produto, simbolo in CONTINUO.items():
        try:
            for d, c in yahoo(simbolo, "10y"):
                linhas.append((d, produto, simbolo, c))
        except Exception as e:
            falhas.append("%s: %s" % (simbolo, e))
        time.sleep(1)
    gravar("continuo.csv", ["data", "produto", "simbolo", "fechamento"], sorted(linhas))
    return len(linhas), falhas

def ptax():
    ini = (HOJE - dt.timedelta(days=3650)).strftime("%d/%m/%Y")
    fim = HOJE.strftime("%d/%m/%Y")
    url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?formato=json&dataInicial=%s&dataFinal=%s"
           % (ini, fim))
    linhas = []
    for r in baixar(url):
        d = dt.datetime.strptime(r["data"], "%d/%m/%Y").date().isoformat()
        linhas.append((d, float(r["valor"])))
    gravar("dolar_ptax.csv", ["data", "ptax_venda"], linhas)
    return len(linhas), []

def cftc():
    linhas, falhas = [], []
    for produto, codigo in CFTC.items():
        q = urllib.parse.urlencode({"cftc_contract_market_code": codigo,
                                    "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "260"})
        try:
            for r in baixar("https://publicreporting.cftc.gov/resource/72hh-3qpy.json?" + q):
                comprado = int(float(r["m_money_positions_long_all"]))
                vendido = int(float(r["m_money_positions_short_all"]))
                linhas.append((r["report_date_as_yyyy_mm_dd"][:10], produto, comprado, vendido, comprado - vendido))
        except Exception as e:
            falhas.append("%s: %s" % (produto, e))
    gravar("cftc.csv", ["data", "produto", "fundos_comprado", "fundos_vendido", "fundos_liquido"], sorted(linhas))
    return len(linhas), falhas

if __name__ == "__main__":
    status = {"rodou_em_utc": dt.datetime.utcnow().isoformat(timespec="seconds"), "fontes": {}}
    for nome, fn in [("futuros", futuros), ("continuo", continuo), ("ptax", ptax), ("cftc", cftc)]:
        try:
            n, falhas = fn()
            status["fontes"][nome] = {"linhas": n, "falhas": falhas}
        except Exception as e:
            status["fontes"][nome] = {"linhas": 0, "falhas": [str(e)]}
    os.makedirs(OUT, exist_ok=True)
    json.dump(status, open(os.path.join(OUT, "status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(status, ensure_ascii=False, indent=1))
