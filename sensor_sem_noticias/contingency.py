"""Modo de contingência: lê o recorte histórico (JSON) fornecido pelo docente."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import IO

from .core import parse_ts


@dataclass
class Snapshot:
    devices: list[dict]               # [{id, name, latestReading}]
    rows: dict[str, list[dict]]       # alias -> observações
    collected_at: datetime | None
    mode: str


def load_snapshot(source: str | IO) -> Snapshot:
    """Aceita um caminho ou um ficheiro aberto. Levanta ValueError com mensagem clara."""
    try:
        if isinstance(source, str):
            with open(source, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        else:
            doc = json.load(source)
    except FileNotFoundError:
        raise ValueError("Ficheiro de contingência não encontrado.")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("O ficheiro não é um JSON válido.")
    try:
        devices = doc["devices"]["data"]
        series = doc["data_classifications"]
        meta = doc.get("metadata") or {}
        rows = {alias: (v.get("data") or []) for alias, v in series.items()}
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Estrutura inesperada: faltam «devices» ou «data_classifications».")
    return Snapshot(
        devices=devices,
        rows=rows,
        collected_at=parse_ts(meta.get("collected_at_utc")),
        mode=str(meta.get("mode", "desconhecido")),
    )
