# -*- coding: utf-8 -*-
"""Pruebas de ``dml.models.capm``: Beta, prima de riesgo, CAPM y precios objetivo.

Los dos modos del pliego se contrastan de forma explicita:

* ``estandar``: covarianza **muestral** (``ddof=1``) / varianza muestral.
* ``excel``: covarianza **poblacional** (``ddof=0``, como ``COVAR`` de Excel) /
  varianza muestral (``VAR``), y precio proyectado sobre ``PROMEDIO(precios)``,
  que mezcla escalas (inconsistencia documentada).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dml.models.capm import (
    MODO_ESTANDAR,
    MODO_EXCEL,
    beta_covarianza,
    beta_ols,
    nota_inconsistencia_excel,
    precio_objetivo_capm,
    precio_proyectado_trg,
    prima_riesgo_excel,
    prima_riesgo_mercado,
    rendimiento_capm,
)
from dml.models.rendimientos import rendimientos_simples


def math_isfinite(valor: float) -> bool:
    """Utilidad local: comprueba que un numero es finito."""
    return bool(np.isfinite(float(valor)))


@pytest.fixture
def rm_ruidoso() -> pd.Series:
    """Serie mensual de mercado reproducible (24 puntos)."""
    rng = np.random.default_rng(7)
    return pd.Series(rng.normal(0.008, 0.04, 24), name="mercado")


@pytest.fixture
def ra_ruidoso(rm_ruidoso: pd.Series) -> pd.Series:
    """Accion con Beta teorica 1.2 mas ruido idiosincratico."""
    rng = np.random.default_rng(11)
    return pd.Series(1.2 * rm_ruidoso + rng.normal(0.0, 0.02, 24), name="accion")


# ==========================================================================
# 1. Beta por covarianza
# ==========================================================================


def test_beta_serie_sin_ruido_es_el_factor_exacto(par_beta_conocida):
    """Si ``Ra = 1.5 * Rm + c`` la Beta es exactamente 1.5 en ambos modos.

    Con termino independiente la varianza de ``Rm`` no cambia, pero la
    covarianza con ``ddof=0`` (modo excel) se reduce en el factor ``(n-1)/n``.
    """
    ra, rm = par_beta_conocida
    n = len(rm)
    assert beta_covarianza(ra, rm, "estandar") == pytest.approx(1.5, rel=1e-12)
    assert beta_covarianza(ra, rm, "excel") == pytest.approx(1.5 * (n - 1) / n, rel=1e-12)
    # Lo que nunca cambia es la pendiente del MCO
    assert beta_ols(ra, rm) == pytest.approx(1.5, rel=1e-9)


def test_beta_dos_a_uno_exacta():
    """``Ra = 2 * Rm`` (sin termino independiente) => Beta == 2 en modo estandar.

    En modo ``excel`` la Beta es ``1.75`` = ``2 * (n-1)/n`` porque el numerador
    (``COVAR`` poblacional) divide por ``n`` y el denominador (``VAR`` muestral)
    por ``n-1``: es exactamente la inconsistencia que el pliego pide documentar.
    """
    rm = pd.Series([0.01, -0.02, 0.03, 0.015, -0.005, 0.02, -0.01, 0.0])
    ra = 2.0 * rm
    assert beta_covarianza(ra, rm, MODO_ESTANDAR) == pytest.approx(2.0, rel=1e-12)
    n = len(rm)
    assert beta_covarianza(ra, rm, MODO_EXCEL) == pytest.approx(2.0 * (n - 1) / n, rel=1e-12)
    assert beta_covarianza(ra, rm, MODO_EXCEL) == pytest.approx(1.75, rel=1e-12)
    assert beta_ols(ra, rm) == pytest.approx(2.0, rel=1e-9)


def test_beta_modo_excel_vs_estandar_diferencia_numerica(ra_ruidoso, rm_ruidoso):
    """El modo excel usa COVAR poblacional y el estandar covarianza muestral."""
    estandar = beta_covarianza(ra_ruidoso, rm_ruidoso, MODO_ESTANDAR)
    excel = beta_covarianza(ra_ruidoso, rm_ruidoso, MODO_EXCEL)

    cov_muestral = float(np.cov(ra_ruidoso.values, rm_ruidoso.values, ddof=1)[0, 1])
    cov_poblacional = float(np.cov(ra_ruidoso.values, rm_ruidoso.values, ddof=0)[0, 1])
    var_muestral = float(np.var(rm_ruidoso.values, ddof=1))

    assert estandar == pytest.approx(cov_muestral / var_muestral, rel=1e-12)
    assert excel == pytest.approx(cov_poblacional / var_muestral, rel=1e-12)
    # La relacion entre ambos modos es exactamente (n-1)/n
    n = len(ra_ruidoso)
    assert excel == pytest.approx(estandar * (n - 1) / n, rel=1e-12)
    assert excel != pytest.approx(estandar, rel=1e-6)


def test_beta_ols_coincide_con_statsmodels(ra_ruidoso, rm_ruidoso):
    """``beta_ols`` es la pendiente del MCO de ``Ra ~ Rm``."""
    sm = pytest.importorskip("statsmodels.api", reason="statsmodels es necesario para contrastar la Beta MCO")
    esperado = float(sm.OLS(ra_ruidoso.values, sm.add_constant(rm_ruidoso.values)).fit().params[1])
    assert beta_ols(ra_ruidoso, rm_ruidoso) == pytest.approx(esperado, rel=1e-9)


def test_beta_ols_y_covarianza_coinciden_en_modo_estandar(ra_ruidoso, rm_ruidoso):
    """Ambos son el mismo estimador minimo cuadratico."""
    assert beta_ols(ra_ruidoso, rm_ruidoso) == pytest.approx(
        beta_covarianza(ra_ruidoso, rm_ruidoso, MODO_ESTANDAR), rel=1e-9
    )


def test_beta_alinea_series_con_indices_distintos(rm_ruidoso):
    """Solo cuentan las observaciones comunes; con menos de 3 no hay Beta."""
    indice_accion = rm_ruidoso.index[:10]
    ra = pd.Series(1.5 * rm_ruidoso.values[:10], index=indice_accion)
    assert beta_covarianza(ra, rm_ruidoso, MODO_ESTANDAR) == pytest.approx(1.5, rel=1e-12)

    ra_corta = pd.Series([0.01, 0.02], index=rm_ruidoso.index[:2])
    assert beta_covarianza(ra_corta, rm_ruidoso, MODO_ESTANDAR) is None
    assert beta_ols(ra_corta, rm_ruidoso) is None


def test_beta_con_varianza_de_mercado_nula(ra_ruidoso):
    """Si el mercado no se mueve la Beta es indefinida (``None``)."""
    rm_constante = pd.Series(np.zeros(len(ra_ruidoso)), index=ra_ruidoso.index)
    assert beta_covarianza(ra_ruidoso, rm_constante, MODO_ESTANDAR) is None
    assert beta_covarianza(ra_ruidoso, rm_constante, MODO_EXCEL) is None


def test_beta_y_capm_sobre_series_del_conftest(precios_mensuales, precios_indice):
    """Prueba de integracion con las series sinteticas de la suite."""
    ra = rendimientos_simples(precios_mensuales)
    rm = rendimientos_simples(precios_indice)
    beta = beta_covarianza(ra, rm, MODO_ESTANDAR)
    assert beta is not None
    assert math_isfinite(beta)
    assert beta == pytest.approx(beta_ols(ra, rm), rel=1e-9)


# ==========================================================================
# 2. Primas de riesgo
# ==========================================================================


def test_prima_riesgo_excel_usa_los_rendimientos_de_la_accion():
    """Modo excel: media mensual de ``(R_accion - R_TLR)``."""
    ra = pd.Series([0.05, -0.02, 0.03])
    rf = pd.Series([0.004, 0.004, 0.004])
    assert prima_riesgo_excel(ra, rf) == pytest.approx(float((ra - rf).mean()), rel=1e-12)
    assert prima_riesgo_excel(ra, rf) == pytest.approx(0.016, rel=1e-12)


def test_prima_riesgo_mercado_anualiza_multiplicando_por_doce():
    """Modo estandar: ``E[Rm - Rf]`` mensual multiplicada por 12."""
    rm = pd.Series([0.020, 0.010, 0.030, 0.000])
    rf = pd.Series([0.004, 0.004, 0.004, 0.004])
    mensual = prima_riesgo_mercado(rm, rf, anualizar=False)
    anual = prima_riesgo_mercado(rm, rf, anualizar=True)
    assert mensual == pytest.approx(float((rm - rf).mean()), rel=1e-12)
    assert anual == pytest.approx(mensual * 12.0, rel=1e-12)
    assert prima_riesgo_mercado(rm, rf, anualizar=True, periodos_por_anio=4) == pytest.approx(mensual * 4.0)


def test_prima_riesgo_mercado_alinea_y_tolera_vacios():
    """Sin observaciones comunes no hay prima de riesgo."""
    rm = pd.Series([0.01, 0.02], index=pd.date_range("2024-01-31", periods=2, freq="ME"))
    rf_otro = pd.Series([0.001], index=pd.date_range("2025-01-31", periods=1, freq="ME"))
    assert prima_riesgo_mercado(rm, rf_otro) is None


# ==========================================================================
# 3. CAPM y precios objetivo
# ==========================================================================


def test_rendimiento_capm_aritmetica():
    """``Rend_CAPM = TLR + Beta x PRH``."""
    assert rendimiento_capm(0.04, 1.2, 0.05) == pytest.approx(0.10, rel=1e-12)
    assert rendimiento_capm(0.0435, 0.9, 0.06) == pytest.approx(0.0435 + 0.054, rel=1e-12)
    assert rendimiento_capm(0.04, 0.0, 0.05) == pytest.approx(0.04, rel=1e-12)
    assert rendimiento_capm(0.04, -0.5, 0.05) == pytest.approx(0.015, rel=1e-12)


@pytest.mark.parametrize(
    ("tlr", "beta", "prh"),
    [(None, 1.0, 0.05), (0.04, None, 0.05), (0.04, 1.0, None), (0.04, "N/D", 0.05)],
)
def test_rendimiento_capm_propaga_nd(tlr, beta, prh):
    """Si falta cualquiera de los tres factores el CAPM es N/D."""
    assert rendimiento_capm(tlr, beta, prh) is None


def test_precio_objetivo_capm_aritmetica():
    """``Precio objetivo = Spot x (1 + Rend_CAPM)``."""
    assert precio_objetivo_capm(100.0, 0.10) == pytest.approx(110.0, rel=1e-12)
    assert precio_objetivo_capm(250.0, -0.04) == pytest.approx(240.0, rel=1e-12)
    assert precio_objetivo_capm(None, 0.10) is None
    assert precio_objetivo_capm(100.0, None) is None


def test_flujo_completo_beta_prima_capm_objetivo(ra_ruidoso, rm_ruidoso):
    """Cadena completa: Beta -> prima de mercado -> CAPM -> precio objetivo."""
    rf_mensual = pd.Series(np.full(len(rm_ruidoso), 0.0435 / 12.0), index=rm_ruidoso.index)
    beta = beta_covarianza(ra_ruidoso, rm_ruidoso, MODO_ESTANDAR)
    prh = prima_riesgo_mercado(rm_ruidoso, rf_mensual, anualizar=True)
    tlr = 0.0435
    esperado = tlr + beta * prh
    assert rendimiento_capm(tlr, beta, prh) == pytest.approx(esperado, rel=1e-12)
    assert precio_objetivo_capm(200.0, esperado) == pytest.approx(200.0 * (1.0 + esperado), rel=1e-12)


# ==========================================================================
# 4. Precio proyectado con la TRG en ambos modos
# ==========================================================================


def test_precio_proyectado_trg_modo_estandar():
    """Modo estandar: ``Spot x (1 + TRG)^meses`` (mantiene la escala del spot)."""
    trg_mensual = 0.01
    esperado = 100.0 * (1.01 ** 12)
    assert precio_proyectado_trg(100.0, trg_mensual, 12, MODO_ESTANDAR) == pytest.approx(esperado, rel=1e-12)
    assert precio_proyectado_trg(100.0, trg_mensual, 1, MODO_ESTANDAR) == pytest.approx(101.0, rel=1e-12)
    assert precio_proyectado_trg(100.0, 0.0, 24, MODO_ESTANDAR) == pytest.approx(100.0, rel=1e-12)


def test_precio_proyectado_trg_modo_excel_usa_el_promedio():
    """Modo excel: ``PROMEDIO(precios) x (1 + TRG)``; ignora el spot."""
    precios = pd.Series([100.0, 120.0, 140.0])  # media = 120
    proyectado = precio_proyectado_trg(200.0, 0.05, 12, MODO_EXCEL, precios)
    assert proyectado == pytest.approx(120.0 * 1.05, rel=1e-12)
    # El spot NO interviene en modo excel: dos spots distintos dan lo mismo
    assert precio_proyectado_trg(999.0, 0.05, 12, MODO_EXCEL, precios) == pytest.approx(proyectado, rel=1e-12)
    # Un solo mes de proyeccion, no la capitalizacion de 12
    assert proyectado != pytest.approx(200.0 * (1.05 ** 12), rel=1e-6)


def test_precio_proyectado_trg_inconsistencia_de_escala_documentada():
    """El modo excel mezcla la escala del promedio historico con la del spot."""
    precios = pd.Series([50.0, 100.0, 150.0])  # media 100, spot actual 300
    estandar = precio_proyectado_trg(300.0, 0.02, 12, MODO_ESTANDAR, precios)
    excel = precio_proyectado_trg(300.0, 0.02, 12, MODO_EXCEL, precios)
    assert excel == pytest.approx(102.0, rel=1e-12)
    assert estandar == pytest.approx(300.0 * 1.02 ** 12, rel=1e-12)
    assert excel < estandar / 3.0, "la inconsistencia de escala debe ser evidente"

    nota = nota_inconsistencia_excel(300.0, excel, estandar)
    assert "MODO EXCEL" in nota
    assert "PROMEDIO(precios)" in nota
    assert "300.00" in nota and "102.00" in nota


@pytest.mark.parametrize(
    ("spot", "trg_valor", "modo", "precios"),
    [
        (None, 0.01, MODO_ESTANDAR, None),
        (100.0, None, MODO_ESTANDAR, None),
        (100.0, 0.01, MODO_EXCEL, None),                      # excel necesita la serie
        (100.0, 0.01, MODO_EXCEL, pd.Series(dtype="float64")),  # serie vacia
        (100.0, None, MODO_EXCEL, pd.Series([100.0, 110.0])),
        ("N/D", 0.01, MODO_ESTANDAR, None),
    ],
)
def test_precio_proyectado_trg_devuelve_none_sin_datos(spot, trg_valor, modo, precios):
    """Faltando el spot (estandar) o la serie (excel) no hay proyeccion."""
    assert precio_proyectado_trg(spot, trg_valor, 12, modo, precios) is None


def test_precio_proyectado_trg_excel_con_serie_del_conftest(precios_mensuales):
    """Modo excel sobre las series sinteticas de la suite."""
    proyectado = precio_proyectado_trg(999.0, 0.01, 12, MODO_EXCEL, precios_mensuales)
    assert proyectado == pytest.approx(float(precios_mensuales.mean()) * 1.01, rel=1e-12)
