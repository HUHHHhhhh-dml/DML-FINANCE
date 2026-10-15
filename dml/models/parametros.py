# -*- coding: utf-8 -*-
"""Resolucion de los parametros efectivos del analisis.

El panel "Parametros" de la interfaz permite editar en vivo ``r``, ``q``,
``sigma``, ``T``, el strike ``K`` y los umbrales de la parrilla. Este modulo
centraliza la precedencia:

1. Lo que el usuario escribio en pantalla (**override**).
2. Lo estimado a partir de los datos (TLR, dividend yield, sigma anual, T desde
   las fechas reales, K = Forward).
3. Los valores por defecto de ``config.yaml`` / ``DEFAULT_CONFIG``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from ..core.tipos import Params
from ..core.util import a_float

LOG = logging.getLogger("dml.parametros")

DIAS_POR_ANIO = 365


def anios_entre(inicio: date, fin: date, dias_por_anio: int = DIAS_POR_ANIO) -> float:
    """Tiempo en anios entre dos fechas: ``(fin - inicio) / 365``.

    Se calcula con fechas reales (nunca ``YEARFRAC`` con base invalida, como
    exige el pliego). Devuelve 0.0 si el vencimiento no es posterior.
    """
    if inicio is None or fin is None:
        return 0.0
    dias = (fin - inicio).days
    if dias <= 0:
        return 0.0
    return dias / float(dias_por_anio)


def fecha_vencimiento(dias: int = 365, hoy: Optional[date] = None) -> date:
    """Fecha de vencimiento por defecto: hoy + ``dias`` (365 = 1 anio)."""
    base = hoy or date.today()
    return base + timedelta(days=int(dias))


def parametros_efectivos(
    datos: Any,
    config: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    hoy: Optional[date] = None,
) -> Params:
    """Resuelve los parametros efectivos del analisis.

    Args:
        datos: :class:`~dml.core.tipos.DatosTicker` (o cualquier objeto con
            ``tasas``, ``fundamentales`` y ``precios_mensuales``).
        config: configuracion efectiva (``black_scholes``, ``umbrales``...).
        overrides: valores escritos por el usuario en el panel de parametros.

    Returns:
        Una instancia de :class:`~dml.core.tipos.Params` con todo resuelto.
    """
    config = config or {}
    overrides = overrides or {}
    bs = config.get("black_scholes", {}) or {}
    umbrales = config.get("umbrales", {}) or {}
    reglas = config.get("decision", {}) or {}
    general = config.get("general", {}) or {}

    p = Params()
    p.modo = str(overrides.get("modo", general.get("modo", "estandar")))
    p.indice = str(overrides.get("indice", general.get("indice", "^GSPC")))
    p.meses = int(overrides.get("meses", general.get("meses", 60)) or 60)
    p.meses_pronostico = int(overrides.get("meses_pronostico", general.get("meses_pronostico", 12)) or 12)

    p.beta_max = a_float(umbrales.get("beta_max")) or 1.10
    p.r2_min = a_float(umbrales.get("r2_min")) or 0.70
    margen = a_float(umbrales.get("trg_extra_tlr"))
    p.margen_tlr_extra = 0.01 if margen is None else margen
    p.delta_call_min = a_float(umbrales.get("delta_call_min")) or 0.50
    p.comprar_min = a_float(reglas.get("comprar_min")) or 0.70
    p.mantener_min = a_float(reglas.get("mantener_min")) or 0.40

    # --- r: tasa libre de riesgo (TLR) ------------------------------------
    r_datos = None
    tasas = getattr(datos, "tasas", None)
    if tasas is not None:
        r_datos = a_float(getattr(tasas, "tbill_4w", None))
    p.r = a_float(overrides.get("r"))
    if p.r is None:
        p.r = r_datos

    # --- q: dividend yield -------------------------------------------------
    # Si no hay dividendo declarado se usa ``q = 0``: es la convencion del modelo
    # (Black-Scholes-Merton con un activo que no reparte dividendo) y ademas es lo
    # que hace el libro de referencia. Dejar ``q`` en ``None`` rompia la cadena
    # entera -``b = r - q``, el forward, el strike y las griegas quedaban en N/D-
    # por un dato que solo es una entrada secundaria del modelo. Solo se aplica
    # cuando NO hay dato; si el usuario fija ``q`` en pantalla, manda su valor.
    fundamentales = getattr(datos, "fundamentales", None)
    q_datos = a_float(getattr(fundamentales, "dividend_yield", None)) if fundamentales is not None else None
    p.q = a_float(overrides.get("q"))
    if p.q is None:
        p.q = q_datos if q_datos is not None else 0.0

    # --- sigma: volatilidad anual -----------------------------------------
    p.sigma = a_float(overrides.get("sigma"))

    # --- T: tiempo al vencimiento en anios --------------------------------
    t_override = a_float(overrides.get("T"))
    if t_override is not None:
        p.T = t_override
    else:
        dias = int(bs.get("vencimiento_dias", 365) or 365)
        venc = overrides.get("vencimiento")
        if isinstance(venc, date):
            p.vencimiento = venc
        else:
            p.vencimiento = fecha_vencimiento(dias, hoy)
        p.T = anios_entre(hoy or date.today(), p.vencimiento, int(bs.get("dias_por_anio", DIAS_POR_ANIO) or DIAS_POR_ANIO))
    if p.vencimiento is None and p.T:
        p.vencimiento = (hoy or date.today()) + timedelta(days=int(round(p.T * DIAS_POR_ANIO)))

    # --- strike ------------------------------------------------------------
    p.strike_modo = str(overrides.get("strike_modo", bs.get("strike_modo", "forward")) or "forward")
    strike_manual = a_float(overrides.get("strike"))
    if strike_manual is None:
        strike_manual = a_float(bs.get("strike_manual"))
    if p.strike_modo == "manual" and strike_manual is not None:
        p.strike = strike_manual
    # Si no es manual, el strike lo fija el modelo (K = Forward) y se rellena
    # en el analisis; aqui solo se conserva el valor manual si existe.

    activos = overrides.get("criterios_activos")
    if isinstance(activos, dict):
        p.criterios_activos = {int(k): bool(v) for k, v in activos.items()}

    LOG.debug(
        "Parametros efectivos: modo=%s r=%s q=%s sigma=%s T=%s K=%s",
        p.modo, p.r, p.q, p.sigma, p.T, p.strike,
    )
    return p


def strike_objetivo(
    spot: Optional[float], r: Optional[float], q: Optional[float], T: Optional[float], modo: str = "forward"
) -> Optional[float]:
    """Strike por defecto: ``K = S x e^(bT)`` con ``b = r - q`` (precio forward).

    El pliego define el "strike price" como el propio precio forward. Con
    ``modo='manual'`` el strike lo aporta el usuario y esta funcion no se usa.
    """
    import math

    s, rr, qq, t = a_float(spot), a_float(r), a_float(q), a_float(T)
    if s is None or rr is None or qq is None or t is None:
        return None
    b = rr - qq
    return float(s * math.exp(b * t))
