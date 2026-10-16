# -*- coding: utf-8 -*-
"""Rendimientos, tasas equivalentes y Tasa de Rentabilidad Geometrica (TRG).

Convenios
---------
* Rendimiento **simple** mensual: ``P_t / P_{t-1} - 1``.
* Rendimiento **logaritmico** mensual: ``ln(P_t / P_{t-1})``.
* **TRG**: ``(prod(P_t/P_{t-1}))^(1/n) - 1``; es la tasa geometrica mensual
  implicita en la serie (no confundir con el rendimiento medio aritmetico).
* **TLR mensual**:

  - modo ``estandar``: ``TLR_anual / 12`` (tasa nominal dividida en 12 periodos).
  - modo ``excel``: ``TLR_anual / 365 * 28`` (mes "de 28 dias", replica la
    metodologia del libro de referencia).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from ..core.util import a_float

LOG = logging.getLogger("dml.rendimientos")

DIAS_MES_EXCEL = 28
DIAS_ANIO = 365


def rendimientos_simples(precios: pd.Series) -> pd.Series:
    """Rendimiento simple periodo a periodo: ``P_t / P_{t-1} - 1``.

    Args:
        precios: serie de precios ordenada cronologicamente.

    Returns:
        Serie de rendimientos sin el primer valor (que no tiene periodo previo).
    """
    p = pd.Series(precios).astype(float).dropna()
    return p.pct_change().dropna()


def rendimientos_logaritmicos(precios: pd.Series) -> pd.Series:
    """Rendimiento logaritmico periodo a periodo: ``ln(P_t / P_{t-1})``."""
    p = pd.Series(precios).astype(float).dropna()
    p = p[p > 0]
    if len(p) < 2:
        return pd.Series(dtype="float64")
    return np.log(p / p.shift(1)).dropna()


def trg(precios: pd.Series) -> Optional[float]:
    """Tasa de Rentabilidad Geometrica mensual: ``(prod(P_t/P_{t-1}))^(1/n) - 1``.

    Equivale a ``(P_n/P_0)^(1/(n-1)) - 1`` pero se calcula como producto de
    factores para ser explicito y numericamente estable.

    Returns:
        La tasa geometrica **mensual** en fraccion, o ``None`` si la serie es
        demasiado corta o contiene precios no positivos.
    """
    p = pd.Series(precios).astype(float).dropna()
    if len(p) < 2 or (p <= 0).any():
        return None
    factores = p.iloc[1:].values / p.iloc[:-1].values
    n = len(factores)
    if n == 0:
        return None
    producto = float(np.prod(factores))
    if producto <= 0:
        return None
    return float(producto ** (1.0 / n) - 1.0)


def media_geometrica(rendimientos: pd.Series) -> Optional[float]:
    """Media geometrica de una serie de rendimientos: ``(prod(1+r))^(1/n) - 1``."""
    r = pd.Series(rendimientos).astype(float).dropna()
    if len(r) == 0:
        return None
    factores = 1.0 + r.values
    if (factores <= 0).any():
        return None
    return float(np.prod(factores) ** (1.0 / len(factores)) - 1.0)


def tlr_mensual(
    tlr_anual: Optional[float], modo: str = "estandar", dias_mes: int = DIAS_MES_EXCEL, dias_anio: int = DIAS_ANIO
) -> Optional[float]:
    """Convierte la TLR anual en una tasa mensual segun el modo de calculo.

    Args:
        tlr_anual: tasa anual en fraccion (p. ej. ``0.0435``).
        modo: ``estandar`` -> ``TLR/12`` [ESTANDAR]; ``excel`` -> ``TLR/365*28``.

    Returns:
        Tasa mensual en fraccion o ``None`` si la entrada no es valida.
    """
    r = a_float(tlr_anual)
    if r is None:
        return None
    if modo == "excel":
        return r / float(dias_anio) * float(dias_mes)
    return r / 12.0


def serie_tlr_mensual(serie_anual: Optional[pd.Series], modo: str = "estandar") -> Optional[pd.Series]:
    """Aplica :func:`tlr_mensual` a una serie anual completa de TLR."""
    if serie_anual is None or len(serie_anual) == 0:
        return None
    s = pd.Series(serie_anual).astype(float).dropna()
    if len(s) == 0:
        return None
    return s.map(lambda r: tlr_mensual(r, modo)).astype(float)


def anualizar(tasa_periodica: Optional[float], periodos_por_anio: int = 12, compuesta: bool = False) -> Optional[float]:
    """Anualiza una tasa periodica.

    Args:
        tasa_periodica: tasa del periodo en fraccion.
        periodos_por_anio: 12 para datos mensuales.
        compuesta: ``True`` aplica capitalizacion ``(1+r)^k - 1``; ``False``
            multiplica por ``k`` (tasa nominal anual, coherente con la TLR
            cotizada que se usa en el CAPM).
    """
    r = a_float(tasa_periodica)
    if r is None:
        return None
    if compuesta:
        return float((1.0 + r) ** periodos_por_anio - 1.0)
    return r * float(periodos_por_anio)


def desanualizar(tasa_anual: Optional[float], periodos_por_anio: int = 12) -> Optional[float]:
    """Convierte una tasa anual nominal en la tasa del periodo (division simple)."""
    r = a_float(tasa_anual)
    if r is None:
        return None
    return r / float(periodos_por_anio)
