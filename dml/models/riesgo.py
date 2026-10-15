# -*- coding: utf-8 -*-
"""Metricas de riesgo sobre rendimientos mensuales.

Convenios
---------
* ``sigma_mensual`` es la desviacion tipica **muestral** (``ddof=1``) de los
  rendimientos mensuales.
* ``sigma_anual = sigma_mensual * sqrt(12)`` [ESTÃNDAR]. La volatilidad que
  entra en Black-Scholes **debe** ser anual; en modo ``excel`` se usa la mensual
  sin anualizar y se deja constancia en :attr:`MetricasRiesgo.nota_sigma`.
* Descomposicion del riesgo total: ``Var(Ra) = Beta^2 Var(Rm) + Var(residuo)``,
  de modo que ``riesgo_total = riesgo_sistematico + riesgo_no_sistematico``.
* VaR parametrico: ``VaR = mu + z_alpha * sigma`` con ``z`` negativo para
  colas a la izquierda; se informa como rendimiento (negativo) del periodo.
"""

from __future__ import annotations

import logging
import math
from statistics import NormalDist
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from ..core.tipos import MetricasRiesgo
from ..core.util import a_float

LOG = logging.getLogger("dml.riesgo")

PERIODOS_ANIO = 12


def cuantil_normal(p: float) -> float:
    """Cuantil de la normal estandar (sin depender de scipy)."""
    return float(NormalDist().inv_cdf(p))


def _sigma_muestral(datos: np.ndarray, ddof: int = 1) -> Optional[float]:
    """Desviacion tipica de un vector, o ``None`` si no hay datos suficientes."""
    if datos is None or len(datos) < 2:
        return None
    s = float(np.std(datos, ddof=ddof))
    return s if math.isfinite(s) else None


def var_parametrico(
    media: Optional[float], sigma: Optional[float], confianza: float = 0.95, horizonte: float = 1.0
) -> Optional[float]:
    """VaR parametrico (normal) como rendimiento del periodo.

    Args:
        media: rendimiento medio del periodo.
        sigma: desviacion tipica del periodo.
        confianza: nivel de confianza (0.95 -> z = -1.6449).
        horizonte: numero de periodos; escala ``mu`` y ``sigma`` por ``h`` y
            ``sqrt(h)`` respectivamente.

    Returns:
        El VaR como rendimiento (tipicamente negativo), o ``None``.
    """
    mu, s = a_float(media), a_float(sigma)
    if mu is None or s is None:
        return None
    h = float(horizonte) if horizonte and horizonte > 0 else 1.0
    z = cuantil_normal(1.0 - float(confianza))
    return float(mu * h + z * s * math.sqrt(h))


def ratio_sharpe(rendimiento: Optional[float], tlr: Optional[float], sigma: Optional[float]) -> Optional[float]:
    """``Sharpe = (R - TLR) / sigma`` con magnitudes en la misma escala."""
    r, rf, s = a_float(rendimiento), a_float(tlr), a_float(sigma)
    if r is None or rf is None or s is None or s == 0:
        return None
    return (r - rf) / s


def ratio_treynor(rendimiento: Optional[float], tlr: Optional[float], beta: Optional[float]) -> Optional[float]:
    """``Treynor = (R - TLR) / Beta`` (riesgo sistematico como denominador)."""
    r, rf, b = a_float(rendimiento), a_float(tlr), a_float(beta)
    if r is None or rf is None or b is None or b == 0:
        return None
    return (r - rf) / b


def max_drawdown(precios: pd.Series) -> Optional[float]:
    """Maxima caida desde un pico previo, como fraccion negativa (``-0.25`` = -25%)."""
    p = pd.Series(precios).astype(float).dropna()
    if len(p) < 2:
        return None
    pico = p.cummax()
    caida = (p - pico) / pico
    valor = float(caida.min())
    return valor if math.isfinite(valor) else None


def metricas_riesgo(
    ra: pd.Series,
    rm: Optional[pd.Series] = None,
    beta: Optional[float] = None,
    tlr: Optional[float] = None,
    confianzas: Sequence[float] = (0.95, 0.99),
    modo: str = "estandar",
    precios: Optional[pd.Series] = None,
) -> MetricasRiesgo:
    """Calcula el bloque completo de riesgo.

    Args:
        ra: rendimientos mensuales de la accion.
        rm: rendimientos mensuales del mercado (para descomponer el riesgo).
        beta: Beta estimada.
        tlr: tasa libre de riesgo **anual** en fraccion (para Sharpe/Treynor).
        confianzas: niveles de VaR a informar (0.95 y 0.99 por defecto).
        modo: ``estandar`` anualiza la sigma; ``excel`` la deja mensual y avisa.
        precios: serie de precios para la maxima caida (si no, se usa ``ra``
            como aproximacion acumulada).

    Returns:
        Una instancia de :class:`~dml.core.tipos.MetricasRiesgo`.
    """
    resultado = MetricasRiesgo()
    r = pd.Series(ra).astype(float).dropna() if ra is not None else pd.Series(dtype="float64")
    if len(r) < 2:
        resultado.nota_sigma = "Sin rendimientos suficientes para calcular el riesgo"
        return resultado

    valores = r.values
    sigma_m = _sigma_muestral(valores, ddof=1)
    resultado.sigma_mensual = sigma_m
    if sigma_m is None:
        resultado.nota_sigma = "Varianza no calculable"
        return resultado

    if modo == "excel":
        resultado.sigma_anual = sigma_m
        resultado.nota_sigma = (
            "MODO EXCEL: se usa la sigma MENSUAL sin anualizar. La sigma de Black-Scholes debe ser anual."
        )
    else:
        resultado.sigma_anual = sigma_m * math.sqrt(PERIODOS_ANIO)
        resultado.nota_sigma = f"Sigma anualizada: {sigma_m:.6f} x sqrt(12)"

    var_r = float(np.var(valores, ddof=1))
    resultado.riesgo_total = var_r

    if rm is not None and beta is not None:
        datos = pd.concat(
            [r.rename("a"), pd.Series(rm).astype(float).rename("m")], axis=1, sort=False
        ).dropna()
        if len(datos) >= 3:
            var_m = float(np.var(datos["m"].values, ddof=1))
            sistematico = float(beta) ** 2 * var_m
            resultado.riesgo_sistematico = sistematico
            resultado.riesgo_no_sistematico = max(var_r - sistematico, 0.0)

    mu = float(np.mean(valores))
    z95 = cuantil_normal(1.0 - float(confianzas[0]))
    resultado.var_95 = float(mu + z95 * sigma_m)
    if len(confianzas) > 1:
        z99 = cuantil_normal(1.0 - float(confianzas[1]))
        resultado.var_99 = float(mu + z99 * sigma_m)

    sigma_anual = resultado.sigma_anual
    resultado.sharpe = ratio_sharpe(mu * PERIODOS_ANIO, tlr, sigma_anual)
    resultado.treynor = ratio_treynor(mu * PERIODOS_ANIO, tlr, beta)

    if precios is not None and len(pd.Series(precios).dropna()) >= 2:
        resultado.max_drawdown = max_drawdown(precios)
    else:
        acumulado = (1.0 + r).cumprod()
        resultado.max_drawdown = max_drawdown(acumulado)
    return resultado


def tabla_riesgo(metricas: MetricasRiesgo) -> pd.DataFrame:
    """Tabla "metrica / valor / formula" para la pestana RDR."""
    m = metricas
    return pd.DataFrame(
        [
            {"Metrica": "Sigma mensual", "Valor": m.sigma_mensual, "Formula": "STDEV.S(rendimientos mensuales)"},
            {"Metrica": "Sigma anual", "Valor": m.sigma_anual, "Formula": "sigma_mensual * SQRT(12) [ESTÃNDAR]"},
            {"Metrica": "Riesgo total (varianza)", "Valor": m.riesgo_total, "Formula": "VAR.S(rendimientos)"},
            {
                "Metrica": "Riesgo sistematico",
                "Valor": m.riesgo_sistematico,
                "Formula": "Beta^2 * VAR.S(rendimientos del mercado)",
            },
            {
                "Metrica": "Riesgo no sistematico",
                "Valor": m.riesgo_no_sistematico,
                "Formula": "Riesgo total - Riesgo sistematico",
            },
            {"Metrica": "VaR 95%", "Valor": m.var_95, "Formula": "mu + NORM.S.INV(0.05) * sigma_mensual"},
            {"Metrica": "VaR 99%", "Valor": m.var_99, "Formula": "mu + NORM.S.INV(0.01) * sigma_mensual"},
            {"Metrica": "Sharpe", "Valor": m.sharpe, "Formula": "(R anual - TLR) / sigma anual"},
            {"Metrica": "Treynor", "Valor": m.treynor, "Formula": "(R anual - TLR) / Beta"},
            {"Metrica": "Maxima caida", "Valor": m.max_drawdown, "Formula": "MIN((P - MAX acumulado) / MAX acumulado)"},
        ]
    )
