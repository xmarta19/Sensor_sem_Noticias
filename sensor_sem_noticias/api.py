"""Cliente mínimo da API Human Experience (só leitura, consulta manual)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DEFAULT_BASE = "https://sensorblock.humanexperience.pt"
MAX_WINDOW = timedelta(hours=24)
TIMEOUT = 20


class ApiError(Exception):
    """Erro com mensagem já adequada para mostrar ao utilizador."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "config" | "login" | "auth" | "network" | "http" | "format"
        self.message = message


def load_dotenv(path: str = ".env") -> None:
    """Lê KEY=VALUE de um .env local (não versionado). Não sobrepõe variáveis já definidas."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def check_base(base: str) -> str:
    base = base.rstrip("/")
    if not base.startswith("https://"):
        raise ApiError("config", "A base da API tem de usar HTTPS.")
    host = base.split("://", 1)[1]
    if ":" in host:
        raise ApiError("config", "Não acrescentes porta (ex.: :3333) à base da API.")
    return base


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(method: str, url: str, **kw):
    try:
        resp = requests.request(method, url, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        raise ApiError(
            "network",
            "API indisponível (sem ligação ou tempo esgotado). Não há dados atuais. "
        )
    return resp


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        raise ApiError("format", "A API respondeu num formato inesperado.")


def login(base: str, email: str, password: str) -> str:
    base = check_base(base)
    if not email or not password:
        raise ApiError("config", "Faltam credenciais (variáveis HE_EMAIL e HE_PASSWORD).")
    resp = _request(
        "POST", f"{base}/api/login",
        json={"email": email, "password": password, "clientType": "web"},
    )
    if resp.status_code == 400:
        raise ApiError("login", "Login recusado (400): confirma email, password e clientType.")
    if resp.status_code in (401, 403):
        raise ApiError("auth", f"Login recusado ({resp.status_code}).")
    if not resp.ok:
        raise ApiError("http", f"Erro {resp.status_code} no login.")
    token = (_json(resp).get("data") or {}).get("token")
    if not token:
        raise ApiError("format", "Login sem token na resposta.")
    return token


def list_devices(base: str, token: str) -> list[dict]:
    base = check_base(base)
    resp = _request("GET", f"{base}/api/devices", headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        raise ApiError("auth", "Token ausente ou inválido (401): volta a ligar.")
    if not resp.ok:
        raise ApiError("http", f"Erro {resp.status_code} ao listar dispositivos.")
    data = _json(resp).get("data")
    if not isinstance(data, list):
        raise ApiError("format", "Lista de dispositivos em formato inesperado.")
    return data


def fetch_observations(
    base: str, token: str, device_id: str, dt_from: datetime, dt_to: datetime
) -> list[dict]:
    """Uma consulta limitada a 24 h. Lista vazia é um resultado válido (não um erro)."""
    base = check_base(base)
    if dt_to - dt_from > MAX_WINDOW:
        raise ApiError("config", "O período pedido excede 24 horas.")
    resp = _request(
        "GET", f"{base}/api/data-classifications",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "deviceId": device_id,
            "includeData": "true",
            "dateFrom": iso_z(dt_from),
            "dateTo": iso_z(dt_to),
        },
    )
    if resp.status_code == 401:
        raise ApiError("auth", "Token ausente ou inválido (401): volta a ligar.")
    if not resp.ok:
        raise ApiError("http", f"Erro {resp.status_code} ao consultar o dispositivo.")
    data = _json(resp).get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise ApiError("format", "Dados em formato inesperado.")
    return data
