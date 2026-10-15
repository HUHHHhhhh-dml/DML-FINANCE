# -*- coding: utf-8 -*-
"""Utilidades numericas, de formato y de serializacion.

Todas las funciones toleran ``None``, ``NaN`` e ``inf`` y devuelven ``None`` en
lugar de propagar valores invalidos: en la interfaz, ``None`` se pinta como
``N/D``.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

ND = "N/D"


def a_float(valor: Any) -> Optional[float]:
    """Convierte ``valor`` en ``float`` o devuelve ``None`` si no es utilizable.

    Rechaza ``None``, cadenas vacias, ``NaN``, ``inf`` y objetos no numericos.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, (int, float, np.integer, np.floating)):
        f = float(valor)
        return f if math.isfinite(f) else None
    if isinstance(valor, str):
        texto = valor.strip().replace("%", "").replace("$", "").replace(" ", "")
        if not texto or texto.upper() in {"N/D", "NA", "NAN", "NULL", "-", "--"}:
            return None
        if "," in texto and "." in texto:
            texto = texto.replace(",", "") if texto.rfind(",") < texto.rfind(".") else texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        try:
            f = float(texto)
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def sane(valor: Any) -> Optional[float]:
    """Alias explicito de :func:`a_float` para dejar clara la intencion."""
    return a_float(valor)


def fmt_num(valor: Any, decimales: int = 4, miles: bool = True) -> str:
    """Formatea un numero con separador de miles o ``N/D`` si no es valido."""
    f = a_float(valor)
    if f is None:
        return ND
    formato = f"{f:,.{decimales}f}" if miles else f"{f:.{decimales}f}"
    return formato


def fmt_pct(valor: Any, decimales: int = 2) -> str:
    """Formatea una fraccion como porcentaje (``0.1234`` -> ``12.34%``)."""
    f = a_float(valor)
    if f is None:
        return ND
    return f"{f * 100.0:.{decimales}f}%"


def fmt_moneda(valor: Any, decimales: int = 2, simbolo: str = "$") -> str:
    """Formatea un importe monetario."""
    f = a_float(valor)
    if f is None:
        return ND
    return f"{simbolo}{f:,.{decimales}f}"


def ahora_iso() -> str:
    """Fecha y hora local actual en formato ISO corto (segundos)."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def hoy() -> date:
    """Fecha actual (envoltorio para facilitar las pruebas)."""
    return date.today()


def normalizar_dividend_yield(
    dividend_yield: Any,
    dividend_rate: Any = None,
    spot: Any = None,
) -> Optional[float]:
    """Normaliza el dividend yield a fracion decimal.

    El campo ``dividendYield`` de Yahoo Finance **cambia de escala segun el
    proveedor y la version**: historicamente devolvia ``0.025`` para un 2,5 %,
    pero las versiones actuales devuelven ``0.025`` para un **0,025 %**, es decir
    el numero en puntos porcentuales. Adivinar por magnitud es fragil (una accion
    con un 0,02 % de dividendo y otra con un 2 % producen el mismo ``0.02``), asi
    que la regla es:

    1. Si hay dividendo anual por accion y spot, se calcula
       ``dividend_rate / spot``: es exacto y no depende de la escala del campo.
    2. Si no hay dividendo anual, ``dividend_yield`` se interpreta como **puntos
       porcentuales** (``0.43`` -> 0,43 %). Adivinar la escala por magnitud es
       imposible: un 0,02 % y un 2 % producen el mismo ``0.02``.

    Args:
        dividend_yield: valor crudo del proveedor (``0.43``, ``2.5``, ``0.025``...).
        dividend_rate: dividendo anual por accion, si se conoce.
        spot: precio actual, necesario para la via exacta.

    Returns:
        El yield como fraccion (``0.0043`` = 0,43 %) o ``None``.
    """
    tasa = a_float(dividend_rate)
    precio = a_float(spot)
    if tasa is not None and precio:
        return tasa / precio
    valor = a_float(dividend_yield)
    if valor is None or valor == 0.0:
        return None
    # El campo se interpreta SIEMPRE como puntos porcentuales: 0.43 -> 0.0043.
    return valor / 100.0


def json_default(obj: Any) -> Any:
    """Serializador para ``json.dumps`` de tipos pandas/numpy/fecha."""
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, pd.Series):
        return {"__serie__": True, "index": [str(i) for i in obj.index], "valores": [a_float(v) for v in obj.tolist()]}
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="list")
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return a_float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
    return str(obj)


def serie_desde_json(dato: Any) -> Optional[pd.Series]:
    """Reconstruye una ``Series`` guardada por :func:`json_default`."""
    if isinstance(dato, dict) and dato.get("__serie__"):
        try:
            indice = pd.to_datetime(dato["index"])
            return pd.Series(dato["valores"], index=indice, dtype="float64")
        except Exception:
            return None
    return None


def normalizar_mensual(serie: Optional[pd.Series]) -> Optional[pd.Series]:
    """Normaliza el indice de una serie mensual al ultimo dia del mes.

    Permite alinear series de distinta procedencia (yfinance marca inicio de
    mes, FRED marca fin de mes) sobre una misma rejilla temporal.
    """
    if serie is None or len(serie) == 0:
        return None
    s = pd.Series(serie).astype(float).copy()
    s.index = pd.to_datetime(s.index)
    s.index = s.index.to_period("M").to_timestamp("M")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def truncar_meses(serie: Optional[pd.Series], meses: int) -> Optional[pd.Series]:
    """Ordena y recorta una serie mensual a los ultimos ``meses`` puntos."""
    if serie is None or len(serie) == 0:
        return None
    s = normalizar_mensual(serie)
    if s is None:
        return None
    return s.tail(int(meses))


def a_serie(valor: Any) -> Optional[pd.Series]:
    """Convierte listas/dicts/Series en ``Series`` o ``None``."""
    if valor is None:
        return None
    if isinstance(valor, pd.Series):
        return valor if len(valor) else None
    try:
        s = pd.Series(valor).astype(float).dropna()
    except Exception:
        return None
    return s if len(s) else None
