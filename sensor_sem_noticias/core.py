"""Lógica pura (sem rede nem interface): fácil de testar.

Regra central
-------------
atraso = instante de referência - instante da última observação VÁLIDA.

- Instante da observação = ``data.createdAt`` (momento da medição), não o
  ``createdAt`` exterior (momento da classificação).
- Observação válida = tem pelo menos uma das métricas escolhidas com valor numérico.
  Ausência (null) não é zero e nunca conta como leitura.
- Estado: EM_DIA se atraso <= limiar; SEM_NOTICIAS se atraso > limiar;
  SEM_DADOS se não existe nenhuma observação válida no período.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

METRICS: dict[str, str] = {
    "Temperatura (°C)": "si7021Temp",
    "Humidade (%)": "si7021Humidity",
    "Luz (lux)": "veml3328Lux",
}

EM_DIA = "EM_DIA"
SEM_NOTICIAS = "SEM_NOTICIAS"
SEM_DADOS = "SEM_DADOS"


def parse_ts(value: Any) -> datetime | None:
    """Converte ISO 8601 (com Z) em datetime UTC; devolve None se inválido."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and not math.isnan(float(value))
    )


@dataclass
class Observation:
    ts: datetime
    values: dict[str, float]  # campo -> valor numérico (só campos escolhidos e presentes)


@dataclass
class QualityStats:
    rows_received: int = 0
    invalid_timestamp: int = 0      # linhas sem data.createdAt utilizável
    duplicates_removed: int = 0     # mesmo instante repetido
    without_valid_value: int = 0    # linha existe mas todas as métricas escolhidas são null
    after_reference: int = 0        # posteriores ao instante de referência (ignoradas)
    before_window: int = 0          # anteriores ao início do período (ignoradas)


@dataclass
class Episode:
    start: datetime
    end: datetime
    minutes: float
    ongoing: bool  # True = silêncio ainda em curso à hora de referência


@dataclass
class DeviceReport:
    device_id: str
    status: str
    reference: datetime
    window_from: datetime
    threshold_min: float
    last_valid: datetime | None
    delay: timedelta | None
    last_by_metric: dict[str, tuple[float, datetime] | None]
    episodes: list[Episode]
    observations: list[Observation]
    stats: QualityStats = field(default_factory=QualityStats)
    # Última observação válida ANTERIOR ao período (só conhecida se os dados a incluírem,
    # como no ficheiro histórico; numa consulta à API limitada ao período fica None).
    last_before_window: datetime | None = None

    @property
    def delay_minutes(self) -> float | None:
        return None if self.delay is None else self.delay.total_seconds() / 60


def to_observations(
    rows: Iterable[dict], fields: list[str]
) -> tuple[list[Observation], QualityStats]:
    """Normaliza as linhas da API: ordena, remove duplicados e descarta ausências."""
    stats = QualityStats()
    seen: set[datetime] = set()
    out: list[Observation] = []
    for row in rows or []:
        stats.rows_received += 1
        data = row.get("data") if isinstance(row, dict) else None
        ts = parse_ts(data.get("createdAt")) if isinstance(data, dict) else None
        if ts is None:
            stats.invalid_timestamp += 1
            continue
        if ts in seen:
            stats.duplicates_removed += 1
            continue
        seen.add(ts)
        values = {f: float(data[f]) for f in fields if is_number(data.get(f))}
        if not values:
            stats.without_valid_value += 1
            continue
        out.append(Observation(ts=ts, values=values))
    out.sort(key=lambda o: o.ts)
    return out, stats


def analyse_device(
    device_id: str,
    rows: Iterable[dict],
    fields: list[str],
    reference: datetime,
    window_hours: float,
    threshold_min: float,
) -> DeviceReport:
    """Calcula atraso, estado e episódios de silêncio para um dispositivo."""
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    window_from = reference - timedelta(hours=window_hours)

    all_obs, stats = to_observations(rows, fields)
    obs: list[Observation] = []
    last_before: datetime | None = None
    for o in all_obs:
        if o.ts > reference:
            stats.after_reference += 1
        elif o.ts < window_from:
            stats.before_window += 1
            last_before = o.ts  # all_obs está ordenado: fica o mais recente
        else:
            obs.append(o)

    last_by_metric: dict[str, tuple[float, datetime] | None] = {}
    for f in fields:
        hit = next((o for o in reversed(obs) if f in o.values), None)
        last_by_metric[f] = (hit.values[f], hit.ts) if hit else None

    episodes: list[Episode] = []
    for a, b in zip(obs, obs[1:]):
        gap = (b.ts - a.ts).total_seconds() / 60
        if gap > threshold_min:
            episodes.append(Episode(a.ts, b.ts, gap, ongoing=False))

    if not obs:
        return DeviceReport(
            device_id, SEM_DADOS, reference, window_from, threshold_min,
            None, None, last_by_metric, episodes, obs, stats, last_before,
        )

    last = obs[-1].ts
    delay = reference - last
    delay_min = delay.total_seconds() / 60
    if delay_min > threshold_min:
        episodes.append(Episode(last, reference, delay_min, ongoing=True))
    status = SEM_NOTICIAS if delay_min > threshold_min else EM_DIA
    return DeviceReport(
        device_id, status, reference, window_from, threshold_min,
        last, delay, last_by_metric, episodes, obs, stats, last_before,
    )


def segment_ids(timestamps: list[datetime], threshold_min: float) -> list[int]:
    """Número de segmento de cada leitura (ordenadas). Muda quando o intervalo para a leitura
    anterior excede o limiar, para o gráfico não ligar com uma linha o que é ausência de dados."""
    ids: list[int] = []
    seg = 0
    for i, t in enumerate(timestamps):
        if i and (t - timestamps[i - 1]).total_seconds() / 60 > threshold_min:
            seg += 1
        ids.append(seg)
    return ids


def format_duration(td: timedelta | None) -> str:
    if td is None:
        return "-"
    total = int(td.total_seconds())
    if total < 0:
        return "-"
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h >= 24:
        d, h = divmod(h, 24)
        return f"{d} d {h} h {m} min"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"
