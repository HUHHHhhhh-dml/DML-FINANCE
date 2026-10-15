# -*- coding: utf-8 -*-
"""Proveedores externos de datos: Investing.com, FRED, Yahoo Finance y manual.

Cada funcion devuelve ``None`` (nunca lanza) cuando la fuente no responde, para
que la cadena de respaldos pueda continuar. Se respetan los terminos de uso:
pausa configurable entre peticiones, numero de reintentos limitado y backoff
exponencial.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from ..core.cache import Cache
from ..core.config import clave_api
from ..core.util import a_float

LOG = logging.getLogger("dml.proveedores")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Cabeceras de navegador para Investing.com (cloudscraper/requests).
CABECERAS_NAVEGADOR = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    "Referer": "https://www.investing.com/",
}

#: FRED (``stlouisfed.org``) bloquea las peticiones que se identifican como
#: navegador: con una cabecera de Chrome la conexion se queda colgada hasta el
#: timeout (comprobado: 20 s sin respuesta), mientras que con un agente honesto y
#: sencillo responde en ~300 ms. Identificarse de forma transparente es ademas lo
#: correcto ante los terminos de uso de la fuente.
USER_AGENT_FRED = "DML-FINANCE/2.0 (analisis financiero; +python-urllib)"

DIAS_ANIO_BONO = 365
DIAS_ANIO_DESCUENTO = 360

#: Callback opcional para pedir un valor manual. Lo registra la interfaz cuando
#: se invoca desde el **hilo principal** (nunca desde un hilo de trabajo: Qt no
#: permite abrir dialogos fuera del hilo de la interfaz).
PEDIDOR_MANUAL: Optional[Callable[[str], Optional[float]]] = None

#: Motivo por el que un dato quedo pendiente de captura manual en un hilo de
#: trabajo. La interfaz lo lee despues para preguntar en el hilo correcto.
MOTIVO_MANUAL_PENDIENTE = "requiere captura manual (se solicitara al terminar el analisis)"

#: Interruptor de seguridad de FRED. El endpoint publico ``fredgraph.csv``
#: responde a veces con cortes de conexion y tiempos de espera; cuando eso pasa,
#: insistir con cada serie cuesta minutos por analisis. Tras un fallo de red se
#: marca FRED como no disponible y se pasa directo a los respaldos.
_FRED_CAIDO = False


#: Marca de tiempo de la ultima peticion a FRED, para espaciarlas.
_ULTIMA_PETICION_FRED = 0.0

#: Separacion minima entre peticiones a FRED (segundos). El endpoint publico
#: limita por IP y responde cerrando la conexion cuando se le insiste.
PAUSA_FRED_SEG = 0.6


def fred_disponible() -> bool:
    """True si FRED no se ha marcado como caido en este proceso."""
    return not _FRED_CAIDO


def _esperar_turno_fred() -> None:
    """Espera lo necesario para no superar el ritmo de peticiones a FRED."""
    global _ULTIMA_PETICION_FRED
    transcurrido = time.time() - _ULTIMA_PETICION_FRED
    if 0 < transcurrido < PAUSA_FRED_SEG:
        time.sleep(PAUSA_FRED_SEG - transcurrido)
    _ULTIMA_PETICION_FRED = time.time()


def marcar_fred_caido(motivo: str = "") -> None:
    """Marca FRED como no disponible para el resto del proceso.

    Se llama cuando una peticion a FRED falla por red (no cuando devuelve una
    serie vacia, que puede ser legitimo). Evita repetir timeouts de 25 s con cada
    serie y mantiene el analisis por debajo de un minuto.
    """
    global _FRED_CAIDO
    if not _FRED_CAIDO:
        LOG.warning("FRED marcado como no disponible (%s): se usaran los respaldos", motivo or "fallo de red")
    _FRED_CAIDO = True


def reiniciar_estado_fred() -> None:
    """Reactiva FRED (lo usa el boton "Actualizar datos" para forzar un reintento)."""
    global _FRED_CAIDO
    _FRED_CAIDO = False


def pausa(segundos: float) -> None:
    """Pausa cortes entre peticiones HTTP para respetar los terminos de uso."""
    if segundos and segundos > 0:
        time.sleep(float(segundos))


def _cfg_datos(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Subconfiguracion ``datos`` con los valores por defecto aplicados."""
    datos = ((config or {}).get("datos") or {}) if config else {}
    return {
        "timeout_seg": int(datos.get("timeout_seg", 25) or 25),
        "reintentos": int(datos.get("reintentos", 3) or 3),
        "pausa_peticiones_seg": float(datos.get("pausa_peticiones_seg", 1.5) or 0.0),
    }


# --------------------------------------------------------------------------
# Investing.com
# --------------------------------------------------------------------------


def parsear_numero_investing(texto: Any) -> Optional[float]:
    """Interpreta numeros con formato anglosajon (1,234.56) o europeo (1.234,56).

    Ejemplos:
        >>> parsear_numero_investing("4,352")
        4352.0
        >>> parsear_numero_investing("4.35")
        4.35
        >>> parsear_numero_investing("N/D") is None
        True
    """
    if texto is None:
        return None
    t = re.sub(r"[^\d.,\-]", "", str(texto))
    if not t or t in {"-", ".", ","}:
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(",") < t.rfind(".") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) <= 2 else t.replace(",", "")
    return a_float(t)


def _sesion_http():
    """Crea una sesion HTTP: cloudscraper si esta disponible, si no requests."""
    try:
        import cloudscraper  # type: ignore

        LOG.debug("Investing.com: usando cloudscraper")
        return cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    except Exception:
        try:
            import requests  # type: ignore

            LOG.debug("Investing.com: usando requests con cabeceras de navegador")
            return requests.Session()
        except Exception as exc:
            LOG.warning("Ni cloudscraper ni requests estan disponibles: %s", exc)
            return None


#: Expresiones regulares que localizan el ultimo precio en el HTML de Investing.com.
PATRONES_PRECIO_INVESTING = (
    r'data-test="instrument-price-last"[^>]*>([\d.,]+)<',
    r'"last_last"\s*:\s*"?([\d.,]+)"?',
    r'"last"\s*:\s*"?([\d.,]+)"?',
    r'id="last_last"[^>]*>([\d.,]+)<',
)


def _extraer_precio_investing(html: str) -> Optional[float]:
    """Extrae el ultimo precio de un HTML de Investing.com usando los patrones."""
    for patron in PATRONES_PRECIO_INVESTING:
        coincidencia = re.search(patron, html)
        if coincidencia:
            valor = parsear_numero_investing(coincidencia.group(1))
            if valor is not None:
                return valor
    return None


def _descargar_urllib(url: str, timeout: int) -> Tuple[Optional[int], str]:
    """Descarga una URL con ``urllib`` y cabeceras de navegador.

    Es el **motor mas fiable** contra Investing.com en las pruebas: Cloudflare
    responde 403 al cliente HTTP de ``requests``/``cloudscraper`` (su huella TLS
    lo delata) mientras que acepta la peticion de ``urllib`` con las mismas
    cabeceras (comprobado: 200 con ~926 KB de HTML frente a 403 con 3 bytes).

    Returns:
        ``(codigo_http, cuerpo)``; el codigo es ``None`` si la peticion fallo.
    """
    peticion = urllib.request.Request(url, headers=CABECERAS_NAVEGADOR)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return getattr(respuesta, "status", 200), respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        LOG.warning("Investing.com (urllib) fallo para %s: %s", url, exc)
        return None, ""


def _descargar_sesion(sesion: Any, url: str, timeout: int) -> Tuple[Optional[int], str]:
    """Descarga una URL con una sesion ``requests``/``cloudscraper``."""
    try:
        respuesta = sesion.get(url, headers=CABECERAS_NAVEGADOR, timeout=timeout)
        codigo = getattr(respuesta, "status_code", None)
        return codigo, respuesta.text if codigo == 200 else ""
    except Exception as exc:
        LOG.warning("Investing.com (sesion) fallo para %s: %s", url, exc)
        return None, ""


def scrape_investing(url: str, config: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Lee el ultimo valor de una pagina de Investing.com.

    Prueba varios motores HTTP por orden de eficacia comprobada:

    1. ``urllib`` con cabeceras de navegador (el unico que Cloudflare no bloquea
       en las pruebas: 200 con el HTML completo).
    2. ``cloudscraper``, pensado para retos de Cloudflare.
    3. ``requests`` con cabeceras de navegador.

    Si un motor recibe 403/404 se pasa al siguiente sin gastar reintentos, y el
    ciclo de reintentos con backoff lineal se reserva para los fallos de red.

    Returns:
        El ultimo valor publicado, o ``None`` si ningun motor lo consigue.
    """
    if not url:
        return None
    cfg = _cfg_datos(config)
    sesion = _sesion_http()

    motores: List[Tuple[str, Callable[[], Tuple[Optional[int], str]]]] = [
        ("urllib", lambda: _descargar_urllib(url, cfg["timeout_seg"])),
    ]
    if sesion is not None:
        motores.append((type(sesion).__name__, lambda: _descargar_sesion(sesion, url, cfg["timeout_seg"])))

    for intento in range(1, cfg["reintentos"] + 1):
        for nombre, motor in motores:
            codigo, html = motor()
            if codigo == 200 and html:
                valor = _extraer_precio_investing(html)
                if valor is not None:
                    LOG.info("Investing.com (%s): %s -> %s", nombre, url, valor)
                    return valor
                LOG.warning("Investing.com (%s): pagina recibida pero sin valor reconocible (%s)", nombre, url)
                continue
            if codigo in (403, 404, 429):
                LOG.info("Investing.com (%s): HTTP %s, se prueba el siguiente motor (%s)", nombre, codigo, url)
                continue
            LOG.warning("Investing.com (%s) intento %s/%s: codigo %s", nombre, intento, cfg["reintentos"], codigo)
        if intento < cfg["reintentos"]:
            pausa(cfg["pausa_peticiones_seg"] * intento)  # backoff lineal
    LOG.warning("Investing.com: ningun motor pudo leer %s", url)
    return None


def scrape_investing_playwright(url: str, config: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Respaldo con navegador headless (Playwright) para Investing.com.

    Requiere ``pip install playwright`` y ``playwright install chromium``. Si
    Playwright no esta disponible devuelve ``None`` sin lanzar excepciones.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        LOG.info("Playwright no disponible (%s): se omite este respaldo", exc)
        return None
    cfg = _cfg_datos(config)
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            try:
                pagina = navegador.new_page(user_agent=USER_AGENT)
                pagina.goto(url, timeout=cfg["timeout_seg"] * 1000, wait_until="domcontentloaded")
                pagina.wait_for_timeout(2500)  # deja que se pinte el precio
                texto = ""
                for selector in ('[data-test="instrument-price-last"]', "#last_last", "span.text-2xl"):
                    try:
                        elemento = pagina.query_selector(selector)
                        if elemento:
                            texto = elemento.inner_text()
                            if texto:
                                break
                    except Exception:
                        continue
                valor = parsear_numero_investing(texto)
                if valor is not None:
                    LOG.info("Investing.com (Playwright): %s -> %s", url, valor)
                return valor
            finally:
                navegador.close()
    except Exception as exc:
        LOG.warning("Playwright fallo para %s: %s", url, exc)
        return None


# --------------------------------------------------------------------------
# FRED
# --------------------------------------------------------------------------


def _csv_fred_publico(series_id: str, timeout: int = 25, reintentos: int = 3, pausa_seg: float = 1.0) -> Optional[pd.Series]:
    """Descarga una serie de FRED por su endpoint CSV publico (sin API key).

    Reintenta con backoff exponencial: el endpoint publico de FRED sufre cortes
    y tiempos de espera intermitentes (observados en pruebas reales), y sin
    reintentos un fallo puntual dejaria la TLR como ``N/D``.
    """
    urls = [
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}",
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}&cosd=1990-01-01",
    ]
    ultimo_error: Optional[Exception] = None
    intentos_realizados = 0
    for intento in range(1, max(1, reintentos) + 1):
        url = urls[(intento - 1) % len(urls)]
        intentos_realizados = intento
        try:
            _esperar_turno_fred()
            peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_FRED, "Accept": "text/csv"})
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                contenido = respuesta.read().decode("utf-8", errors="replace")
            serie = _parsear_csv_fred(contenido)
            if serie is not None:
                return serie
            LOG.warning("FRED %s: CSV vacio o sin observaciones (intento %s)", series_id, intento)
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
            # Fallo de red: no se insiste (FRED limita por IP y cada intento
            # cuesta hasta el timeout completo). Se pasa a los respaldos.
            ultimo_error = exc
            LOG.warning(
                "FRED %s no responde (%s): se abandonan los reintentos y se usaran los respaldos", series_id, exc
            )
            marcar_fred_caido(f"{series_id}: {exc}")
            break
        except Exception as exc:  # pragma: no cover - defensivo
            ultimo_error = exc
            LOG.warning("FRED %s intento %s/%s fallido: %s", series_id, intento, reintentos, exc)
        if intento < reintentos:
            time.sleep(pausa_seg * (2 ** (intento - 1)))  # backoff exponencial
    if ultimo_error is not None:
        LOG.error(
            "No se pudo descargar %s de FRED (%s intento(s)): %s", series_id, intentos_realizados, ultimo_error
        )
    return None


def _parsear_csv_fred(contenido: str) -> Optional[pd.Series]:
    """Convierte el CSV de FRED en una serie indexada por fecha."""
    if not contenido or not contenido.strip():
        return None
    lector = csv.reader(io.StringIO(contenido))
    filas = list(lector)
    if len(filas) < 2:
        return None
    idx_fecha = 0
    idx_valor = 1 if len(filas[0]) > 1 else 0
    fechas: List[pd.Timestamp] = []
    valores: List[float] = []
    for fila in filas[1:]:
        if len(fila) <= max(idx_fecha, idx_valor):
            continue
        fecha = pd.to_datetime(fila[idx_fecha], errors="coerce")
        valor = a_float(fila[idx_valor])
        if fecha is pd.NaT or valor is None:
            continue
        fechas.append(fecha)
        valores.append(valor)
    if not fechas:
        return None
    return pd.Series(valores, index=pd.DatetimeIndex(fechas), dtype="float64").sort_index()


def tasa_yahoo_simple(simbolo: str, timeout: int = 25, reintentos: int = 2) -> Optional[float]:
    """Ultimo rendimiento publicado por Yahoo para un simbolo de tipo de interes.

    Se usa como **ultimo respaldo automatico** de la TLR. Importante: Yahoo no
    publica el T-Bill a 4 semanas, por lo que el unico proxy disponible es
    ``^IRX``, que es el T-Bill a **13 semanas**. Quien lo consuma debe
    etiquetarlo como proxy y avisar de la diferencia de plazo: el pliego prohibe
    presentar ``^IRX`` como si fuera la TLR de 4 semanas.
    """
    import json as _json

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(simbolo)}?range=1mo&interval=1d"
    for intento in range(1, max(1, reintentos) + 1):
        try:
            peticion = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                datos = _json.loads(respuesta.read().decode("utf-8"))
            resultado = (datos.get("chart", {}).get("result") or [None])[0]
            if not resultado:
                continue
            precio = a_float((resultado.get("meta") or {}).get("regularMarketPrice"))
            if precio is None:
                cierres = ((resultado.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
                validos = [c for c in cierres if c is not None]
                precio = a_float(validos[-1]) if validos else None
            if precio is not None:
                LOG.info("Yahoo %s = %s (respaldo de la TLR)", simbolo, precio)
                return precio
        except Exception as exc:
            LOG.warning("Yahoo %s intento %s/%s fallido: %s", simbolo, intento, reintentos, exc)
        if intento < reintentos:
            time.sleep(1.0 * intento)
    return None


def _json_fred_api(series_id: str, api_key: str, timeout: int = 25) -> Optional[pd.Series]:
    """Descarga una serie de FRED con la API oficial (requiere ``FRED_API_KEY``)."""
    parametros = urllib.parse.urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": "1990-01-01",
        }
    )
    url = f"https://api.stlouisfed.org/fred/series/observations?{parametros}"
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT_FRED})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    observaciones = datos.get("observations") or []
    fechas: List[pd.Timestamp] = []
    valores: List[float] = []
    for obs in observaciones:
        valor = a_float(obs.get("value"))
        fecha = pd.to_datetime(obs.get("date"), errors="coerce")
        if valor is None or fecha is pd.NaT:
            continue
        fechas.append(fecha)
        valores.append(valor)
    if not fechas:
        return None
    return pd.Series(valores, index=pd.DatetimeIndex(fechas), dtype="float64").sort_index()


def serie_fred(
    series_id: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None
) -> Optional[pd.Series]:
    """Serie historica diaria de FRED (API key o CSV publico).

    Se usa la API oficial si ``FRED_API_KEY`` esta definida en el entorno; en
    caso contrario se descarga el ``fredgraph.csv`` publico, que no requiere
    clave. La clave **nunca** se escribe en el codigo ni en el YAML.
    """
    cfg = _cfg_datos(config)

    def productor() -> Optional[Dict[str, Any]]:
        if not fred_disponible():
            LOG.info("FRED esta marcado como no disponible: se omite %s", series_id)
            return None
        clave = clave_api("FRED_API_KEY")
        serie: Optional[pd.Series] = None
        if clave:
            try:
                serie = _json_fred_api(series_id, clave, cfg["timeout_seg"])
                if serie is not None:
                    LOG.info("FRED API: %s (%s observaciones)", series_id, len(serie))
            except Exception as exc:
                LOG.warning("FRED API fallo para %s (%s): se intenta el CSV publico", series_id, exc)
        if serie is None:
            try:
                serie = _csv_fred_publico(
                    series_id,
                    cfg["timeout_seg"],
                    reintentos=int(cfg.get("reintentos", 3) or 3),
                    pausa_seg=float(cfg.get("pausa_peticiones_seg", 1.0) or 1.0),
                )
                if serie is not None:
                    LOG.info("FRED CSV publico: %s (%s observaciones)", series_id, len(serie))
            except Exception as exc:
                LOG.error("No se pudo descargar %s de FRED: %s", series_id, exc)
                return None
        if serie is None:
            return None
        return {"index": [d.isoformat() for d in serie.index], "valores": [a_float(v) for v in serie.tolist()]}

    if cache is not None:
        paquete = cache.obtener(f"fred|{series_id}", productor)
    else:
        paquete = productor()
    if not paquete or "index" not in paquete:
        return None
    try:
        return pd.Series(paquete["valores"], index=pd.to_datetime(paquete["index"]), dtype="float64").dropna()
    except Exception:  # pragma: no cover
        return None


# --------------------------------------------------------------------------
# Yahoo Finance: tasas
# --------------------------------------------------------------------------


def tasa_yfinance(
    simbolo: str, cache: Optional[Cache] = None, config: Optional[Dict[str, Any]] = None
) -> Optional[float]:
    """Ultimo cierre de un simbolo de tasa de Yahoo Finance (``^TNX``, ``^TYX``).

    Nota: ``^TNX`` y ``^TYX`` cotizan el rendimiento **multiplicado por 10**
    (p. ej. ``43.5`` = 4,35%); la conversion a fraccion la hace
    :func:`dml.data.tasas._normalizar_tasa_porcentaje` dividiendo por 100.
    ``^IRX`` **no** se usa como TLR de 4 semanas porque es el T-Bill a 13
    semanas.
    """
    cfg = _cfg_datos(config)

    def productor() -> Optional[float]:
        try:
            from .mercado import yahoo_chart

            df = yahoo_chart(simbolo, "1mo", "1d", cfg["timeout_seg"])
            valor = float(df["Close"].dropna().iloc[-1])
            LOG.info("Yahoo Finance %s = %s", simbolo, valor)
            return valor
        except Exception as exc:
            LOG.warning("Yahoo Finance no devolvio %s: %s", simbolo, exc)
            return None

    if cache is not None:
        return a_float(cache.obtener(f"yf_tasa|{simbolo}", productor))
    return a_float(productor())


# --------------------------------------------------------------------------
# Captura manual
# --------------------------------------------------------------------------


def pedir_valor_manual(nombre: str, config: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Pide un valor manualmente usando el callback registrado.

    La interfaz registra un callback que abre un cuadro de dialogo; ese callback
    debe ejecutarse en el **hilo principal** de Qt. Por eso, cuando la descarga
    corre dentro de un hilo de trabajo, el analisis pasa
    ``datos.permitir_manual = False`` y el dato queda como ``N/D`` con el motivo
    :data:`MOTIVO_MANUAL_PENDIENTE`; la interfaz pregunta despues, ya en el hilo
    de la interfaz, y recalcula.
    """
    if not ((config or {}).get("datos", {}) or {}).get("usar_manual", True):
        return None
    if PEDIDOR_MANUAL is None:
        LOG.info("Sin captura manual disponible para %s: el dato quedara como N/D", nombre)
        return None
    try:
        valor = PEDIDOR_MANUAL(nombre)
    except Exception as exc:
        LOG.warning("La captura manual de %s fallo: %s", nombre, exc)
        return None
    return a_float(valor)


def registrar_pedidor_manual(funcion: Optional[Callable[[str], Optional[float]]]) -> None:
    """Registra (o limpia) el callback de captura manual de valores."""
    global PEDIDOR_MANUAL
    PEDIDOR_MANUAL = funcion
