# -*- coding: utf-8 -*-
"""Pruebas de ``dml.models.econometria`` (MCO de Precio ~ periodo).

Se contrasta el ajuste completo contra ``statsmodels.api.OLS`` (pendiente, error
estandar, t, p, R2, R2 ajustado, F y Durbin-Watson), se comprueba el intervalo de
prediccion, el veredicto de confiabilidad y el rechazo de series demasiado
cortas (``n < 5`` -> ``None``).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from dml.core.tipos import ND
from dml.models.econometria import (
    MIN_OBSERVACIONES,
    durbin_watson,
    interpretar,
    jp_texto,
    ols_econometrico,
    pruebas_residuos,
)

sm = pytest.importorskip("statsmodels.api", reason="statsmodels es necesario para contrastar el MCO")

TOL = 1e-8


@pytest.fixture
def precios_ols() -> pd.Series:
    """Serie mensual con tendencia mas ruido determinista (reproducible)."""
    rng = np.random.default_rng(2024)
    n = 60
    tendencia = 100.0 + 1.8 * np.arange(1, n + 1)
    ruido = rng.normal(0.0, 6.0, n)
    return pd.Series(tendencia + ruido, index=pd.date_range("2019-01-31", periods=n, freq="ME"))


def _modelo_statsmodels(serie: pd.Series):
    """Ajusta el mismo modelo con statsmodels para contrastar."""
    y = np.asarray(serie.values, dtype=float)
    x = np.arange(1, len(y) + 1, dtype=float)
    return sm.OLS(y, sm.add_constant(x)).fit(), x, y


# ==========================================================================
# 1. Cross-validacion contra statsmodels
# ==========================================================================


def test_ols_coincide_con_statsmodels_en_todos_los_estadisticos(precios_ols):
    """Slope, SE, t, p, R2, R2 ajustado, F y Durbin-Watson a ~1e-8."""
    resultado = ols_econometrico(precios_ols, meses_pronostico=12)
    assert resultado is not None
    assert resultado.metodo == "statsmodels"

    modelo, _x, _y = _modelo_statsmodels(precios_ols)

    assert resultado.n == len(precios_ols)
    assert resultado.intercepto == pytest.approx(float(modelo.params[0]), rel=TOL, abs=1e-10)
    assert resultado.pendiente == pytest.approx(float(modelo.params[1]), rel=TOL, abs=1e-12)
    assert resultado.se_intercepto == pytest.approx(float(modelo.bse[0]), rel=TOL, abs=1e-10)
    assert resultado.se_pendiente == pytest.approx(float(modelo.bse[1]), rel=TOL, abs=1e-12)
    assert resultado.t_intercepto == pytest.approx(float(modelo.tvalues[0]), rel=TOL, abs=1e-10)
    assert resultado.t_pendiente == pytest.approx(float(modelo.tvalues[1]), rel=TOL, abs=1e-10)
    assert resultado.p_intercepto == pytest.approx(float(modelo.pvalues[0]), rel=1e-6, abs=1e-12)
    assert resultado.p_pendiente == pytest.approx(float(modelo.pvalues[1]), rel=1e-6, abs=1e-12)
    assert resultado.r2 == pytest.approx(float(modelo.rsquared), rel=TOL, abs=1e-12)
    assert resultado.r2_ajustado == pytest.approx(float(modelo.rsquared_adj), rel=TOL, abs=1e-12)
    assert resultado.f_stat == pytest.approx(float(modelo.fvalue), rel=TOL, abs=1e-8)
    assert resultado.f_pvalue == pytest.approx(float(modelo.f_pvalue), rel=1e-6, abs=1e-12)
    assert resultado.se_regresion == pytest.approx(math.sqrt(float(modelo.mse_resid)), rel=TOL, abs=1e-12)
    assert resultado.durbin_watson == pytest.approx(float(durbin_watson(np.asarray(modelo.resid))), rel=TOL, abs=1e-12)


def test_ols_residuos_y_ajustados_son_coherentes(precios_ols):
    """``residuo = precio observado - precio ajustado`` y suma cero."""
    resultado = ols_econometrico(precios_ols)
    residuos = np.asarray(resultado.residuos, dtype=float)
    ajustados = np.asarray(resultado.ajustados, dtype=float)
    precios = np.asarray(resultado.precios, dtype=float)

    assert len(residuos) == len(ajustados) == len(precios) == len(precios_ols)
    assert np.allclose(residuos, precios - ajustados, atol=1e-9)
    assert abs(float(np.sum(residuos))) < 1e-8
    assert list(resultado.periodos) == list(range(1, len(precios_ols) + 1))


def test_ols_intervalo_de_pronostico(precios_ols):
    """El intervalo se calcula con la t de Student y n - 2 grados de libertad."""
    meses = 6
    resultado = ols_econometrico(precios_ols, meses_pronostico=meses)
    n = len(precios_ols)
    modelo, x, _y = _modelo_statsmodels(precios_ols)

    x0 = float(n + meses)
    se_reg = math.sqrt(float(modelo.mse_resid))
    se_pred = se_reg * math.sqrt(1.0 + 1.0 / n + (x0 - float(np.mean(x))) ** 2 / float(np.sum((x - np.mean(x)) ** 2)))
    centro = float(modelo.params[0]) + float(modelo.params[1]) * x0

    assert resultado.meses_pronostico == meses
    assert resultado.pronostico_precio == pytest.approx(centro, rel=TOL, abs=1e-9)
    assert resultado.pronostico_li < resultado.pronostico_precio < resultado.pronostico_ls
    assert resultado.pronostico_li < resultado.pronostico_ls
    assert (resultado.pronostico_ls - resultado.pronostico_li) / 2.0 == pytest.approx(
        abs(resultado.pronostico_precio - resultado.pronostico_li), rel=1e-9
    )
    # El margen debe ser coherente con el error estandar de prediccion (t ~ 2)
    assert 1.5 * se_pred < (resultado.pronostico_ls - resultado.pronostico_precio) < 2.5 * se_pred


def test_pronostico_mas_lejano_tiene_intervalo_mas_ancho(precios_ols):
    """A mas meses de horizonte, mayor incertidumbre (intervalo mas ancho)."""
    corto = ols_econometrico(precios_ols, meses_pronostico=1)
    largo = ols_econometrico(precios_ols, meses_pronostico=24)
    ancho_corto = corto.pronostico_ls - corto.pronostico_li
    ancho_largo = largo.pronostico_ls - largo.pronostico_li
    assert ancho_largo > ancho_corto > 0.0


# ==========================================================================
# 2. Veredicto de confiabilidad
# ==========================================================================


def test_veredicto_alta_en_serie_casi_perfecta():
    """Una serie practicamente lineal da R2 ~ 1 y veredicto de confiabilidad alta."""
    precios = pd.Series(100.0 + 2.0 * np.arange(1, 41), index=pd.date_range("2020-01-31", periods=40, freq="ME"))
    resultado = ols_econometrico(precios)

    assert resultado is not None
    assert resultado.r2 == pytest.approx(1.0, abs=1e-9)
    assert resultado.r2_ajustado == pytest.approx(1.0, abs=1e-9)
    assert resultado.veredicto == "Alta"
    assert "Confiabilidad Alta" in resultado.justificacion
    assert "R2" in resultado.justificacion and "pendiente significativa" in resultado.justificacion

    interpretacion = interpretar(resultado)
    assert interpretacion["disponible"] is True
    assert interpretacion["r2_supera_umbral"] is True
    assert interpretacion["pendiente_significativa"] is True
    assert interpretacion["veredicto"] == "Alta"


def test_veredicto_baja_con_ruido_sin_tendencia():
    """Sin relacion entre precio y periodo el veredicto no puede ser alto."""
    rng = np.random.default_rng(3)
    precios = pd.Series(100.0 + rng.normal(0.0, 5.0, 40), index=pd.date_range("2020-01-31", periods=40, freq="ME"))
    resultado = ols_econometrico(precios)
    assert resultado is not None
    assert resultado.veredicto in {"Baja", "Media"}
    assert resultado.r2 < 0.70


def test_interpretar_sin_modelo_devuelve_banderas_falsas():
    """``interpretar(None)`` no lanza y deja todo en falso con veredicto N/D."""
    interpretacion = interpretar(None)
    assert interpretacion["disponible"] is False
    assert interpretacion["veredicto"] == ND
    assert all(
        interpretacion[clave] is False
        for clave in (
            "r2_supera_umbral",
            "pendiente_significativa",
            "residuos_autocorrelacionados",
            "residuos_normales",
            "heterocedasticidad",
        )
    )


def test_umbral_de_r2_configurable(precios_ols):
    """El umbral de R2 del veredicto es un parametro y se refleja en la justificacion.

    No se fija el formato exacto del texto (el pliego no lo especifica): se
    comprueba que el R2 aparece con su valor y su veredicto, y que al endurecer
    el umbral el R2 deja de contar como punto a favor.
    """
    resultado_normal = ols_econometrico(precios_ols)
    resultado_estricto = ols_econometrico(precios_ols, r2_min=0.999999)

    assert resultado_normal is not None and resultado_estricto is not None

    # Con el umbral por defecto el R2 (0.9678) si supera el umbral y lo indica
    assert resultado_normal.r2 >= 0.70
    assert "R2" in resultado_normal.justificacion
    assert "0.70" in resultado_normal.justificacion
    assert "Confiabilidad" in resultado_normal.justificacion
    assert resultado_normal.veredicto in {"Alta", "Media", "Baja"}

    # Con un umbral inalcanzable el R2 se marca por debajo y no suma puntos
    assert f"R2 = {resultado_estricto.r2:.4f}" in resultado_estricto.justificacion
    assert "1.00" in resultado_estricto.justificacion
    assert "(+0)" in resultado_estricto.justificacion.split(";")[0]
    assert "pendiente significativa" in resultado_estricto.justificacion
    assert resultado_estricto.veredicto in {"Alta", "Media", "Baja"}

    # La puntuacion publicada es coherente con el veredicto (< 2 -> Baja, etc.)
    puntuacion = int(resultado_estricto.justificacion.split("(")[1].split("/")[0])
    esperado = "Alta" if puntuacion >= 4 else ("Media" if puntuacion >= 2 else "Baja")
    assert resultado_estricto.veredicto == esperado


# ==========================================================================
# 3. Series demasiado cortas
# ==========================================================================


def test_serie_demasiado_corta_devuelve_none():
    """``n < 5`` observaciones no permiten estimar el MCO."""
    assert MIN_OBSERVACIONES == 5
    for n in (0, 1, 2, 3, 4):
        serie = pd.Series(np.linspace(100.0, 110.0, n) if n else [], dtype="float64")
        assert ols_econometrico(serie) is None, f"con n={n} deberia devolver None"


def test_serie_de_cinco_observaciones_si_se_estima():
    """Justo en el minimo (5) el modelo se ajusta."""
    precios = pd.Series([100.0, 102.0, 104.0, 103.0, 107.0], index=pd.date_range("2024-01-31", periods=5, freq="ME"))
    resultado = ols_econometrico(precios)
    assert resultado is not None
    assert resultado.n == 5
    assert resultado.pronostico_li < resultado.pronostico_ls


def test_ols_ignora_valores_invalidos():
    """Los huecos (``None``/``NaN``) se descartan antes de estimar."""
    precios = pd.Series([100.0, np.nan, 106.0, None, 112.0, 115.0, 118.0], dtype="object")
    resultado = ols_econometrico(precios)
    assert resultado is not None
    assert resultado.n == 5


def test_ols_tolera_entrada_no_convertible():
    """Una entrada absurda devuelve ``None`` en lugar de lanzar excepcion."""
    assert ols_econometrico(None) is None
    assert ols_econometrico(pd.Series(["a", "b", "c", "d", "e"])) is None


# ==========================================================================
# 4. Diagnosticos de residuos y utilidades
# ==========================================================================


def test_pruebas_residuos_estructura(precios_ols):
    """La tabla de contrastes incluye Jarque-Bera, Breusch-Pagan y Durbin-Watson."""
    resultado = ols_econometrico(precios_ols)
    tabla = pruebas_residuos(resultado)
    assert len(tabla) == 3
    assert list(tabla.columns) == ["Prueba", "Estadistico", "p-value", "Interpretacion"]
    assert tabla["Prueba"].tolist() == [
        "Jarque-Bera (normalidad)",
        "Breusch-Pagan (heterocedasticidad)",
        "Durbin-Watson (autocorrelacion)",
    ]
    assert tabla["Interpretacion"].str.len().gt(0).all()
    # Durbin-Watson no tiene p-value
    assert math.isnan(float(tabla.loc[2, "p-value"]))


def test_pruebas_residuos_sin_modelo(precios_ols):
    """Sin modelo la tabla llega vacia pero con las columnas correctas."""
    tabla = pruebas_residuos(None)
    assert tabla.empty
    assert list(tabla.columns) == ["Prueba", "Estadistico", "p-value", "Interpretacion"]


def test_durbin_watson_valores_conocidos():
    """``DW = sum((e_t - e_{t-1})^2) / sum(e_t^2)``."""
    residuos = np.array([1.0, -1.0, 1.0, -1.0])
    esperado = float(np.sum(np.diff(residuos) ** 2) / np.sum(residuos ** 2))
    assert durbin_watson(residuos) == pytest.approx(esperado, rel=1e-12)
    assert durbin_watson([1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.0, abs=1e-12)
    assert math.isnan(durbin_watson([0.0, 0.0, 0.0]))
    assert math.isnan(durbin_watson([1.0]))


def test_jp_texto_formatea_y_usa_nd():
    """``jp_texto`` no imprime ``nan``: usa ``N/D``."""
    assert jp_texto(0.05) == "0.0500"
    assert jp_texto(None) == ND
    assert jp_texto(float("nan")) == ND
