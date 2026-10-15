# -*- coding: utf-8 -*-
"""Datos de demostracion para ``python main.py --demo``.

Los datos son **ficticios** y se marcan como ``DEMO`` en todos los resultados,
en la interfaz y en el Excel exportado. Permiten probar la aplicacion completa
sin conexion y sin depender de ninguna fuente externa.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..core.tipos import DatosTicker, Evidence, Fundamental, Tasas
from ..core.util import ahora_iso

LOG = logging.getLogger("dml.demo")

SEED = 20261009


def _precios_mensuales(meses: int = 60, spot: float = 100.0, base: float = 55.0) -> pd.Series:
    """Genera una serie mensual sintetica con tendencia y ruido, anclada al spot."""
    rng = np.random.default_rng(SEED)
    fin = pd.Timestamp.today().to_period("M").to_timestamp("M")
    indice = pd.date_range(end=fin, periods=meses, freq="ME")
    deriva = (spot / base) ** (1.0 / max(meses - 1, 1)) - 1.0
    pasos = rng.normal(loc=deriva, scale=0.055, size=meses - 1)
    valores = [base]
    for paso in pasos:
        valores.append(valores[-1] * (1.0 + float(paso)))
    serie = pd.Series(valores, index=indice, dtype="float64")
    # Se ancla el ultimo cierre al spot para que la validacion de coherencia pase.
    serie.iloc[-1] = float(spot)
    return serie


def _indice_mensual(meses: int = 60, base: float = 4200.0) -> pd.Series:
    """Serie mensual sintetica del indice de mercado (correlacionada con la accion)."""
    rng = np.random.default_rng(SEED + 1)
    fin = pd.Timestamp.today().to_period("M").to_timestamp("M")
    indice = pd.date_range(end=fin, periods=meses, freq="ME")
    valores = [base]
    for _ in range(meses - 1):
        valores.append(valores[-1] * (1.0 + float(rng.normal(0.009, 0.035))))
    return pd.Series(valores, index=indice, dtype="float64")


def _serie_tlr(meses: int = 60, inicial: float = 0.052, final: float = 0.0435) -> pd.Series:
    """Serie mensual sintetica de la TLR (T-Bill 4 semanas) en fraccion."""
    fin = pd.Timestamp.today().to_period("M").to_timestamp("M")
    indice = pd.date_range(end=fin, periods=meses, freq="ME")
    valores = np.linspace(inicial, final, meses)
    return pd.Series(valores, index=indice, dtype="float64")


def _precios_diarios(dias: int = 200, spot: float = 100.0) -> pd.Series:
    """Serie diaria sintetica de cierres (para el MACD)."""
    rng = np.random.default_rng(SEED + 2)
    indice = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=dias)
    pasos = rng.normal(loc=0.0006, scale=0.014, size=dias - 1)
    valores = [spot * 0.92]
    for paso in pasos:
        valores.append(valores[-1] * (1.0 + float(paso)))
    serie = pd.Series(valores, index=indice, dtype="float64")
    serie.iloc[-1] = float(spot)
    return serie


def datos_demo(
    ticker: str = "DEMO",
    meses: int = 60,
    indice: str = "^GSPC",
    spot: float = 100.0,
    config: Optional[Dict[str, Any]] = None,
) -> DatosTicker:
    """Construye un :class:`~dml.core.tipos.DatosTicker` con datos **ficticios**.

    Todos los ``Evidence`` quedan con ``fuente='DEMO (datos ficticios)'`` y
    ``metodo='demo'`` para que sea imposible confundirlos con datos reales.
    """
    ahora = ahora_iso()
    fuente = "DEMO (datos ficticios)"
    precios = _precios_mensuales(meses, spot)
    indice_serie = _indice_mensual(meses)
    tlr_serie = _serie_tlr(meses)
    diarios = _precios_diarios(200, spot)

    demo_fund = Fundamental(
        sector="Technology",
        industria="Software ficticio (DEMO)",
        per=24.5,
        per_sector=32.0,
        eps=4.10,
        eps_forecast=3.95,
        p_fcf=27.2,
        p_fcf_sector=30.0,
        dividend_rate=0.80,
        dividend_yield=0.008,
        market_cap=250_000_000_000.0,
        free_cash_flow=9_200_000_000.0,
        beta_publicada=1.05,
        nombre=f"{ticker} DEMO Corporation (datos ficticios)",
        bolsa="DEMO",
        moneda="USD",
        notas=["Datos de demostracion: no corresponden a ninguna empresa real"],
    )
    for atributo in ("ev_per", "ev_per_sector", "ev_eps", "ev_eps_forecast", "ev_p_fcf", "ev_p_fcf_sector", "ev_dividendo", "ev_beta_publicada"):
        ev = getattr(demo_fund, atributo)
        ev.fuente = fuente
        ev.metodo = "demo"
        ev.consultado = ahora

    tasas = Tasas(
        tbill_4w=float(tlr_serie.iloc[-1]),
        ust_10y=0.0421,
        ust_30y=0.0448,
        serie_tbill_mensual=tlr_serie,
        serie_10y_mensual=(tlr_serie + 0.0025),
        serie_30y_mensual=(tlr_serie + 0.0055),
        metodos={"tbill_4w": "demo", "ust_10y": "demo", "ust_30y": "demo"},
    )
    tasas.ev_tbill_4w = Evidence(value=tasas.tbill_4w, serie=tlr_serie, fuente=fuente, metodo="demo", consultado=ahora)
    tasas.ev_ust_10y = Evidence(value=tasas.ust_10y, fuente=fuente, metodo="demo", consultado=ahora)
    tasas.ev_ust_30y = Evidence(value=tasas.ust_30y, fuente=fuente, metodo="demo", consultado=ahora)

    datos = DatosTicker(
        ticker=ticker.upper(),
        nombre=demo_fund.nombre,
        bolsa="DEMO",
        moneda="USD",
        sector="Technology",
        spot=Evidence(value=spot, fuente=fuente, metodo="demo", consultado=ahora),
        precios_mensuales=Evidence(
            value=float(precios.iloc[-1]),
            serie=precios,
            fuente=fuente,
            metodo="demo",
            consultado=ahora,
            nota="Serie mensual sintetica de 60 meses (DEMO)",
        ),
        precios_diarios=Evidence(
            value=float(diarios.iloc[-1]),
            serie=diarios,
            fuente=fuente,
            metodo="demo",
            consultado=ahora,
            nota="Serie diaria sintetica para el MACD (DEMO)",
        ),
        indice_nombre=indice,
        indice_mensual=Evidence(
            value=float(indice_serie.iloc[-1]),
            serie=indice_serie,
            fuente=fuente,
            metodo="demo",
            consultado=ahora,
        ),
        tasas=tasas,
        fundamentales=demo_fund,
        advertencias=["Analisis en modo DEMO: todos los datos son ficticios"],
        demo=True,
    )
    LOG.info("Datos DEMO generados para %s (%s meses)", ticker, meses)
    return datos
