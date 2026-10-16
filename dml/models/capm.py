# -*- coding: utf-8 -*-
"""Beta, prima de riesgo, CAPM y precios objetivo.

Los dos modos de calculo del pliego se implementan aqui:

* ``estandar`` [ESTANDAR]: estimadores **coherentes** en numerador y
  denominador (covarianza y varianza muestrales, ``ddof=1``), prima de riesgo
  de **mercado** ``E[Rm - Rf]`` anualizada y precio objetivo de la TRG a escala
  mensual correcta.
* ``excel``: replica fiel de la metodologia del libro de referencia, incluidas
  sus inconsistencias: ``COVAR`` poblacional / ``VAR`` muestral, prima de
  riesgo calculada con los rendimientos de **la accion** (no del mercado) y
  precio objetivo ``PROMEDIO(precios) * (1 + TRG)``, que mezcla la escala del
  promedio historico con la del spot.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from ..core.util import a_float

LOG = logging.getLogger("dml.capm")

MODO_ESTANDAR = "estandar"
MODO_EXCEL = "excel"
PERIODOS_ANIO = 12


def _alinear(ra: pd.Series, rm: pd.Series) -> Optional[pd.DataFrame]:
    """Alinea dos series de rendimientos y las devuelve sin valores faltantes."""
    try:
        datos = pd.concat(
            [pd.Series(ra).astype(float).rename("accion"), pd.Series(rm).astype(float).rename("mercado")],
            axis=1,
            sort=False,
        ).dropna()
    except Exception as exc:  # pragma: no cover - proteccion defensiva
        LOG.warning("No se pudieron alinear los rendimientos: %s", exc)
        return None
    if len(datos) < 3:
        LOG.warning("Menos de 3 observaciones comunes: no se puede estimar la Beta")
        return None
    return datos


def beta_covarianza(ra: pd.Series, rm: pd.Series, modo: str = MODO_ESTANDAR) -> Optional[float]:
    """Beta = ``Cov(R_accion, R_mercado) / Var(R_mercado)`` con rendimientos mensuales.

    Args:
        ra: rendimientos mensuales de la accion.
        rm: rendimientos mensuales del indice de mercado.
        modo: ``estandar`` usa ``ddof=1`` en numerador y denominador;
            ``excel`` usa la covarianza poblacional (``ddof=0``, como ``COVAR``
            de Excel) dividida por la varianza muestral (``ddof=1``, ``VAR``).

    Returns:
        La Beta estimada, o ``None`` si no hay datos suficientes o la varianza
        del mercado es nula.
    """
    datos = _alinear(ra, rm)
    if datos is None:
        return None
    x = datos["accion"].values
    y = datos["mercado"].values
    ddof_cov = 0 if modo == MODO_EXCEL else 1
    cov = float(np.cov(x, y, ddof=ddof_cov)[0, 1])
    var = float(np.var(y, ddof=1))
    if var == 0:
        LOG.warning("Varianza del mercado nula: Beta indefinida")
        return None
    return cov / var


def beta_ols(ra: pd.Series, rm: pd.Series) -> Optional[float]:
    """Beta por regresion MCO de ``Ra`` sobre ``Rm`` (pendiente de la recta).

    Coincide numericamente con :func:`beta_covarianza` en modo ``estandar``
    (ambos son el estimador minimo cuadratico), y se expone por separado porque
    el pliego pide mostrar las dos vias y su diferencia.
    """
    datos = _alinear(ra, rm)
    if datos is None:
        return None
    x = datos["mercado"].values.astype(float)
    y = datos["accion"].values.astype(float)
    try:
        import statsmodels.api as sm  # type: ignore

        modelo = sm.OLS(y, sm.add_constant(x)).fit()
        return float(modelo.params[1])
    except Exception as exc:
        LOG.debug("statsmodels no disponible para beta_ols (%s): se usa numpy", exc)
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception as exc:  # pragma: no cover - defensivo
        LOG.error("No se pudo estimar la Beta por OLS: %s", exc)
        return None


def prima_riesgo_excel(ra: pd.Series, rf_mensual: pd.Series) -> Optional[float]:
    """PRH del modo ``excel``: promedio **mensual** de ``(R_accion - R_TLR)``.

    Es la metodologia del libro de referencia: usa los rendimientos de la accion
    para la prima, no los del mercado. Por eso el resultado **no** es una prima
    de riesgo de mercado; queda etiquetado como inconsistencia conocida.
    """
    try:
        datos = pd.concat(
            [pd.Series(ra).astype(float).rename("accion"), pd.Series(rf_mensual).astype(float).rename("rf")],
            axis=1,
            sort=False,
        ).dropna()
    except Exception as exc:  # pragma: no cover
        LOG.warning("No se pudo calcular la PRH modo excel: %s", exc)
        return None
    if len(datos) == 0:
        return None
    return float((datos["accion"] - datos["rf"]).mean())


def prima_riesgo_mercado(
    rm: pd.Series, rf_mensual: pd.Series, anualizar: bool = True, periodos_por_anio: int = PERIODOS_ANIO
) -> Optional[float]:
    """PRH de **mercado**: promedio de ``(Rm - Rf)``, anualizado si se pide.

    [ESTANDAR] La anualizacion es una multiplicacion por 12 (tasa nominal), que
    es coherente con la TLR cotizada que se suma en el CAPM: si la TLR es anual
    y la prima se deja mensual, el CAPM sumaria magnitudes de distinta escala.
    """
    try:
        datos = pd.concat(
            [pd.Series(rm).astype(float).rename("mercado"), pd.Series(rf_mensual).astype(float).rename("rf")],
            axis=1,
            sort=False,
        ).dropna()
    except Exception as exc:  # pragma: no cover
        LOG.warning("No se pudo calcular la prima de riesgo de mercado: %s", exc)
        return None
    if len(datos) == 0:
        return None
    prima_mensual = float((datos["mercado"] - datos["rf"]).mean())
    return prima_mensual * float(periodos_por_anio) if anualizar else prima_mensual


def rendimiento_capm(tlr: Optional[float], beta: Optional[float], prh: Optional[float]) -> Optional[float]:
    """``Rend_CAPM = TLR + Beta x PRH``.

    Requiere que ``TLR`` y ``PRH`` esten en la misma escala temporal (ambas
    anuales en modo estandar; ambas mensuales en modo excel).
    """
    r, b, p = a_float(tlr), a_float(beta), a_float(prh)
    if r is None or b is None or p is None:
        return None
    return r + b * p


def precio_objetivo_capm(spot: Optional[float], rend_capm: Optional[float]) -> Optional[float]:
    """``Precio objetivo = Spot x (1 + Rend_CAPM)``."""
    s, r = a_float(spot), a_float(rend_capm)
    if s is None or r is None:
        return None
    return s * (1.0 + r)


def precio_proyectado_trg(
    spot: Optional[float],
    trg_valor: Optional[float],
    meses: int = 12,
    modo: str = MODO_ESTANDAR,
    precios: Optional[pd.Series] = None,
) -> Optional[float]:
    """Precio proyectado con la TRG.

    * ``estandar`` [ESTANDAR]: ``Spot x (1 + TRG)^meses``, con ``TRG`` mensual y
      ``meses`` el numero de periodos mensuales equivalentes al horizonte ``T``.
      Mantiene la escala del spot.
    * ``excel``: ``PROMEDIO(precios) x (1 + TRG)``. Replica el libro de
      referencia **incluida su inconsistencia de escala**: proyecta un solo mes
      sobre el promedio historico de precios, no sobre el spot.

    Returns:
        El precio proyectado o ``None`` si faltan datos.
    """
    t = a_float(trg_valor)
    if modo == MODO_EXCEL:
        if precios is None or len(pd.Series(precios).dropna()) == 0:
            LOG.warning("Modo excel sin serie de precios: no se puede calcular PROMEDIO(precios)")
            return None
        media = float(pd.Series(precios).astype(float).dropna().mean())
        if t is None:
            return None
        return media * (1.0 + t)
    s = a_float(spot)
    if s is None or t is None:
        return None
    return s * (1.0 + t) ** int(meses)


def nota_inconsistencia_excel(spot: Optional[float], precio_excel: Optional[float], precio_estandar: Optional[float]) -> str:
    """Texto de advertencia que se muestra al usar el modo ``excel``.

    El pliego exige avisar de forma visible en cada punto donde el modo excel
    difiere del estandar.
    """
    partes = [
        "[MODO EXCEL] Precio proyectado = PROMEDIO(precios) x (1 + TRG): mezcla la escala del "
        "promedio historico con la del spot."
    ]
    if spot is not None:
        partes.append(f"Spot = {spot:,.2f}")
    if precio_excel is not None:
        partes.append(f"Proyeccion excel = {precio_excel:,.2f}")
    if precio_estandar is not None:
        partes.append(f"Proyeccion estandar = {precio_estandar:,.2f}")
    return " | ".join(partes)
