import json
import math
import pathlib
import datetime as dt

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Gestor de Carteira v4.0", page_icon="📈", layout="wide")
ARQ = pathlib.Path("carteira.json")


def brl(x):
    if x is None or pd.isna(x):
        return "—"
    return "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- DADOS BASE
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


def carregar():
    if ARQ.exists():
        try:
            return json.loads(ARQ.read_text(encoding="utf-8"))
        except Exception:
            st.warning("carteira.json ilegível, usando dados base.")
    return {"carteira": BASE, "reserva": 338.64, "historico": []}


def salvar():
    ARQ.write_text(json.dumps(st.session_state.dados, ensure_ascii=False, indent=2), encoding="utf-8")


if "dados" not in st.session_state:
    st.session_state.dados = carregar()
D = st.session_state.dados


# ---------------------------------------------------------------- COTAÇÕES
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
def proventos_12m(t):
    try:
        d = yf.Ticker(t).dividends
        if d.empty:
            return None
        d.index = d.index.tz_localize(None)
        return float(d[d.index >= pd.Timestamp.now() - pd.DateOffset(years=1)].sum())
    except Exception:
        return None


cotacoes = obter_cotacoes(tuple(D["carteira"].keys()))

# ---------------------------------------------------------------- SIDEBAR
sb = st.sidebar
sb.header("⚙️ Parâmetros")
aporte = sb.number_input("Aporte do mês (R$)", min_value=0.0, value=300.0, step=50.0)
D["reserva"] = sb.number_input("Reserva em caixa (R$)", min_value=0.0, value=float(D["reserva"]), step=50.0)
taxa_bazin = sb.slider("Taxa Bazin (%)", 4.0, 14.0, 6.0, 0.5,
                       help="Com Selic alta, 6% deixa o teto muito permissivo. Teste 8–10%.") / 100
modo = sb.selectbox("Filtro de valuation", ["Bazin + Graham", "Só Bazin", "Sem filtro"])
pvp_max = sb.slider("P/VP máximo p/ FIIs", 0.70, 1.30, 1.05, 0.01)
max_ativos = sb.slider("Máx. ativos por aporte", 1, 6, 3)
teto_setor = sb.slider("Teto por setor (% da carteira)", 10, 60, 35)
meta_renda = sb.number_input("Meta de renda mensal (R$)", min_value=0.0, value=100.0, step=50.0)

sb.markdown("---")
sb.header("✏️ Registrar compra")
tick_sel = sb.selectbox("Ativo", [t.replace(".SA", "") for t in D["carteira"]])
cot_sel = cotacoes.get(f"{tick_sel}.SA", 10.0)
qtd_add = sb.number_input("Quantidade", min_value=1, value=1)
preco_pago = sb.number_input("Preço pago (R$)", min_value=0.01, value=round(cot_sel, 2), key=f"pp_{tick_sel}")
if sb.button("Registrar compra"):
    a = D["carteira"][f"{tick_sel}.SA"]
    nova = a["qtd"] + qtd_add
    a["pm"] = (a["qtd"] * a["pm"] + qtd_add * preco_pago) / nova
    a["qtd"] = nova
    D["historico"].append({"data": dt.date.today().isoformat(), "ativo": tick_sel,
                           "qtd": int(qtd_add), "preco": float(preco_pago)})
    salvar()
    st.session_state.msg = f"Compra de {qtd_add}x {tick_sel} registrada."
    st.rerun()
if "msg" in st.session_state:
    st.toast(st.session_state.pop("msg"), icon="✅")

if sb.button("🔄 Atualizar proventos (12m Yahoo)"):
    n = 0
    for t, a in D["carteira"].items():
        p = proventos_12m(t)
        if p and p > 0:
            a["est_prov"] = round(p, 2)
            n += 1
    salvar()
    st.session_state.msg = f"Proventos atualizados em {n} ativos."
    st.rerun()

# ---------------------------------------------------------------- DATAFRAME
df = pd.DataFrame.from_dict(D["carteira"], orient="index")
df["cotacao"] = df.index.map(cotacoes)
falhas = df.index[df["cotacao"].isna()].tolist()
if falhas:
    st.warning(f"⚠️ Sem cotação para {', '.join(falhas)}. Esses ativos ficam fora do plano de compra.")
df["valor_total"] = df["qtd"] * df["cotacao"].fillna(df["pm"])
df["empresa"] = df["nome"].str.replace(r" (ON|PN)$", "", regex=True)
df["bazin"] = df["est_prov"] / taxa_bazin
df["graham"] = [math.sqrt(22.5 * r.lpa * r.vpa) if r.tipo != "FII" and r.lpa > 0 and r.vpa > 0 else np.nan
                for r in df.itertuples()]
df["pvp"] = np.where(df["vpa"] > 0, df["cotacao"] / df["vpa"], np.nan)
df["dy"] = df["est_prov"] / df["cotacao"] * 100


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
base = pat_ativos + aporte  # a reserva NÃO entra na base das metas
df["valor_empresa"] = df.groupby("empresa")["valor_total"].transform("sum")
df["meta_empresa"] = df.groupby("empresa")["meta_pct"].transform("sum")
df["defasagem"] = np.maximum(0, base * df["meta_empresa"] / 100 - df["valor_empresa"])


# ---------------------------------------------------------------- PLANO DE COMPRA
def gerar_plano():
    el = df[(df["meta_pct"] > 0) & df["elegivel"] & (df["defasagem"] > 0)]
    el = el.sort_values("defasagem", ascending=False).head(max_ativos)
    gap = el["defasagem"].to_dict()
    preco = el["cotacao"].to_dict()
    setor = el["setor"].to_dict()
    set_val = df.groupby("setor")["valor_total"].sum().to_dict()
    compras, saldo = {}, aporte
    while True:
        cand = [t for t in gap if preco[t] <= saldo and gap[t] >= preco[t] / 2
                and set_val.get(setor[t], 0) + preco[t] <= teto_setor / 100 * base]
        if not cand:
            break
        t = max(cand, key=lambda x: gap[x])
        compras[t] = compras.get(t, 0) + 1
        gap[t] -= preco[t]
        saldo -= preco[t]
        set_val[setor[t]] = set_val.get(setor[t], 0) + preco[t]
    return compras, saldo


# ---------------------------------------------------------------- KPIs
st.title("🚀 Gestor Inteligente de Carteira v4.0")
renda_anual = (df["qtd"] * df["est_prov"]).sum()
custo = (df["qtd"] * df["pm"]).sum()
k = st.columns(5)
k[0].metric("Ativos", brl(pat_ativos), f"{(pat_ativos / custo - 1) * 100:+.1f}% vs custo" if custo else None)
k[1].metric("Reserva", brl(D["reserva"]))
k[2].metric("Patrimônio total", brl(pat_ativos + D["reserva"]))
k[3].metric("Renda mensal estimada", brl(renda_anual / 12))
k[4].metric("Yield on cost", f"{renda_anual / custo * 100:.1f}%" if custo else "—")
st.progress(min(1.0, renda_anual / 12 / meta_renda) if meta_renda else 0.0,
            text=f"Meta de renda: {brl(renda_anual / 12)} de {brl(meta_renda)}/mês")

t1, t2, t3, t4, t5, t6, t7 = st.tabs(["🎯 Aporte", "💼 Carteira", "📊 Valuation", "🎚️ Metas",
                                       "📈 Gráficos", "🧾 Histórico", "🤖 Copilot"])

with t1:
    st.caption(f"Filtro: **{modo}** · máx. {max_ativos} ativos · teto por setor {teto_setor}% · "
               "defasagem calculada por empresa (ON+PN somadas).")
    compras, saldo = gerar_plano()
    if compras:
        linhas = [{"Código": t.replace(".SA", ""), "Ativo": df.at[t, "nome"], "Setor": df.at[t, "setor"],
                   "Comprar": f"{q} un.", "Preço": brl(df.at[t, "cotacao"]),
                   "Total": brl(q * df.at[t, "cotacao"])} for t, q in compras.items()]
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
        st.info(f"💵 Sobra para o próximo aporte: **{brl(saldo)}**")
    else:
        st.warning("Nenhum ativo qualificado. Tente relaxar o filtro, a taxa Bazin ou o teto por setor.")
    near = df[(df["meta_pct"] > 0) & ~df["elegivel"] & df["cotacao"].notna()].copy()
    if not near.empty:
        near["acima_%"] = (near["cotacao"] / near["bazin"] - 1) * 100
        with st.expander("Fora do critério (quanto falta cair)"):
            st.dataframe(near.sort_values("acima_%")[["nome", "cotacao", "bazin", "graham", "acima_%"]]
                         .rename(columns={"nome": "Ativo", "cotacao": "Cotação", "bazin": "Teto Bazin",
                                          "graham": "Graham", "acima_%": "Acima do Bazin (%)"}).round(2),
                         width="stretch")

with t2:
    pos = df[df["qtd"] > 0].copy()
    if pos.empty:
        st.info("Nenhuma posição ainda. Registre compras na barra lateral.")
    else:
        pos["Custo"] = pos["qtd"] * pos["pm"]
        pos["Resultado %"] = (pos["valor_total"] / pos["Custo"] - 1) * 100
        pos["Renda/mês"] = pos["qtd"] * pos["est_prov"] / 12
        st.dataframe(pos[["nome", "qtd", "pm", "cotacao", "valor_total", "Resultado %", "dy", "Renda/mês"]]
                     .rename(columns={"nome": "Ativo", "qtd": "Qtd", "pm": "PM", "cotacao": "Cotação",
                                      "valor_total": "Valor", "dy": "DY %"}).round(2), width="stretch")

with t3:
    v = df[["nome", "setor", "cotacao", "bazin", "graham", "pvp", "dy", "status"]].copy()
    v.columns = ["Empresa", "Setor", "Cotação", "Teto Bazin", "Graham", "P/VP", "DY %", "Diagnóstico"]
    st.dataframe(v.round(2), width="stretch")
    st.caption("Graham não se aplica a FIIs (—). Bazin/Graham são triagem; bancos e empresas cíclicas distorcem.")

with t4:
    st.write("Edite metas e dados fundamentalistas. A soma das metas deve ser 100%.")
    ed = st.data_editor(df[["nome", "setor", "meta_pct", "est_prov", "lpa", "vpa"]],
                        disabled=["nome", "setor"], width="stretch", key="editor")
    soma = ed["meta_pct"].sum()
    (st.success if abs(soma - 100) < 0.01 else st.error)(f"Soma das metas: {soma:.1f}%")
    if st.button("💾 Salvar alterações"):
        for t, r in ed.iterrows():
            D["carteira"][t].update(meta_pct=float(r.meta_pct), est_prov=float(r.est_prov),
                                    lpa=float(r.lpa), vpa=float(r.vpa))
        salvar()
        st.rerun()

with t5:
    c1, c2 = st.columns(2)
    s = df.groupby("setor")["valor_total"].sum().reset_index()
    if s["valor_total"].sum() > 0:
        c1.plotly_chart(px.pie(s, values="valor_total", names="setor", hole=0.4, title="Alocação por setor"),
                        width="stretch")
    g = df.groupby("empresa").agg(valor=("valor_total", "sum"), meta=("meta_pct", "sum")).reset_index()
    g["Atual %"] = g["valor"] / pat_ativos * 100 if pat_ativos else 0
    g = g[(g["meta"] > 0) | (g["Atual %"] > 0)].rename(columns={"meta": "Meta %"})
    c2.plotly_chart(px.bar(g.melt("empresa", ["Atual %", "Meta %"]), x="empresa", y="value", color="variable",
                           barmode="group", title="Atual vs Meta (%)", labels={"value": "%", "empresa": ""}),
                    width="stretch")

with t6:
    h = pd.DataFrame(D["historico"])
    if h.empty:
        st.info("Nenhuma compra registrada ainda.")
    else:
        h["total"] = h["qtd"] * h["preco"]
        st.dataframe(h.iloc[::-1], hide_index=True, width="stretch")
        st.caption(f"Total investido via app: {brl(h['total'].sum())}")

with t7:
    st.write("Pergunte sobre sua carteira. Requer `ANTHROPIC_API_KEY` em `.streamlit/secrets.toml`.")
    q = st.text_area("Pergunta:")
    if st.button("Analisar") and q:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            ctx = df[["nome", "setor", "qtd", "cotacao", "valor_total", "meta_pct", "bazin", "graham",
                      "pvp", "dy", "status"]].round(2).to_csv()
            r = client.messages.create(
                model="claude-sonnet-5-5", max_tokens=1000,
                system="Você analisa carteiras de investimento brasileiras. Use só os dados fornecidos, "
                       "aponte riscos e limitações, e lembre que não é recomendação de investimento.",
                messages=[{"role": "user", "content": f"Carteira (aporte {brl(aporte)}):\n{ctx}\n\n{q}"}])
            st.markdown(r.content[0].text)
        except Exception as e:
            st.error(f"Não foi possível consultar a IA: {e}")
            