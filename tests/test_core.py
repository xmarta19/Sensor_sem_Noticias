"""Testes da lógica. Os dados SIMULADOS estão identificados como tal."""
from datetime import datetime, timedelta, timezone

import pytest

from sensor_sem_noticias import api, contingency, core

UTC = timezone.utc
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
FIELDS = [core.METRICS["Temperatura (°C)"]]


def row(minutes, temp=21.0, **extra):
    """SIMULADO: linha no formato da API, instante = T0 + minutes."""
    ts = (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d = {"createdAt": ts, "si7021Temp": temp, "si7021Humidity": 50, "veml3328Lux": 10}
    d.update(extra)
    return {"deviceId": "SIM", "createdAt": ts, "data": d}


def analyse(rows, ref_min, threshold=10, hours=24, fields=FIELDS):
    return core.analyse_device("SIM", rows, fields, T0 + timedelta(minutes=ref_min), hours, threshold)


# --- cenário normal ----------------------------------------------------------
def test_em_dia_quando_atraso_dentro_do_limiar():
    r = analyse([row(0), row(5), row(10)], ref_min=12)
    assert r.status == core.EM_DIA
    assert r.delay_minutes == pytest.approx(2)
    assert r.episodes == []


def test_limiar_exato_nao_e_sem_noticias():
    r = analyse([row(0)], ref_min=10, threshold=10)
    assert r.status == core.EM_DIA


# --- cenário que ativa a funcionalidade --------------------------------------
def test_sem_noticias_quando_atraso_acima_do_limiar():
    r = analyse([row(0), row(5)], ref_min=60)
    assert r.status == core.SEM_NOTICIAS
    assert r.delay_minutes == pytest.approx(55)
    assert r.episodes[-1].ongoing and r.episodes[-1].minutes == pytest.approx(55)


def test_alterar_limiar_muda_o_resultado():
    rows = [row(0), row(5), row(17), row(22)]  # lacuna de 12 min
    assert len(analyse(rows, 25, threshold=15).episodes) == 0
    assert len(analyse(rows, 25, threshold=10).episodes) == 1


def test_alterar_referencia_muda_o_resultado():
    rows = [row(0), row(5)]
    assert analyse(rows, 8).status == core.EM_DIA
    assert analyse(rows, 40).status == core.SEM_NOTICIAS


def test_leituras_posteriores_a_referencia_sao_ignoradas():
    r = analyse([row(0), row(5), row(30)], ref_min=8)
    assert r.last_valid == T0 + timedelta(minutes=5)
    assert r.stats.after_reference == 1


# --- dados em falta / erro ---------------------------------------------------
def test_resposta_vazia_e_sem_dados_nao_normal():
    r = analyse([], ref_min=0)
    assert r.status == core.SEM_DADOS
    assert r.delay is None and r.last_valid is None


def test_null_nao_e_zero_nem_leitura_valida():
    rows = [row(0, temp=None, si7021Humidity=None, veml3328Lux=None)]
    r = analyse(rows, ref_min=1)
    assert r.status == core.SEM_DADOS
    assert r.stats.without_valid_value == 1


def test_ultimo_valor_por_metrica_nao_usa_zero_para_ausentes():
    rows = [row(0, temp=20.0), row(5, temp=None)]
    r = analyse(rows, ref_min=6)
    assert r.last_by_metric["si7021Temp"] == (20.0, T0)
    assert r.last_valid == T0 + timedelta(minutes=0)  # só a de t=0 é válida p/ a temperatura


def test_duplicados_sao_removidos_e_contados():
    r = analyse([row(0), row(0), row(5)], ref_min=6)
    assert len(r.observations) == 2
    assert r.stats.duplicates_removed == 1


def test_desordenados_e_instante_invalido():
    rows = [row(5), {"data": {"createdAt": "lixo", "si7021Temp": 20}}, row(0)]
    r = analyse(rows, ref_min=6)
    assert [o.ts for o in r.observations] == [T0, T0 + timedelta(minutes=5)]
    assert r.stats.invalid_timestamp == 1


def test_periodo_exclui_leituras_antigas():
    r = analyse([row(0)], ref_min=300, hours=1)
    assert r.status == core.SEM_DADOS
    assert r.stats.before_window == 1


def test_usa_instante_da_medicao_e_nao_o_da_classificacao():
    r = row(0)
    r["createdAt"] = (T0 + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rep = analyse([r], ref_min=1)
    assert rep.last_valid == T0


def test_sem_dados_no_periodo_mas_leitura_anterior_conhecida():
    r = analyse([row(0)], ref_min=300, hours=1)
    assert r.status == core.SEM_DADOS
    assert r.last_before_window == T0


# --- leituras ao longo do tempo -----------------------------------------------
def test_segmentos_partem_a_linha_nas_lacunas():
    ts = [T0 + timedelta(minutes=m) for m in (0, 5, 10, 30, 35)]
    assert core.segment_ids(ts, 10) == [0, 0, 0, 1, 1]
    assert core.segment_ids(ts, 30) == [0, 0, 0, 0, 0]


def test_tabela_e_grafico_das_leituras():
    from sensor_sem_noticias import charts

    fields = ["si7021Temp", "si7021Humidity"]
    rep = analyse([row(0, temp=20.0), row(5, temp=None), row(10, temp=21.0)], 12, fields=fields)
    df = charts.readings_dataframe(rep, fields)
    assert len(df) == 3 and df["si7021Temp"].isna().sum() == 1  # ausente = NaN, não 0
    tbl = charts.table_for_display(df, ["si7021Temp"], {"si7021Temp": "Temperatura (°C)"})
    assert len(tbl) == 2 and list(tbl.columns) == [charts.TIME_COL, "Temperatura (°C)"]
    assert charts.metric_chart(df, "si7021Temp", "Temperatura (°C)", rep) is not None
    assert charts.metric_chart(df.assign(si7021Temp=float("nan")), "si7021Temp", "T", rep) is None


# --- API e contingência ------------------------------------------------------
def test_api_rejeita_http_e_porta():
    with pytest.raises(api.ApiError):
        api.check_base("http://sensorblock.humanexperience.pt")
    with pytest.raises(api.ApiError):
        api.check_base("https://sensorblock.humanexperience.pt:3333")


def test_api_rejeita_janela_acima_de_24h():
    with pytest.raises(api.ApiError):
        api.fetch_observations(api.DEFAULT_BASE, "t", "x", T0, T0 + timedelta(hours=25))


def test_api_indisponivel_da_mensagem_compreensivel(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("SIMULADO")

    monkeypatch.setattr(requests, "request", boom)
    with pytest.raises(api.ApiError) as e:
        api.fetch_observations(api.DEFAULT_BASE, "t", "x", T0, T0 + timedelta(hours=1))
    assert e.value.kind == "network" and "indisponível" in e.value.message


def test_contingencia_ficheiro_invalido(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        contingency.load_snapshot(str(p))
