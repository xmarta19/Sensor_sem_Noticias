"""Construção de tabelas e gráficos das leituras ao longo do tempo (UTC)."""
from __future__ import annotations

import altair as alt
import pandas as pd

from . import core

TIME_COL = "Instante (UTC)"


def readings_dataframe(report: core.DeviceReport, fields: list[str]) -> pd.DataFrame:
    """Uma linha por leitura válida; métrica ausente fica vazia (NaN), nunca 0."""
    rows = []
    for o in report.observations:
        row = {TIME_COL: o.ts.replace(tzinfo=None)}
        for f in fields:
            row[f] = o.values.get(f)
        rows.append(row)
    df = pd.DataFrame(rows, columns=[TIME_COL] + list(fields))
    for f in fields:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    return df


def table_for_display(df: pd.DataFrame, fields: list[str], labels: dict[str, str]) -> pd.DataFrame:
    """Mais recente primeiro, só linhas com pelo menos uma das métricas escolhidas."""
    out = df[[TIME_COL] + list(fields)].dropna(subset=fields, how="all")
    out = out.sort_values(TIME_COL, ascending=False)
    out = out.rename(columns=labels)
    out[TIME_COL] = out[TIME_COL].dt.strftime("%d/%m/%Y %H:%M")
    return out


def metric_chart(
    df: pd.DataFrame, field: str, label: str, report: core.DeviceReport, height: int = 170
) -> alt.Chart | None:
    """Série de uma métrica. A linha parte-se onde o intervalo excede o limiar e os episódios
    sem notícias aparecem sombreados. Devolve None se não há valores."""
    d = df[[TIME_COL, field]].dropna().rename(columns={TIME_COL: "instante", field: "valor"})
    if d.empty:
        return None
    d = d.sort_values("instante").reset_index(drop=True)
    d["segmento"] = core.segment_ids(list(d["instante"].dt.to_pydatetime()), report.threshold_min)

    start = report.window_from.replace(tzinfo=None).isoformat()
    end = report.reference.replace(tzinfo=None).isoformat()
    x = alt.X("instante:T", title="Instante (UTC)", scale=alt.Scale(domain=[start, end]))
    base = alt.Chart(d).encode(
        x=x,
        y=alt.Y("valor:Q", title=label, scale=alt.Scale(zero=False)),
        tooltip=[
            alt.Tooltip("instante:T", title="Instante (UTC)", format="%d/%m/%Y %H:%M"),
            alt.Tooltip("valor:Q", title=label),
        ],
    )
    layers = []
    if report.episodes:
        ep = pd.DataFrame({
            "inicio": [e.start.replace(tzinfo=None) for e in report.episodes],
            "fim": [e.end.replace(tzinfo=None) for e in report.episodes],
        })
        layers.append(
            alt.Chart(ep).mark_rect(color="red", opacity=0.15).encode(
                x=alt.X("inicio:T", scale=alt.Scale(domain=[start, end])), x2="fim:T")
        )
    layers.append(base.mark_line().encode(detail="segmento:N"))
    layers.append(base.mark_point(filled=True, size=25))
    return alt.layer(*layers).properties(height=height)
