# -*- coding: utf-8 -*-
"""Configuracion comun de la bateria de pruebas de DML FINANCE.

Este archivo hace cuatro cosas, en este orden:

1. Inserta la raiz del repositorio en ``sys.path`` para que el paquete ``dml``
   sea importable sin instalar nada.
2. Fuerza el backend ``Agg`` de matplotlib **antes** de que cualquier modulo de
   la aplicacion importe ``matplotlib.pyplot`` (la suite es headless).
3. Define las series sinteticas (precios mensuales, indice, serie de TLR) y el
   directorio temporal de cache que reutilizan todas las pruebas.
4. Activa una barrera de red: cualquier intento de conexion TCP durante la
   suite falla con un error explicito, de modo que las pruebas son OFFLINE y
   deterministas por construccion y no por buena voluntad.
"""

from __future__ import annotations

import os
import pathlib
import socket
import sys
import tempfile
from typing import Tuple

import numpy as np
import pandas as pd
import pytest

# --------------------------------------------------------------------------
# 1. Raiz del repositorio en sys.path
# --------------------------------------------------------------------------
RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# --------------------------------------------------------------------------
# 2. matplotlib sin ventana (backend Agg) y variables de Qt
# --------------------------------------------------------------------------
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# El directorio de cache de matplotlib del usuario no siempre es escribible en el
# entorno de integracion: se usa una subcarpeta de la cache temporal del sistema.
_DIR_MPL = pathlib.Path(tempfile.gettempdir()) / "dml-matplotlib-cache"
try:
    _DIR_MPL.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(_DIR_MPL)
except Exception:  # pragma: no cover - solo si el temporal no es escribible
    pass

# La aplicacion escribe su log en su carpeta de datos (que por defecto esta en el
# perfil del usuario). Las pruebas no deben tocar el perfil de quien las ejecuta:
# se redirige a una carpeta temporal del proyecto. ``DML_FINANCE_HOME`` se lee en
# cada proceso hijo, asi que basta con fijarla aqui.
_DIR_DATOS_PRUEBAS = pathlib.Path(tempfile.gettempdir()) / "dml-pruebas-datos"
try:
    _DIR_DATOS_PRUEBAS.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DML_FINANCE_HOME", str(_DIR_DATOS_PRUEBAS))
except Exception:  # pragma: no cover - solo si el temporal no es escribible
    pass

try:  # matplotlib puede no estar instalado todavia mientras se instala el stack
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    plt.switch_backend("Agg")
except Exception:  # pragma: no cover - solo afecta al entorno de instalacion
    pass


# En algunos entornos Windows el directorio temporal del proceso apunta al propio
# proyecto, de modo que pytest deja carpetas sueltas (``pytest-of-<usuario>``) en
# la raiz. Si eso ocurre, se fija el directorio base de pytest dentro del
# proyecto, en una carpeta ignorada por git, y se limpia al terminar la sesion.
# Se comprueba antes de redirigir: en un entorno donde el propio proyecto tiene
# restricciones de escritura, mover los temporales dentro empeoraria las cosas.
_DIR_TMP_PYTEST = RAIZ / ".tmp_pytest"


def _sonda_temporal() -> bool:
    """True si el directorio temporal del sistema se puede usar de verdad.

    Se reproduce lo que hace pytest (crear su carpeta base, listarla y borrarla):
    no basta con que el directorio exista.
    """
    import shutil

    try:
        raiz_temporal = pathlib.Path(tempfile.gettempdir())
        if raiz_temporal.resolve() == RAIZ.resolve():
            return False
        sonda = raiz_temporal / "pytest-sonda-dml"
        sonda.mkdir(parents=True, exist_ok=True)
        try:
            list(sonda.iterdir())
            (sonda / "f.txt").write_text("x", encoding="utf-8")
            (sonda / "f.txt").read_text(encoding="utf-8")
        finally:
            shutil.rmtree(sonda, ignore_errors=True)
        return True
    except Exception:  # pragma: no cover - depende del sistema de archivos
        return False


def pytest_configure(config: "pytest.Config") -> None:
    """Redirige los temporales de pytest al proyecto si el sistema no sirve."""
    if _sonda_temporal():
        return
    try:
        base = _DIR_TMP_PYTEST / "basetemp"
        base.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
    except Exception:  # pragma: no cover - proyecto de solo lectura
        pass


def pytest_sessionfinish(session: "pytest.Session", exitstatus: int) -> None:
    """Borra la carpeta de temporales al terminar la sesion (si se creo)."""
    if not _DIR_TMP_PYTEST.exists():
        return
    import shutil

    try:
        shutil.rmtree(_DIR_TMP_PYTEST, ignore_errors=True)
    except Exception:  # pragma: no cover - depende del sistema de archivos
        pass


# --------------------------------------------------------------------------
# 3. Semillas y utilidades de series sinteticas
# --------------------------------------------------------------------------
SEMILLA_PRECIOS = 20240517
SEMILLA_INDICE = 987654
SEMILLA_TLR = 4242


def fin_de_mes(inicio: str, periodos: int) -> pd.DatetimeIndex:
    """Rejilla de fin de mes, que es la convencion de la aplicacion."""
    return pd.date_range(inicio, periods=int(periodos), freq="ME")


def serie_precios(n: int = 60, inicio: float = 100.0, deriva: float = 0.008, sigma: float = 0.02,
                  semilla: int = SEMILLA_PRECIOS, fecha_inicio: str = "2019-01-31") -> pd.Series:
    """Genera una serie de precios mensual reproducible (camino aleatorio con deriva).

    Args:
        n: numero de observaciones mensuales.
        inicio: primer precio de la serie.
        deriva: rendimiento simple medio mensual.
        sigma: desviacion tipica de los rendimientos mensuales.
        semilla: semilla del generador, para que la serie sea siempre la misma.
        fecha_inicio: fecha del primer punto (fin de mes).

    Returns:
        ``pandas.Series`` de precios con indice de fin de mes.
    """
    rng = np.random.default_rng(semilla)
    rendimientos = rng.normal(deriva, sigma, int(n))
    precios = float(inicio) * np.cumprod(1.0 + rendimientos)
    return pd.Series(precios, index=fin_de_mes(fecha_inicio, n), name="precio")


def serie_rendimientos(n: int = 60, semilla: int = SEMILLA_PRECIOS, fecha_inicio: str = "2019-01-31",
                       media: float = 0.008, sigma: float = 0.02) -> pd.Series:
    """Serie de rendimientos mensuales reproducible."""
    rng = np.random.default_rng(semilla)
    return pd.Series(rng.normal(media, sigma, int(n)), index=fin_de_mes(fecha_inicio, n), name="rendimiento")


def serie_indice(n: int = 60, inicio: float = 3000.0, deriva: float = 0.006, sigma: float = 0.015,
                 semilla: int = SEMILLA_INDICE, fecha_inicio: str = "2019-01-31") -> pd.Series:
    """Serie sintetica del indice de mercado, con la misma rejilla temporal."""
    return serie_precios(n=n, inicio=inicio, deriva=deriva, sigma=sigma, semilla=semilla,
                         fecha_inicio=fecha_inicio).rename("indice")


def serie_tlr(n: int = 60, nivel: float = 0.0425, fecha_inicio: str = "2019-01-31") -> pd.Series:
    """Serie de TLR anual con una leve tendencia determinista (sin ruido).

    La componente lenta evita series constantes (que harian degenerar algunas
    formulas) manteniendo el caracter reproducible.
    """
    onda = 0.004 * np.sin(np.arange(int(n)) / 6.0) + 0.0004 * np.arange(int(n))
    valores = float(nivel) + onda
    return pd.Series(valores, index=fin_de_mes(fecha_inicio, n), name="tlr")


def rendimientos_de(precios: pd.Series) -> pd.Series:
    """Rendimientos simples de una serie de precios (utilidad de las pruebas)."""
    return pd.Series(precios).astype(float).pct_change().dropna()


# --------------------------------------------------------------------------
# 4. Fixtures
# --------------------------------------------------------------------------
@pytest.fixture
def precios_mensuales() -> pd.Series:
    """Serie sintetica de precios mensuales (60 puntos, fin de mes)."""
    return serie_precios()


@pytest.fixture
def rendimientos_accion(precios_mensuales: pd.Series) -> pd.Series:
    """Rendimientos mensuales de la accion sintetica."""
    return rendimientos_de(precios_mensuales)


@pytest.fixture
def precios_indice() -> pd.Series:
    """Serie sintetica del indice de mercado, alineada con ``precios_mensuales``."""
    return serie_indice()


@pytest.fixture
def rendimientos_mercado(precios_indice: pd.Series) -> pd.Series:
    """Rendimientos mensuales del indice de mercado."""
    return rendimientos_de(precios_indice)


@pytest.fixture
def serie_tlr_anual() -> pd.Series:
    """Serie mensual de TLR anual (fraccion) para los modos mensual/anual."""
    return serie_tlr()


@pytest.fixture
def ra_rm(rendimientos_accion: pd.Series, rendimientos_mercado: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Par (R_accion, R_mercado) ya alineado por indice."""
    return rendimientos_accion, rendimientos_mercado


@pytest.fixture
def par_beta_conocida() -> Tuple[pd.Series, pd.Series]:
    """Par de rendimientos con Beta conocida y exacta (Ra = 1.5 * Rm + 0.002)."""
    rm = pd.Series(
        [0.010, -0.020, 0.030, 0.005, -0.015, 0.025, 0.000, 0.018, -0.008, 0.012, 0.004, -0.006],
        index=fin_de_mes("2020-01-31", 12),
        name="mercado",
    )
    ra = 1.5 * rm + 0.002
    ra.name = "accion"
    return ra, rm


@pytest.fixture
def precios_con_caida() -> pd.Series:
    """Serie con una caida conocida del 25% para la maxima caida."""
    return pd.Series([100.0, 120.0, 90.0, 110.0], index=fin_de_mes("2020-01-31", 4))


@pytest.fixture
def cache_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Directorio temporal y aislado para la cache en disco."""
    destino = tmp_path / "cache_dml"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


@pytest.fixture
def config_default() -> dict:
    """Copia de la configuracion por defecto de la aplicacion."""
    from dml.core.config import cargar_config

    return cargar_config(None)


# --------------------------------------------------------------------------
# 5. Barrera de red: la suite no puede salir a Internet
# --------------------------------------------------------------------------
class ErrorDeRedEnPruebas(RuntimeError):
    """Se lanza cuando una prueba intenta abrir una conexion TCP."""


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch):
    """Bloquea toda conexion TCP mientras dure cada prueba.

    Las pruebas deben ser OFFLINE: si un modulo intenta descargar datos, la
    prueba falla con un mensaje claro en lugar de depender de la red.
    """

    def _conectar_bloqueado(self, *args, **kwargs):  # noqa: ANN001 - firma de socket
        destino = args[0] if args else "desconocido"
        raise ErrorDeRedEnPruebas(
            f"La suite de pruebas es OFFLINE: se bloqueo una conexion a {destino}. "
            "Usa monkeypatch para sustituir la funcion de datos."
        )

    monkeypatch.setattr(socket.socket, "connect", _conectar_bloqueado, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _conectar_bloqueado, raising=False)
    yield
