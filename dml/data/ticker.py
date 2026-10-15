# -*- coding: utf-8 -*-
"""Orquestacion de la descarga de datos de un ticker.

Une todos los proveedores en un unico :class:`~dml.core.tipos.DatosTicker`,
registrando la procedencia de cada dato y acumulando advertencias. Es la puerta
de entrada que usa el analisis (y por tanto la interfaz grafica).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from ..core.cache import Cache
from ..core.tipos import DatosTicker, Evidence, Fuentes
from ..core.util import a_float, ahora_iso
from ..models.tecnicos import macd_resumen
from .fundamentales import obtener_fundamentales, obtener_info_yf
from .mercado import obtener_indice, obtener_precios_mensuales, obtener_spot
from .tasas import obtener_tasas

LOG = logging.getLogger("dml.ticker")

#: Firma del callback de progreso: ``(mensaje, fraccion)``.
Progreso = Optional[Callable[[str, float], None]]


def _avisar(progreso: Progreso, mensaje: str, fraccion: float) -> None:
    """Emite un mensaje de progreso si hay callback."""
    LOG.info("%s (%.0f%%)", mensaje, fraccion * 100)
    if progreso is not None:
        try:
            progreso(mensaje, fraccion)
        except Exception:  # pragma: no cover - la interfaz nunca debe romper el analisis
            LOG.debug("El callback de progreso fallo para %s", mensaje)


def obtener_datos(
    ticker: str,
    cache: Optional[Cache] = None,
    config: Optional[Dict[str, Any]] = None,
    fuentes: Optional[Fuentes] = None,
    progreso: Progreso = None,
    meses: Optional[int] = None,
    indice: Optional[str] = None,
    manuales: Optional[Dict[str, float]] = None,
    permitir_manual: bool = True,
) -> DatosTicker:
    """Descarga y consolida todos los datos de mercado de ``ticker``.

    Orden de trabajo: spot -> serie mensual -> indice -> tasas -> fundamentales
    -> precios diarios (MACD). Cada bloque es tolerante a fallos: lo que no se
    consiga queda como ``N/D`` con el motivo registrado en :class:`Fuentes`.

    Args:
        ticker: simbolo a analizar.
        cache: cache local por dia.
        config: configuracion efectiva.
        fuentes: registro de procedencia (se crea uno si no se pasa).
        progreso: callback ``(mensaje, fraccion)`` para la barra de progreso.
        meses: meses de historico mensual (por defecto ``config.general.meses``).
        indice: simbolo del indice de mercado (por defecto ``config.general.indice``).
        manuales: valores manuales de tasas.
        permitir_manual: ``False`` cuando se ejecuta en un hilo de trabajo (Qt no
            permite abrir dialogos fuera del hilo de la interfaz).

    Returns:
        Un :class:`~dml.core.tipos.DatosTicker` completo.
    """
    config = config or {}
    general = config.get("general", {}) or {}
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("Se requiere un ticker para analizar")
    meses = int(meses if meses is not None else general.get("meses", 60) or 60)
    indice = str(indice or general.get("indice", "^GSPC"))
    fuentes = fuentes if fuentes is not None else Fuentes()

    _avisar(progreso, f"Consultando spot de {ticker}...", 0.02)
    ev_spot = obtener_spot(ticker, cache, fuentes, config)
    spot = a_float(ev_spot.value)

    _avisar(progreso, f"Descargando serie mensual de {ticker} ({meses} meses)...", 0.12)
    ev_precios = obtener_precios_mensuales(ticker, meses, cache, fuentes, config, spot)
    _avisar(progreso, f"Serie mensual de {ticker} lista", 0.30)

    _avisar(progreso, f"Descargando indice {indice}...", 0.36)
    ev_indice = obtener_indice(indice, meses, cache, fuentes, config)
    _avisar(progreso, f"Indice {indice} listo", 0.48)

    _avisar(progreso, "Consultando Investing.com: T-Bill 4 semanas, bono 10 y 30 anios...", 0.52)
    tasas = obtener_tasas(cache, fuentes, config, meses=meses, manuales=manuales, permitir_manual=permitir_manual)
    _avisar(progreso, "Tasas de referencia obtenidas", 0.74)

    _avisar(progreso, "Descargando fundamentales (PER, EPS, FCF, dividendo, Beta)...", 0.78)
    info = obtener_info_yf(ticker, cache, config)
    fundamentales = obtener_fundamentales(ticker, cache, fuentes, config, spot, info)
    _avisar(progreso, "Fundamentales obtenidos", 0.90)

    _avisar(progreso, "Calculando MACD de 1 mes con precios diarios...", 0.93)
    diarios = None
    ev_diarios = Evidence(
        fuente="Yahoo Finance (yfinance)",
        url=f"https://finance.yahoo.com/quote/{ticker}/history",
        metodo="N/D",
        consultado=ahora_iso(),
        nota="No se pudo obtener la serie diaria de precios",
    )
    try:
        from .mercado import precios_diarios_para_macd

        diarios, fuente_diaria = precios_diarios_para_macd(ticker, cache, config)
        if diarios is not None:
            ev_diarios = Evidence(
                value=a_float(diarios.iloc[-1]),
                serie=diarios,
                fuente=fuente_diaria,
                url=f"https://finance.yahoo.com/quote/{ticker}/history",
                metodo="API" if "yfinance" in fuente_diaria else "respaldo",
                consultado=ahora_iso(),
                nota="Serie diaria usada para el MACD de 1 mes",
            )
            fuentes.add(
                f"Serie diaria de {ticker} ({len(diarios)} cierres)",
                f"{diarios.iloc[-1]:.2f}",
                fuente_diaria,
                f"https://finance.yahoo.com/quote/{ticker}/history",
                ev_diarios.metodo,
                categoria="tecnico",
            )
    except Exception as exc:  # pragma: no cover - red
        LOG.warning("No se pudo obtener la serie diaria de %s: %s", ticker, exc)

    cfg_macd = (config.get("fundamentales", {}) or {}).get("macd", {}) or {}
    dias_macd = int(cfg_macd.get("dias_analisis", 30) or 30)
    macd_datos = None
    macd_senal = "N/D"
    macd_detalle = "No se pudo obtener la serie diaria de precios"
    if diarios is not None and len(diarios) > 0:
        from ..models.tecnicos import calcular_macd

        macd_datos = calcular_macd(
            diarios,
            int(cfg_macd.get("rapida", 12) or 12),
            int(cfg_macd.get("lenta", 26) or 26),
            int(cfg_macd.get("senal", 9) or 9),
        )
        _, macd_senal, macd_detalle = macd_resumen(diarios, dias_macd)
        fuentes.add(
            "Senal tecnica MACD (1 mes)",
            macd_senal,
            "Calculado con precios diarios de Yahoo Finance",
            f"https://www.investing.com/equities/{ticker.lower()}-technical",
            "calculo",
            macd_detalle,
            categoria="tecnico",
        )

    datos = DatosTicker(
        ticker=ticker,
        nombre=fundamentales.nombre or ticker,
        bolsa=fundamentales.bolsa,
        moneda=fundamentales.moneda,
        sector=fundamentales.sector,
        spot=ev_spot,
        precios_mensuales=ev_precios,
        precios_diarios=ev_diarios,
        indice_nombre=indice,
        indice_mensual=ev_indice,
        tasas=tasas,
        fundamentales=fundamentales,
        macd_datos=macd_datos,
        macd_senal=macd_senal,
        macd_detalle=macd_detalle,
        advertencias=list(tasas.advertencias),
        demo=False,
    )

    if not ev_precios.ok:
        datos.advertencias.append(
            f"N/D: no se pudo obtener la serie mensual de {ticker}; los modelos que dependen de ella no se calcularan"
        )
    if not ev_spot.ok:
        datos.advertencias.append(f"N/D: no se pudo obtener el spot de {ticker}")
    if not ev_indice.ok:
        datos.advertencias.append(f"N/D: no se pudo obtener el indice {indice}; la Beta y la PRH no se calcularan")
    if spot and ev_precios.value:
        tol = float(general.get("tolerancia_spot_pct", 0.05) or 0.05)
        if abs(ev_precios.value - spot) / spot > tol:
            datos.advertencias.append(
                f"Aviso: el ultimo cierre mensual ({ev_precios.value:.2f}) difiere del spot ({spot:.2f}) mas de {tol:.0%}"
            )
    datos.advertencias.extend(fundamentales.notas)

    _avisar(progreso, "Datos descargados", 1.0)
    LOG.info("Datos de %s consolidados con %s advertencias", ticker, len(datos.advertencias))
    return datos
