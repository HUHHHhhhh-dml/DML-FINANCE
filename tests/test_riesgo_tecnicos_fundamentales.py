# -*- coding: utf-8 -*-
"""Pruebas de riesgo, indicadores tecnicos y fundamentales.

Cubre:

* ``dml.models.riesgo``: anualizacion de la sigma (``sqrt(12)``), descomposicion
  del riesgo en sistematico y no sistematico, orden del VaR (el 99% es mas
  negativo que el 95%), aritmetica de Sharpe/Treynor y maxima caida.
* ``dml.models.tecnicos``: MACD y su clasificacion en Buy/Sell/Neutral sobre
  series fabricadas a proposito.
* ``dml.models.fundamentales``: PER, Renta PER, Price to FCF y RDR, incluida la
  propagacion de ``None`` (N/D).
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from dml.models.fundamentales import (
    margen_seguridad,
    per_valor,
    price_to_fcf,
    rdr,
    renta_per,
)
from dml.models.riesgo import (
    cuantil_normal,
    max_drawdown,
    metricas_riesgo,
    ratio_sharpe,
    ratio_treynor,
    var_parametrico,
)
from dml.models.tecnicos import calcular_macd, clasificar_macd, macd_resumen


# ==========================================================================
# 1. Riesgo
# ==========================================================================


@pytest.fixture
def rendimientos_riesgo() -> tuple[pd.Series, pd.Series]:
    """Par (R_accion, R_mercado) con Beta aproximada de 1.1."""
    rng = np.random.default_rng(3)
    rm = pd.Series(rng.normal(0.010, 0.040, 60), index=pd.date_range("2019-01-31", periods=60, freq="ME"))
    ra = pd.Series(1.1 * rm.values + rng.normal(0.0, 0.020, 60), index=rm.index)
    return ra, rm


def test_sigma_se_anualiza_con_raiz_de_doce(rendimientos_riesgo):
    """``sigma_anual = sigma_mensual * sqrt(12)`` en modo estandar."""
    ra, rm = rendimientos_riesgo
    metricas = metricas_riesgo(ra, rm, beta=1.1, tlr=0.04)
    assert metricas.sigma_mensual == pytest.approx(float(np.std(ra.values, ddof=1)), rel=1e-12)
    assert metricas.sigma_anual == pytest.approx(metricas.sigma_mensual * math.sqrt(12.0), rel=1e-12)
    assert "sqrt(12)" in metricas.nota_sigma


def test_modo_excel_usa_la_sigma_mensual_y_avisa(rendimientos_riesgo):
    """En modo excel la sigma no se anualiza y queda constancia en la nota."""
    ra, rm = rendimientos_riesgo
    metricas = metricas_riesgo(ra, rm, beta=1.1, tlr=0.04, modo="excel")
    assert metricas.sigma_anual == pytest.approx(metricas.sigma_mensual, rel=1e-12)
    assert "MENSUAL" in metricas.nota_sigma
    assert "Black-Scholes" in metricas.nota_sigma


def test_descomposicion_sistematica_y_no_sistematica(rendimientos_riesgo):
    """``Var(Ra) = Beta^2 Var(Rm) + Var(residuo)`` (riesgo total = suma)."""
    ra, rm = rendimientos_riesgo
    beta = 1.1
    metricas = metricas_riesgo(ra, rm, beta=beta, tlr=0.04)

    var_mercado = float(np.var(rm.values, ddof=1))
    sistematico_esperado = beta ** 2 * var_mercado
    total_esperado = float(np.var(ra.values, ddof=1))

    assert metricas.riesgo_total == pytest.approx(total_esperado, rel=1e-12)
    assert metricas.riesgo_sistematico == pytest.approx(sistematico_esperado, rel=1e-12)
    assert metricas.riesgo_no_sistematico == pytest.approx(total_esperado - sistematico_esperado, rel=1e-9)
    assert metricas.riesgo_sistematico + metricas.riesgo_no_sistematico == pytest.approx(
        metricas.riesgo_total, rel=1e-9
    )
    assert metricas.riesgo_sistematico >= 0.0
    assert metricas.riesgo_no_sistematico >= 0.0


def test_riesgo_sistematico_domina_con_beta_alta(rendimientos_riesgo):
    """Con Beta = 2 el riesgo sistematico explica la mayor parte de la varianza."""
    ra, rm = rendimientos_riesgo
    metricas = metricas_riesgo(ra, rm, beta=2.0)
    assert metricas.riesgo_sistematico > metricas.riesgo_no_sistematico
    assert metricas.riesgo_no_sistematico >= 0.0


def test_var_parametrico_aritmetica():
    """``VaR = mu + z_alpha * sigma`` con ``z`` negativo en la cola izquierda."""
    mu, sigma = 0.008, 0.05
    z95 = NormalDist().inv_cdf(0.05)
    z99 = NormalDist().inv_cdf(0.01)
    assert var_parametrico(mu, sigma, 0.95) == pytest.approx(mu + z95 * sigma, rel=1e-12)
    assert var_parametrico(mu, sigma, 0.99) == pytest.approx(mu + z99 * sigma, rel=1e-12)
    assert var_parametrico(mu, sigma, 0.95) == pytest.approx(-0.0742426, abs=1e-6)
    assert var_parametrico(None, sigma) is None
    assert var_parametrico(mu, None) is None
    assert cuantil_normal(0.975) == pytest.approx(1.959963985, rel=1e-9)


def test_var_99_es_mas_negativo_que_el_95(rendimientos_riesgo):
    """El VaR al 99% esta mas a la izquierda que el del 95%."""
    ra, rm = rendimientos_riesgo
    metricas = metricas_riesgo(ra, rm, beta=1.1, tlr=0.04)
    assert metricas.var_99 < metricas.var_95
    assert metricas.var_95 < 0.0 and metricas.var_99 < 0.0
    # Ambos coinciden con la formula parametrica con la sigma mensual
    mu = float(np.mean(ra.values))
    sigma = float(np.std(ra.values, ddof=1))
    assert metricas.var_95 == pytest.approx(mu + NormalDist().inv_cdf(0.05) * sigma, rel=1e-12)
    assert metricas.var_99 == pytest.approx(mu + NormalDist().inv_cdf(0.01) * sigma, rel=1e-12)


def test_sharpe_y_treynor_aritmetica(rendimientos_riesgo):
    """``Sharpe = (R_anual - TLR)/sigma_anual`` y ``Treynor = (R_anual - TLR)/Beta``."""
    ra, rm = rendimientos_riesgo
    tlr = 0.04
    beta = 1.1
    metricas = metricas_riesgo(ra, rm, beta=beta, tlr=tlr)
    r_anual = float(np.mean(ra.values)) * 12.0
    assert metricas.sharpe == pytest.approx((r_anual - tlr) / metricas.sigma_anual, rel=1e-12)
    assert metricas.treynor == pytest.approx((r_anual - tlr) / beta, rel=1e-12)

    # Funciones sueltas: mismo numerador, distinto denominador
    assert ratio_sharpe(0.10, 0.04, 0.20) == pytest.approx(0.30, rel=1e-12)
    assert ratio_treynor(0.10, 0.04, 0.80) == pytest.approx(0.075, rel=1e-12)
    assert ratio_sharpe(0.10, 0.04, 0.0) is None
    assert ratio_treynor(0.10, 0.04, 0.0) is None
    assert ratio_sharpe(None, 0.04, 0.20) is None


def test_max_drawdown_calculo():
    """Caida maxima como fraccion negativa del pico previo."""
    precios = pd.Series([100.0, 120.0, 90.0, 110.0])
    assert max_drawdown(precios) == pytest.approx(-0.25, rel=1e-12)
    assert max_drawdown(pd.Series([100.0, 110.0, 120.0])) == pytest.approx(0.0, abs=1e-12)
    assert max_drawdown(pd.Series([100.0, 50.0, 200.0, 100.0])) == pytest.approx(-0.50, rel=1e-12)
    assert max_drawdown(pd.Series([100.0])) is None
    assert max_drawdown(pd.Series(dtype="float64")) is None


def test_max_drawdown_en_metricas_usa_los_precios(rendimientos_riesgo):
    """Si se pasan precios, la caida se calcula sobre ellos."""
    ra, rm = rendimientos_riesgo
    precios = pd.Series(np.linspace(100.0, 80.0, 60), index=ra.index)
    metricas = metricas_riesgo(ra, rm, beta=1.1, tlr=0.04, precios=precios)
    assert metricas.max_drawdown == pytest.approx(max_drawdown(precios), rel=1e-12)
    assert metricas.max_drawdown <= 0.0


def test_metricas_riesgo_sin_datos_suficientes():
    """Con menos de dos rendimientos no hay metricas: se informa y no se lanza."""
    metricas = metricas_riesgo(pd.Series([0.01]))
    assert metricas.sigma_mensual is None
    assert metricas.sigma_anual is None
    assert metricas.nota_sigma

    metricas_vacio = metricas_riesgo(pd.Series(dtype="float64"))
    assert metricas_vacio.sigma_anual is None
    assert metricas_vacio.sharpe is None
    assert metricas_vacio.max_drawdown is None


def test_metricas_riesgo_sin_mercado_no_descompone(rendimientos_riesgo):
    """Sin ``rm``/``beta`` no hay descomposicion, pero si sigma y VaR."""
    ra, _rm = rendimientos_riesgo
    metricas = metricas_riesgo(ra, tlr=0.04)
    assert metricas.riesgo_sistematico is None
    assert metricas.riesgo_no_sistematico is None
    assert metricas.sigma_anual is not None
    assert metricas.var_95 is not None and metricas.var_99 is not None


# ==========================================================================
# 2. Indicadores tecnicos: MACD
# ==========================================================================


def _serie_alcista(n: int = 120) -> pd.Series:
    """Serie con crecimiento exponencial **acelerado**: histograma MACD creciente.

    Los precios pasan de ~100 a ~159 en seis meses con la tasa de crecimiento
    subiendo mes a mes, que es el escenario que la regla 1 del clasificador
    (histograma positivo y creciente) identifica como ``Buy``.
    """
    t = np.arange(n, dtype=float)
    base = 100.0 * np.exp(0.0015 * t + 0.00002 * t ** 2)
    return pd.Series(base, index=pd.date_range("2023-01-02", periods=n, freq="B"))


def _serie_bajista(n: int = 120) -> pd.Series:
    """Serie con crecimiento exponencial **desacelerado**: histograma decreciente.

    Los precios siguen subiendo (~100 a ~154) pero cada vez mas despacio, que es
    el escenario que la regla 2 (histograma negativo y decreciente) identifica
    como ``Sell``.
    """
    t = np.arange(n, dtype=float)
    base = 100.0 * np.exp(0.006 * t - 0.00002 * t ** 2)
    return pd.Series(base, index=pd.date_range("2023-01-02", periods=n, freq="B"))


def test_calcular_macd_estructura_y_formula():
    """Columnas ``macd``/``senal``/``histograma`` e ``hist = macd - senal``."""
    precios = _serie_alcista()
    macd = calcular_macd(precios)
    assert macd is not None
    assert list(macd.columns) == ["macd", "senal", "histograma"]
    assert len(macd) == len(precios)
    assert np.allclose(macd["histograma"], macd["macd"] - macd["senal"])

    # La linea MACD es EMA(12) - EMA(26) con adjust=False
    esperado = precios.ewm(span=12, adjust=False).mean() - precios.ewm(span=26, adjust=False).mean()
    assert np.allclose(macd["macd"], esperado)
    señal_esperada = esperado.ewm(span=9, adjust=False).mean()
    assert np.allclose(macd["senal"], señal_esperada)


def test_macd_serie_insuficiente():
    """Por debajo de ``lenta + senal`` (35) no hay MACD."""
    assert calcular_macd(pd.Series(np.arange(34, dtype=float))) is None
    assert calcular_macd(pd.Series([1.0, 2.0, 3.0])) is None
    assert calcular_macd(pd.Series(dtype="float64")) is None
    assert calcular_macd(_serie_alcista(35)) is not None


def test_clasificar_macd_compra_en_serie_alcista():
    """Histograma positivo y creciente -> Buy."""
    senal, detalle = clasificar_macd(calcular_macd(_serie_alcista()))
    assert senal == "Buy"
    assert "alcista" in detalle or "positivo" in detalle


def test_clasificar_macd_venta_en_serie_bajista():
    """Histograma negativo y decreciente -> Sell."""
    senal, detalle = clasificar_macd(calcular_macd(_serie_bajista()))
    assert senal == "Sell"
    assert "bajista" in detalle or "negativo" in detalle


def test_clasificar_macd_neutral_con_histograma_plano():
    """Sin direccion clara -> Neutral."""
    datos = pd.DataFrame(
        {
            "macd": [0.0, 0.0, 0.0, 0.0],
            "senal": [0.0, 0.0, 0.0, 0.0],
            "histograma": [0.05, 0.04, 0.03, 0.02],
        }
    )
    senal, detalle = clasificar_macd(datos)
    assert senal == "Neutral"
    assert "sin direccion clara" in detalle.lower()

    # Un histograma descendente tambien es Neutral: no hay cruce en el ultimo punto
    datos_descendentes = datos.assign(histograma=[0.02, 0.01, 0.005, 0.002])
    assert clasificar_macd(datos_descendentes)[0] == "Neutral"

    # Histograma constante en cero (precios estables) es Neutral
    datos_planos = datos.assign(histograma=[0.0, 0.0, 0.0, 0.0])
    assert clasificar_macd(datos_planos)[0] == "Neutral"


def test_clasificar_macd_por_cruce():
    """Cruce de negativo a positivo -> Buy; de positivo a negativo -> Sell."""
    cruce_al_alza = pd.DataFrame(
        {"macd": [0.0] * 4, "senal": [0.0] * 4, "histograma": [-0.05, -0.02, -0.01, 0.01]}
    )
    assert clasificar_macd(cruce_al_alza)[0] == "Buy"
    cruce_a_la_baja = pd.DataFrame(
        {"macd": [0.0] * 4, "senal": [0.0] * 4, "histograma": [0.05, 0.02, 0.01, -0.01]}
    )
    assert clasificar_macd(cruce_a_la_baja)[0] == "Sell"


def test_clasificar_macd_sin_datos():
    """Sin datos suficientes la senal es ``N/D`` con explicacion."""
    assert clasificar_macd(None) == ("N/D", "Serie insuficiente para calcular el MACD (se necesitan al menos 35 cierres diarios)")
    senal, detalle = clasificar_macd(pd.DataFrame({"histograma": [0.1, 0.2]}))
    assert senal == "N/D"
    assert "insuficiente" in detalle.lower()


def test_macd_resumen_recorta_los_ultimos_dias():
    """``macd_resumen`` calcula el MACD sobre la cola de la serie."""
    precios = _serie_alcista(200)
    datos, senal, detalle = macd_resumen(precios, dias=30)
    assert datos is not None
    assert senal == "Buy"
    assert isinstance(detalle, str) and detalle
    # 30 dias + margen (lenta + senal) = 65 puntos como maximo
    assert len(datos) <= 30 + 26 + 9


# ==========================================================================
# 3. Fundamentales
# ==========================================================================


def test_per_valor_aritmetica():
    """``PER = Precio / EPS``."""
    per, nota = per_valor(100.0, 4.0)
    assert per == pytest.approx(25.0, rel=1e-12)
    assert nota == ""
    assert per_valor(90.0, 3.0)[0] == pytest.approx(30.0, rel=1e-12)


@pytest.mark.parametrize(
    ("precio", "eps"),
    [(None, 4.0), (100.0, None), (100.0, 0.0), (None, None), (float("nan"), 4.0), (100.0, "N/D")],
)
def test_per_valor_propaga_nd(precio, eps):
    """Sin precio o sin EPS (o con EPS nulo) el PER es N/D con su nota."""
    per, nota = per_valor(precio, eps)
    assert per is None
    assert nota.startswith("N/D")


def test_per_valor_rechaza_per_negativo():
    """Un PER negativo (perdidas) no es comparable: N/D con nota explicativa."""
    per, nota = per_valor(100.0, -2.0)
    assert per is None
    assert "negativo" in nota
    assert "perdidas" in nota


def test_renta_per_aritmetica():
    """``Renta PER = 1 / PER``."""
    renta, nota = renta_per(25.0)
    assert renta == pytest.approx(0.04, rel=1e-12)
    assert nota == ""
    assert renta_per(20.0)[0] == pytest.approx(0.05, rel=1e-12)


@pytest.mark.parametrize("per", [None, 0.0, -10.0, float("nan")])
def test_renta_per_propaga_nd(per):
    """Sin PER positivo la Renta PER no es interpretable."""
    renta, nota = renta_per(per)
    assert renta is None
    assert nota.startswith("N/D")


def test_price_to_fcf_aritmetica():
    """``P/FCF = Capitalizacion / Free Cash Flow``."""
    p_fcf, nota = price_to_fcf(1.0e11, 4.0e9)
    assert p_fcf == pytest.approx(25.0, rel=1e-12)
    assert nota == ""
    # Via alternativa: precio / FCF por accion
    p_fcf2, nota2 = price_to_fcf(None, None, precio=100.0, fcf_por_accion=5.0)
    assert p_fcf2 == pytest.approx(20.0, rel=1e-12)
    assert nota2 == ""


@pytest.mark.parametrize(
    ("market_cap", "fcf"),
    [(None, 4.0e9), (1.0e11, None), (1.0e11, 0.0), (1.0e11, -1.0e9), (None, None)],
)
def test_price_to_fcf_propaga_nd(market_cap, fcf):
    """Sin capitalizacion o con FCF no positivo el multiplo no es interpretable."""
    p_fcf, nota = price_to_fcf(market_cap, fcf)
    assert p_fcf is None
    assert nota.startswith("N/D")


def test_rdr_aritmetica():
    """``RDR = Rend_CAPM / Riesgo`` y ademas la diferencia Rend_CAPM - Riesgo."""
    cociente, diferencia, nota = rdr(0.10, 0.20)
    assert cociente == pytest.approx(0.5, rel=1e-12)
    assert diferencia == pytest.approx(-0.10, rel=1e-12)
    assert nota == ""

    cociente2, diferencia2, _ = rdr(0.25, 0.20)
    assert cociente2 == pytest.approx(1.25, rel=1e-12)
    assert diferencia2 == pytest.approx(0.05, rel=1e-12)


@pytest.mark.parametrize(("rend", "riesgo"), [(None, 0.2), (0.1, None), (None, None), (float("nan"), 0.2)])
def test_rdr_propaga_nd(rend, riesgo):
    """Sin rendimiento CAPM o sin riesgo no hay RDR."""
    cociente, diferencia, nota = rdr(rend, riesgo)
    assert cociente is None
    assert diferencia is None
    assert nota.startswith("N/D")


def test_rdr_con_riesgo_nulo_o_negativo():
    """El cociente no se define con riesgo <= 0, pero la diferencia si."""
    cociente, diferencia, nota = rdr(0.10, 0.0)
    assert cociente is None
    assert diferencia == pytest.approx(0.10, rel=1e-12)
    assert "no esta definido" in nota

    cociente2, diferencia2, _ = rdr(0.10, -0.05)
    assert cociente2 is None
    assert diferencia2 == pytest.approx(0.15, rel=1e-12)


def test_margen_seguridad():
    """``(Precio objetivo - Spot) / Spot``."""
    assert margen_seguridad(100.0, 120.0) == pytest.approx(0.20, rel=1e-12)
    assert margen_seguridad(100.0, 80.0) == pytest.approx(-0.20, rel=1e-12)
    assert margen_seguridad(0.0, 120.0) is None
    assert margen_seguridad(None, 120.0) is None
