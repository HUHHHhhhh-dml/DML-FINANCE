# -*- coding: utf-8 -*-
"""Orquestacion del analisis: de los datos crudos al resultado completo.

Este modulo es el corazon de la aplicacion y **no depende de Qt**: la interfaz
grafica solo llama a :func:`analizar_ticker`, :func:`recalcular` y
:func:`analizar_demo`, y pinta el :class:`~dml.core.tipos.ResultadoAnalisis`.

Flujo:
    1. Datos (spot, serie mensual, indice, tasas, fundamentales, MACD).
    2. Rendimientos mensuales y TLR mensual.
    3. Beta (covarianza y OLS), PRH, CAPM y precios objetivo.
    4. MCO econometrico y metricas de riesgo.
    5. Black-Scholes-Merton generalizado: forward, strike, primas y griegas.
    6. Parrilla de 12 criterios y decision final.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .core.cache import Cache
from .core.config import cargar_config
from .core.tipos import (
    ND,
    DatosTicker,
    Estados,
    Fuentes,
    MetricasRiesgo,
    ResultadoAnalisis,
    TablaTicker,
)
from .core.util import a_float, ahora_iso, fmt_pct, normalizar_mensual, truncar_meses
from .data.demo import datos_demo as _datos_demo
from .data.ticker import Progreso, obtener_datos
from .models import blackscholes as bsm
from .models import econometria as eco
from .models.capm import (
    beta_covarianza,
    beta_ols,
    precio_objetivo_capm,
    precio_proyectado_trg,
    prima_riesgo_excel,
    prima_riesgo_mercado,
    rendimiento_capm,
)
from .models.parametros import parametros_efectivos
from .models.parrilla import (
    aplicar_activos,
    calcular_calificacion,
    config_con_overrides,
    construir_parrilla,
)
from .models.rendimientos import rendimientos_simples, serie_tlr_mensual, tlr_mensual, trg
from .models.riesgo import metricas_riesgo

LOG = logging.getLogger("dml.analisis")

MESES_ANIO = 12


# --------------------------------------------------------------------------
# Utilidades internas
# --------------------------------------------------------------------------


def _aviso(resultado: ResultadoAnalisis, texto: str) -> None:
    """Anade una advertencia al resultado evitando duplicados."""
    if texto and texto not in resultado.advertencias:
        resultado.advertencias.append(texto)


def _tabla_mensual(
    precios: pd.Series,
    indice: Optional[pd.Series],
    tlr_anual: Optional[pd.Series],
    modo: str,
) -> TablaTicker:
    """Construye la tabla mensual (precio, rendimientos, TLR y PRH) del analisis."""
    precios = normalizar_mensual(precios)
    tabla = TablaTicker()
    if precios is None or len(precios) == 0:
        return tabla
    r_accion = rendimientos_simples(precios)

    indice_n = normalizar_mensual(indice) if indice is not None else None
    r_mercado = rendimientos_simples(indice_n) if indice_n is not None else None

    tlr_m = serie_tlr_mensual(tlr_anual, modo) if tlr_anual is not None else None

    tabla.index = precios.index
    tabla.precio = [a_float(v) for v in precios.tolist()]
    tabla.r_accion = [a_float(r_accion.get(fecha)) for fecha in precios.index]
    tabla.indice = [a_float(indice_n.get(fecha)) if indice_n is not None else None for fecha in precios.index]
    tabla.r_mercado = [
        a_float(r_mercado.get(fecha)) if r_mercado is not None else None for fecha in precios.index
    ]
    tabla.tlr_anual = [
        a_float(tlr_anual.get(fecha)) if tlr_anual is not None else None for fecha in precios.index
    ]
    tabla.tlr_mensual = [a_float(tlr_m.get(fecha)) if tlr_m is not None else None for fecha in precios.index]
    tabla.prh_mensual = [
        (tabla.r_accion[i] - tabla.tlr_mensual[i])
        if tabla.r_accion[i] is not None and tabla.tlr_mensual[i] is not None
        else None
        for i in range(len(precios.index))
    ]
    return tabla


# --------------------------------------------------------------------------
# Analisis principal
# --------------------------------------------------------------------------


def analizar_datos(
    datos: DatosTicker,
    config: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    fuentes: Optional[Fuentes] = None,
    hoy: Optional[date] = None,
) -> ResultadoAnalisis:
    """Calcula todos los modelos a partir de datos ya descargados.

    Se separa de :func:`analizar_ticker` para poder recalcular en vivo (al mover
    un parametro) y para las pruebas sin red.

    Args:
        datos: datos consolidados del ticker.
        config: configuracion efectiva.
        overrides: parametros editados por el usuario en pantalla.
        fuentes: registro de procedencia (se amplia con los calculos).
        hoy: fecha de referencia (facilita las pruebas).

    Returns:
        El :class:`~dml.core.tipos.ResultadoAnalisis` completo.
    """
    config = config or cargar_config()
    fuentes = fuentes if fuentes is not None else Fuentes()
    hoy = hoy or date.today()

    resultado = ResultadoAnalisis(
        ticker=datos.ticker,
        fecha_analisis=ahora_iso(),
        nombre=datos.nombre,
        bolsa=datos.bolsa,
        moneda=datos.moneda,
        sector=datos.sector,
        demo=datos.demo,
        spot=a_float(datos.spot.value),
        indice_nombre=datos.indice_nombre,
        fundamentales=datos.fundamentales,
        tasas=datos.tasas,
        macd_senal=datos.macd_senal,
        macd_detalle=datos.macd_detalle,
        macd_datos=datos.macd_datos,
        advertencias=list(datos.advertencias),
        _datos=datos,
    )
    resultado.ruta_investing = {
        "per": f"https://www.investing.com/equities/{datos.ticker.lower()}-ratios",
        "eps": f"https://www.investing.com/equities/{datos.ticker.lower()}-earnings",
        "tecnico": f"https://www.investing.com/equities/{datos.ticker.lower()}-technical",
        "beta": f"https://www.investing.com/equities/{datos.ticker.lower()}",
        "tasa": "https://www.investing.com/rates-bonds/u.s.-4-week-bond-yield",
        "bono10": "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield",
        "bono30": "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield",
    }

    # 1) Parametros efectivos -------------------------------------------------
    params = parametros_efectivos(datos, config, overrides, hoy)
    resultado.params = params
    resultado.modo = params.modo
    resultado.strike_modo = params.strike_modo

    precios = normalizar_mensual(datos.precios_mensuales.serie)
    if precios is not None:
        precios = truncar_meses(precios, params.meses)
    indice_serie = normalizar_mensual(datos.indice_mensual.serie)
    if indice_serie is not None:
        indice_serie = truncar_meses(indice_serie, params.meses)
    resultado.precios = precios
    resultado.indice_precios = indice_serie

    # La tasa libre de riesgo efectiva es la de :class:`Params`, que ya resuelve
    # la precedencia: lo que el usuario escribio en pantalla > TLR descargada.
    tlr_anual = a_float(params.r)
    if tlr_anual is None:
        tlr_anual = a_float(datos.tasas.tbill_4w)
    resultado.tlr = tlr_anual
    resultado.tlr_mensual_valor = tlr_mensual(tlr_anual, params.modo)

    # 2) Tabla mensual y rendimientos ---------------------------------------
    serie_tlr = datos.tasas.serie_tbill_mensual
    if serie_tlr is not None and len(serie_tlr):
        serie_tlr = truncar_meses(serie_tlr, params.meses)
    # Si el usuario fijo la tasa en pantalla, la serie historica debe reflejar ese
    # valor: de lo contrario la PRH y el CAPM mezclarian dos tasas distintas.
    if a_float((overrides or {}).get("r")) is not None and precios is not None and len(precios):
        serie_tlr = pd.Series(float(tlr_anual), index=precios.index, dtype="float64")
    resultado.tabla = _tabla_mensual(precios, indice_serie, serie_tlr, params.modo)

    if precios is None or len(precios) < 13:
        _aviso(resultado, "N/D: serie mensual insuficiente (se necesitan al menos 13 meses); los modelos no se pueden calcular")
        resultado.estados = _estados_desde_criterios([])
        return _finalizar(resultado, config, fuentes)

    r_accion = rendimientos_simples(precios)
    r_mercado = rendimientos_simples(indice_serie) if indice_serie is not None else None
    rf_mensual = serie_tlr_mensual(serie_tlr, params.modo) if serie_tlr is not None else None
    if rf_mensual is None and tlr_anual is not None:
        rf_mensual = pd.Series(
            [tlr_mensual(tlr_anual, params.modo)] * len(r_accion), index=r_accion.index, dtype="float64"
        )

    # 3) Beta, PRH y CAPM ----------------------------------------------------
    if r_mercado is not None:
        resultado.beta_cov = beta_covarianza(r_accion, r_mercado, params.modo)
        resultado.beta_ols = beta_ols(r_accion, r_mercado)
        resultado.prh = prima_riesgo_mercado(r_mercado, rf_mensual, anualizar=(params.modo != "excel"))
    else:
        _aviso(resultado, "N/D: sin indice de mercado no se puede estimar la Beta ni la prima de riesgo")
    resultado.beta_publicada = a_float(datos.fundamentales.beta_publicada)

    if params.modo == "excel":
        resultado.prh_mensual_promedio = prima_riesgo_excel(r_accion, rf_mensual) if rf_mensual is not None else None
        base_tlr = resultado.tlr_mensual_valor
        base_prh = resultado.prh_mensual_promedio
        _aviso(
            resultado,
            "[MODO EXCEL] PRH = promedio mensual de (rendimiento de la ACCION - TLR): "
            "no es una prima de riesgo de mercado.",
        )
        if base_tlr is None or base_prh is None:
            _aviso(resultado, "[MODO EXCEL] N/D: no se pudo calcular la PRH mensual ni la TLR mensual")
    else:
        resultado.prh_mensual_promedio = (
            prima_riesgo_mercado(r_mercado, rf_mensual, anualizar=False) if r_mercado is not None and rf_mensual is not None else None
        )
        base_tlr = tlr_anual
        base_prh = resultado.prh

    beta_usada = resultado.beta_cov if resultado.beta_cov is not None else resultado.beta_ols
    resultado.rend_capm = rendimiento_capm(base_tlr, beta_usada, base_prh)
    resultado.precio_objetivo = precio_objetivo_capm(resultado.spot, resultado.rend_capm)

    if resultado.beta_cov is not None and resultado.beta_ols is not None:
        diferencia = abs(resultado.beta_cov - resultado.beta_ols)
        if diferencia > 0.05:
            _aviso(
                resultado,
                f"Aviso: la Beta por covarianza ({resultado.beta_cov:.4f}) y la Beta por regresion "
                f"({resultado.beta_ols:.4f}) difieren en {diferencia:.4f}.",
            )
    if resultado.beta_publicada is not None and beta_usada is not None:
        diferencia_pub = abs(resultado.beta_publicada - beta_usada)
        if diferencia_pub > 0.20:
            _aviso(
                resultado,
                f"Aviso: la Beta publicada ({resultado.beta_publicada:.3f}) difiere de la calculada "
                f"({beta_usada:.3f}) en {diferencia_pub:.3f}.",
            )

    # 4) MCO econometrico ----------------------------------------------------
    meses_pronostico = int(params.meses_pronostico)
    resultado.ols = eco.ols_econometrico(precios, meses_pronostico, params.r2_min)
    if resultado.ols is None:
        _aviso(resultado, "N/D: el modelo econometrico no se pudo estimar")

    # 5) TRG y precio proyectado --------------------------------------------
    resultado.trg_valor = trg(precios)
    resultado.precio_proyectado_trg = precio_proyectado_trg(
        resultado.spot,
        resultado.trg_valor,
        meses=max(int(round((params.T or 1.0) * MESES_ANIO)), 1),
        modo=params.modo,
        precios=precios,
    )
    if params.modo == "excel":
        _aviso(
            resultado,
            "[MODO EXCEL] Precio proyectado = PROMEDIO(precios) x (1 + TRG): "
            "no es comparable con el spot (inconsistencia de escala conocida).",
        )

    # 6) Riesgo --------------------------------------------------------------
    resultado.riesgo = metricas_riesgo(
        r_accion,
        rm=r_mercado,
        beta=beta_usada,
        tlr=tlr_anual,
        modo=params.modo,
        precios=precios,
    )
    if params.modo == "excel":
        _aviso(
            resultado,
            "[MODO EXCEL] La sigma de riesgo es MENSUAL y no se anualiza; Black-Scholes exige sigma anual, "
            "por lo que se usa la sigma anual como entrada del modelo de opciones.",
        )

    # 7) Black-Scholes: forward, strike, primas y griegas --------------------
    sigma = a_float(params.sigma)
    if sigma is None:
        sigma = a_float(resultado.riesgo.sigma_anual)
        if sigma is None:
            _aviso(resultado, "N/D: no se pudo determinar la volatilidad (sigma); las griegas no estan disponibles")
    resultado.q = params.q
    resultado.T = params.T
    r_anual = tlr_anual if tlr_anual is not None else params.r
    resultado.b = (a_float(r_anual) - a_float(params.q)) if (r_anual is not None and params.q is not None) else None

    # El dividendo desconocido se modela como q = 0 (ver ``parametros_efectivos``).
    # Se deja constancia en el registro de fuentes: es un supuesto del modelo, no un
    # dato descargado, y el pliego exige poder distinguirlo.
    dividendos = getattr(datos.fundamentales, "dividend_yield", None) if datos.fundamentales is not None else None
    if a_float(dividendos) is None and params.q is not None:
        fuentes.add(
            "Dividend yield (q)",
            0.0,
            "Supuesto: sin dividendo declarado se usa q = 0 (accion que no reparte dividendo)",
            "",
            "supuesto",
            "La fuente no declara dividendo para este ticker; se modela como si no repartiera",
            categoria="opciones",
        )

    if resultado.spot and resultado.b is not None and resultado.T:
        forward = bsm.precio_forward(resultado.spot, resultado.b, resultado.T)
        if params.strike_modo == "manual" and params.strike is not None:
            resultado.strike = params.strike
        else:
            resultado.strike = forward
        resultado.vencimiento = params.vencimiento
        try:
            argumentos = (resultado.spot, resultado.strike, resultado.T, a_float(r_anual) or 0.0, a_float(params.q) or 0.0, resultado.b, sigma)
            resultado.griegas_call = bsm.griegas(*argumentos, tipo="call")
            resultado.griegas_put = bsm.griegas(*argumentos, tipo="put")
            resultado.paridad = bsm.verificar_paridad(*argumentos)
            resultado.griegas_fd = bsm.verificar_griegas_fd(*argumentos)
            if not resultado.paridad.get("ok", True):
                _aviso(resultado, "Aviso: la paridad Put-Call no se cumple dentro de la tolerancia configurada.")
            if not resultado.griegas_fd.get("ok", True):
                _aviso(resultado, "Aviso: alguna griega no coincide con su aproximacion por diferencias finitas.")
            fuentes.add("Spot (S)", resultado.spot, "Yahoo Finance", "", "API", categoria="opciones")
            fuentes.add("Strike (K = Forward)", resultado.strike, "Calculado: S x e^(bT)", "", "calculo", categoria="opciones")
            fuentes.add("Volatilidad (sigma anual)", sigma, "Calculado con rendimientos mensuales", "", "calculo", categoria="opciones")
            fuentes.add("Costo de mantener (b = r - q)", resultado.b, "Calculado", "", "calculo", categoria="opciones")
            fuentes.add("Tiempo al vencimiento (T)", resultado.T, "Calculado con fechas reales /365", "", "calculo", categoria="opciones")
        except Exception as exc:
            LOG.error("No se pudieron calcular las griegas de %s: %s", datos.ticker, exc)
            _aviso(resultado, f"N/D: no se pudieron calcular las griegas ({exc})")
    else:
        _aviso(resultado, "N/D: faltan spot, tasa o plazo para calcular el forward y las griegas")

    # 8) Parrilla de decision ------------------------------------------------
    # Los umbrales editados en el panel "Parametros" se inyectan en la
    # configuracion para que la parrilla y la regla de decision cambien de verdad.
    config_parrilla = config_con_overrides(config, overrides)
    criterios = construir_parrilla(resultado, config_parrilla)
    activos = params.criterios_activos or None
    resultado.criterios = aplicar_activos(criterios, activos)
    resultado.calificacion, resultado.decision = calcular_calificacion(resultado.criterios, config_parrilla)
    resultado.estados = _estados_desde_criterios(resultado.criterios)

    if resultado.demo:
        _aviso(resultado, "MODO DEMO: los datos mostrados son ficticios")
    return _finalizar(resultado, config, fuentes)


def _estados_desde_criterios(criterios: List[Any]) -> Estados:
    """Traduce la parrilla a las etiquetas de estado que pinta la interfaz."""
    estados = Estados()
    mapa = {
        1: "per",
        2: "eps",
        3: "tecnico",
        4: "pfcf",
        5: "capm",
        6: "beta",
        7: "renta_per",
        8: "rdr",
        9: "r2",
        10: "trg",
        11: "forward",
        12: "delta",
    }
    for criterio in criterios:
        atributo = mapa.get(criterio.numero)
        if atributo:
            setattr(estados, atributo, "SI" if criterio.cumple else "NO")
    return estados


def _finalizar(resultado: ResultadoAnalisis, config: Dict[str, Any], fuentes: Fuentes) -> ResultadoAnalisis:
    """Registra la calificacion y la decision en el registro de fuentes."""
    fuentes.add(
        "Calificacion de la parrilla",
        resultado.calificacion,
        "Calculado: promedio de los criterios activos",
        "",
        "calculo",
        categoria="decision",
    )
    fuentes.add("Decision final", resultado.decision, "Regla: >0.70 COMPRAR; 0.40-0.70 MANTENER; <0.40 NO INVERTIR", "", "calculo", categoria="decision")
    if resultado.demo:
        resultado.advertencias = ["MODO DEMO: datos ficticios"] + [
            a for a in resultado.advertencias if "DEMO" not in a.upper()
        ]
    return resultado


# --------------------------------------------------------------------------
# API de alto nivel
# --------------------------------------------------------------------------


def analizar_ticker(
    ticker: str,
    config: Optional[Dict[str, Any]] = None,
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    progreso: Progreso = None,
    overrides: Optional[Dict[str, Any]] = None,
    datos: Optional[DatosTicker] = None,
    permitir_manual: bool = True,
) -> ResultadoAnalisis:
    """Descarga los datos de ``ticker`` y devuelve el analisis completo.

    Args:
        ticker: simbolo de la accion (``NVDA``, ``AAPL``...).
        config: configuracion efectiva (por defecto se carga ``config.yaml``).
        cache: cache local por dia.
        fuentes: registro de procedencia.
        progreso: callback ``(mensaje, fraccion)``.
        overrides: parametros del panel de la interfaz.
        datos: datos ya descargados (evita la descarga; util en pruebas).
        permitir_manual: ``False`` cuando corre en un hilo de trabajo; la interfaz
            pregunta despues por los datos que falten.
    """
    config = config or cargar_config()
    fuentes = fuentes if fuentes is not None else Fuentes()
    if datos is None:
        datos = obtener_datos(
            ticker,
            cache=cache,
            config=config,
            fuentes=fuentes,
            progreso=progreso,
            meses=(overrides or {}).get("meses"),
            indice=(overrides or {}).get("indice"),
            manuales=(overrides or {}).get("manuales"),
            permitir_manual=permitir_manual,
        )
    return analizar_datos(datos, config, overrides, fuentes)


def analizar_demo(
    ticker: str = "DEMO",
    config: Optional[Dict[str, Any]] = None,
    meses: int = 60,
    indice: str = "^GSPC",
    overrides: Optional[Dict[str, Any]] = None,
    fuentes: Optional[Fuentes] = None,
) -> ResultadoAnalisis:
    """Analisis completo con **datos ficticios** (``python main.py --demo``).

    No toca la red: sirve para probar la interfaz y como prueba de humo.
    """
    config = config or cargar_config()
    fuentes = fuentes if fuentes is not None else Fuentes()
    spot = a_float(((config.get("demo") or {}).get("spot", 100.0))) or 100.0
    datos = _datos_demo(ticker=ticker, meses=meses, indice=indice, spot=spot, config=config)
    fuentes.add("Analisis DEMO", "datos ficticios", "DEMO", "", "demo", "Modo demostracion sin conexion", categoria="demo")
    return analizar_datos(datos, config, overrides, fuentes)


def analizar_varios(
    tickers: List[str],
    config: Optional[Dict[str, Any]] = None,
    cache: Optional[Cache] = None,
    progreso: Optional[Callable[[str, float], None]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    demo: bool = False,
) -> List[ResultadoAnalisis]:
    """Analiza varios tickers en secuencia, aislando los fallos de cada uno.

    Si un ticker falla, se registra el error y se continua con el resto: la
    interfaz muestra los que si se pudieron analizar. Es la version **sin Qt** del
    bucle que ejecuta :class:`~dml.ui.worker.TrabajadorAnalisis`; se conserva aqui
    para poder analizar varios tickers desde un script o una prueba.

    Args:
        tickers: simbolos a analizar.
        config: configuracion efectiva.
        cache: cache local por dia.
        progreso: callback ``(mensaje, fraccion)`` con el avance global.
        overrides: parametros editados en pantalla.
        demo: usa datos ficticios en lugar de descargar.

    Returns:
        Un resultado por ticker; los que fallan llevan el motivo en sus advertencias.
    """
    config = config or cargar_config()
    resultados: List[ResultadoAnalisis] = []
    total = max(len(tickers), 1)
    for posicion, ticker in enumerate(tickers):
        base = posicion / total

        def _progreso(mensaje: str, fraccion: float, _base: float = base, _ticker: str = ticker) -> None:
            if progreso is not None:
                progreso(f"[{_ticker}] {mensaje}", _base + fraccion / total)

        try:
            if demo:
                resultados.append(analizar_demo(ticker, config, overrides=overrides))
            else:
                resultados.append(
                    analizar_ticker(ticker, config, cache=cache, progreso=_progreso, overrides=overrides)
                )
        except Exception as exc:
            LOG.error("El analisis de %s fallo: %s", ticker, exc)
            fallo = ResultadoAnalisis(ticker=ticker.upper(), fecha_analisis=ahora_iso(), demo=demo)
            fallo.advertencias.append(f"No se pudo analizar {ticker}: {exc}")
            fallo.decision = "N/D"
            resultados.append(fallo)
    return resultados


def resumen_ejecutivo(resultado: ResultadoAnalisis) -> Dict[str, Any]:
    """Datos de las tarjetas de la pestana "Principal"."""
    riesgo = resultado.riesgo or MetricasRiesgo()
    return {
        "Ticker": resultado.ticker,
        "Nombre": resultado.nombre,
        "Bolsa": resultado.bolsa,
        "Fecha de analisis": resultado.fecha_analisis,
        "Spot (valor actual)": resultado.spot,
        "Strike Price (Forward)": resultado.strike,
        "Time to Maturity (anios)": resultado.T,
        "Dividend (q)": resultado.q,
        "Tasa Libre (r)": resultado.tlr,
        "Costo de mantener (b = r - q)": resultado.b,
        "Volatilidad (sigma anual)": riesgo.sigma_anual,
        "Rendimiento esperado (CAPM)": resultado.rend_capm,
        "Precio objetivo CAPM": resultado.precio_objetivo,
        "TRG mensual": resultado.trg_valor,
        "Precio proyectado por TRG": resultado.precio_proyectado_trg,
        "Beta (covarianza)": resultado.beta_cov,
        "Beta (regresion)": resultado.beta_ols,
        "Beta publicada": resultado.beta_publicada,
        "PRH": resultado.prh,
        "Calificacion": resultado.calificacion,
        "Decision": resultado.decision,
        "Modo": resultado.modo,
    }


def texto_estado(resultado: ResultadoAnalisis, fuentes: Optional[Fuentes] = None) -> str:
    """Frase para la barra de estado al terminar un analisis.

    Resume decision, calificacion, que datos vinieron de Investing.com, cuales
    de respaldo y cuales quedaron como ``N/D`` (requisito del pliego).
    """
    calificacion = fmt_pct(resultado.calificacion, 1) if resultado.calificacion is not None else ND
    partes = [f"{resultado.ticker}: {resultado.decision} (calificacion {calificacion})"]
    de_investing = [f.dato for f in (fuentes.items if fuentes else []) if f.metodo == "scraping"]
    de_respaldo = [f.dato for f in (fuentes.items if fuentes else []) if f.metodo == "respaldo"]
    faltantes = [f.dato for f in (fuentes.items if fuentes else []) if not f.ok]
    partes.append(f"Investing.com: {', '.join(de_investing) if de_investing else 'ningun dato'}")
    partes.append(f"Respaldo: {', '.join(de_respaldo) if de_respaldo else 'ninguno'}")
    partes.append(f"N/D: {', '.join(faltantes) if faltantes else 'ninguno'}")
    if resultado.demo:
        partes.append("DEMO: datos ficticios")
    return " | ".join(partes)
