# -*- coding: utf-8 -*-
"""Indicadores fundamentales: PER, Renta PER, Price to FCF y RDR.

Todas las funciones son tolerantes a datos ausentes: devuelven ``None`` (que la
interfaz pinta como ``N/D``) en lugar de lanzar excepciones o inventar valores.
El pliego exige ademas que un PER negativo o no disponible se marque como
``N/D`` y califique el criterio como 0 con nota explicativa.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from ..core.util import a_float

LOG = logging.getLogger("dml.fundamentales")


def per_valor(precio: Optional[float], eps: Optional[float]) -> Tuple[Optional[float], str]:
    """PER = ``Precio / EPS``.

    Returns:
        ``(per, nota)``. ``per`` es ``None`` (N/D) si falta algun dato, si el
        EPS es cero o si el PER resultante es negativo (empresa con perdidas):
        un PER negativo no es comparable con el del sector.
    """
    p, e = a_float(precio), a_float(eps)
    if p is None or e is None:
        return None, "N/D: falta el precio o el EPS"
    if e == 0:
        return None, "N/D: EPS igual a cero, el PER no esta definido"
    per = p / e
    if per < 0:
        return None, f"N/D: PER negativo ({per:.2f}) porque el EPS es negativo (perdidas)"
    return per, ""


def renta_per(per: Optional[float]) -> Tuple[Optional[float], str]:
    """Renta PER = ``1 / PER`` (rentabilidad implicita del precio pagado).

    Es la "earnings yield": se compara directamente con la TLR para decidir si
    la accion compensa frente a un bono sin riesgo.
    """
    valor = a_float(per)
    if valor is None:
        return None, "N/D: sin PER valido no se puede calcular la Renta PER"
    if valor <= 0:
        return None, "N/D: PER no positivo, la Renta PER no es interpretable"
    return 1.0 / valor, ""


def price_to_fcf(
    market_cap: Optional[float], free_cash_flow: Optional[float], precio: Optional[float] = None, fcf_por_accion: Optional[float] = None
) -> Tuple[Optional[float], str]:
    """Price to FCF = ``Capitalizacion / Free Cash Flow``.

    Si no hay capitalizacion pero si precio y FCF por accion, se usa
    ``precio / fcf_por_accion`` (mismo cociente).

    Returns:
        ``(p_fcf, nota)``. Es ``None`` si falta informacion o si el FCF no es
        positivo (un multiplo negativo carece de interpretacion).
    """
    cap, fcf = a_float(market_cap), a_float(free_cash_flow)
    if cap is not None and fcf is not None:
        if fcf <= 0:
            return None, f"N/D: FCF no positivo ({fcf:,.0f}); el multiplo no es interpretable"
        return cap / fcf, ""
    p, fpa = a_float(precio), a_float(fcf_por_accion)
    if p is not None and fpa is not None:
        if fpa <= 0:
            return None, "N/D: FCF por accion no positivo"
        return p / fpa, ""
    return None, "N/D: faltan la capitalizacion o el flujo de caja libre"


def rdr(rend_capm: Optional[float], riesgo: Optional[float]) -> Tuple[Optional[float], Optional[float], str]:
    """RDR: Rendimiento sobre Riesgo.

    Returns:
        ``(cociente, diferencia, nota)``:

        * ``cociente = Rend_CAPM / Riesgo`` (cuanto rendimiento por unidad de riesgo),
        * ``diferencia = Rend_CAPM - Riesgo`` (criterio 8 del pliego:
          ``Rend_CAPM > Riesgo``).
    """
    r, s = a_float(rend_capm), a_float(riesgo)
    if r is None or s is None:
        return None, None, "N/D: falta el rendimiento CAPM o la desviacion estandar"
    if s <= 0:
        return None, r - s, "Riesgo no positivo: el cociente Rend/Riesgo no esta definido"
    return r / s, r - s, ""


def margen_seguridad(spot: Optional[float], precio_objetivo: Optional[float]) -> Optional[float]:
    """Margen de seguridad implicito: ``(Precio objetivo - Spot) / Spot``."""
    s, o = a_float(spot), a_float(precio_objetivo)
    if s is None or o is None or s == 0:
        return None
    return (o - s) / s


def decision_por_margen(margen: Optional[float]) -> str:
    """Etiqueta cualitativa del margen de seguridad."""
    m = a_float(margen)
    if m is None:
        return "N/D"
    if m >= 0.20:
        return "Infravalorada"
    if m >= 0.05:
        return "Ligeramente infravalorada"
    if m > -0.05:
        return "En valor razonable"
    if m > -0.20:
        return "Ligeramente sobrevalorada"
    return "Sobrevalorada"


def normalizar_sector(sector: Any, mapa: Optional[dict] = None) -> str:
    """Normaliza el nombre del sector al usado en ``config.yaml``."""
    texto = str(sector or "").strip()
    mapa = mapa or {}
    if texto in mapa:
        return texto
    for clave in mapa:
        if clave.lower() == texto.lower():
            return clave
    return texto or "DESCONOCIDO"


def multiplo_sector(sector: str, tabla: dict, por_defecto: float = 20.0) -> float:
    """Devuelve el multiplo de referencia de un sector (PER o P/FCF)."""
    if not isinstance(tabla, dict):
        return por_defecto
    if sector in tabla:
        return float(tabla[sector])
    for clave, valor in tabla.items():
        if clave.lower() == str(sector).lower():
            return float(valor)
    return float(tabla.get("DESCONOCIDO", por_defecto))
