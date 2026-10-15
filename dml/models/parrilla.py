# -*- coding: utf-8 -*-
"""Parrilla de decision de 12 criterios binarios y regla de decision final.

Cada criterio vale 1 si se cumple y 0 si no. La **calificacion** es el promedio
de los criterios **activos** (por defecto los 12) y la decision se deriva de
ella:

===============  =========================
Calificacion     Decision
===============  =========================
``> 0.70``       COMPRAR
``0.40 - 0.70``  MANTENER
``< 0.40``       NO INVERTIR
===============  =========================

Los umbrales son parametros editables: se leen de ``config['umbrales']`` y
``config['decision']``, y el panel "Parametros" de la interfaz los inyecta en esa
misma configuracion mediante :func:`config_con_overrides`, de modo que cualquier
cambio en pantalla recalcula la parrilla sin volver a descargar datos.

Un dato ``N/D`` **nunca** se inventa: el criterio se marca como no cumplido,
se califica 0 y se anota el motivo, tal y como exige el pliego.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.tipos import ND, Criterio
from ..core.util import a_float


LOG = logging.getLogger("dml.parrilla")

TOTAL_CRITERIOS = 12

#: Ruta de Investing.com de la que procede el dato de cada criterio.
RUTAS_INVESTING = {
    "per": "https://www.investing.com/equities/{ticker}-ratios",
    "eps": "https://www.investing.com/equities/{ticker}-earnings",
    "fcf": "https://www.investing.com/equities/{ticker}-ratios",
    "tecnico": "https://www.investing.com/equities/{ticker}-technical",
    "beta": "https://www.investing.com/equities/{ticker}",
    "capm": "https://www.investing.com/equities/{ticker}",
    "tasa": "https://www.investing.com/rates-bonds/u.s.-4-week-bond-yield",
    "bono10": "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield",
    "bono30": "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield",
}

#: Claves que el panel "Parametros" puede sobrescribir, con su seccion de config.
MAPA_OVERRIDES: Dict[str, Tuple[str, str]] = {
    "beta_max": ("umbrales", "beta_max"),
    "r2_min": ("umbrales", "r2_min"),
    "trg_extra_tlr": ("umbrales", "trg_extra_tlr"),
    "delta_call_min": ("umbrales", "delta_call_min"),
    "comprar_min": ("decision", "comprar_min"),
    "mantener_min": ("decision", "mantener_min"),
    "meses_pronostico": ("general", "meses_pronostico"),
    "modo": ("general", "modo"),
}


def config_con_overrides(config: Optional[Dict[str, Any]], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Inyecta los umbrales editados en pantalla dentro de la configuracion.

    Es lo que permite que mover un control del panel "Parametros" cambie de
    verdad el resultado de la parrilla (y no solo los modelos).

    Args:
        config: configuracion efectiva.
        overrides: diccionario del panel (``beta_max``, ``r2_min``,
            ``trg_extra_tlr``, ``delta_call_min``, ``comprar_min``,
            ``mantener_min``, ``meses_pronostico``, ``modo``).

    Returns:
        Una copia de la configuracion con las secciones ``umbrales``,
        ``decision`` y ``general`` actualizadas.
    """
    salida: Dict[str, Any] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (config or {}).items()}
    if not overrides:
        return salida
    for clave_panel, (seccion, clave) in MAPA_OVERRIDES.items():
        if clave_panel not in overrides:
            continue
        valor = overrides.get(clave_panel)
        if valor is None:
            continue
        if clave_panel != "modo" and a_float(valor) is None:
            continue
        salida[seccion] = {**(salida.get(seccion) or {}), clave: valor}
    return salida


def rutas_investing(ticker: str) -> Dict[str, str]:
    """Devuelve las URLs de Investing.com del ticker con el simbolo sustituido."""
    simbolo = (ticker or "").lower()
    return {clave: url.format(ticker=simbolo) for clave, url in RUTAS_INVESTING.items()}


def _es_numero(valor: Any) -> bool:
    """True si el valor es un numero utilizable (ni ``None`` ni ``NaN``)."""
    return a_float(valor) is not None


def _criterio(
    numero: int,
    nombre: str,
    optimo: str,
    valor: Any,
    comparacion: Any,
    cumple: bool,
    fuente: str,
    ruta: str = "",
    nota: str = "",
    activo: bool = True,
    unidad: str = "numero",
    formula: str = "",
) -> Criterio:
    """Construye un criterio aplicando la regla "N/D => 0 puntos con nota"."""
    motivo = nota
    if not _es_numero(valor) and not isinstance(valor, str):
        if not motivo:
            motivo = "N/D: dato no disponible; el criterio se califica 0"
    if not cumple and not motivo and not _es_numero(comparacion) and not isinstance(comparacion, str):
        motivo = "N/D: falta el valor de comparacion; el criterio se califica 0"
    return Criterio(
        numero=numero,
        nombre=nombre,
        optimo=optimo,
        valor=valor if valor is not None else ND,
        comparacion=comparacion if comparacion is not None else ND,
        cumple=bool(cumple),
        calificacion=1 if cumple else 0,
        fuente=fuente,
        ruta=ruta,
        nota=motivo,
        activo=activo,
        unidad=unidad,
        formula=formula,
    )


def construir_parrilla(r: Any, config: Optional[Dict[str, Any]] = None) -> List[Criterio]:
    """Construye los 12 criterios binarios a partir de un resultado de analisis.

    Args:
        r: instancia de :class:`~dml.core.tipos.ResultadoAnalisis` ya calculada.
        config: configuracion efectiva (``umbrales``, ``decision``). Si falta, se
            usan los valores por defecto del pliego.

    Returns:
        Lista de 12 :class:`~dml.core.tipos.Criterio` en el orden del pliego.
    """
    config = config or {}
    umbrales = config.get("umbrales", {}) or {}
    beta_max = a_float(umbrales.get("beta_max")) or 1.10
    r2_min = a_float(umbrales.get("r2_min")) or 0.70
    margen_extra = a_float(umbrales.get("trg_extra_tlr"))
    margen_extra = 0.01 if margen_extra is None else margen_extra
    delta_min = a_float(umbrales.get("delta_call_min")) or 0.50

    f = r.fundamentales
    tlr = a_float(r.tlr)
    rutas = rutas_investing(r.ticker)
    criterios: List[Criterio] = []

    # 1. PER empresa < PER sector -------------------------------------------------
    nota = ""
    if f.per is not None and a_float(f.per) is not None and a_float(f.per) < 0:
        nota = "PER negativo (perdidas): no cumple por definicion"
    elif not _es_numero(f.per) or not _es_numero(f.per_sector):
        nota = "N/D: falta el PER de la empresa o del sector; el criterio se califica 0"
    cumple1 = bool(
        _es_numero(f.per) and _es_numero(f.per_sector) and a_float(f.per) > 0 and a_float(f.per) < a_float(f.per_sector)
    )
    criterios.append(
        _criterio(
            1,
            "PER empresa < PER sector",
            "Menor es mejor",
            f.per,
            f.per_sector,
            cumple1,
            "Yahoo Finance (yfinance) / Investing.com - Ratios",
            rutas["per"],
            nota,
            formula="=PER!B{filas} < PER!C{filas}",
        )
    )

    # 2. EPS actual >= EPS estimado ----------------------------------------------
    nota2 = (
        ""
        if (_es_numero(f.eps) and _es_numero(f.eps_forecast))
        else "N/D: falta el EPS actual o el estimado; se califica 0"
    )
    cumple2 = bool(_es_numero(f.eps) and _es_numero(f.eps_forecast) and a_float(f.eps) >= a_float(f.eps_forecast))
    criterios.append(
        _criterio(
            2,
            "EPS actual >= EPS estimado (forecast)",
            "Mayor o igual es mejor",
            f.eps,
            f.eps_forecast,
            cumple2,
            "Yahoo Finance (yfinance) / Investing.com - Earnings",
            rutas["eps"],
            nota2,
            formula="=EPS!B{filas} >= EPS!C{filas}",
        )
    )

    # 3. Tecnico: MACD distinto de Sell ------------------------------------------
    senal = r.macd_senal or ND
    cumple3 = senal in {"Buy", "Neutral"}
    criterios.append(
        _criterio(
            3,
            "Tecnico: senal MACD (1 mes) distinta de Sell",
            "Neutral o Buy",
            senal,
            "Sell",
            cumple3,
            "Calculado con precios diarios de Yahoo Finance (yfinance); resumen de Investing.com - Technical",
            rutas["tecnico"],
            r.macd_detalle or ("N/D: no se pudo calcular el MACD" if senal == ND else ""),
            unidad="texto",
            formula='=IF(Tecnico!B{filas}<>"Sell",1,0)',
        )
    )

    # 4. Price to FCF empresa < sector -------------------------------------------
    nota4 = ""
    if not _es_numero(f.p_fcf) or not _es_numero(f.p_fcf_sector):
        nota4 = "N/D: falta el Price to FCF de la empresa o del sector; el criterio se califica 0"
    cumple4 = bool(
        _es_numero(f.p_fcf) and _es_numero(f.p_fcf_sector) and a_float(f.p_fcf) < a_float(f.p_fcf_sector)
    )
    criterios.append(
        _criterio(
            4,
            "Price to FCF empresa < Price to FCF sector",
            "Menor es mejor",
            f.p_fcf,
            f.p_fcf_sector,
            cumple4,
            "Yahoo Finance (yfinance) / Investing.com - Ratios",
            rutas["fcf"],
            nota4,
        )
    )

    # 5. Rend_CAPM > TLR ---------------------------------------------------------
    nota5 = (
        ""
        if (_es_numero(r.rend_capm) and _es_numero(tlr))
        else "N/D: falta el Rend_CAPM o la TLR; se califica 0"
    )
    cumple5 = bool(_es_numero(r.rend_capm) and _es_numero(tlr) and a_float(r.rend_capm) > a_float(tlr))
    criterios.append(
        _criterio(
            5,
            "Rend_CAPM > TLR",
            "Mayor es mejor",
            r.rend_capm,
            tlr,
            cumple5,
            "Calculado: TLR (Investing.com - T-Bill 4 semanas) + Beta x PRH",
            rutas["tasa"],
            nota5,
            unidad="porcentaje",
            formula="=CAPM!Rend_CAPM > CAPM!TLR",
        )
    )

    # 6. Beta < beta_max ---------------------------------------------------------
    beta = r.beta_cov if _es_numero(r.beta_cov) else r.beta_ols
    nota6 = "" if _es_numero(beta) else "N/D: no se pudo estimar la Beta; se califica 0"
    cumple6 = bool(_es_numero(beta) and a_float(beta) < beta_max)
    criterios.append(
        _criterio(
            6,
            f"Beta < {beta_max:.2f}",
            "Menor es mejor",
            beta,
            beta_max,
            cumple6,
            "Calculado con COVAR/VAR de rendimientos mensuales; contrastado con la Beta publicada de Investing.com",
            rutas["beta"],
            nota6,
        )
    )

    # 7. Renta PER (1/PER) > TLR -------------------------------------------------
    renta = None
    per_val = a_float(f.per)
    if per_val is not None and per_val > 0:
        renta = 1.0 / per_val
    nota7 = (
        ""
        if (renta is not None and tlr is not None)
        else "N/D: sin PER positivo o sin TLR no se puede comparar la Renta PER"
    )
    cumple7 = bool(renta is not None and tlr is not None and renta > tlr)
    criterios.append(
        _criterio(
            7,
            "Renta PER (1/PER) > TLR",
            "Mayor es mejor",
            renta,
            tlr,
            cumple7,
            "Calculado con el PER de la empresa (yfinance / Investing.com - Ratios) y la TLR de Investing.com",
            rutas["per"],
            nota7,
            unidad="porcentaje",
            formula="=1/PER!B{filas} > Tasas!TLR",
        )
    )

    # 8. RDR: Rend_CAPM > Riesgo (desviacion estandar) ---------------------------
    riesgo = r.riesgo.sigma_anual if r.riesgo is not None else None
    nota8 = (
        ""
        if (_es_numero(r.rend_capm) and _es_numero(riesgo))
        else "N/D: falta el Rend_CAPM o la desviacion estandar; se califica 0"
    )
    cumple8 = bool(_es_numero(r.rend_capm) and _es_numero(riesgo) and a_float(r.rend_capm) > a_float(riesgo))
    criterios.append(
        _criterio(
            8,
            "RDR: Rend_CAPM > Riesgo (desviacion estandar anual)",
            "Mayor es mejor",
            r.rend_capm,
            riesgo,
            cumple8,
            "Calculado: Rend_CAPM y sigma anual de los rendimientos mensuales",
            rutas["capm"],
            nota8,
            unidad="porcentaje",
            formula="=RDR!Rend_CAPM > RDR!Sigma_anual",
        )
    )

    # 9. R2 del modelo econometrico > r2_min -------------------------------------
    r2 = r.ols.r2 if r.ols is not None else None
    nota9 = "" if _es_numero(r2) else "N/D: el modelo econometrico no se pudo estimar; se califica 0"
    cumple9 = bool(_es_numero(r2) and a_float(r2) > r2_min)
    criterios.append(
        _criterio(
            9,
            f"R2 del modelo econometrico > {r2_min:.2f}",
            "Mayor es mejor",
            r2,
            r2_min,
            cumple9,
            "Calculado: MCO de Precio ~ periodo mensual (statsmodels)",
            rutas["capm"],
            nota9,
        )
    )

    # 10. Precio proyectado por TRG > Spot x (1 + TLR + 1%) ----------------------
    proyeccion = a_float(r.precio_proyectado_trg)
    umbral10 = None
    if _es_numero(r.spot) and tlr is not None:
        umbral10 = a_float(r.spot) * (1.0 + tlr + margen_extra)
    nota10 = ""
    if r.modo == "excel":
        nota10 = (
            "[MODO EXCEL] Se compara PROMEDIO(precios) x (1 + TRG) contra Spot x (1 + TLR + 1%): "
            "las escalas no son homogeneas."
        )
    if proyeccion is None or umbral10 is None:
        nota10 = (nota10 + " " if nota10 else "") + "N/D: falta el precio proyectado por TRG o el spot; se califica 0"
    cumple10 = bool(proyeccion is not None and umbral10 is not None and proyeccion > umbral10)
    criterios.append(
        _criterio(
            10,
            f"TRG: precio proyectado > Spot x (1 + TLR + {margen_extra:.2%})",
            "Mayor es mejor",
            proyeccion,
            umbral10,
            cumple10,
            "Calculado: TRG de la serie mensual y TLR de Investing.com",
            rutas["tasa"],
            nota10,
            unidad="moneda",
        )
    )

    # 11. Forward: Spot < Strike (Forward) ---------------------------------------
    strike = a_float(r.strike)
    forward_nota = "Este criterio cumple casi siempre que r > q, porque K = S x e^(bT) con b = r - q."
    if r.strike_modo == "manual":
        forward_nota += " Strike definido manualmente."
    nota11 = forward_nota
    if not _es_numero(r.spot) or strike is None:
        nota11 += " N/D: falta el spot o el strike; se califica 0"
    cumple11 = bool(_es_numero(r.spot) and strike is not None and a_float(r.spot) < strike)
    criterios.append(
        _criterio(
            11,
            "Forward: Spot < Strike (precio forward)",
            "Cumple si el forward esta por encima del spot",
            r.spot,
            strike,
            cumple11,
            "Calculado: Strike = S x e^(bT), con b = r - q",
            rutas["tasa"],
            nota11,
            unidad="moneda",
        )
    )

    # 12. Delta Call > delta_min -------------------------------------------------
    delta = a_float(r.griegas_call.get("delta")) if r.griegas_call else None
    nota12 = (
        "Con K = Forward la Delta tiende a superar 0.5 en la mayoria de los casos "
        "(depende del signo de b = r - q)."
    )
    if delta is None:
        nota12 += " N/D: no se pudo calcular la Delta; se califica 0"
    cumple12 = bool(delta is not None and delta > delta_min)
    criterios.append(
        _criterio(
            12,
            f"Delta Call > {delta_min:.2f}",
            "Mayor es mejor",
            delta,
            delta_min,
            cumple12,
            "Calculado: Black-Scholes-Merton generalizado",
            rutas["tasa"],
            nota12,
        )
    )

    return criterios


def aplicar_activos(criterios: Sequence[Criterio], activos: Optional[Dict[int, bool]]) -> List[Criterio]:
    """Marca como inactivos los criterios indicados en ``activos``.

    Args:
        criterios: lista de criterios.
        activos: mapa ``{numero: bool}``. Los numeros ausentes se consideran
            activos (comportamiento por defecto: los 12).
    """
    if not activos:
        return list(criterios)
    salida: List[Criterio] = []
    for c in criterios:
        c.activo = bool(activos.get(c.numero, True))
        salida.append(c)
    return salida


def calcular_calificacion(
    criterios: Sequence[Criterio], config: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[float], str]:
    """Califica la parrilla promediando **solo** los criterios activos.

    Returns:
        ``(calificacion, decision)``. La calificacion es ``None`` si no hay
        ningun criterio activo. La decision sale de ``config['decision']``:

        * ``calificacion > comprar_min`` -> ``COMPRAR``
        * ``calificacion >= mantener_min`` -> ``MANTENER``
        * en otro caso -> ``NO INVERTIR``
    """
    config = config or {}
    reglas = config.get("decision", {}) or {}
    comprar_min = a_float(reglas.get("comprar_min"))
    comprar_min = 0.70 if comprar_min is None else comprar_min
    mantener_min = a_float(reglas.get("mantener_min"))
    mantener_min = 0.40 if mantener_min is None else mantener_min

    activos = [c for c in criterios if c.activo]
    if not activos:
        return None, ND
    cumplidos = sum(1 for c in activos if c.cumple)
    calificacion = cumplidos / float(len(activos))
    return calificacion, decision_desde_calificacion(calificacion, comprar_min, mantener_min)


def decision_desde_calificacion(
    calificacion: Optional[float], comprar_min: float = 0.70, mantener_min: float = 0.40
) -> str:
    """Aplica la regla de decision del pliego a una calificacion promedio."""
    c = a_float(calificacion)
    if c is None:
        return ND
    if c > comprar_min:
        return "COMPRAR"
    if c >= mantener_min:
        return "MANTENER"
    return "NO INVERTIR"


def resumen_parrilla(criterios: Sequence[Criterio]) -> Dict[str, Any]:
    """Resumen de la parrilla para la barra de estado y el informe."""
    activos = [c for c in criterios if c.activo]
    cumplidos = [c for c in activos if c.cumple]
    return {
        "total": len(criterios),
        "activos": len(activos),
        "cumplidos": len(cumplidos),
        "fallidos": len(activos) - len(cumplidos),
        "sin_datos": [c.numero for c in activos if not _es_numero(c.valor) and not isinstance(c.valor, str)],
        "detalle_cumplidos": [c.nombre for c in cumplidos],
    }


def tabla_criterios(criterios: Sequence[Criterio]) -> List[Dict[str, Any]]:
    """Convierte la parrilla en filas listas para una tabla Qt o un DataFrame."""
    filas: List[Dict[str, Any]] = []
    for c in criterios:
        filas.append(
            {
                "#": c.numero,
                "Criterio": c.nombre,
                "Optimo": c.optimo,
                "Valor obtenido": c.valor,
                "Valor de comparacion": c.comparacion,
                "Cumple": "SI" if c.cumple else "NO",
                "Calificacion": c.calificacion,
                "Activo": "SI" if c.activo else "NO",
                "Fuente": c.fuente,
                "Ruta Investing": c.ruta,
                "Nota": c.nota,
            }
        )
    return filas
