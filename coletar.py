#!/usr/bin/env python3
"""Coleta diária de preços para o Monitor de Commodities (Arar Capital).
Grava CSVs em data/ e um data/status.json dizendo o que funcionou.
Cada fonte roda isolada: a falha de uma não derruba as outras.
Fontes: Yahoo Finance (futuros CBOT e ICE por contrato e série contínua),
Banco Central (PTAX venda, série SGS 1), CFTC (posição dos fundos),
B3 (arquivo oficial de negócios consolidados: ajustes do boi gordo e do milho),
Cepea (widget oficial de indicadores), Sistema Faep (prêmios de Paranaguá e
dólar comercial, dados da CMA e da Econf) e AgRural (praças de soja e milho)."""
import csv, datetime as dt, html, json, os, re, time, urllib.parse, urllib.request

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


# ---------- arquivos prontos para o painel ----------
BOLSA = {"Soja": ("CBOT", "US¢/bu", 10), "Milho": ("CBOT", "US¢/bu", 10), "Algodão": ("ICE", "US¢/lb", 30)}
ATIVOS = {"Soja": ["Jan", "Mar", "Mai", "Jul", "Nov"], "Milho": ["Mar", "Mai", "Jul", "Dez"], "Algodão": ["Mar", "Mai", "Jul", "Dez"]}
MESNUM = {m: i + 1 for i, m in enumerate(["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"])}

def _ler(nome):
    with open(os.path.join(OUT, nome), encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _venc(contrato):
    m, a = contrato.split("/")
    return (2000 + int(a), MESNUM[m])

def _chave(*partes):
    t = "_".join(partes).lower()
    for a, b in zip("áàâãéêíóôõúç", "aaaaeeiooouc"):
        t = t.replace(a, b)
    return "".join(ch if ch.isalnum() else "_" for ch in t)

def montar():
    """Gera, a partir dos CSVs, os JSON no formato do painel."""
    fut = _ler("futuros.csv")
    por = {}
    for r in fut:
        por.setdefault((r["produto"], r["data"]), []).append(r)
    anterior = {}
    recente, hist = [], []
    datas = sorted({r["data"] for r in fut})
    ultimas = set(datas[-20:])
    for (produto, data) in sorted(por, key=lambda k: (k[1], k[0])):
        bolsa, unidade, folga = BOLSA[produto]
        linhas = sorted(por[(produto, data)], key=lambda r: _venc(r["contrato"]))
        d = dt.date.fromisoformat(data) + dt.timedelta(days=folga)
        principal = next((r["contrato"] for r in linhas
                          if r["contrato"].split("/")[0] in ATIVOS[produto] and _venc(r["contrato"]) > (d.year, d.month)), None)
        for n, r in enumerate(linhas):
            c = float(r["fechamento"])
            hist.append({"data": data, "produto": produto, "contrato": r["contrato"], "fechamento": c})
            ant = anterior.get((produto, r["contrato"]))
            anterior[(produto, r["contrato"])] = c
            if data in ultimas:
                recente.append({"chave": _chave(data, produto, r["contrato"]), "principal": 1 if r["contrato"] == principal else 0,
                                "data": data, "produto": produto, "bolsa": bolsa, "contrato": r["contrato"], "ordem": n + 1,
                                "fechamento": c, "unidade": unidade, "var_dia": None if ant is None else round(c - ant, 4),
                                "fonte": "Yahoo Finance (ajuste %s), coleta automática" % bolsa})
    corte = (HOJE - dt.timedelta(days=5 * 365)).isoformat()
    cont = [{"data": r["data"], "produto": r["produto"], "fechamento": float(r["fechamento"])} for r in _ler("continuo.csv") if r["data"] >= corte]
    cont += [{"data": r["data"], "produto": "Dólar PTAX", "fechamento": float(r["ptax_venda"])} for r in _ler("dolar_ptax.csv") if r["data"] >= corte]
    fundos = [{"chave": _chave(r["data"], r["produto"]), "data": r["data"], "produto": r["produto"], "comprado": int(r["fundos_comprado"]),
               "vendido": int(r["fundos_vendido"]), "liquido": int(r["fundos_liquido"])} for r in _ler("cftc.csv")]
    for nome, dados in [("painel_futuros_recente.json", recente), ("painel_historico_futuros.json", hist),
                        ("painel_historico_continuo.json", cont), ("painel_cftc.json", fundos)]:
        json.dump(dados, open(os.path.join(OUT, nome), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return {"futuros_recente": len(recente), "historico_futuros": len(hist), "historico_continuo": len(cont), "cftc": len(fundos)}


# ---------- fontes brasileiras ----------
BRT = dt.timezone(dt.timedelta(hours=-3))
HOJE_BR = dt.datetime.now(BRT).date()
MESPT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

def baixar_bytes(url, espera=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=espera) as r:
        return r.read()

def _num(t):
    t = t.replace("R$", "").replace("%", "").strip()
    if not t or t in "-–":
        return None
    return float(t.replace(".", "").replace(",", "."))

def _texto(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", " ", h, flags=re.S)))).strip()

def _tabelas(pagina):
    """Lista de (posição, linhas); cada linha é a lista de textos das células."""
    saida = []
    pagina = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), pagina, flags=re.S)
    for m in re.finditer(r"<table.*?</table>", pagina, flags=re.S | re.I):
        linhas = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), flags=re.S | re.I):
            cel = [_texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
            if cel:
                linhas.append(cel)
        saida.append((m.start(), linhas))
    return saida

def _acumular(nome, cabecalho, novas, nchave):
    """Junta as linhas novas ao CSV existente; a chave são as nchave primeiras colunas."""
    atual = {}
    caminho = os.path.join(OUT, nome)
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            leitor = csv.reader(f)
            if next(leitor, None) == cabecalho:
                for r in leitor:
                    atual[tuple(r[:nchave])] = r
    for r in novas:
        r = ["" if v is None else str(v) for v in r]
        atual[tuple(r[:nchave])] = r
    gravar(nome, cabecalho, [atual[k] for k in sorted(atual)])
    return len(atual)

def _data_ddmm(t):
    """'25/11' -> data mais recente com esse dia e mês que não esteja no futuro."""
    d, m = [int(x) for x in t.split("/")[:2]]
    data = dt.date(HOJE_BR.year, m, d)
    if data > HOJE_BR + dt.timedelta(days=2):
        data = dt.date(HOJE_BR.year - 1, m, d)
    return data

B3_PROD = {"BGI": "Boi gordo", "CCM": "Milho B3"}

def b3():
    """Ajustes do boi gordo e do milho no arquivo oficial de negócios consolidados da B3."""
    cab = ["data", "produto", "contrato", "simbolo", "ajuste", "ultimo", "variacao_pct", "negocios"]
    caminho = os.path.join(OUT, "b3_agro.csv")
    tem = set()
    if os.path.exists(caminho):
        tem = {r["data"] for r in _ler("b3_agro.csv")}
    dias = 40 if len(tem) < 20 else 8
    novas, falhas = [], []
    for k in range(dias, 0, -1):
        d = HOJE_BR - dt.timedelta(days=k)
        if d.weekday() >= 5 or (d.isoformat() in tem and k > 3):
            continue
        try:
            j = json.loads(baixar_bytes("https://arquivos.b3.com.br/api/download/requestname?fileName="
                                        "TradeInformationConsolidatedFile&date=%s&recaptchaToken=" % d.isoformat()))
            bruto = baixar_bytes("https://arquivos.b3.com.br/api/download/?token=" + j["token"], 300).decode("latin-1")
        except Exception as e:  # feriado ou arquivo ainda não publicado
            if k <= 3:
                falhas.append("%s: %s" % (d, e))
            continue
        linhas = bruto.splitlines()
        ini = next((i for i, l in enumerate(linhas) if l.startswith("RptDt;")), None)
        if ini is None:
            falhas.append("%s: cabeçalho não encontrado" % d)
            continue
        for r in csv.DictReader(linhas[ini:], delimiter=";"):
            s = r.get("TckrSymb") or ""
            if len(s) == 6 and s[:3] in B3_PROD and s[3] in MES and s[4:].isdigit() and r.get("SgmtNm") == "AGRIBUSINESS":
                aj = _num(r.get("AdjstdQt") or "")
                if aj is None:
                    continue
                novas.append([r["RptDt"], B3_PROD[s[:3]], "%s/%s" % (MES[s[3]], s[4:]), s, aj,
                              _num(r.get("LastPric") or ""), _num(r.get("OscnPctg") or ""), _num(r.get("TradQty") or "")])
        time.sleep(1)
    n = _acumular("b3_agro.csv", cab, novas, 4)
    return n, falhas

CEPEA_IDS = [2, 77, 12, 92, 54]  # boi gordo, milho, soja Paraná, soja Paranaguá, algodão
CEPEA_SERIES = [("paranagu", "soja_paranagua"), ("soja", "soja_parana"), ("milho", "milho_cepea"),
                ("algod", "algodao_cepea"), ("boi", "boi_cepea")]

def cepea():
    """Indicadores do Cepea pelo widget que o próprio Cepea oferece para sites de terceiros."""
    q = "fonte=arial&tamanho=10&largura=400px&corfundo=dbd6b2&cortexto=333333&corlinha=ede7bf"
    q += "".join("&id_indicador%5B%5D=" + str(i) for i in CEPEA_IDS)
    bruto = baixar_bytes("https://www.cepea.org.br/br/widgetproduto.js.php?" + q).decode("utf-8", "replace")
    bruto = bruto.replace("\\/", "/").replace('\\"', '"')
    novas, vistos = [], []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", bruto, flags=re.S | re.I):
        cel = [_texto(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(cel) < 3 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", cel[0]):
            continue
        nome = cel[1].lower()
        serie = next((s for k, s in CEPEA_SERIES if k in nome), None)
        valor = _num(cel[2])
        vistos.append(cel[1])
        if serie and valor is not None:
            novas.append([dt.datetime.strptime(cel[0], "%d/%m/%Y").date().isoformat(), serie, valor, cel[1]])
    falhas = []
    faltam = sorted({s for _, s in CEPEA_SERIES} - {r[1] for r in novas})
    if faltam:
        falhas.append("séries não encontradas: %s; nomes vistos: %s; início da resposta: %s"
                      % (", ".join(faltam), vistos, _texto(bruto)[:200]))
    n = _acumular("cepea.csv", ["data", "serie", "valor", "nome_cepea"], novas, 2)
    return n, falhas

def faep():
    """Prêmios da soja em Paranaguá (CMA) e dólar comercial (Econf), na página de cotações do Sistema Faep."""
    pagina = baixar_bytes("https://www.sistemafaep.org.br/cotacoes/").decode("utf-8", "replace")
    premios, cambio, falhas = [], [], []
    for pos, linhas in _tabelas(pagina):
        titulo = _texto(pagina[max(0, pos - 900):pos]).lower()
        cab = linhas[0]
        datas = [(i, _data_ddmm(c)) for i, c in enumerate(cab) if re.fullmatch(r"\d{2}/\d{2}", c)]
        datas = [(i, d) for i, d in datas if d < HOJE_BR]  # a coluna de hoje é parcial
        if not datas:
            continue
        for r in linhas[1:]:
            nome = r[0]
            for i, d in datas:
                v = _num(r[i]) if i < len(r) else None
                if v is None:
                    continue
                if "prêmio soja paranagu" in titulo[-160:]:
                    m = re.fullmatch(r"([A-Za-z]{3})\. ?(\d{2})", nome.strip())
                    if m and m.group(1).lower() in MESPT:
                        premios.append([d.isoformat(), "%s/%s" % (m.group(1).capitalize(), m.group(2)), round(v / 100, 4)])
                elif nome.lower().startswith("dolar comercial - venda"):
                    cambio.append([d.isoformat(), v])
    if not premios:
        falhas.append("tabela de prêmios não encontrada")
    if not cambio:
        falhas.append("dólar comercial não encontrado")
    n = _acumular("premios_paranagua.csv", ["data", "embarque", "premio_usd_bu"], premios, 2)
    n += _acumular("dolar_comercial.csv", ["data", "dolar_comercial_venda"], cambio, 1)
    return n, falhas

def agrural():
    """Retrato das praças de soja e milho (preço de compra, R$/sc) da AgRural."""
    pagina = baixar_bytes("https://agrural.com.br/precossojaemilho/").decode("utf-8", "replace")
    linhas_out, falhas = [], []
    for _, linhas in _tabelas(pagina):
        if len(linhas) < 3 or linhas[0][0].strip().upper() not in ("SOJA", "MILHO"):
            continue
        produto = linhas[0][0].strip().capitalize()
        m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{2})", linhas[0][-1].strip())
        meses = {"jan": 1, "feb": 2, "fev": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "mai": 5, "jun": 6, "jul": 7,
                 "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10, "out": 10, "nov": 11, "dec": 12, "dez": 12}
        if not m or m.group(2).lower() not in meses:
            falhas.append("%s: data não reconhecida (%s)" % (produto, linhas[0][-1]))
            continue
        data = dt.date(2000 + int(m.group(3)), meses[m.group(2).lower()], int(m.group(1))).isoformat()
        uf = ""
        for r in linhas[2:]:
            if len(r) >= 6 and len(r[0]) == 2:
                uf, r = r[0], r[1:]
            if len(r) >= 2 and _num(r[1]) is not None:
                linhas_out.append([data, produto, uf, r[0], _num(r[1])])
    if not linhas_out:
        falhas.append("tabelas não encontradas")
    else:
        gravar("pracas_agrural.csv", ["data", "produto", "uf", "praca", "preco_rs_sc"], linhas_out)
    return len(linhas_out), falhas

def montar_boi():
    """Boi gordo B3 no formato de precos_futuros: últimos 20 pregões, quatro primeiros vencimentos."""
    linhas = [r for r in _ler("b3_agro.csv") if r["produto"] == "Boi gordo"]
    datas = sorted({r["data"] for r in linhas})
    anterior, saida = {}, []
    for data in datas:
        dia = sorted([r for r in linhas if r["data"] == data], key=lambda r: _venc(r["contrato"]))
        d = dt.date.fromisoformat(data)
        principal = next((r["contrato"] for r in dia if _venc(r["contrato"]) > (d.year, d.month)), None)
        for n, r in enumerate(dia):
            c = float(r["ajuste"])
            ant = anterior.get(r["contrato"])
            anterior[r["contrato"]] = c
            if data in datas[-20:] and n < 4:
                saida.append({"chave": _chave(data, "boi gordo", r["contrato"]), "principal": 1 if r["contrato"] == principal else 0,
                              "data": data, "produto": "Boi gordo", "bolsa": "B3", "contrato": r["contrato"], "ordem": n + 1,
                              "fechamento": c, "unidade": "R$/@", "var_dia": None if ant is None else round(c - ant, 2),
                              "fonte": "B3 (preço de ajuste, arquivo de negócios consolidados), coleta automática"})
    json.dump(saida, open(os.path.join(OUT, "painel_boi_recente.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return len(saida)

if __name__ == "__main__":
    import sys
    if "--so-montar" in sys.argv:
        print(montar())
        sys.exit(0)
    status = {"rodou_em_utc": dt.datetime.utcnow().isoformat(timespec="seconds"), "fontes": {}}
    for nome, fn in [("futuros", futuros), ("continuo", continuo), ("ptax", ptax), ("cftc", cftc),
                     ("b3", b3), ("cepea", cepea), ("faep", faep), ("agrural", agrural)]:
        try:
            n, falhas = fn()
            status["fontes"][nome] = {"linhas": n, "falhas": falhas}
        except Exception as e:
            status["fontes"][nome] = {"linhas": 0, "falhas": [str(e)]}
    try:
        status["painel"] = montar()
    except Exception as e:
        status["painel"] = {"falha": str(e)}
    try:
        status["painel"]["boi_recente"] = montar_boi()
    except Exception as e:
        status["painel"]["boi_falha"] = str(e)
    os.makedirs(OUT, exist_ok=True)
    json.dump(status, open(os.path.join(OUT, "status.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(status, ensure_ascii=False, indent=1))
