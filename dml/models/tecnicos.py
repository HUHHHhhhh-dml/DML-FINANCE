# -*- coding: utf-8 -*-
"""Indicadores tecnicos: MACD(12,26,9) y su clasificacion.

El pliego pide el "resumen tecnico / MACD de 1 mes": se calcula el MACD sobre
los ultimos ``dias_analisis`` dias de cotizacion (30 por defecto) y se clasifica
la senal como ``Buy`` / ``Neutral`` / ``Sell`` segun el cruce y la pendiente del
histograma.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import pandas as pd

LOG = logging.getLogger("dml.tecnicos")

RAPIDA = 12
LENTA = 26
SENAL = 9


def calcular_macd(
    precios: pd.Series, rapida: int = RAPIDA, lenta: int = LENTA, senal: int = SENAL
) -> Optional[pd.DataFrame]:
    """Calcula el MACD: linea MACD, linea de senal e histograma.

    Args:
        precios: serie de precios diarios (o del periodo que se quiera analizar).
        rapida: periodo de la EMA rapida (12).
        lenta: periodo de la EMA lenta (26).
        senal: periodo de la EMA de senal (9).

    Returns:
        ``DataFrame`` con columnas ``macd``, ``senal`` e ``histograma``, o
        ``None`` si la serie es demasiado corta (se exigen ``lenta + senal``
        observaciones para que la EMA de senal este suficientemente formada).
    """
    p = pd.Series(precios).astype(float).dropna()
    if len(p) < lenta + senal:
        LOG.debug("Serie insuficiente para el MACD: %s observaciones", len(p))
        return None
    ema_rapida = p.ewm(span=rapida, adjust=False).mean()
    ema_lenta = p.ewm(span=lenta, adjust=False).mean()
    macd = ema_rapida - ema_lenta
    linea_senal = macd.ewm(span=senal, adjust=False).mean()
    histograma = macd - linea_senal
    return pd.DataFrame({"macd": macd, "senal": linea_senal, "histograma": histograma}).dropna()


def clasificar_macd(datos_macd: Optional[pd.DataFrame]) -> Tuple[str, str]:
    """Clasifica la senal del MACD del ultimo periodo analizado.

    Reglas (documentadas porque el pliego exige saber de donde sale la senal):

    1. Histograma positivo y creciente -> ``Buy`` (momentum alcista).
    2. Histograma negativo y decreciente -> ``Sell`` (momentum bajista).
    3. Cruce del histograma de negativo a positivo -> ``Buy``.
    4. Cruce de positivo a negativo -> ``Sell``.
    5. Cualquier otro caso -> ``Neutral``.

    Returns:
        ``(senal, detalle)`` donde ``detalle`` explica el motivo en espanol.
    """
    if datos_macd is None or len(datos_macd) < 3:
        return "N/D", "Serie insuficiente para calcular el MACD (se necesitan al menos 35 cierres diarios)"
    hist = datos_macd["histograma"]
    ultimo = float(hist.iloc[-1])
    anterior = float(hist.iloc[-2])
    pendiente = ultimo - anterior
    if ultimo > 0 and pendiente >= 0:
        return "Buy", f"Histograma positivo ({ultimo:.4f}) y creciente: momentum alcista"
    if ultimo < 0 and pendiente <= 0:
        return "Sell", f"Histograma negativo ({ultimo:.4f}) y decreciente: momentum bajista"
    if ultimo > 0 > anterior:
        return "Buy", "Cruce del histograma al alza en el ultimo mes"
    if ultimo < 0 < anterior:
        return "Sell", "Cruce del histograma a la baja en el ultimo mes"
    return "Neutral", f"Histograma sin direccion clara ({ultimo:.4f}, pendiente {pendiente:+.4f})"


def macd_resumen(precios_diarios: pd.Series, dias: int = 30) -> Tuple[Optional[pd.DataFrame], str, str]:
    """Calcula y clasifica el MACD sobre los ultimos ``dias`` cierres.

    Returns:
        ``(datos_macd, senal, detalle)``.
    """
    serie = pd.Series(precios_diarios).astype(float).dropna()
    if dias and dias > 0:
        serie = serie.tail(int(dias) + LENTA + SENAL)  # margen para que las EMA converjan
    datos = calcular_macd(serie)
    senal, detalle = clasificar_macd(datos)
    return datos, senal, detalle
