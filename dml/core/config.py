# -*- coding: utf-8 -*-
"""Configuracion de la aplicacion: ``config.yaml`` + defaults internos.

Precedencia (de menor a mayor):

1. ``DEFAULT_CONFIG`` definido aqui.
2. ``config.yaml`` del directorio de trabajo o del directorio de la app.
3. El diccionario de *overrides* que pasa la interfaz (panel "Parametros").

Las claves de API **nunca** viven en el YAML: se leen de variables de entorno
(``FRED_API_KEY``, ``FMP_API_KEY``, ``FINNHUB_API_KEY``).
"""

from __future__ import annotations

import copy
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

LOG = logging.getLogger("dml.config")

RUTA_YAML = "config.yaml"

DEFAULT_CONFIG: Dict[str, Any] = {
    "general": {
        "meses": 60,
        "indice": "^GSPC",
        "modo": "estandar",
        "periodo_historico": "10y",
        "tolerancia_spot_pct": 0.05,
        "meses_pronostico": 12,
    },
    "umbrales": {
        "beta_max": 1.10,
        "r2_min": 0.70,
        "trg_extra_tlr": 0.01,
        "delta_call_min": 0.50,
        "var_confianza": [0.95, 0.99],
    },
    "decision": {
        "comprar_min": 0.70,
        "mantener_min": 0.40,
    },
    "black_scholes": {
        "strike_modo": "forward",
        "strike_manual": None,
        "vencimiento_dias": 365,
        "tolerancia_griegas": 0.001,
        "dias_por_anio": 365,
    },
    "datos": {
        "cache": True,
        "cache_dir": ".dml_cache",
        "cache_ttl_horas": 24,
        "pausa_peticiones_seg": 1.5,
        "reintentos": 3,
        "timeout_seg": 25,
        "intentar_investing": True,
        "usar_playwright": True,
        "usar_fred": True,
        "usar_yfinance_tasas": True,
        "usar_manual": True,
        "agregacion_fred": "last",
        "investing_urls": {
            # Investing.com retiro la pagina "u.s.-4-week-bond-yield" (404); el
            # T-Bill a 4 semanas se publica ahora como "1 month" (comprobado:
            # devuelve el mismo rendimiento a 4 semanas).
            "tbill_4w": "https://www.investing.com/rates-bonds/u.s.-1-month-bond-yield",
            "ust_10y": "https://www.investing.com/rates-bonds/u.s.-10-year-bond-yield",
            "ust_30y": "https://www.investing.com/rates-bonds/u.s.-30-year-bond-yield",
        },
        "fred_series": {
            "tbill_4w": "DGS1MO",
            "tbill_4w_descuento": "DTB4WK",
            "ust_10y": "DGS10",
            "ust_30y": "DGS30",
        },
        "yf_series": {
            # ^TNX y ^TYX: bono a 10 y 30 anios (mismos plazos que se piden).
            "ust_10y": "^TNX",
            "ust_30y": "^TYX",
            # ^IRX es el T-Bill a 13 SEMANAS: solo se usa como PROXY etiquetado
            # de la TLR, nunca como si fuera el de 4 semanas.
            "tbill_4w_proxy": "^IRX",
        },
        # T-Bill de descuento: plazo en dias para convertir a rendimiento
        # equivalente de bono (y = 365*d / (360 - d*t)).
        "dias_tbill_descuento": 28,
    },
    "fundamentales": {
        "fmp_api_key_env": "FMP_API_KEY",
        "finnhub_api_key_env": "FINNHUB_API_KEY",
        "usar_mediana_pares": False,
        "macd": {"rapida": 12, "lenta": 26, "senal": 9, "dias_analisis": 30},
    },
    "sectores": {
        "per_default": {
            "Technology": 32.0,
            "Communication Services": 22.0,
            "Consumer Cyclical": 24.0,
            "Consumer Defensive": 21.0,
            "Healthcare": 22.0,
            "Financial Services": 14.5,
            "Industrials": 20.0,
            "Energy": 13.0,
            "Basic Materials": 16.0,
            "Utilities": 17.5,
            "Real Estate": 30.0,
            "DESCONOCIDO": 20.0,
        },
        "p_fcf_default": {
            "Technology": 30.0,
            "Communication Services": 20.0,
            "Consumer Cyclical": 22.0,
            "Consumer Defensive": 20.0,
            "Healthcare": 21.0,
            "Financial Services": 12.0,
            "Industrials": 18.0,
            "Energy": 10.0,
            "Basic Materials": 13.0,
            "Utilities": 16.0,
            "Real Estate": 24.0,
            "DESCONOCIDO": 18.0,
        },
        "pares": {},
    },
    "ui": {
        "tema": "oscuro",
        "tickers_historial": 12,
        "guardar_geometria": True,
    },
    "demo": {
        "ticker": "DEMO",
        "spot": 100.0,
        "meses": 60,
    },
}


def directorio_aplicacion() -> Path:
    """Directorio de la aplicacion, tanto en Python como empaquetada con PyInstaller.

    En un ejecutable ``--onedir``/``--onefile`` los datos viajan junto al binario:
    ``sys._MEIPASS`` es la carpeta de datos empaquetados y la carpeta del ``.exe``
    la de los ficheros que el usuario puede editar (``config.yaml``).
    """
    import sys

    if getattr(sys, "frozen", False):  # empaquetado con PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def directorio_datos_empaquetados() -> Optional[Path]:
    """Carpeta interna de datos de PyInstaller (``sys._MEIPASS``), si existe.

    En un ``--onefile`` los ficheros añadidos con ``--add-data`` se extraen a esta
    carpeta en cada arranque; en ``--onedir`` es la carpeta ``_internal``.
    """
    import sys

    ruta = getattr(sys, "_MEIPASS", None)
    return Path(ruta) if ruta else None


def ruta_config() -> Optional[Path]:
    """Devuelve la ruta del ``config.yaml`` efectivo, si existe.

    Orden de busqueda:

    1. ``DML_FINANCE_CONFIG`` (ruta explicita por variable de entorno).
    2. Directorio de la aplicacion (junto al ``.exe`` si esta empaquetada).
    3. Carpeta de datos empaquetados (``sys._MEIPASS``): es donde acaba el
       ``config.yaml`` de un ejecutable ``--onefile``, que de otro modo se
       ignoraria y la aplicacion arrancaria con los valores por defecto.
    4. Directorio de trabajo actual (permite tener configuraciones por proyecto).
    """
    explicito = os.environ.get("DML_FINANCE_CONFIG")
    candidatos = []
    if explicito:
        candidatos.append(Path(explicito))
    candidatos.append(directorio_aplicacion() / RUTA_YAML)
    empaquetados = directorio_datos_empaquetados()
    if empaquetados is not None:
        candidatos.append(empaquetados / RUTA_YAML)
    try:
        candidatos.append(Path.cwd() / RUTA_YAML)
    except Exception:  # pragma: no cover - el cwd puede no existir ya
        pass
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    return None


#: Nombre de la carpeta de datos cuando hay que crearla junto a la aplicacion
#: (ultimo recurso). Es una unica carpeta con todo dentro: cache, trazas y cache
#: de matplotlib. Se evita asi repartir archivos sueltos por la carpeta del
#: programa, que es justo lo que se comparte.
NOMBRE_CARPETA_DATOS = ".dml_datos"

#: Carpeta de datos ya resuelta (ver :func:`ruta_datos_app`).
_DATOS_APP_RESUELTO: Optional[Path] = None


def _directorio_escribible(ruta: Path) -> bool:
    """True si se puede crear ``ruta`` y escribir dentro de ella.

    Comprueba las dos cosas por separado: crear la carpeta y dejar un archivo
    dentro (hay carpetas que se crean pero no admiten escritura) y lo borra en el
    acto. Nunca lanza excepciones.
    """
    try:
        ruta.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - cualquier fallo significa "no sirve"
        return False
    try:
        sonda = ruta / ".dml-escritura.tmp"
        sonda.write_text("", encoding="utf-8")
        sonda.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


def candidatos_datos_app() -> List[Path]:
    """Carpetas candidatas para los datos de la aplicacion, en orden de preferencia.

    1. ``DML_FINANCE_HOME`` (lo elige el usuario; si no se puede usar, se avisa).
    2. ``%USERPROFILE%\\.dml_finance``, el sitio habitual.
    3. ``%LOCALAPPDATA%\\DML-FINANCE``, por si el perfil del usuario esta
       restringido pero su carpeta local si es escribible.
    4. El directorio temporal del sistema, como ultimo recurso (la cache y las
       preferencias se pierden al reiniciar, pero la aplicacion **funciona**).
    """
    candidatos: List[Path] = []

    def anadir(ruta: Optional[Path]) -> None:
        if ruta is None:
            return
        try:
            normalizada = Path(ruta)
        except Exception:  # noqa: BLE001
            return
        if normalizada not in candidatos:
            candidatos.append(normalizada)

    anadir(Path(os.environ["DML_FINANCE_HOME"]) if os.environ.get("DML_FINANCE_HOME") else None)
    anadir(_carpeta_usuario() / ".dml_finance")
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if local:
        anadir(Path(local) / "DML-FINANCE")
    try:
        import tempfile

        anadir(Path(tempfile.gettempdir()) / "DML-FINANCE")
    except Exception:  # noqa: BLE001 - no hay directorio temporal
        pass
    return candidatos


def _carpeta_usuario() -> Path:
    """Carpeta personal del usuario, sin lanzar si no se puede resolver."""
    try:
        return Path.home()
    except Exception:  # noqa: BLE001 - perfiles sin carpeta personal
        return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")


def ruta_datos_app() -> Path:
    """Directorio de datos de la aplicacion (config de matplotlib, cache, log).

    **Nunca lanza**: si el sitio habitual no se puede crear ni escribir (perfil de
    Windows restringido, politica del equipo, ``~/.dml_finance`` creado por otro
    usuario...), se usa la primera alternativa escribible de
    :func:`candidatos_datos_app`. Antes, un ``PermissionError`` aqui abortaba el
    arranque con un cuadro de error, que es justo lo que no debe pasar: los datos
    auxiliares son prescindibles, la aplicacion no.

    La carpeta elegida se recuerda: la decision no cambia durante la ejecucion y
    asi no se repiten las comprobaciones de escritura en cada consulta.
    """
    if _DATOS_APP_RESUELTO is not None:
        return _DATOS_APP_RESUELTO

    candidatos = candidatos_datos_app()
    for ruta in candidatos:
        if _directorio_escribible(ruta):
            _recordar_datos_app(ruta)
            return ruta
    # Ultimo recurso: una unica carpeta dentro del directorio de la aplicacion. Se
    # agrupa todo ahi (cache, trazas, matplotlib) para no repartir archivos sueltos
    # por la carpeta del programa, que es lo que se comparte con otras personas.
    respaldo = directorio_aplicacion() / NOMBRE_CARPETA_DATOS
    if _directorio_escribible(respaldo):
        LOG.warning("No hay carpeta de datos del usuario utilizable; se usara %s", respaldo)
        _recordar_datos_app(respaldo)
        return respaldo
    LOG.error("No se pudo preparar ninguna carpeta de datos; se trabaja sin cache ni trazas")
    _recordar_datos_app(Path("."))
    return Path(".")


def _recordar_datos_app(ruta: Optional[Path]) -> None:
    """Guarda (o invalida) la carpeta de datos ya resuelta."""
    global _DATOS_APP_RESUELTO
    _DATOS_APP_RESUELTO = Path(ruta) if ruta is not None else None


def olvidar_ruta_datos_app() -> None:
    """Olvida la carpeta de datos resuelta para volver a calcularla.

    La usa quien cambia ``DML_FINANCE_HOME`` en caliente (pruebas y herramientas):
    sin esto, el valor memorizado por :func:`ruta_datos_app` seguiria siendo el
    anterior.
    """
    _recordar_datos_app(None)


def ruta_archivo_datos(nombre: str) -> Optional[Path]:
    """Ruta de un archivo dentro de la carpeta de datos, o ``None`` si no se puede.

    Es la forma segura de pedir un archivo de datos (log, preferencias): si la
    carpeta no admite escritura, devuelve ``None`` en lugar de lanzar, y quien
    llama decide como degradar.
    """
    try:
        carpeta = ruta_datos_app()
    except Exception:  # noqa: BLE001 - blindaje extra: nunca propagar
        return None
    return carpeta / nombre if _directorio_escribible(carpeta) else None


def fusionar_config(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fusiona recursivamente ``override`` sobre ``base`` sin mutar ninguno."""
    salida = copy.deepcopy(base)
    if not override:
        return salida
    for clave, valor in override.items():
        if isinstance(valor, dict) and isinstance(salida.get(clave), dict):
            salida[clave] = fusionar_config(salida[clave], valor)
        else:
            salida[clave] = copy.deepcopy(valor)
    return salida


def copiar_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Copia profunda de una configuracion."""
    return copy.deepcopy(config)


def _leer_yaml(ruta: Path) -> Dict[str, Any]:
    """Lee un YAML y devuelve un diccionario (vacio si falla)."""
    try:
        import yaml  # type: ignore
    except Exception:
        LOG.warning("PyYAML no esta instalado: se usan solo los valores por defecto")
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = yaml.safe_load(fh) or {}
        if not isinstance(datos, dict):
            LOG.warning("El archivo %s no contiene un diccionario: se ignora", ruta)
            return {}
        return datos
    except Exception as exc:
        LOG.error("No se pudo leer %s: %s", ruta, exc)
        return {}


def cargar_config(ruta: Optional[Path] = None, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Devuelve la configuracion efectiva fusionando defaults, YAML y overrides."""
    base = copy.deepcopy(DEFAULT_CONFIG)
    archivo = Path(ruta) if ruta is not None else ruta_config()
    if archivo is not None and Path(archivo).is_file():
        base = fusionar_config(base, _leer_yaml(Path(archivo)))
    return fusionar_config(base, overrides)


def guardar_config(config: Dict[str, Any], ruta: Optional[Path] = None) -> Optional[Path]:
    """Guarda la configuracion completa en YAML. Devuelve la ruta o ``None``.

    Aviso: PyYAML **no conserva los comentarios**, asi que esta funcion reescribe
    el archivo sin ellos. Para guardar solo el tema preferido (lo que hace la
    interfaz al conmutar de tema) se usa :func:`guardar_tema`, que modifica
    unicamente esa linea y conserva el resto del archivo intacto.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        LOG.warning("PyYAML no esta instalado: no se puede guardar la configuracion")
        return None
    destino = Path(ruta) if ruta is not None else (ruta_config() or directorio_aplicacion() / RUTA_YAML)
    try:
        with open(destino, "w", encoding="utf-8") as fh:
            yaml.safe_dump(config, fh, allow_unicode=True, sort_keys=False)
        return destino
    except Exception as exc:
        LOG.error("No se pudo guardar %s: %s", destino, exc)
        return None


def guardar_tema(tema: str, ruta: Optional[Path] = None) -> Optional[Path]:
    """Guarda la preferencia de tema **conservando los comentarios** del YAML.

    Reescribe unicamente la clave ``ui.tema`` mediante una sustitucion de texto,
    de modo que el archivo de configuracion documentado del usuario no pierda sus
    comentarios al cambiar de tema en la interfaz.
    """
    destino = Path(ruta) if ruta is not None else (ruta_config() or directorio_aplicacion() / RUTA_YAML)
    try:
        if not destino.is_file():
            return guardar_config(cargar_config(), destino)
        texto = destino.read_text(encoding="utf-8")
        patron = re.compile(r"^(\s*tema\s*:\s*).*$", re.MULTILINE)
        if patron.search(texto):
            nuevo = patron.sub(lambda m: f'{m.group(1)}"{tema}"', texto, count=1)
        else:
            nuevo = texto.rstrip() + f'\n\nui:\n  tema: "{tema}"\n'
        if nuevo != texto:
            destino.write_text(nuevo, encoding="utf-8")
        return destino
    except Exception as exc:
        LOG.warning("No se pudo guardar el tema en %s: %s", destino, exc)
        return None


def clave_api(nombre_env: str) -> Optional[str]:
    """Lee una clave de API desde el entorno (con soporte de ``.env``)."""
    valor = os.environ.get(nombre_env)
    if valor:
        return valor.strip()
    try:  # carga perezosa de .env, si python-dotenv esta disponible
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
        valor = os.environ.get(nombre_env)
        return valor.strip() if valor else None
    except Exception:
        return None
