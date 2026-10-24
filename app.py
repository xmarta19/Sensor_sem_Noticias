"""Sensor sem notícias - interface Streamlit.

Executar:  streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from sensor_sem_noticias import api, charts, contingency, core

DEFAULT_JSON = "data/DADOS_CONTINGENCIA_20261021.json"
STATUS_LABEL = {
    core.EM_DIA: "🟩  Em dia",
    core.SEM_NOTICIAS: "🟥 Sem notícias",
    core.SEM_DADOS: "⬜ Sem dados",
}
UTC = timezone.utc

st.set_page_config(page_title="Sensor sem notícias", layout="wide")
api.load_dotenv()


def fmt_ts(dt: datetime | None) -> str:
    return "-" if dt is None else dt.strftime("%d/%m/%Y %H:%M UTC")


def state() -> dict:
    return st.session_state.setdefault("ds", {})


st.title("Sensor sem notícias")
st.caption(
    "Há quanto tempo cada dispositivo não envia uma leitura válida? "
)

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("Dados")
    source = st.radio(
        "Fonte", ["Online (API)", "Dados históricos (JSON)"],
        help="Escolhe a fonte de dados: API online ou ficheiro de contingência.",

    )
    historical = source.startswith("Dados")
    ds = state()
    if ds.get("historical") != historical:
        ds.clear()          # mudar de fonte descarta dados carregados
        ds["historical"] = historical

    if historical:
        up = st.file_uploader("Ficheiro JSON de contingência", type="json")
        if st.button("Carregar ficheiro", width="stretch"):
            try:
                snap = contingency.load_snapshot(up if up is not None else DEFAULT_JSON)
                ds.update(snapshot=snap, devices=snap.devices,
                          source_name=(up.name if up is not None else DEFAULT_JSON))
                st.success("Ficheiro carregado.")
            except ValueError as e:
                ds.pop("snapshot", None)
                ds.pop("devices", None)
                st.error(str(e))
    else:
        base = st.text_input("Base da API", value=os.environ.get("HE_BASE_URL", api.DEFAULT_BASE))
        if st.button("Ligar à API", width="stretch"):
            try:
                token = api.login(base, os.environ.get("HE_EMAIL", ""),
                                  os.environ.get("HE_PASSWORD", ""))
                devices = api.list_devices(base, token)
                ds.update(base=base, token=token, devices=devices, rows=None)
                if not devices:
                    st.warning("A API não devolveu dispositivos.")
            except api.ApiError as e:
                ds.pop("devices", None)
                st.error(e.message)

    devices = ds.get("devices") or []
    ids = [d.get("id") for d in devices if d.get("id")]
    chosen = st.multiselect("Dispositivos", ids, default=ids[:1], disabled=not ids)

    hours = st.select_slider("Período (horas)", options=[1, 3, 6, 12, 24], value=24,
                             help="Intervalo de tempo a considerar para o cálculo do atraso e episódios de silêncio.")
    threshold = st.slider("Limiar (min)", 5, 120, 10, step=1,
                          help="Se o atraso de um dispositivo ultrapassar este limiar, considera-se que está sem notícias. ")
    metric_labels = st.multiselect("Métricas (1 a 3)", list(core.METRICS),
                                   default=list(core.METRICS))
    fields = [core.METRICS[m] for m in metric_labels]

    reference: datetime | None = None
    if historical:
        snap = ds.get("snapshot")
        default_ref = (snap.collected_at if snap and snap.collected_at else datetime.now(UTC))
        choice = st.selectbox("Instante de referência",
                              ["Momento da recolha do ficheiro", "Agora", "Personalizado"])
        if choice.startswith("Momento"):
            reference = default_ref
        elif choice == "Agora":
            reference = datetime.now(UTC)
        else:
            d = st.date_input("Data (UTC)", value=default_ref.date())
            t = st.time_input("Hora (UTC)", value=default_ref.time().replace(second=0, microsecond=0))
            reference = datetime.combine(d, t, tzinfo=UTC)
    else:
        if st.button("Atualizar dados", type="primary", width="stretch",
                     disabled=not (ds.get("token") and chosen)):
            now = datetime.now(UTC)
            rows, errors = {}, []
            for dev in chosen:
                try:
                    rows[dev] = api.fetch_observations(
                        ds["base"], ds["token"], dev, now - timedelta(hours=hours), now)
                except api.ApiError as e:
                    errors.append(f"{dev}: {e.message}")
            ds.update(rows=rows or None, fetched_at=now, fetched_hours=hours,
                      errors=errors, fetched_ids=list(chosen))
        reference = ds.get("fetched_at")

# ------------------------------------------------------------------ área principal
if not metric_labels:
    st.info("Escolhe pelo menos uma métrica.")
    st.stop()

if historical:
    snap = ds.get("snapshot")
    if snap is None:
        st.info("Carrega o ficheiro de contingência na barra lateral.")
        st.stop()
    rows_by_dev = {k: v for k, v in snap.rows.items() if k in chosen}
    window_hours = hours
    st.warning(
        f"**Dados históricos:** "
        f"recolhido em {fmt_ts(snap.collected_at)}. Não é tempo real."
    )
else:
    rows_by_dev = ds.get("rows")
    window_hours = ds.get("fetched_hours", hours)
    for msg in ds.get("errors", []):
        st.error(msg)
    if not ds.get("token"):
        st.info("Clica em Ligar à API na barra lateral ou escolhe Dados em JSON.")
        st.stop()
    if rows_by_dev is None:
        if not ds.get("errors"):
            st.info("Escolhe dispositivos e carrega em Atualizar dados.")
        st.stop()

if not chosen or not rows_by_dev:
    st.info("Escolhe pelo menos um dispositivo.")
    st.stop()

reports = [
    core.analyse_device(dev, rows_by_dev.get(dev, []), fields, reference, window_hours, threshold)
    for dev in chosen if dev in rows_by_dev
]
if not reports:
    st.info("Sem dados para os dispositivos escolhidos. Atualiza os dados.")
    st.stop()

first = reports[0]
origin = ("API sensorblock.humanexperience.pt" if not historical
          else "ficheiro de contingência")
st.markdown(
    f"**Origem:** {origin} · **Período:** {fmt_ts(first.window_from)} → {fmt_ts(first.reference)} "
    f"({window_hours} h) · **Limiar:** {threshold} min · "
    f"**Métricas:** {', '.join(metric_labels)}"
)
valid_lasts = [r.last_valid for r in reports if r.last_valid]
st.markdown(f"**Observação válida mais recente:** "
            f"{fmt_ts(max(valid_lasts)) if valid_lasts else 'nenhuma no período'}")

summary = pd.DataFrame([{
    "Dispositivo": r.device_id,
    "Estado": STATUS_LABEL[r.status],
    "Última leitura válida": fmt_ts(r.last_valid),
    "Atraso": core.format_duration(r.delay),
    "Episódios sem notícias": len(r.episodes),
    "Leituras válidas": len(r.observations),
    "Duplicados removidos": r.stats.duplicates_removed,
} for r in reports])
st.dataframe(summary, hide_index=True, width="stretch")

for r in reports:
    with st.expander(f"{r.device_id} - {STATUS_LABEL[r.status]}", expanded=len(reports) == 1):
        if r.status == core.SEM_DADOS:
            st.warning(
                f"Nenhuma leitura válida entre {fmt_ts(r.window_from)} e {fmt_ts(r.reference)}. "
            )
            if r.last_before_window:
                st.error(
                    f"Última leitura válida: "
                    f"{fmt_ts(r.last_before_window)}, há "
                    f"{core.format_duration(r.reference - r.last_before_window)} "
                    f"face à referência."
                )
            continue
        if r.status == core.SEM_NOTICIAS:
            st.error(
                f"Última leitura válida há {core.format_duration(r.delay)} "
                f"({fmt_ts(r.last_valid)}), acima do limiar de {threshold} min."
            )
        else:
            st.success(f"Última leitura válida há {core.format_duration(r.delay)}.")

        cols = st.columns(len(metric_labels))
        for col, label in zip(cols, metric_labels):
            hit = r.last_by_metric.get(core.METRICS[label])
            if hit:
                col.metric(label, f"{hit[0]:g}")
                col.caption(f"em {fmt_ts(hit[1])}")
            else:
                col.metric(label, "sem dados")

        if r.episodes:
            st.markdown("**Episódios sem notícias**")
            st.dataframe(pd.DataFrame([{
                "Início (última leitura antes)": fmt_ts(e.start),
                "Fim": fmt_ts(e.end) + (" (ainda em curso)" if e.ongoing else ""),
                "Duração (min)": round(e.minutes, 1),
            } for e in r.episodes]), hide_index=True, width="stretch")
        else:
            st.caption("Sem episódios acima do limiar neste período.")

        st.markdown("**Leituras ao longo do tempo**")
        shown = st.multiselect(
            "Métricas a mostrar", metric_labels, default=metric_labels,
            key=f"vm_{r.device_id}",
        )
        view = st.radio("Vista", ["Gráfico", "Tabela"], horizontal=True,
                        key=f"vv_{r.device_id}")
        if not shown:
            st.info("Escolhe pelo menos uma métrica para ver as leituras.")
        else:
            shown_fields = [core.METRICS[m] for m in shown]
            df = charts.readings_dataframe(r, shown_fields)
            if view == "Tabela":
                labels = {core.METRICS[m]: m for m in shown}
                tbl = charts.table_for_display(df, shown_fields, labels)
                st.dataframe(tbl, hide_index=True, width="stretch")
                st.caption("Mais recente primeiro. Célula vazia = sem valor nessa leitura.")
            else:
                for m in shown:
                    ch = charts.metric_chart(df, core.METRICS[m], m, r)
                    if ch is None:
                        st.caption(f"{m}: sem valores neste período.")
                    else:
                        st.altair_chart(ch, width="stretch")
                st.caption("A linha parte-se onde o intervalo entre leituras excede o limiar. "
                           "Zona vermelha = episódio sem notícias.")

        if len(r.observations) > 1:
            gaps = pd.DataFrame({
                "Instante": [b.ts for b in r.observations[1:]],
                "Minutos desde a leitura anterior": [
                    (b.ts - a.ts).total_seconds() / 60
                    for a, b in zip(r.observations, r.observations[1:])],
            })
            bars = alt.Chart(gaps).mark_bar().encode(
                x=alt.X("Instante:T", title="Instante (UTC)"),
                y=alt.Y("Minutos desde a leitura anterior:Q"),
                tooltip=["Instante:T", "Minutos desde a leitura anterior:Q"],
            )
            rule = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(
                color="red", strokeDash=[4, 4]).encode(y="y:Q")
            st.altair_chart(bars + rule, width="stretch")
            st.caption("Intervalo entre leituras consecutivas. Linha vermelha = limiar.")

        s = r.stats
        notes = []
        if s.duplicates_removed: notes.append(f"{s.duplicates_removed} duplicado(s) removido(s)")
        if s.without_valid_value: notes.append(f"{s.without_valid_value} linha(s) sem valor nas métricas escolhidas")
        if s.invalid_timestamp: notes.append(f"{s.invalid_timestamp} linha(s) sem instante válido")
        if s.after_reference: notes.append(f"{s.after_reference} leitura(s) posteriores à referência ignoradas")
        if notes:
            st.caption("Tratamento dos dados: " + "; ".join(notes) + ".")
