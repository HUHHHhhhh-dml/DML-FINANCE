# -*- coding: utf-8 -*-
"""Pruebas de ``dml.models.rendimientos``.

Se comprueban las dos convenciones de rendimiento (simple y logaritmico), la
Tasa de Rentabilidad Geometrica (TRG) sobre una serie conocida y la conversion
de la TLR anual a mensual en los modos ``estandar`` (``TLR/12``) y ``excel``
(``TLR/365*28``).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from dml.models.rendimientos import (
    anualizar,
    desanualizar,
    media_geometrica,
    rendimientos_logaritmicos,
    rendimientos_simples,
    serie_tlr_mensual,
    tlr_mensual,
    trg,
)

# ==========================================================================
# 1. Rendimientos simples y logaritmicos
# ==========================================================================


def test_rendimientos_simples_calculo_explicito():
    """``R_t = P_t / P_{t-1} - 1`` y se descarta el primer periodo."""
    precios = pd.Series([100.0, 110.0, 121.0, 108.9])
    simples = rendimientos_simples(precios)
    assert len(simples) == len(precios) - 1
    assert simples.iloc[0] == pytest.approx(0.10, rel=1e-12)
    assert simples.iloc[1] == pytest.approx(0.10, rel=1e-12)
    assert simples.iloc[2] == pytest.approx(-0.10, rel=1e-12)
    # Equivalencia con la formula directa
    assert list(simples) == pytest.approx(list(precios.pct_change().dropna()), rel=1e-12)


def test_rendimientos_logaritmicos_calculo_explicito():
    """``r_t = ln(P_t / P_{t-1})`` y se descarta el primer periodo."""
    precios = pd.Series([100.0, 110.0, 121.0, 108.9])
    logs = rendimientos_logaritmicos(precios)
    assert len(logs) == len(precios) - 1
    assert logs.iloc[0] == pytest.approx(math.log(1.10), rel=1e-12)
    assert logs.iloc[1] == pytest.approx(math.log(1.10), rel=1e-12)
    assert logs.iloc[2] == pytest.approx(math.log(0.90), rel=1e-12)


def test_simple_y_logaritmico_coinciden_en_primera_linea():
    """Para rendimientos pequenos, ``ln(1+r)`` y ``r`` difieren a segundo orden."""
    rng = np.random.default_rng(2024)
    precios = pd.Series(100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 40)))
    simples = rendimientos_simples(precios)
    logs = rendimientos_logaritmicos(precios)
    assert list(logs) == pytest.approx(list(np.log1p(simples)), rel=1e-10)
    assert float(np.max(np.abs(logs - simples))) < 1e-3


def test_rendimientos_conservan_el_indice():
    """Los rendimientos mantienen las fechas de los periodos comparados."""
    fechas = pd.date_range("2024-01-31", periods=4, freq="ME")
    precios = pd.Series([100.0, 105.0, 103.0, 110.0], index=fechas)
    simples = rendimientos_simples(precios)
    logs = rendimientos_logaritmicos(precios)
    assert list(simples.index) == list(fechas[1:])
    assert list(logs.index) == list(fechas[1:])


def test_rendimientos_ignoran_huecos_nan():
    """Los precios faltantes se eliminan antes de calcular rendimientos."""
    precios = pd.Series([100.0, np.nan, 121.0, 133.1])
    simples = rendimientos_simples(precios)
    assert list(simples) == pytest.approx([121.0 / 100.0 - 1.0, 0.10], rel=1e-12)


@pytest.mark.parametrize("funcion", [rendimientos_simples, rendimientos_logaritmicos])
def test_rendimientos_serie_corta_no_falla(funcion):
    """Una serie de un solo punto (o vacia) devuelve una serie vacia, no un error."""
    assert len(funcion(pd.Series([100.0]))) == 0
    assert len(funcion(pd.Series(dtype="float64"))) == 0


# ==========================================================================
# 2. TRG y media geometrica
# ==========================================================================


def test_trg_serie_conocida_seis_puntos():
    """TRG de una serie 100 -> 140 en 5 periodos: ``(140/100)^(1/5) - 1``."""
    precios = pd.Series([100.0, 105.0, 99.0, 130.0, 128.0, 140.0])
    esperado = (140.0 / 100.0) ** (1.0 / 5.0) - 1.0
    assert trg(precios) == pytest.approx(esperado, rel=1e-12)
    assert trg(precios) == pytest.approx(0.06961037572506878, rel=1e-12)


def test_trg_crecimiento_constante_iguala_el_rendimiento():
    """Con crecimiento geometrico constante la TRG reproduce ese rendimiento."""
    precios = pd.Series([100.0 * (1.10 ** k) for k in range(6)])
    assert trg(precios) == pytest.approx(0.10, rel=1e-12)


def test_trg_es_la_media_geometrica_de_los_factores():
    """La TRG coincide con la media geometrica de los rendimientos simples."""
    precios = pd.Series([100.0, 103.0, 99.5, 104.2, 101.0, 108.0])
    assert trg(precios) == pytest.approx(media_geometrica(rendimientos_simples(precios)), rel=1e-12)


def test_media_geometrica_calculo_explicito():
    """``(prod(1+r))^(1/n) - 1``."""
    rendimientos = pd.Series([0.10, -0.05, 0.02, 0.03])
    esperado = (1.10 * 0.95 * 1.02 * 1.03) ** 0.25 - 1.0
    assert media_geometrica(rendimientos) == pytest.approx(esperado, rel=1e-12)
    assert media_geometrica(pd.Series(dtype="float64")) is None
    # Un rendimiento de -100% hace indefinida la media geometrica
    assert media_geometrica(pd.Series([0.10, -1.0])) is None


@pytest.mark.parametrize(
    "precios",
    [
        pd.Series([100.0]),                      # un solo punto
        pd.Series(dtype="float64"),              # serie vacia
        pd.Series([100.0, 0.0, 120.0]),          # precio no positivo
        pd.Series([100.0, -5.0, 120.0]),         # precio negativo
    ],
)
def test_trg_devuelve_none_sin_datos_validos(precios):
    """Sin al menos dos precios positivos la TRG no es calculable."""
    assert trg(precios) is None


# ==========================================================================
# 3. TLR mensual: modo estandar vs modo excel
# ==========================================================================

TLR = 0.0435


def test_tlr_mensual_modo_excel_usa_mes_de_28_dias():
    """Modo excel: ``TLR/365*28`` (metodologia del libro de referencia)."""
    esperado = TLR / 365.0 * 28.0
    assert tlr_mensual(TLR, "excel") == pytest.approx(esperado, rel=1e-12)
    assert tlr_mensual(TLR, "excel") == pytest.approx(0.003336986301369863, rel=1e-12)
    assert tlr_mensual(TLR) != pytest.approx(esperado, rel=1e-6)


def test_tlr_mensual_modo_estandar_divide_entre_doce():
    """Modo estandar: ``TLR/12``."""
    assert tlr_mensual(TLR, "estandar") == pytest.approx(TLR / 12.0, rel=1e-12)
    assert tlr_mensual(TLR, "estandar") == pytest.approx(0.003625, rel=1e-12)


def test_tlr_mensual_ambos_modos_difieren():
    """Las dos convenciones no son intercambiables: hay una diferencia medible."""
    estandar = tlr_mensual(TLR, "estandar")
    excel = tlr_mensual(TLR, "excel")
    assert estandar == pytest.approx(TLR / 12.0)
    assert excel == pytest.approx(TLR / 365.0 * 28.0)
    assert estandar - excel == pytest.approx(0.0002880137, abs=1e-9)
    assert estandar > excel


def test_tlr_mensual_modo_desconocido_cae_en_estandar():
    """Cualquier modo que no sea ``excel`` se trata como ``estandar``."""
    assert tlr_mensual(TLR, "otro") == pytest.approx(TLR / 12.0)


@pytest.mark.parametrize("valor", [None, float("nan"), float("inf"), "N/D", "abc", ""])
def test_tlr_mensual_devuelve_none_sin_tasa(valor):
    """Sin TLR valida no hay conversion posible."""
    assert tlr_mensual(valor, "estandar") is None
    assert tlr_mensual(valor, "excel") is None


def test_tlr_mensual_acepta_cadena_numerica():
    """La TLR puede llegar como texto (por ejemplo, desde la interfaz)."""
    assert tlr_mensual("4.35%", "estandar") == pytest.approx(4.35 / 12.0, rel=1e-12)


def test_serie_tlr_mensual_aplica_la_conversion_punto_a_punto():
    """``serie_tlr_mensual`` transforma cada valor y conserva el indice."""
    serie = pd.Series([0.04, 0.0425, 0.05], index=pd.date_range("2024-01-31", periods=3, freq="ME"))
    estandar = serie_tlr_mensual(serie, "estandar")
    excel = serie_tlr_mensual(serie, "excel")
    assert list(estandar) == pytest.approx(list(serie / 12.0), rel=1e-12)
    assert list(excel) == pytest.approx(list(serie / 365.0 * 28.0), rel=1e-12)
    assert list(estandar.index) == list(serie.index)
    assert list(excel.index) == list(serie.index)


@pytest.mark.parametrize("entrada", [None, pd.Series(dtype="float64")])
def test_serie_tlr_mensual_sin_datos(entrada):
    """Sin serie anual no hay serie mensual."""
    assert serie_tlr_mensual(entrada, "estandar") is None


def test_anualizar_y_desanualizar_son_coherentes():
    """La anualizacion nominal (x12) se deshace con la division simple."""
    mensual = tlr_mensual(TLR, "estandar")
    assert anualizar(mensual) == pytest.approx(TLR, rel=1e-12)
    assert desanualizar(TLR) == pytest.approx(TLR / 12.0, rel=1e-12)
    compuesta = anualizar(0.01, 12, compuesta=True)
    assert compuesta == pytest.approx(1.01 ** 12 - 1.0, rel=1e-12)
    assert anualizar(None) is None
    assert desanualizar(None) is None
