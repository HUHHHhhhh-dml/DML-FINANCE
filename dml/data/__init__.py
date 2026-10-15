# -*- coding: utf-8 -*-
"""Capa de datos de DML-FINANCE.

Orden de intentos exigido por el pliego para las tasas de referencia
(Investing.com -> Playwright -> FRED -> Yahoo Finance -> manual), con cache
local por dia, pausas entre peticiones, reintentos con backoff y registro de la
procedencia de cada dato.
"""

from __future__ import annotations

from .demo import datos_demo
from .fundamentales import FUNDAMENTALES_DEMO, obtener_fundamentales, obtener_info_yf, obtener_precios_diarios
from .mercado import (
    descargar_precios,
    obtener_indice,
    obtener_precios_mensuales,
    obtener_spot,
    yahoo_chart,
    yfinance_descarga,
)
from .proveedores import (
    MOTIVO_MANUAL_PENDIENTE,
    fred_disponible,
    marcar_fred_caido,
    pedir_valor_manual,
    registrar_pedidor_manual,
    reiniciar_estado_fred,
    scrape_investing,
    scrape_investing_playwright,
    serie_fred,
    tasa_yahoo_simple,
    tasa_yfinance,
)
from .tasas import (
    CLAVES as CLAVES_TASAS,
    descuento_a_rendimiento,
    obtener_tasas,
    proxy_tlr_yahoo,
    rendimiento_equivalente_bono,
    resumen_tasas,
    serie_tasas_fred,
)
from .ticker import obtener_datos

#: Alias conservados de la version 1.x de la aplicacion (misma funcionalidad).
cargar_precios = descargar_precios
obtener_serie_mensual = obtener_precios_mensuales
obtener_tasa_fred = serie_fred
obtener_tasa_yahoo = tasa_yfinance

__all__ = [
    "datos_demo",
    "FUNDAMENTALES_DEMO",
    "obtener_fundamentales",
    "obtener_info_yf",
    "obtener_precios_diarios",
    "descargar_precios",
    "cargar_precios",
    "obtener_indice",
    "obtener_precios_mensuales",
    "obtener_serie_mensual",
    "obtener_spot",
    "yahoo_chart",
    "yfinance_descarga",
    "pedir_valor_manual",
    "registrar_pedidor_manual",
    "MOTIVO_MANUAL_PENDIENTE",
    "fred_disponible",
    "marcar_fred_caido",
    "reiniciar_estado_fred",
    "tasa_yahoo_simple",
    "scrape_investing",
    "scrape_investing_playwright",
    "serie_fred",
    "obtener_tasa_fred",
    "tasa_yfinance",
    "obtener_tasa_yahoo",
    "descuento_a_rendimiento",
    "obtener_tasas",
    "proxy_tlr_yahoo",
    "rendimiento_equivalente_bono",
    "resumen_tasas",
    "serie_tasas_fred",
    "CLAVES_TASAS",
    "obtener_datos",
]
