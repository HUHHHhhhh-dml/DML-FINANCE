# -*- coding: utf-8 -*-
"""Tasas de referencia de EE.UU.: T-Bill 4 semanas, bono 10 y 30 anios.

Cadena de respaldos exigida por el pliego
-----------------------------------------
1. **Investing.com** con ``cloudscraper``/``requests`` y cabeceras de navegador.
2. **Investing.com** con **Playwright** (navegador headless).
3. **FRED** (``FRED_API_KEY`` o ``fredgraph.csv`` publico):

   - TLR 4 semanas: ``DGS1MO`` (rendimiento constante de inversion).
     Si solo hubiera ``DTB4WK`` (base a **descuento**), se convierte a
     rendimiento equivalente de bono **antes** de usarla.
   - 10 anios: ``DGS10``. 30 anios: ``DGS30``.
4. **Yahoo Finance** solo para 10 anios (``^TNX``) y 30 anios (``^TYX``).
   ``^IRX`` es el T-Bill a **13 semanas** y por eso **no** se usa como TLR de 4
   semanas.
5. **Manual**: se pide el valor al usuario y queda registrado como ``manual``.

Conversion descuento -> rendimiento
-----------------------------------
Un T-Bill se cotiza a descuento: ``d`` es la tasa de descuento anualizada sobre
el valor nominal. El rendimiento equivalente de bono (base 365, el que se puede
comparar con los rendimientos de Investing.com) es:

.. math:: y = \\frac{365 \\cdot d}{360 - d \\cdot t}

con ``t`` el plazo en dias (28 para el T-Bill de 4 semanas). Nunca se mezcla una
tasa a descuento con rendimientos de Investing sin convertir: la diferencia
ronda los 15-20 puntos base.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..core.cache import Cache
from ..core.tipos import Evidence, Fuentes, Tasas
from ..core.util import a_float, ahora_iso, normalizar_mensual, truncar_meses
from .proveedores import (
    DIAS_ANIO_BONO,
    DIAS_ANIO_DESCUENTO,
    MOTIVO_MANUAL_PENDIENTE,
    pedir_valor_manual,
    scrape_investing,
    scrape_investing_playwright,
    serie_fred,
    tasa_yahoo_simple,
    tasa_yfinance,
)

LOG = logging.getLogger("dml.tasas")

CLAVES = ("tbill_4w", "ust_10y", "ust_30y")
ETIQUETAS = {
    "tbill_4w": "T-Bill EE.UU. 4 semanas (TLR)",
    "ust_10y": "Bono EE.UU. 10 anios",
    "ust_30y": "Bono EE.UU. 30 anios",
}


def rendimiento_equivalente_bono(
    tasa_descuento: Optional[float], dias: int = 28, dias_anio: int = DIAS_ANIO_BONO, base_descuento: int = DIAS_ANIO_DESCUENTO
) -> Optional[float]:
    """Convierte una tasa a **descuento** en rendimiento equivalente de bono.

    Formula del pliego: ``y = 365 * d / (360 - d * t)`` con ``t`` en dias.

    Args:
        tasa_descuento: tasa de descuento anualizada en fraccion (``0.0425`` = 4,25%).
        dias: plazo del instrumento en dias (28 para el T-Bill de 4 semanas).
        dias_anio: base del rendimiento de salida (365).
        base_descuento: base de la tasa de descuento (360).

    Returns:
        El rendimiento equivalente en fraccion, o ``None`` si la entrada no es
        valida o el denominador se anula.
    """
    d = a_float(tasa_descuento)
    if d is None:
        return None
    denominador = float(base_descuento) - d * float(dias)
    if denominador <= 0:
        LOG.warning("Conversion descuento->rendimiento imposible: denominador %s", denominador)
        return None
    return float(dias_anio) * d / denominador


def descuento_a_rendimiento(tasa_descuento: Optional[float], dias: int = 28) -> Optional[float]:
    """Alias corto y explicito de :func:`rendimiento_equivalente_bono`."""
    return rendimiento_equivalente_bono(tasa_descuento, dias=dias)


def _normalizar_tasa_porcentaje(valor: Any) -> Optional[float]:
    """Convierte un valor cotizado en porcentaje (``4.35``) a fraccion (``0.0435``).

    Investing.com, FRED y Yahoo publican las tasas en tanto por ciento. Si el
    valor ya viniera en fraccion (``0.0435``) se respeta tal cual.
    """
    v = a_float(valor)
    if v is None:
        return None
    return v / 100.0 if abs(v) > 1.0 else v


def _producto_cache(cache: Optional[Cache], clave: str, productor) -> Any:
    """Envuelve el cacheo para no repetir peticiones dentro del mismo dia."""
    if cache is None:
        return productor()
    return cache.obtener(clave, productor)


def _fila_fred(cache: Optional[Cache], series_id: str, config: Dict[str, Any]) -> Optional[pd.Series]:
    """Serie diaria de FRED, cacheada, ya normalizada a mensual si se pide."""
    clave = f"fred|{series_id}"
    guardado = _producto_cache(cache, clave, lambda: serie_fred(series_id, cache=None, config=config))
    if guardado is None:
        return None
    if isinstance(guardado, dict) and "index" in guardado:
        try:
            s = pd.Series(guardado["valores"], index=pd.to_datetime(guardado["index"]), dtype="float64")
            return s.dropna()
        except Exception:  # pragma: no cover
            return None
    return guardado if isinstance(guardado, pd.Series) else None


def _agregar_mensual(serie: Optional[pd.Series], modo: str = "last") -> Optional[pd.Series]:
    """Agrega una serie diaria a mensual (ultimo dato o media del mes)."""
    if serie is None or len(serie) == 0:
        return None
    s = pd.Series(serie).astype(float).dropna()
    if len(s) == 0:
        return None
    s.index = pd.to_datetime(s.index)
    agrupado = s.resample("ME")
    mensual = agrupado.last() if modo == "last" else agrupado.mean()
    return normalizar_mensual(mensual.dropna())


def _serie_tbill_fred(cache: Optional[Cache], config: Dict[str, Any]) -> Tuple[Optional[pd.Series], str]:
    """Serie mensual de la TLR desde FRED, convirtiendo el descuento si es preciso.

    Prioridad: ``DGS1MO`` (rendimiento de inversion). Si no hay, ``DTB4WK``
    (descuento) **convertido** a rendimiento equivalente de bono.

    Returns:
        ``(serie_mensual_en_fraccion, descripcion_del_metodo)``.
    """
    datos_cfg = config.get("datos", {}) or {}
    series = datos_cfg.get("fred_series", {}) or {}
    dias = int(datos_cfg.get("dias_tbill_descuento", 28) or 28)
    agregacion = str(datos_cfg.get("agregacion_fred", "last"))

    identificador = series.get("tbill_4w", "DGS1MO")
    serie = _fila_fred(cache, identificador, config)
    if serie is not None and len(serie) > 0:
        fraccion = serie.map(_normalizar_tasa_porcentaje)
        return _agregar_mensual(fraccion, agregacion), f"FRED {identificador} (rendimiento de inversion)"

    descuento_id = series.get("tbill_4w_descuento", "DTB4WK")
    LOG.warning("FRED %s no disponible: se intenta %s y se convierte de descuento a rendimiento", identificador, descuento_id)
    serie_d = _fila_fred(cache, descuento_id, config)
    if serie_d is not None and len(serie_d) > 0:
        convertida = serie_d.map(lambda v: rendimiento_equivalente_bono(_normalizar_tasa_porcentaje(v), dias=dias))
        return (
            _agregar_mensual(convertida, agregacion),
            f"FRED {descuento_id} convertido a rendimiento de bono (y = 365d/(360-d*{dias}))",
        )

    return None, ""


def proxy_tlr_yahoo(
    cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[float], str]:
    """Ultimo respaldo automatico de la TLR: ``^IRX`` de Yahoo Finance.

    Yahoo no publica el T-Bill a **4 semanas**, asi que el unico proxy disponible
    es ``^IRX``, que es el T-Bill a **13 semanas**. El pliego prohibe presentar
    ``^IRX`` como si fuera la TLR de 4 semanas, por lo que este respaldo se usa
    **etiquetado como proxy** y acompanado de un aviso visible con la diferencia
    de plazo. Quien necesite el dato exacto puede escribirlo en el panel de
    parametros (queda registrado como ``manual``).

    Returns:
        ``(valor_en_fraccion, url_consultada)``; el valor es ``None`` si el proxy
        no responde.
    """
    datos_cfg = (config or {}).get("datos", {}) or {}
    simbolo = str((datos_cfg.get("yf_series", {}) or {}).get("tbill_4w_proxy", "^IRX"))
    url = f"https://finance.yahoo.com/quote/{simbolo}"
    try:
        bruto = _producto_cache(
            cache,
            f"yf_proxy|{simbolo}",
            lambda: tasa_yahoo_simple(simbolo, int(datos_cfg.get("timeout_seg", 25) or 25)),
        )
    except Exception as exc:  # pragma: no cover - red
        LOG.warning("El proxy %s de Yahoo fallo: %s", simbolo, exc)
        return None, url
    return _normalizar_tasa_porcentaje(bruto), url


def _serie_tasa_generica(cache: Optional[Cache], clave: str, config: Dict[str, Any]) -> Tuple[Optional[pd.Series], str]:
    """Serie mensual de una tasa desde FRED (DGS10 / DGS30)."""
    datos_cfg = config.get("datos", {}) or {}
    series = datos_cfg.get("fred_series", {}) or {}
    agregacion = str(datos_cfg.get("agregacion_fred", "last"))
    identificador = series.get(clave)
    if not identificador:
        return None, ""
    serie = _fila_fred(cache, identificador, config)
    if serie is None or len(serie) == 0:
        return None, ""
    fraccion = serie.map(_normalizar_tasa_porcentaje)
    return _agregar_mensual(fraccion, agregacion), f"FRED {identificador}"


def obtener_tasas(
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    config: Optional[Dict[str, Any]] = None,
    meses: int = 60,
    manuales: Optional[Dict[str, float]] = None,
    permitir_manual: bool = True,
) -> Tasas:
    """Obtiene la TLR de 4 semanas y los bonos a 10 y 30 anios.

    Recorre la cadena Investing.com -> Playwright -> FRED -> Yahoo (solo 10 y 30)
    -> manual, registrando en :class:`~dml.core.tipos.Tasas` el **metodo** real
    usado para cada tasa, la diferencia en puntos base entre Investing y el
    respaldo, y las advertencias correspondientes.

    Args:
        cache: cache local por dia.
        fuentes: registro de procedencia de los datos.
        config: configuracion efectiva (``datos.investing_urls``, ``datos.fred_series``...).
        meses: meses de historico mensual de la TLR que se guardan.
        manuales: valores manuales previos (``{'tbill_4w': 0.0435}``) que tienen
            prioridad y quedan registrados como ``manual``.
        permitir_manual: ``False`` cuando la descarga corre en un hilo de trabajo
            (Qt no permite abrir dialogos fuera del hilo de la interfaz): los
            datos que falten se marcan como pendientes de captura manual.

    Returns:
        Una instancia de :class:`~dml.core.tipos.Tasas`.
    """
    config = config or {}
    datos_cfg = config.get("datos", {}) or {}
    urls = datos_cfg.get("investing_urls", {}) or {}
    manuales = manuales or {}
    resultado = Tasas()
    ahora = ahora_iso()

    for clave in CLAVES:
        etiqueta = ETIQUETAS[clave]
        url = urls.get(clave, "")
        valor: Optional[float] = None
        metodo = "N/D"
        fuente = ""
        nota = ""

        # ---- 0) valor manual declarado explicitamente --------------------
        manual = a_float(manuales.get(clave))
        if manual is not None:
            valor, metodo, fuente = manual, "manual", "Introducido manualmente"
            nota = "Valor manual indicado por el usuario: tiene prioridad sobre las fuentes automaticas"

        # ---- 1) Investing.com (cloudscraper / requests) ------------------
        if valor is None and datos_cfg.get("intentar_investing", True) and url:
            leer = lambda u=url: scrape_investing(u, config)  # noqa: E731
            bruto = _producto_cache(cache, f"investing|{clave}", leer)
            if bruto is not None:
                valor = _normalizar_tasa_porcentaje(bruto)
                metodo, fuente = "scraping", "Investing.com"
                LOG.info("Investing.com %s = %s", clave, valor)

        # ---- 2) Investing.com con Playwright ----------------------------
        if valor is None and datos_cfg.get("intentar_investing", True) and datos_cfg.get("usar_playwright", True) and url:
            leer_pw = lambda u=url: scrape_investing_playwright(u, config)  # noqa: E731
            bruto = _producto_cache(cache, f"investing_pw|{clave}", leer_pw)
            if bruto is not None:
                valor = _normalizar_tasa_porcentaje(bruto)
                metodo, fuente = "scraping", "Investing.com (Playwright)"
                nota = "Obtenido con navegador headless porque el scraping simple fue bloqueado"
                LOG.info("Investing.com (Playwright) %s = %s", clave, valor)

        # ---- 3) FRED (respaldo) -----------------------------------------
        if valor is None and datos_cfg.get("usar_fred", True):
            try:
                if clave == "tbill_4w":
                    serie, descripcion = _serie_tbill_fred(cache, config)
                else:
                    serie, descripcion = _serie_tasa_generica(cache, clave, config)
            except Exception as exc:  # pragma: no cover - red
                LOG.warning("FRED fallo para %s: %s", clave, exc)
                serie, descripcion = None, ""
            if serie is not None and len(serie) > 0:
                valor = float(serie.dropna().iloc[-1])
                metodo, fuente = "respaldo", "FRED"
                nota = descripcion
                if clave == "tbill_4w":
                    resultado.serie_tbill_mensual = truncar_meses(serie, meses)
                elif clave == "ust_10y":
                    resultado.serie_10y_mensual = truncar_meses(serie, meses)
                else:
                    resultado.serie_30y_mensual = truncar_meses(serie, meses)

        # ---- 4) Yahoo Finance -------------------------------------------
        # 10 y 30 anios: ^TNX y ^TYX son exactamente esos plazos.
        # 4 semanas: Yahoo NO lo publica; el unico proxy es ^IRX (13 semanas),
        # asi que se usa ETIQUETADO como proxy y con aviso de la diferencia.
        if valor is None and datos_cfg.get("usar_yfinance_tasas", True):
            if clave in {"ust_10y", "ust_30y"}:
                simbolo = (datos_cfg.get("yf_series", {}) or {}).get(clave)
                if simbolo:
                    bruto = _producto_cache(cache, f"yf_tasa|{simbolo}", lambda s=simbolo: tasa_yfinance(s, None, config))
                    if bruto is not None:
                        valor = _normalizar_tasa_porcentaje(bruto)
                        metodo, fuente = "respaldo", f"Yahoo Finance ({simbolo})"
                        nota = "Respaldo de Yahoo Finance (solo disponible para 10 y 30 anios)"
            else:
                proxy, url_proxy = proxy_tlr_yahoo(cache, config)
                if proxy is not None:
                    valor = proxy
                    metodo, fuente = "respaldo", "Yahoo Finance (^IRX, 13 semanas)"
                    nota = (
                        "ATENCION: ^IRX es el T-Bill a 13 SEMANAS, no a 4. Se usa como proxy "
                        "porque ninguna otra fuente automatica respondio; escriba el valor exacto "
                        "de la TLR en el panel de parametros si necesita precision."
                    )
                    url = url_proxy
                    resultado.advertencias.append(
                        "La TLR se ha tomado del proxy ^IRX (T-Bill a 13 semanas), NO del T-Bill a 4 semanas: "
                        "revisa el valor manualmente."
                    )

        # ---- 5) manual interactivo --------------------------------------
        if valor is None and datos_cfg.get("usar_manual", True) and permitir_manual:
            valor = pedir_valor_manual(etiqueta, config)
            if valor is not None:
                metodo, fuente = "manual", "Introducido manualmente"
                nota = "Ninguna fuente automatica respondio: valor solicitado manualmente"

        # ---- registro ----------------------------------------------------
        valor_final = a_float(valor)
        if valor_final is not None:
            ev = Evidence(
                value=valor_final,
                fuente=fuente,
                url=url,
                metodo=metodo,
                consultado=ahora,
                nota=nota,
            )
        else:
            pendiente = bool(datos_cfg.get("usar_manual", True)) and not permitir_manual
            ev = Evidence(
                fuente=fuente or "Investing.com / FRED / Yahoo Finance",
                url=url,
                metodo="N/D",
                consultado=ahora,
                nota=MOTIVO_MANUAL_PENDIENTE if pendiente else "No se pudo obtener de ninguna fuente automatica ni manual",
            )
            resultado.advertencias.append(
                f"{etiqueta}: N/D (se intento Investing.com, Playwright, FRED"
                + (", Yahoo Finance" if clave in {"ust_10y", "ust_30y"} else "")
                + ("; queda pendiente la captura manual" if pendiente else " y captura manual")
                + ")"
            )
            if pendiente:
                resultado.pendientes_manual.append(etiqueta)

        resultado.metodos[clave] = metodo
        if clave == "tbill_4w":
            resultado.tbill_4w, resultado.ev_tbill_4w = valor_final, ev
        elif clave == "ust_10y":
            resultado.ust_10y, resultado.ev_ust_10y = valor_final, ev
        else:
            resultado.ust_30y, resultado.ev_ust_30y = valor_final, ev

        if fuentes is not None:
            fuentes.add(etiqueta, valor_final, fuente or "N/D", url, metodo, ev.nota, categoria="tasas")

    # ---- diferencia en puntos base entre Investing y el respaldo --------
    resultado.diferencias_pb = _diferencias_pb(cache, config, resultado)
    for clave, pb in resultado.diferencias_pb.items():
        if abs(pb) > 25.0:
            aviso = (
                f"{ETIQUETAS[clave]}: la diferencia entre Investing.com y el respaldo es de "
                f"{pb:+.1f} pb (> 25 pb): revisa que no se este mezclando una tasa a descuento con un rendimiento."
            )
            resultado.advertencias.append(aviso)
            LOG.warning(aviso)

    # La serie mensual historica de la TLR se necesita para la tabla de la
    # pestana "Bonos y tasas" y para los rendimientos mensuales del CAPM, con
    # independencia de la fuente que haya dado el valor puntual de hoy. Se pide a
    # FRED solo para el historico.
    if resultado.serie_tbill_mensual is None and datos_cfg.get("usar_fred", True):
        try:
            serie, _ = _serie_tbill_fred(cache, config)
            resultado.serie_tbill_mensual = truncar_meses(serie, meses)
        except Exception as exc:  # pragma: no cover - red
            LOG.warning("No se pudo obtener la serie historica mensual de la TLR: %s", exc)
    if resultado.serie_tbill_mensual is None and resultado.tbill_4w is not None:
        # Respaldo sin red: el CAPM necesita una serie mensual alineada con los
        # precios, asi que se usa el valor actual de forma constante.
        LOG.info("Sin serie historica de la TLR: se usara el valor actual constante")
        resultado.advertencias.append(
            "Serie historica mensual de la TLR no disponible: se usa el valor actual de forma constante "
            "en los calculos mensuales (la pestana 'Bonos y tasas' mostrara solo el valor de hoy)."
        )
    elif resultado.serie_tbill_mensual is None:
        resultado.advertencias.append(
            "Serie historica mensual de la TLR no disponible: los calculos que la necesitan se marcaran como N/D"
        )

    return resultado


def _diferencias_pb(cache: Optional[Cache], config: Dict[str, Any], resultado: Tasas) -> Dict[str, float]:
    """Diferencia en puntos base entre el valor principal y el respaldo FRED.

    Solo se calcula cuando el valor principal vino de Investing.com y existe un
    respaldo FRED para el mismo concepto.
    """
    diferencias: Dict[str, float] = {}
    datos_cfg = config.get("datos", {}) or {}
    if not datos_cfg.get("usar_fred", True):
        return diferencias
    for clave in CLAVES:
        if resultado.metodos.get(clave) != "scraping":
            continue
        principal = a_float(getattr(resultado, clave, None))
        if principal is None:
            continue
        try:
            if clave == "tbill_4w":
                serie, _ = _serie_tbill_fred(cache, config)
            else:
                serie, _ = _serie_tasa_generica(cache, clave, config)
        except Exception:  # pragma: no cover - red
            serie = None
        if serie is None or len(serie) == 0:
            continue
        respaldo = a_float(serie.dropna().iloc[-1])
        if respaldo is None:
            continue
        diferencias[clave] = (principal - respaldo) * 10_000.0
    return diferencias


def serie_tasas_fred(series_id: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None) -> Optional[pd.Series]:
    """Serie diaria de FRED lista para usar (envoltorio con cache)."""
    return _fila_fred(cache, series_id, config or {})


def resumen_tasas(tasas: Tasas) -> List[Dict[str, Any]]:
    """Filas listas para la pestana "Bonos y tasas"."""
    filas: List[Dict[str, Any]] = []
    for clave in CLAVES:
        valor = a_float(getattr(tasas, clave, None))
        filas.append(
            {
                "Tasa": ETIQUETAS[clave],
                "Valor": valor,
                "Metodo": tasas.metodo_de(clave),
                "Diferencia vs respaldo (pb)": tasas.diferencias_pb.get(clave),
            }
        )
    return filas
