# -*- coding: utf-8 -*-
"""Precios de mercado: spot, serie mensual de 60 meses e indice de referencia.

Fuente principal: **Yahoo Finance** vía ``yfinance``; respaldo: la API publica
``v8/finance/chart`` de Yahoo descargada con ``urllib`` (sin dependencias). En
ambos casos se respeta la cache local por dia.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..core.cache import Cache
from ..core.tipos import Evidence, Fuentes
from ..core.util import ahora_iso, a_float, normalizar_mensual, truncar_meses
from .proveedores import USER_AGENT, _cfg_datos

LOG = logging.getLogger("dml.mercado")

ETIQUETA_YF = "Yahoo Finance (yfinance)"
ETIQUETA_CHART = "Yahoo Finance (API chart, respaldo)"


def yfinance_descarga(simbolo: str, periodo: str = "10y", intervalo: str = "1mo") -> pd.DataFrame:
    """Descarga un historico con ``yfinance`` y devuelve un ``DataFrame`` con ``Close``.

    Raises:
        RuntimeError: si yfinance no esta instalado o devuelve una serie vacia.
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        raise RuntimeError("yfinance no esta instalado") from exc
    try:
        df = yf.download(simbolo, period=periodo, interval=intervalo, auto_adjust=True, progress=False, threads=False)
    except Exception as exc:
        raise RuntimeError(f"yfinance fallo para {simbolo}: {exc}") from exc
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance devolvio una serie vacia para {simbolo}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        raise RuntimeError(f"yfinance no devolvio la columna Close para {simbolo}")
    salida = df[["Close"]].dropna()
    salida.index = pd.to_datetime(salida.index)
    return salida


def yahoo_chart(simbolo: str, rango: str = "10y", intervalo: str = "1mo", timeout: int = 25) -> pd.DataFrame:
    """Respaldo de precios con la API publica de Yahoo (sin yfinance).

    Returns:
        ``DataFrame`` con la columna ``Close`` (precio ajustado si esta disponible).

    Raises:
        RuntimeError: si la API no devuelve datos utilizables.
    """
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(simbolo)}"
        f"?range={rango}&interval={intervalo}&includeAdjustedClose=true"
    )
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    resultados = (datos.get("chart", {}) or {}).get("result") or []
    if not resultados:
        raise RuntimeError(f"La API de Yahoo no devolvio datos para {simbolo}")
    resultado = resultados[0]
    marcas = resultado.get("timestamp") or []
    indicadores = resultado.get("indicators", {}) or {}
    cierres = ((indicadores.get("quote") or [{}])[0]).get("close") or []
    ajustados = ((indicadores.get("adjclose") or [{}])[0]).get("adjclose") or []
    valores = ajustados if (ajustados and len(ajustados) == len(cierres)) else cierres
    if not marcas or not valores:
        raise RuntimeError(f"Serie vacia en la API de Yahoo para {simbolo}")
    indices = pd.to_datetime(marcas, unit="s", utc=True).tz_convert(None)
    serie = pd.Series(valores, index=indices, dtype="float64").dropna()
    if serie.empty:
        raise RuntimeError(f"Serie sin valores validos para {simbolo}")
    return pd.DataFrame({"Close": serie})


def descargar_precios(
    simbolo: str,
    periodo: str = "10y",
    intervalo: str = "1mo",
    cache: Optional[Cache] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, str]:
    """Descarga precios con yfinance y, si falla, con la API publica de Yahoo.

    Returns:
        ``(DataFrame con Close, etiqueta de la fuente usada)``.

    Raises:
        RuntimeError: si ninguna de las dos vias obtiene datos.
    """
    cfg = _cfg_datos(config)
    clave = f"precios|{simbolo}|{periodo}|{intervalo}"

    def productor() -> Optional[Dict[str, Any]]:
        try:
            df = yfinance_descarga(simbolo, periodo, intervalo)
            return {
                "index": [d.isoformat() for d in df.index],
                "close": [a_float(v) for v in df["Close"].tolist()],
                "fuente": ETIQUETA_YF,
            }
        except Exception as exc:
            LOG.warning("yfinance no disponible para %s (%s): se intenta la API publica de Yahoo", simbolo, exc)
        try:
            df = yahoo_chart(simbolo, periodo, intervalo, cfg["timeout_seg"])
            return {
                "index": [d.isoformat() for d in df.index],
                "close": [a_float(v) for v in df["Close"].tolist()],
                "fuente": ETIQUETA_CHART,
            }
        except Exception as exc:
            LOG.error("Tampoco la API publica de Yahoo devolvio datos de %s: %s", simbolo, exc)
            return None

    if cache is not None:
        paquete = cache.obtener(clave, productor)
    else:
        paquete = productor()
    if not isinstance(paquete, dict) or "close" not in paquete:
        raise RuntimeError(f"No se pudieron obtener datos de {simbolo}")
    indice = pd.to_datetime(paquete["index"]) if paquete.get("index") else pd.RangeIndex(len(paquete["close"]))
    df = pd.DataFrame({"Close": paquete["close"]}, index=indice).dropna()
    return df, str(paquete.get("fuente", ETIQUETA_YF))


def _serie_mensual(serie: pd.Series, meses: int) -> pd.Series:
    """Normaliza a fin de mes y recorta a los ultimos ``meses`` puntos."""
    s = truncar_meses(normalizar_mensual(pd.Series(serie).dropna()), meses)
    return s if s is not None else pd.Series(dtype="float64")


def obtener_spot(
    ticker: str,
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Evidence:
    """Obtiene el precio spot (ultimo cierre diario disponible) del ticker."""
    url = f"https://finance.yahoo.com/quote/{ticker}"
    cfg = _cfg_datos(config)
    try:
        df, fuente = descargar_precios(ticker, "1mo", "1d", cache, config)
        spot = a_float(df["Close"].dropna().iloc[-1])
        if spot is None:
            raise RuntimeError("el ultimo cierre no es un numero valido")
        ev = Evidence(
            value=spot,
            fuente=fuente,
            url=url,
            metodo="API" if "yfinance" in fuente else "respaldo",
            consultado=ahora_iso(),
        )
        if fuentes is not None:
            fuentes.add(f"Spot {ticker}", spot, fuente, url, ev.metodo, categoria="accion")
        return ev
    except Exception as exc:
        LOG.error("No se pudo obtener el spot de %s: %s", ticker, exc)
        ev = Evidence(fuente="Yahoo Finance", url=url, metodo="N/D", consultado=ahora_iso(), nota=str(exc))
        if fuentes is not None:
            fuentes.add(f"Spot {ticker}", None, "Yahoo Finance", url, "N/D", str(exc), categoria="accion")
        return ev


def obtener_precios_mensuales(
    ticker: str,
    meses: int = 60,
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    config: Optional[Dict[str, Any]] = None,
    spot: Optional[float] = None,
) -> Evidence:
    """Serie de cierres **mensuales** de los ultimos ``meses`` meses.

    Valida que el ultimo cierre mensual sea coherente con el spot y devuelve el
    aviso (no bloqueante) cuando la diferencia supera ``tolerancia_spot_pct``:
    suele indicar que el mes en curso esta incompleto.
    """
    config = config or {}
    url = f"https://finance.yahoo.com/quote/{ticker}/history"
    periodo = str(((config.get("general") or {}).get("periodo_historico", "10y")))
    tol = float(((config.get("general") or {}).get("tolerancia_spot_pct", 0.05)) or 0.05)
    try:
        df, fuente = descargar_precios(ticker, periodo, "1mo", cache, config)
        serie = _serie_mensual(df["Close"], meses)
        if len(serie) < 12:
            raise RuntimeError(f"serie mensual demasiado corta ({len(serie)} puntos)")
        nota = ""
        spot_val = a_float(spot)
        ultimo = a_float(serie.iloc[-1])
        if spot_val and ultimo and abs(ultimo - spot_val) / spot_val > tol:
            nota = (
                f"El ultimo cierre mensual ({ultimo:.2f}) difiere del spot ({spot_val:.2f}) mas de {tol:.0%}: "
                "el mes en curso puede estar incompleto."
            )
            LOG.warning("%s: %s", ticker, nota)
        ev = Evidence(
            value=ultimo,
            serie=serie,
            fuente=fuente,
            url=url,
            metodo="API" if "yfinance" in fuente else "respaldo",
            consultado=ahora_iso(),
            nota=nota,
        )
        if fuentes is not None:
            fuentes.add(
                f"Serie mensual de precios {ticker} ({len(serie)} meses)",
                f"{serie.iloc[0]:.2f} -> {serie.iloc[-1]:.2f}",
                fuente,
                url,
                ev.metodo,
                nota,
                categoria="accion",
            )
        return ev
    except Exception as exc:
        LOG.error("No se pudo obtener la serie mensual de %s: %s", ticker, exc)
        ev = Evidence(fuente="Yahoo Finance", url=url, metodo="N/D", consultado=ahora_iso(), nota=str(exc))
        if fuentes is not None:
            fuentes.add(f"Serie mensual de precios {ticker}", None, "Yahoo Finance", url, "N/D", str(exc), categoria="accion")
        return ev


def obtener_indice(
    indice: str = "^GSPC",
    meses: int = 60,
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Evidence:
    """Serie mensual del indice de mercado (``^GSPC``, ``^IXIC`` o ``^DJI``)."""
    config = config or {}
    url = f"https://finance.yahoo.com/quote/{indice}"
    periodo = str(((config.get("general") or {}).get("periodo_historico", "10y")))
    try:
        df, fuente = descargar_precios(indice, periodo, "1mo", cache, config)
        serie = _serie_mensual(df["Close"], meses)
        if len(serie) < 12:
            raise RuntimeError(f"serie del indice demasiado corta ({len(serie)} puntos)")
        ev = Evidence(
            value=a_float(serie.iloc[-1]),
            serie=serie,
            fuente=fuente,
            url=url,
            metodo="API" if "yfinance" in fuente else "respaldo",
            consultado=ahora_iso(),
        )
        if fuentes is not None:
            fuentes.add(
                f"Indice {indice} ({len(serie)} meses)",
                f"{serie.iloc[-1]:.2f}",
                fuente,
                url,
                ev.metodo,
                categoria="mercado",
            )
        return ev
    except Exception as exc:
        LOG.error("No se pudo obtener el indice %s: %s", indice, exc)
        ev = Evidence(fuente="Yahoo Finance", url=url, metodo="N/D", consultado=ahora_iso(), nota=str(exc))
        if fuentes is not None:
            fuentes.add(f"Indice {indice}", None, "Yahoo Finance", url, "N/D", str(exc), categoria="mercado")
        return ev


def precios_diarios_para_macd(
    ticker: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[pd.Series], str]:
    """Serie diaria de cierres (para el MACD de 1 mes).

    Returns:
        ``(serie_diaria, fuente)``; la serie es ``None`` si no se pudo obtener.
    """
    url = f"https://finance.yahoo.com/quote/{ticker}/history"
    try:
        df, fuente = descargar_precios(ticker, "6mo", "1d", cache, config)
        serie = pd.Series(df["Close"]).astype(float).dropna()
        serie.index = pd.to_datetime(serie.index)
        return serie, fuente
    except Exception as exc:
        LOG.warning("No se pudo obtener la serie diaria de %s para el MACD (%s)", ticker, exc)
        return None, "N/D"
