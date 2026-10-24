import copy
import json
import math
import pathlib
import datetime as dt

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Gestor de Carteira v6.1", page_icon="📈", layout="wide")
ARQ = pathlib.Path("carteira.json")


class NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (dt.date, dt.datetime)):
            return o.isoformat()
        return super().default(o)


def brl(x):
    if x is None or pd.isna(x):
        return "—"
    return "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


FALLBACK_MESES = {'Energia': [5, 8, 11, 12], 'Financeiro': [3, 6, 9, 12], 'Seguros': [4, 8, 11],
                  'Saneamento': [6, 12], 'Indústria': [3, 8, 11], 'Tecnologia': [4, 10]}


def _a(nome, tipo, setor, meta, qtd, pm, prov, lpa, vpa):
    return dict(nome=nome, tipo=tipo, setor=setor, meta_pct=meta, qtd=qtd, pm=pm,
                est_prov=prov, lpa=lpa, vpa=vpa)


BASE = {
    'TAEE3.SA': _a('Taesa ON', 'Ação', 'Energia', 10.0, 0, 0.0, 1.15, 1.20, 7.50),
    'TAEE4.SA': _a('Taesa PN', 'Ação', 'Energia', 0.0, 8, 14.64, 1.15, 1.20, 7.50),
    'BBAS3.SA': _a('Banco do Brasil', 'Ação', 'Financeiro', 12.0, 0, 0.0, 2.40, 6.20, 33.10),
    'ITUB4.SA': _a('Itaú Unibanco', 'Ação', 'Financeiro', 10.0, 0, 0.0, 2.10, 3.80, 21.50),
    'BBSE3.SA': _a('BB Seguridade', 'Ação', 'Seguros', 10.0, 0, 0.0, 2.60, 3.90, 5.80),
    'SAPR4.SA': _a('Sanepar PN', 'Ação', 'Saneamento', 8.0, 0, 0.0, 0.38, 1.00, 6.20),
    'CSMG3.SA': _a('Copasa', 'Ação', 'Saneamento', 5.0, 0, 0.0, 1.80, 3.10, 26.00),
    'SBSP3.SA': _a('Sabesp', 'Ação', 'Saneamento', 5.0, 0, 0.0, 2.50, 5.20, 48.00),
    'LWSA3.SA': _a('Locaweb', 'Ação', 'Tecnologia', 2.0, 6, 4.96, 0.05, 0.15, 3.20),
    'POMO4.SA': _a('Marcopolo PN', 'Ação', 'Indústria', 3.0, 0, 0.0, 0.40, 0.85, 4.10),
    'INBR34.SA': _a('Inter & Co', 'BDR', 'Financeiro', 5.0, 0, 0.0, 0.80, 1.10, 12.00),
    'MXRF11.SA': _a('Maxi Renda FII', 'FII', 'FII Papel', 6.0, 0, 0.0, 1.10, 0, 10.00),
    'HGLG11.SA': _a('CSHG Logística', 'FII', 'FII Logística', 8.0, 0, 0.0, 13.20, 0, 155.00),
    'KNRI11.SA': _a('Kinea Renda', 'FII', 'FII Misto', 5.0, 0, 0.0, 12.00, 0, 160.00),
    'KNCR11.SA': _a('Kinea Rendim.', 'FII', 'FII Papel', 6.0, 0, 0.0, 12.50, 0, 101.00),
    'HGBS11.SA': _a('Hedge Shopping', 'FII', 'FII Shopping', 5.0, 0, 0.0, 18.00, 0, 220.00),
}


# ---------------------------------------------------------------- PERSISTÊNCIA
def normalizar(d):
    if not isinstance(d, dict) or "carteira" not in d:
        raise ValueError("arquivo sem a chave 'carteira'")
    d.setdefault("reserva", 0.0)
    d.setdefault("historico", [])
    d.setdefault("proventos", [])
    d.setdefault("sobra", 0.0)
    return d


def carregar():
    if ARQ.exists():
        try:
            return normalizar(json.loads(ARQ.read_text(encoding="utf-8")))
        except Exception:
            st.warning("carteira.json ilegível, usando dados base.")
    return normalizar({"carteira": copy.deepcopy(BASE), "reserva": 338.64})


def salvar():
    st.session_state.sujo = True
    try:
        ARQ.write_text(json.dumps(st.session_state.dados, cls=NpEncoder, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except Exception:
        pass


if "dados" not in st.session_state:
    st.session_state.dados = carregar()
D = st.session_state.dados


def registrar(t, q, p):
    a = D["carteira"][t]
    nova = a["qtd"] + q
    a["pm"] = (a["qtd"] * a["pm"] + q * p) / nova
    a["qtd"] = nova
    D["historico"].append({"data": dt.date.today().isoformat(), "ativo": t.replace(".SA", ""),
                           "qtd": int(q), "preco": float(p)})


def desfazer(i):
    h = D["historico"].pop(i)
    a = D["carteira"].get(h["ativo"] + ".SA")
    if a:
        nq = a["qtd"] - h["qtd"]
        custo = a["qtd"] * a["pm"] - h["qtd"] * h["preco"]
        a["qtd"], a["pm"] = max(nq, 0), (custo / nq if nq > 0 else 0.0)


# ---------------------------------------------------------------- DADOS DE MERCADO
@st.cache_data(ttl=900)
def obter_cotacoes(tickers):
    try:
        d = yf.download(list(tickers), period="5d", progress=False, auto_adjust=False)["Close"]
    except Exception:
        return {}
    out = {}
    for t in tickers:
        try:
            s = d[t].dropna()
            if len(s) and s.iloc[-1] > 0:
                out[t] = float(s.iloc[-1])
        except Exception:
            pass
    return out


@st.cache_data(ttl=86400)
def prov_por_mes(t):
    """Proventos por ação dos últimos 12 meses, agrupados por mês (data-com do Yahoo)."""
    try:
        d = yf.Ticker(t).dividends
        d.index = d.index.tz_localize(None)
        d = d[d.index >= pd.Timestamp.now() - pd.DateOffset(years=1)]
        return {int(k): float(v) for k, v in d.groupby(d.index.month).sum().items()} if len(d) else None
    except Exception:
        return None


cotacoes = obter_cotacoes(tuple(D["carteira"].keys()))

# ---------------------------------------------------------------- SIDEBAR
sb = st.sidebar
sb.header("⚙️ Parâmetros do Aporte")
aporte = sb.number_input("Aporte do mês (R$)", min_value=0.0, value=300.0, step=50.0)
D["sobra"] = sb.number_input("Sobra de aportes anteriores (R$)", min_value=0.0,
                             value=float(D["sobra"]), step=1.0)
D["reserva"] = sb.number_input("Reserva em caixa (R$)", min_value=0.0, value=float(D["reserva"]), step=50.0)
disp = aporte + D["sobra"]
taxa_bazin = sb.slider("Taxa Bazin (%)", 4.0, 14.0, 6.0, 0.5,
                       help="Com Selic alta, 6% deixa o teto permissivo. Teste 8–10%.") / 100
modo = sb.selectbox("Filtro de valuation", ["Bazin + Graham", "Só Bazin", "Sem filtro"])
pvp_max = sb.slider("P/VP máximo p/ FIIs", 0.70, 1.30, 1.05, 0.01)
max_ativos = sb.slider("Máx. ativos por aporte", 1, 6, 3)
teto_setor = sb.slider("Alerta: teto por setor (%)", 10, 60, 35)
teto_ativo = sb.slider("Alerta: teto por empresa (%)", 5, 30, 15)
if sb.button("🔄 Atualizar cotações"):
    obter_cotacoes.clear()
    st.rerun()

sb.markdown("---")
sb.header("✏️ Registrar compra manual")
tick_sel = sb.selectbox("Ativo", [t.replace(".SA", "") for t in D["carteira"]])
cot_sel = cotacoes.get(f"{tick_sel}.SA", 10.0)
qtd_add = sb.number_input("Quantidade", min_value=1, value=1)
preco_pago = sb.number_input("Preço pago (R$)", min_value=0.01, value=round(cot_sel, 2), key=f"pp_{tick_sel}")
if sb.button("Registrar compra"):
    registrar(f"{tick_sel}.SA", qtd_add, preco_pago)
    salvar()
    st.session_state.msg = f"Compra de {qtd_add}x {tick_sel} registrada."
    st.rerun()

sb.markdown("---")
sb.header("💾 Backup")
if st.session_state.get("sujo"):
    sb.warning("Há mudanças sem backup. No Streamlit Cloud o disco é apagado quando o app reinicia!")


def _backup_feito():
    st.session_state.sujo = False


sb.download_button("📥 Baixar carteira.json", data=json.dumps(D, cls=NpEncoder, ensure_ascii=False, indent=2),
                   file_name="carteira.json", mime="application/json", on_click=_backup_feito)
up = sb.file_uploader("📤 Restaurar carteira.json", type=["json"])
if up is not None and st.session_state.get("ultimo_upload") != up.file_id:
    try:
        st.session_state.dados = normalizar(json.load(up))
        st.session_state.ultimo_upload = up.file_id
        salvar()
        st.session_state.sujo = False
        st.session_state.msg = "Carteira restaurada!"
        st.rerun()
    except Exception as e:
        sb.error(f"Arquivo inválido: {e}")
        st.session_state.ultimo_upload = up.file_id

if "msg" in st.session_state:
    st.toast(st.session_state.pop("msg"), icon="✅")

# ---------------------------------------------------------------- DATAFRAME
df = pd.DataFrame.from_dict(D["carteira"], orient="index")
df["cotacao"] = df.index.map(cotacoes)
falhas = df.index[df["cotacao"].isna()].tolist()
if falhas:
    st.warning(f"⚠️ Sem cotação para {', '.join(falhas)}. Ficam fora do plano de compra.")
df["valor_total"] = df["qtd"] * df["cotacao"].fillna(df["pm"])
df["empresa"] = df["nome"].str.replace(r" (ON|PN)$", "", regex=True)
df["bazin"] = df["est_prov"] / taxa_bazin
df["graham"] = [math.sqrt(22.5 * r.lpa * r.vpa) if r.tipo != "FII" and r.lpa > 0 and r.vpa > 0 else np.nan
                for r in df.itertuples()]
df["pvp"] = np.where(df["vpa"] > 0, df["cotacao"] / df["vpa"], np.nan)
df["dy"] = df["est_prov"] / df["cotacao"] * 100
df["prov_mensal"] = df["est_prov"] / 12
df["num_magico"] = np.where(df["prov_mensal"] > 0, np.ceil(df["cotacao"] / df["prov_mensal"]), np.nan)
df["progresso"] = np.where(df["num_magico"] > 0, np.minimum(100, df["qtd"] / df["num_magico"] * 100), 0)


def elegivel(r):
    if pd.isna(r.cotacao):
        return False
    if modo == "Sem filtro":
        return True
    if r.tipo == "FII":
        return bool(pd.notna(r.pvp) and r.pvp <= pvp_max)
    ok = r.cotacao <= r.bazin
    if modo == "Bazin + Graham":
        ok = ok and pd.notna(r.graham) and r.cotacao <= r.graham
    return bool(ok)


df["elegivel"] = [elegivel(r) for r in df.itertuples()]
df["status"] = np.where(df["elegivel"], "🟢 Dentro do critério", "🔴 Fora do critério")

pat_ativos = df["valor_total"].sum()
base = pat_ativos + disp
df["valor_empresa"] = df.groupby("empresa")["valor_total"].transform("sum")
df["meta_empresa"] = df.groupby("empresa")["meta_pct"].transform("sum")
df["defasagem"] = np.maximum(0, base * df["meta_empresa"] / 100 - df["valor_empresa"])


def gerar_plano():
    el = df[(df["meta_pct"] > 0) & df["elegivel"] & (df["defasagem"] > 0)]
    el = el.sort_values("defasagem", ascending=False).head(max_ativos)
    gap, preco = el["defasagem"].to_dict(), el["cotacao"].to_dict()
    setor, empresa = el["setor"].to_dict(), el["empresa"].to_dict()
    set_val = df.groupby("setor")["valor_total"].sum().to_dict()
    emp_val = df.groupby("empresa")["valor_total"].sum().to_dict()
    compras, saldo = {}, disp
    while True:
        cand = [
            t for t in gap 
            if preco[t] <= saldo 
            and gap[t] >= preco[t] / 2
            and set_val.get(setor[t], 0) + preco[t] <= (teto_setor / 100) * base
            and emp_val.get(empresa[t], 0) + preco[t] <= (teto_ativo / 100) * base
        ]
        if not cand:
            break
        t = max(cand, key=lambda x: gap[x])
        compras[t] = compras.get(t, 0) + 1
        gap[t] -= preco[t]
        saldo -= preco[t]
        set_val[setor[t]] = set_val.get(setor[t], 0) + preco[t]
        emp_val[empresa[t]] = emp_val.get(empresa[t], 0) + preco[t]
    return compras, saldo


def alertas_concentracao():
    msgs = []
    sm = df.groupby("setor")["meta_pct"].sum()
    msgs += [f"Setor **{s}**: metas somam {v:.0f}% (teto {teto_setor}%)" for s, v in sm.items() if v > teto_setor]
    em = df.groupby("empresa")["meta_pct"].sum()
    msgs += [f"Empresa **{e}**: meta de {v:.0f}% (teto {teto_ativo}%)" for e, v in em.items() if v > teto_ativo]
    if pat_ativos > 0:
        sa = df.groupby("setor")["valor_total"].sum() / pat_ativos * 100
        msgs += [f"Setor **{s}** já é {v:.0f}% da carteira" for s, v in sa.items() if v > teto_setor]
    return msgs


# ---------------------------------------------------------------- KPIs
st.title("🚀 Gestor Inteligente de Carteira v6.1")
renda_anual = (df["qtd"] * df["est_prov"]).sum()
custo = (df["qtd"] * df["pm"]).sum()
k = st.columns(5)
k[0].metric("Ativos", brl(pat_ativos), f"{(pat_ativos / custo - 1) * 100:+.1f}% vs custo" if custo else None)
k[1].metric("Disponível p/ aporte", brl(disp))
k[2].metric("Patrimônio total", brl(pat_ativos + D["reserva"]))
k[3].metric("Renda mensal estimada", brl(renda_anual / 12))
k[4].metric("Yield on cost", f"{renda_anual / custo * 100:.1f}%" if custo else "—")

tabs = st.tabs(["🎯 Aporte", "💼 Carteira", "📊 Valuation", "🗓️ Calendário", "💰 Proventos",
                "🔥 FIRE", "❄️ Bola de Neve", "🧾 Histórico", "🎚️ Metas", "🤖 Copilot"])

# ---- APORTE
with tabs[0]:
    st.caption(f"Filtro: **{modo}** · máx. {max_ativos} ativos · defasagem por empresa (ON+PN somadas).")
    compras, saldo = gerar_plano()
    if compras:
        linhas = [{"Código": t.replace(".SA", ""), "Ativo": df.at[t, "nome"], "Setor": df.at[t, "setor"],
                   "Comprar": f"{q} un.", "Preço": brl(df.at[t, "cotacao"]),
                   "Total": brl(q * df.at[t, "cotacao"])} for t, q in compras.items()]
        st.dataframe(pd.DataFrame(linhas), hide_index=True
        
