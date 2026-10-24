"""Executa os 3 cenários de validação e escreve TESTES.md com os resultados OBTIDOS.

Uso:  python scripts/cenarios.py [caminho_do_json]
Cenários 1 e 2 usam o recorte histórico real; o cenário 3 usa dados SIMULADOS.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

from sensor_sem_noticias import api, contingency, core  # noqa: E402

JSON = sys.argv[1] if len(sys.argv) > 1 else "data/DADOS_CONTINGENCIA_20261021.json"
UTC = timezone.utc
FIELDS = list(core.METRICS.values())
snap = contingency.load_snapshot(JSON)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def show(r):
    return (f"estado={r.status}; última válida={r.last_valid:%d/%m %H:%M} UTC; "
            f"atraso={core.format_duration(r.delay)}; episódios={len(r.episodes)}")


def img(path, alt, width=360):
    """Imagem embebida no Markdown (HTML <img>, para controlar o tamanho na tabela)."""
    if not Path(path).exists():
        print(f"AVISO: falta a imagem {path}", file=sys.stderr)
    return f'<img src="{path}" alt="{alt}" width="{width}">'


rows = []

# 1. Normal -------------------------------------------------------------------
r1 = core.analyse_device("HE-01", snap.rows["HE-01"], FIELDS, ts("2026-10-21T14:42:00Z"), 24, 10)
ok1 = r1.status == core.EM_DIA and round(r1.delay_minutes) == 2
rows.append((
    "1. Normal (dados históricos reais)",
    "HE-01; referência 21/10 14:42 UTC; período 24 h; limiar 10 min",
    "Em dia; atraso de 2 min; última leitura válida 14:40",
    show(r1) + (" ✔" if ok1 else " ✘"),
    img("docs/evidencia_1.png", "Cenário 1: em dia"),
))

# 2. Ativa a funcionalidade ---------------------------------------------------
r2 = core.analyse_device("HE-01", snap.rows["HE-01"], FIELDS, ts("2026-10-21T16:00:00Z"), 24, 10)
r2b = core.analyse_device("HE-01", snap.rows["HE-01"], FIELDS, ts("2026-10-21T14:42:00Z"), 24, 7)
ok2 = (r2.status == core.SEM_NOTICIAS and round(r2.delay_minutes) == 80
       and r2.episodes[-1].ongoing and len(r2b.episodes) == 1)
rows.append((
    "2. Ativa a funcionalidade (dados históricos reais)",
    "HE-01; referência 21/10 16:00 UTC (80 min após a última leitura); limiar 10 min. "
    "Depois: referência 14:42 e limiar 7 min",
    "Sem notícias, atraso 1 h 20 min, episódio em curso; com limiar 7 min "
    "aparece a lacuna histórica de 10 min (22:50)",
    show(r2) + f" | limiar 7 min: episódios={len(r2b.episodes)}" + (" ✔" if ok2 else " ✘"),
    "Estado e episódio em curso:<br>" + img("docs/evidencia_2.1.png", "Cenário 2: sem notícias")
    + "<br>Limiar 7 min:<br>" + img("docs/evidencia_2.2.png", "Cenário 2: limiar 7 min"),
))

# 3. Dados em falta / erro (SIMULADOS) ---------------------------------------
empty = core.analyse_device("SIM", [], FIELDS, ts("2026-10-21T14:42:00Z"), 24, 10)
nulls = [{"data": {"createdAt": "2026-10-21T14:40:00.000Z", "si7021Temp": None,
                   "si7021Humidity": None, "veml3328Lux": None}}]
rn = core.analyse_device("SIM", nulls, FIELDS, ts("2026-10-21T14:42:00Z"), 24, 10)
try:
    with mock.patch.object(requests, "request", side_effect=requests.ConnectionError("SIMULADO")):
        api.fetch_observations(api.DEFAULT_BASE, "t", "x",
                               ts("2026-10-21T10:00:00Z"), ts("2026-10-21T14:00:00Z"))
    msg = "sem erro"
except api.ApiError as e:
    msg = f"ApiError({e.kind}): {e.message}"
ok3 = (empty.status == core.SEM_DADOS and empty.delay is None
       and rn.status == core.SEM_DADOS and "indisponível" in msg)
rows.append((
    "3. Dados em falta ou erro (SIMULADO)",
    "(a) resposta vazia; (b) linha com todas as métricas null; (c) API indisponível (ligação recusada simulada)",
    "(a) e (b) «Sem dados», sem atraso nem zeros; (c) mensagem de indisponibilidade, sem fingir tempo real",
    f"(a) {empty.status}, atraso={empty.delay}; (b) {rn.status}, sem valor válido; (c) {msg} "
    + ("✔" if ok3 else "✘"),
    "Sem dados:<br>" + img("docs/evidencia_3.1.png", "Cenário 3: sem dados")
    + "<br>API indisponível:<br>" + img("docs/evidencia_3.2.png", "Cenário 3: API indisponível"),
))

out = ["# Validação: três cenários",
       "",
       "Resultados obtidos ao executar `python scripts/cenarios.py`. "
       "Cenários 1 e 2: recorte histórico real. Cenário 3: dados **simulados**.",
       "",
       "| Cenário | Entrada | Resultado esperado | Resultado obtido | Evidência |",
       "|---|---|---|---|---|"]
for r in rows:
    out.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
Path("TESTES.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
sys.exit(0 if (ok1 and ok2 and ok3) else 1)
