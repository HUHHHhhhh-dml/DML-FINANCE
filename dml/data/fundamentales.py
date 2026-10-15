# -*- coding: utf-8 -*-
"""Datos fundamentales: PER, EPS, forecast, Price to FCF, dividendo y Beta publicada.

Fuente principal **Yahoo Finance** (``yfinance``, con respaldo de la API publica
``quoteSummary``); opcionalmente **FMP** o **Finnhub** si existe una clave de API
en el entorno. El PER y el Price to FCF del **sector** se toman de la tabla de
referencia de ``config.yaml`` o, si ``usar_mediana_pares`` esta activo, de la
mediana de los comparables del sector.
"""

from __future__ import annotations

import json
import logging
import statistics
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import pandas as pd

from ..core.cache import Cache
from ..core.config import clave_api
from ..core.tipos import Evidence, Fuentes, Fundamental
from ..core.util import a_float, ahora_iso, normalizar_dividend_yield
from ..models.fundamentales import multiplo_sector, normalizar_sector
from .proveedores import USER_AGENT, _cfg_datos

LOG = logging.getLogger("dml.fundamentales")

#: Fundamentales ficticios usados por ``python main.py --demo`` (marcados como DEMO).
FUNDAMENTALES_DEMO: Dict[str, Any] = {
    "nombre": "DEMO Corporation (datos ficticios)",
    "bolsa": "DEMO",
    "moneda": "USD",
    "sector": "Technology",
    "industria": "Software ficticio",
    "per": 24.5,
    "eps": 4.10,
    "eps_forecast": 3.95,
    "market_cap": 250_000_000_000.0,
    "free_cash_flow": 9_200_000_000.0,
    "dividend_rate": 0.80,
    "dividend_yield": 0.008,
    "beta_publicada": 1.05,
}


def _yahoo_quote_summary_directo(ticker: str, timeout: int = 25) -> Dict[str, Any]:
    """Respaldo de fundamentales con la API publica ``quoteSummary`` de Yahoo.

    Devuelve un diccionario vacio si la API no responde o cambia de formato: el
    pliego exige no inventar datos nunca.
    """
    modulos = "summaryDetail,defaultKeyStatistics,financialData,price,assetProfile,earnings"
    url = (
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
        f"?modules={modulos}"
    )
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except Exception as exc:
        LOG.warning("Yahoo quoteSummary no disponible para %s: %s", ticker, exc)
        return {}
    resultados = ((datos.get("quoteSummary") or {}).get("result") or [])
    if not resultados:
        return {}
    bruto = resultados[0]

    def crudo(valor: Any) -> Optional[float]:
        """Extrae el valor numerico de los objetos ``{'raw': x}`` de Yahoo."""
        if isinstance(valor, dict):
            return a_float(valor.get("raw"))
        return a_float(valor)

    precio_mod = bruto.get("price", {}) or {}
    resumen = bruto.get("summaryDetail", {}) or {}
    estadisticas = bruto.get("defaultKeyStatistics", {}) or {}
    financiero = bruto.get("financialData", {}) or {}
    perfil = bruto.get("assetProfile", {}) or {}
    return {
        "nombre": (precio_mod.get("longName") or precio_mod.get("shortName") or "").strip(),
        "bolsa": (precio_mod.get("exchangeName") or "").strip(),
        "moneda": (precio_mod.get("currency") or "USD").strip(),
        "sector": (perfil.get("sector") or "").strip(),
        "industria": (perfil.get("industry") or "").strip(),
        "per": crudo(resumen.get("trailingPE")) or crudo(estadisticas.get("trailingPE")),
        "per_forward": crudo(resumen.get("forwardPE")) or crudo(estadisticas.get("forwardPE")),
        "eps": crudo(estadisticas.get("trailingEps")),
        "eps_forecast": crudo(estadisticas.get("forwardEps")),
        "dividend_rate": crudo(resumen.get("dividendRate")),
        "dividend_yield": crudo(resumen.get("dividendYield")),
        "market_cap": crudo(precio_mod.get("marketCap")) or crudo(resumen.get("marketCap")),
        "free_cash_flow": crudo(financiero.get("freeCashflow")),
        "beta_publicada": crudo(resumen.get("beta")) or crudo(estadisticas.get("beta")),
    }


def _reparar_cache_yfinance(destino: "Path") -> None:
    """Verifica las bases SQLite de yfinance y borra las que esten corruptas.

    Si el proceso muere de forma brusca (o el disco se llena), las bases ``.db`` con
    sus ``-wal``/``-shm`` quedan a medias y SQLite ya no las puede abrir: yfinance
    lanza entonces ``OperationalError`` en **cualquier** consulta y se pierden los
    metadatos. Un archivo ``.db`` que no supera la comprobacion de integridad no
    aporta nada -son solo cookies y husos horarios, se regeneran-, asi que se borra
    con sus auxiliares para que yfinance cree uno nuevo.
    """
    import sqlite3

    for base in ("cookies.db", "tkr-tz.db", "isin-tkr.db"):
        archivo = destino / base
        if not archivo.is_file():
            continue
        conexion = None
        try:
            conexion = sqlite3.connect(str(archivo))
            conexion.execute("PRAGMA schema_version").fetchone()
            continue  # se puede abrir: nada que hacer
        except Exception as exc:  # noqa: BLE001 - corrupta o bloqueada
            LOG.warning("La base de yfinance %s no es utilizable (%s): se regenera", base, exc)
        finally:
            # Cerrar SIEMPRE: sqlite3 deja el archivo abierto aunque la consulta
            # falle y, en Windows, un archivo abierto no se puede borrar (es el
            # motivo de que la reparacion no hiciera nada).
            if conexion is not None:
                try:
                    conexion.close()
                except Exception:  # noqa: BLE001
                    pass
        for sobrante in (archivo, destino / f"{base}-wal", destino / f"{base}-shm", destino / f"{base}-journal"):
            try:
                sobrante.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001 - puede estar en uso
                LOG.debug("No se pudo borrar %s (%s)", sobrante, exc)


def _configurar_cache_yfinance() -> Optional["Path"]:
    """Apunta la cache de ``yfinance`` a una carpeta que si se puede escribir.

    ``yfinance`` guarda sus **cookies de sesion** en una base de datos SQLite
    dentro de ``platformdirs.user_cache_dir()/'py-yfinance'`` (en Windows,
    ``%LOCALAPPDATA%\\py-yfinance``). Si esa base de datos no se puede abrir -la
    carpeta no existe, no admite escritura, la creo otro usuario o quedo
    **corrupta o bloqueada** por un cierre brusco-, yfinance no degrada: lanza
    ``OperationalError: unable to open database file`` en **cualquier** consulta y
    ``get_info()``/``fast_info()`` devuelven cero datos.

    El efecto visible es que se pierden los metadatos que solo vienen de ahi
    -**bolsa**, **divisa** y **sector**- y, sin sector, el PER y el Price to FCF
    de referencia caen a la tabla por defecto. El resto del analisis (que sale de
    la API de precios) sigue funcionando, y por eso el fallo pasa desapercibido.

    :func:`yfinance.set_tz_cache_location` redirige las tres caches (husos, cookies
    e ISIN) a la carpeta de datos de la aplicacion, que ya se elige de forma
    robusta. Debe llamarse **antes** de la primera consulta; se comprueba que la
    carpeta quede creada, se **reparan** las bases corruptas y, si algo de esto
    falla, se deja a yfinance con su comportamiento por defecto (nunca se
    interrumpe el analisis por unos metadatos).

    Returns:
        La carpeta usada, o ``None`` si no se pudo preparar.
    """
    try:
        from ..core.config import ruta_datos_app

        destino = ruta_datos_app() / "yfinance"
        destino.mkdir(parents=True, exist_ok=True)
        import yfinance as yf  # type: ignore

        yf.set_tz_cache_location(str(destino))
        _reparar_cache_yfinance(destino)
        return destino
    except Exception as exc:  # noqa: BLE001 - datos de metadatos, nunca critico
        LOG.debug("No se pudo redirigir la cache de yfinance (%s)", exc)
        return None


def obtener_info_yf(ticker: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Metadatos y fundamentales basicos del ticker desde ``yfinance``.

    Si ``yfinance`` no esta instalado o falla, se usa la API publica
    ``quoteSummary`` de Yahoo. Devuelve un diccionario (posiblemente vacio).

    Antes de consultar se redirige la cache de yfinance (ver
    :func:`_configurar_cache_yfinance`): sin cookies utilizables, yfinance no
    devuelve **ningun** dato y se pierden bolsa, divisa y sector.
    """
    cfg = _cfg_datos(config)

    def productor() -> Optional[Dict[str, Any]]:
        _configurar_cache_yfinance()
        try:
            import yfinance as yf  # type: ignore

            info = yf.Ticker(ticker).get_info() or {}
            if info:
                LOG.info("yfinance: informacion obtenida para %s", ticker)
                limpio: Dict[str, Any] = {}
                for clave_, valor_ in info.items():
                    if isinstance(valor_, (str, int, float, bool)) or valor_ is None:
                        limpio[clave_] = valor_
                return limpio
        except Exception as exc:
            LOG.warning("yfinance no devolvio informacion de %s (%s): se intenta quoteSummary", ticker, exc)
        return _yahoo_quote_summary_directo(ticker, cfg["timeout_seg"]) or None

    # ``None`` cuando no hay nada: asi la cache no fija el fallo (``obtener`` no
    # guarda los ``None``, pero si guardaria un diccionario vacio).
    def productor_cacheable() -> Optional[Dict[str, Any]]:
        return productor() or None

    # La clave lleva version (``info2``) para **invalidar** los registros vacios que
    # dejaron las ejecuciones en las que yfinance no pudo abrir su cache de
    # cookies: si se reutilizaran, seguirian devolviendo bolsa, divisa y sector en
    # N/D aunque la causa ya este resuelta.
    clave = f"info2|{ticker}"
    valor = cache.obtener(clave, productor_cacheable) if cache is not None else productor()
    return valor or {}


def obtener_precios_diarios(
    ticker: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None, periodo: str = "6mo"
) -> Optional[pd.Series]:
    """Serie diaria de cierres del ticker (para el MACD y el resumen tecnico).

    La importacion de :mod:`dml.data.mercado` es perezosa para evitar un ciclo de
    importacion entre ambos modulos.
    """
    from .mercado import descargar_precios

    try:
        df, _ = descargar_precios(ticker, periodo, "1d", cache, config)
        serie = pd.Series(df["Close"]).astype(float).dropna()
        serie.index = pd.to_datetime(serie.index)
        return serie if len(serie) else None
    except Exception as exc:
        LOG.warning("No se pudo obtener la serie diaria de %s: %s", ticker, exc)
        return None


def _extraer(info: Dict[str, Any], claves: List[str]) -> Optional[float]:
    """Primer valor numerico disponible entre varias claves de ``info``."""
    for clave_ in claves:
        valor = a_float(info.get(clave_))
        if valor is not None:
            return valor
    return None


def _extraer_texto(info: Dict[str, Any], claves: List[str], por_defecto: str = "") -> str:
    """Primer texto no vacio disponible entre varias claves de ``info``."""
    for clave_ in claves:
        valor = info.get(clave_)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return por_defecto


def _fmp_multiplos(ticker: str, api_key: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Optional[float]]:
    """Multiplos desde Financial Modeling Prep (opcional, requiere API key)."""
    cfg = _cfg_datos(config)
    url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{urllib.parse.quote(ticker)}?apikey={api_key}"
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=cfg["timeout_seg"]) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        if isinstance(datos, list) and datos:
            fila = datos[0]
            return {
                "per": a_float(fila.get("peRatioTTM")),
                "p_fcf": a_float(fila.get("priceToFreeCashFlowsRatioTTM")),
                "dividend_yield": a_float(fila.get("dividendYielTTM")) or a_float(fila.get("dividendYielPercentageTTM")),
            }
    except Exception as exc:
        LOG.warning("FMP no devolvio multiplos de %s: %s", ticker, exc)
    return {}


def _finnhub_per(ticker: str, api_key: str, config: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """PER basico desde Finnhub (opcional, requiere API key)."""
    cfg = _cfg_datos(config)
    url = f"https://finnhub.io/api/v1/stock/metric?symbol={urllib.parse.quote(ticker)}&metric=all&token={api_key}"
    try:
        peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(peticion, timeout=cfg["timeout_seg"]) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        return a_float(((datos.get("metric") or {}).get("peTTM")))
    except Exception as exc:
        LOG.warning("Finnhub no devolvio el PER de %s: %s", ticker, exc)
        return None


def _mediana_pares(sector: str, campo: str, cache: Optional[Cache], config: Dict[str, Any]) -> Optional[float]:
    """Mediana de un multiplo entre los comparables del sector.

    Es opcional y lento (una consulta por comparable), por eso esta desactivado
    por defecto en ``config.yaml``.
    """
    pares = ((config.get("sectores") or {}).get("pares") or {}).get(sector) or []
    valores: List[float] = []
    for par in pares:
        try:
            info = obtener_info_yf(par, cache, config)
        except Exception:
            continue
        valor = _extraer(
            info,
            ["trailingPE", "forwardPE"] if campo == "per" else ["priceToFreeCashFlows", "priceToFreeCashFlow"],
        )
        if valor is not None and valor > 0:
            valores.append(valor)
    if len(valores) >= 3:
        return float(statistics.median(valores))
    LOG.info("Mediana de pares insuficiente para el sector %s (%s valores)", sector, len(valores))
    return None


def p_fcf_desde_market_cap(market_cap: Optional[float], fcf: Optional[float]) -> Optional[float]:
    """Price to FCF = capitalizacion / flujo de caja libre (positivo)."""
    cap, flujo = a_float(market_cap), a_float(fcf)
    if cap is None or flujo is None or flujo <= 0:
        return None
    return cap / flujo


def obtener_fundamentales(
    ticker: str,
    cache: Optional[Cache] = None,
    fuentes: Optional[Fuentes] = None,
    config: Optional[Dict[str, Any]] = None,
    spot: Optional[float] = None,
    info: Optional[Dict[str, Any]] = None,
) -> Fundamental:
    """Construye el bloque de fundamentales de la empresa y de su sector.

    Args:
        ticker: simbolo.
        cache: cache local por dia.
        fuentes: registro de procedencia.
        config: configuracion efectiva (tablas de sector, claves de API).
        spot: precio actual, necesario para normalizar el dividend yield.
        info: metadatos ya descargados (evita repetir la peticion).

    Returns:
        Una instancia de :class:`~dml.core.tipos.Fundamental`; los datos que no
        se obtengan quedan en ``None`` (la interfaz los pinta como ``N/D``).
    """
    config = config or {}
    cfg_fund = config.get("fundamentales", {}) or {}
    sectores = config.get("sectores", {}) or {}
    info = info if info is not None else obtener_info_yf(ticker, cache, config)
    ahora = ahora_iso()
    url_yf = f"https://finance.yahoo.com/quote/{ticker}/key-statistics"
    url_inv = f"https://www.investing.com/equities/{ticker.lower()}-ratios"

    f = Fundamental()
    f.nombre = _extraer_texto(info, ["longName", "shortName", "nombre"], ticker)
    f.bolsa = _extraer_texto(info, ["exchangeName", "fullExchangeName", "bolsa"], "")
    f.moneda = _extraer_texto(info, ["currency", "moneda"], "USD")
    f.sector = normalizar_sector(_extraer_texto(info, ["sector"], "DESCONOCIDO"), sectores.get("per_default"))
    f.industria = _extraer_texto(info, ["industry", "industria"], "")

    fuente_base = "Yahoo Finance (yfinance)" if info else "N/D"

    # --- PER de la empresa -------------------------------------------------
    f.per = _extraer(info, ["trailingPE", "per", "per_empresa"])
    if f.per is None:
        eps_ = _extraer(info, ["trailingEps", "eps"])
        precio_ = a_float(spot) or _extraer(info, ["currentPrice", "regularMarketPrice", "previousClose"])
        if eps_ and precio_:
            f.per = precio_ / eps_
            fuente_base = fuente_base if fuente_base != "N/D" else "Calculado con precio y EPS de Yahoo Finance"
    f.ev_per = Evidence(
        value=f.per,
        fuente=fuente_base,
        url=url_yf,
        metodo="API" if f.per is not None else "N/D",
        consultado=ahora,
        nota="" if f.per is not None else "Yahoo Finance no devolvio el PER de la empresa",
    )

    # --- EPS actual y estimado --------------------------------------------
    f.eps = _extraer(info, ["trailingEps", "epsActual", "eps"])
    f.eps_forecast = _extraer(info, ["forwardEps", "epsForward", "eps_forecast", "targetMeanPriceEps"])
    f.ev_eps = Evidence(
        value=f.eps,
        fuente=fuente_base,
        url=f"https://finance.yahoo.com/quote/{ticker}/financials",
        metodo="API" if f.eps is not None else "N/D",
        consultado=ahora,
        nota="" if f.eps is not None else "Sin EPS actual disponible",
    )
    f.ev_eps_forecast = Evidence(
        value=f.eps_forecast,
        fuente=fuente_base,
        url=f"https://www.investing.com/equities/{ticker.lower()}-earnings",
        metodo="API" if f.eps_forecast is not None else "N/D",
        consultado=ahora,
        nota="" if f.eps_forecast is not None else "Sin EPS estimado (forecast) disponible",
    )

    # --- Capitalizacion y FCF ---------------------------------------------
    f.market_cap = _extraer(info, ["marketCap", "market_cap", "capitalizacion"])
    f.free_cash_flow = _extraer(info, ["freeCashflow", "freeCashFlow", "free_cash_flow"])
    f.p_fcf = p_fcf_desde_market_cap(f.market_cap, f.free_cash_flow)
    if f.p_fcf is None:
        f.p_fcf = _extraer(info, ["priceToFreeCashFlows", "priceToFreeCashFlow", "p_fcf"])
    f.ev_p_fcf = Evidence(
        value=f.p_fcf,
        fuente=fuente_base,
        url=url_yf,
        metodo="API" if f.p_fcf is not None else "N/D",
        consultado=ahora,
        nota="" if f.p_fcf is not None else "Faltan capitalizacion o flujo de caja libre en Yahoo Finance",
    )

    # --- Dividendo ---------------------------------------------------------
    f.dividend_rate = _extraer(info, ["dividendRate", "dividend_rate", "trailingAnnualDividendRate"])
    dy_bruto = _extraer(info, ["dividendYield", "dividend_yield", "trailingAnnualDividendYield"])
    f.dividend_yield = normalizar_dividend_yield(dy_bruto, f.dividend_rate, spot)
    f.ev_dividendo = Evidence(
        value=f.dividend_yield,
        fuente=fuente_base,
        url=url_yf,
        metodo="API" if f.dividend_yield is not None else "N/D",
        consultado=ahora,
        nota="" if f.dividend_yield is not None else "Sin dividendo declarado (puede que la empresa no reparta dividendo)",
    )

    # --- Beta publicada ----------------------------------------------------
    f.beta_publicada = _extraer(info, ["beta", "beta3Year", "beta_publicada"])
    f.ev_beta_publicada = Evidence(
        value=f.beta_publicada,
        fuente=fuente_base,
        url=f"https://www.investing.com/equities/{ticker.lower()}",
        metodo="API" if f.beta_publicada is not None else "N/D",
        consultado=ahora,
        nota="" if f.beta_publicada is not None else "Sin Beta publicada disponible",
    )

    # --- Multiplos del sector ---------------------------------------------
    usar_pares = bool(cfg_fund.get("usar_mediana_pares", False))
    if usar_pares and cache is not None:
        f.per_sector = _mediana_pares(f.sector, "per", cache, config)
        f.p_fcf_sector = _mediana_pares(f.sector, "p_fcf", cache, config)
    if f.per_sector is None:
        f.per_sector = multiplo_sector(f.sector, sectores.get("per_default", {}) or {}, 20.0)
    if f.p_fcf_sector is None:
        f.p_fcf_sector = multiplo_sector(f.sector, sectores.get("p_fcf_default", {}) or {}, 18.0)
    f.ev_per_sector = Evidence(
        value=f.per_sector,
        fuente="Mediana de comparables (config.yaml)" if usar_pares else "Tabla de sectores de config.yaml",
        url="",
        metodo="calculo",
        consultado=ahora,
        nota=f"Multiplo de referencia del sector {f.sector}",
    )
    f.ev_p_fcf_sector = Evidence(
        value=f.p_fcf_sector,
        fuente="Mediana de comparables (config.yaml)" if usar_pares else "Tabla de sectores de config.yaml",
        url="",
        metodo="calculo",
        consultado=ahora,
        nota=f"Multiplo de referencia del sector {f.sector}",
    )

    # --- Multiplos alternativos (FMP / Finnhub) ---------------------------
    clave_fmp = clave_api(str(cfg_fund.get("fmp_api_key_env", "FMP_API_KEY")))
    if clave_fmp:
        extra = _fmp_multiplos(ticker, clave_fmp, config)
        if f.per is None and extra.get("per") is not None:
            f.per, f.ev_per.value, f.ev_per.fuente, f.ev_per.metodo = extra["per"], extra["per"], "FMP", "API"
        if f.p_fcf is None and extra.get("p_fcf") is not None:
            f.p_fcf, f.ev_p_fcf.value, f.ev_p_fcf.fuente, f.ev_p_fcf.metodo = (
                extra["p_fcf"], extra["p_fcf"], "FMP", "API",
            )
        if f.dividend_yield is None and extra.get("dividend_yield") is not None:
            f.dividend_yield = normalizar_dividend_yield(extra["dividend_yield"], None, spot)
    clave_fh = clave_api(str(cfg_fund.get("finnhub_api_key_env", "FINNHUB_API_KEY")))
    if clave_fh and f.per is None:
        per_fh = _finnhub_per(ticker, clave_fh, config)
        if per_fh is not None:
            f.per, f.ev_per.value, f.ev_per.fuente, f.ev_per.metodo = per_fh, per_fh, "Finnhub", "API"

    if f.per is None:
        f.notas.append("PER de la empresa no disponible: el criterio 1 se califica 0 (N/D)")
    if f.eps_forecast is None:
        f.notas.append("EPS estimado no disponible: el criterio 2 se califica 0 (N/D)")
    if f.p_fcf is None:
        f.notas.append("Price to FCF no disponible: el criterio 4 se califica 0 (N/D)")

    if fuentes is not None:
        fuentes.add("PER empresa", f.per, f.ev_per.fuente, url_yf, f.ev_per.metodo, f.ev_per.nota, categoria="fundamentales")
        fuentes.add("PER sector", f.per_sector, f.ev_per_sector.fuente, url_inv, "calculo", "", categoria="fundamentales")
        fuentes.add("EPS actual", f.eps, f.ev_eps.fuente, f.ev_eps.url, f.ev_eps.metodo, f.ev_eps.nota, categoria="fundamentales")
        fuentes.add(
            "EPS estimado (forecast)", f.eps_forecast, f.ev_eps_forecast.fuente, f.ev_eps_forecast.url,
            f.ev_eps_forecast.metodo, f.ev_eps_forecast.nota, categoria="fundamentales",
        )
        fuentes.add("Price to FCF empresa", f.p_fcf, f.ev_p_fcf.fuente, url_yf, f.ev_p_fcf.metodo, f.ev_p_fcf.nota, categoria="fundamentales")
        fuentes.add("Price to FCF sector", f.p_fcf_sector, f.ev_p_fcf_sector.fuente, url_inv, "calculo", "", categoria="fundamentales")
        fuentes.add(
            "Dividendo anual", f.dividend_rate, f.ev_dividendo.fuente, url_yf, f.ev_dividendo.metodo,
            f.ev_dividendo.nota, categoria="fundamentales",
        )
        fuentes.add(
            "Dividend yield (q)", f.dividend_yield, f.ev_dividendo.fuente, url_yf, f.ev_dividendo.metodo,
            f.ev_dividendo.nota, categoria="fundamentales",
        )
        fuentes.add(
            "Beta publicada", f.beta_publicada, f.ev_beta_publicada.fuente, f.ev_beta_publicada.url,
            f.ev_beta_publicada.metodo, f.ev_beta_publicada.nota, categoria="fundamentales",
        )

    return f
