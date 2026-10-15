# -*- coding: utf-8 -*-
"""Pruebas de los parametros efectivos y de la cadena del modelo de opciones.

Cubren la regresion que se colo al dejar de enviar los valores por defecto del
panel de parametros como *overrides*: cuando el proveedor **no declara dividendo**,
``dividend_yield`` es ``None`` y ``q`` quedaba en ``None``, de modo que
``b = r - q``, el forward, el strike (``K = S x e^(bT)``) y todas las griegas
salian como ``N/D`` aunque hubiera spot, tasa, plazo y volatilidad.

La regla correcta -y la que aplica el libro de referencia- es modelar el
dividendo desconocido como ``q = 0`` (un activo que no reparte dividendo) y dejar
constancia del supuesto, sin inventar un dato.
"""

from __future__ import annotations

import copy
import math

import pytest

from dml.analisis import analizar_datos, resumen_ejecutivo
from dml.core.config import cargar_config
from dml.core.tipos import DatosTicker, Fundamental
from dml.data.demo import datos_demo
from dml.models.parametros import parametros_efectivos


@pytest.fixture
def config_default() -> dict:
    """Configuracion efectiva del proyecto."""
    return cargar_config(None)


@pytest.fixture
def datos_demo_completos() -> DatosTicker:
    """Datos DEMO con dividendo declarado."""
    return datos_demo(ticker="DEMO", meses=60, indice="^GSPC", spot=100.0, config=cargar_config(None))


def _sin_dividendo(datos: DatosTicker) -> DatosTicker:
    """Copia de los datos con el dividendo sin declarar (el caso que fallaba)."""
    copia = copy.copy(datos)
    fundamentales = copy.copy(datos.fundamentales) if datos.fundamentales is not None else Fundamental()
    fundamentales.dividend_yield = None
    fundamentales.dividend_rate = None
    copia.fundamentales = fundamentales
    return copia


# ==========================================================================
# 1. Resolucion de q
# ==========================================================================
def test_q_usa_el_dividendo_declarado(datos_demo_completos, config_default):
    """Con dividendo declarado, ``q`` es ese dato (no un valor por defecto)."""
    params = parametros_efectivos(datos_demo_completos, config_default, None)
    assert params.q == pytest.approx(0.008, rel=1e-9)


def test_q_es_cero_si_no_hay_dividendo_declarado(datos_demo_completos, config_default):
    """Sin dividendo declarado, ``q`` es 0 (no ``None``)."""
    datos = _sin_dividendo(datos_demo_completos)
    params = parametros_efectivos(datos, config_default, None)
    assert params.q == 0.0, "un dividendo desconocido debe modelarse como q = 0"


def test_q_sigue_mandando_el_valor_del_usuario(datos_demo_completos, config_default):
    """Si el usuario fija ``q`` en pantalla, su valor tiene prioridad."""
    datos = _sin_dividendo(datos_demo_completos)
    params = parametros_efectivos(datos, config_default, {"q": 0.05})
    assert params.q == pytest.approx(0.05, rel=1e-12)


# ==========================================================================
# 2. La cadena b -> forward -> strike -> griegas no se rompe
# ==========================================================================
def test_sin_dividendo_el_modelo_de_opciones_se_calcula_entero(datos_demo_completos, config_default):
    """``b``, strike y griegas deben existir aunque falte el dividendo.

    Es exactamente la regresion observada: ``Dividend (q)`` en N/D arrastraba a
    ``Costo de mantener (b)``, ``Strike Price`` y las griegas.
    """
    datos = _sin_dividendo(datos_demo_completos)
    resultado = analizar_datos(datos, config_default)

    assert resultado.q == 0.0
    assert resultado.b is not None, "b = r - q no puede quedar en N/D"
    assert resultado.b == pytest.approx(resultado.tlr - 0.0, rel=1e-9)
    assert resultado.strike is not None, "K = S x e^(bT) no puede quedar en N/D"
    assert resultado.griegas_call, "las griegas del call no pueden quedar vacias"
    assert resultado.griegas_put, "las griegas del put no pueden quedar vacias"

    # El strike por defecto es el forward: S x e^(bT).
    esperado = resultado.spot * math.exp(resultado.b * resultado.T)
    assert resultado.strike == pytest.approx(esperado, rel=1e-9)


def test_sin_dividendo_el_resumen_no_muestra_nd(datos_demo_completos, config_default):
    """Las tarjetas del resumen ejecutivo no se llenan de N/D."""
    datos = _sin_dividendo(datos_demo_completos)
    resumen = resumen_ejecutivo(analizar_datos(datos, config_default))

    for clave in (
        "Dividend (q)",
        "Costo de mantener (b = r - q)",
        "Strike Price (Forward)",
    ):
        assert resumen[clave] is not None, f"{clave} no deberia ser N/D"
    assert resumen["Dividend (q)"] == 0.0


def test_el_supuesto_del_dividendo_queda_registrado(datos_demo_completos, config_default):
    """Se deja constancia de que q = 0 es un supuesto del modelo, no un dato.

    El pliego exige poder distinguir un dato descargado de un valor asumido.
    """
    from dml.core.tipos import Fuentes

    fuentes = Fuentes()
    datos = _sin_dividendo(datos_demo_completos)
    analizar_datos(datos, config_default, fuentes=fuentes)

    registro = [f for f in fuentes.items if f.dato == "Dividend yield (q)"]
    assert registro, "deberia registrarse el supuesto de dividendo"
    assert registro[0].metodo == "supuesto"
    assert "sin dividendo" in (registro[0].fuente or "").lower()


def test_con_dividendo_no_se_registra_supuesto(datos_demo_completos, config_default):
    """Si el dividendo si existe, no se inventa ningun supuesto."""
    from dml.core.tipos import Fuentes

    fuentes = Fuentes()
    analizar_datos(datos_demo_completos, config_default, fuentes=fuentes)
    assert not [f for f in fuentes.items if f.metodo == "supuesto" and f.dato == "Dividend yield (q)"]


# ==========================================================================
# 3. Cache de yfinance: de ella salen bolsa, divisa y sector
# ==========================================================================
def test_la_cache_de_yfinance_se_redirige_a_una_carpeta_escribible(tmp_path, monkeypatch):
    """``obtener_info_yf`` apunta la cache de yfinance a la carpeta de datos.

    ``yfinance`` guarda sus cookies en una base de datos SQLite dentro de
    ``%LOCALAPPDATA%\\py-yfinance``. Si esa base no se puede abrir, **toda**
    consulta falla con ``OperationalError: unable to open database file`` y
    ``get_info()`` devuelve cero claves: se pierden bolsa, divisa y sector (y con
    ellos el PER de referencia del sector).
    """
    import yfinance as yf

    from dml.data import fundamentales as modulo

    destino = tmp_path / "datos"
    # ``_configurar_cache_yfinance`` importa ``ruta_datos_app`` en tiempo de
    # ejecucion, asi que basta con sustituirla en su modulo.
    monkeypatch.setattr("dml.core.config.ruta_datos_app", lambda: destino)

    usado = modulo._configurar_cache_yfinance()
    assert usado == destino / "yfinance"
    assert usado.is_dir(), "deberia crearse la carpeta de cache de yfinance"
    # ``set_tz_cache_location`` es lo que redirige las tres caches de yfinance.
    assert yf.cache._CookieDBManager._cache_dir.startswith(str(destino))


def test_un_info_vacio_no_se_cachea(tmp_path, monkeypatch):
    """Un fallo de metadatos no debe quedarse pegado 24 horas en la cache.

    Antes se guardaba el diccionario vacio y todas las ejecuciones posteriores
    devolvian bolsa, divisa y sector en N/D aunque la causa ya estuviera resuelta.
    """
    from dml.core.cache import Cache
    from dml.data import fundamentales as modulo

    cache = Cache(tmp_path, ttl_horas=24.0)
    monkeypatch.setattr(modulo, "_configurar_cache_yfinance", lambda: None)
    monkeypatch.setattr(modulo, "_yahoo_quote_summary_directo", lambda *a, **k: {})

    def info_vacia(*_a, **_k):
        raise RuntimeError("yfinance sin cookies")

    import yfinance as yf

    monkeypatch.setattr(yf, "Ticker", info_vacia)

    assert modulo.obtener_info_yf("X", cache, {}) == {}
    assert list(tmp_path.glob("*.json")) == [], "un resultado vacio no debe guardarse en la cache"


def test_los_metadatos_del_ticker_llegan_al_resultado(datos_demo_completos, config_default):
    """Bolsa, divisa y sector se propagan del ``info`` al resultado del analisis.

    Es el camino que se rompia: sin ``info`` el resultado mostraba N/D y
    DESCONOCIDO aunque el resto del analisis (que viene de la API de precios)
    funcionara.
    """
    datos = copy.deepcopy(datos_demo_completos)
    datos.bolsa = "NasdaqGS"
    datos.moneda = "USD"
    datos.sector = "Technology"

    resultado = analizar_datos(datos, config_default)
    assert resultado.bolsa == "NasdaqGS"
    assert resultado.moneda == "USD"
    assert resultado.sector == "Technology"
    # Y con sector, el multiplo de referencia deja de ser el generico.
    assert resultado.fundamentales.per_sector is not None


def test_extraer_texto_usa_las_claves_alternativas():
    """La bolsa llega como ``fullExchangeName`` cuando no hay ``exchangeName``."""
    from dml.data.fundamentales import _extraer_texto

    assert _extraer_texto({"fullExchangeName": "NasdaqGS"}, ["exchangeName", "fullExchangeName"], "") == "NasdaqGS"
    assert _extraer_texto({"exchangeName": "NYQ"}, ["exchangeName", "fullExchangeName"], "") == "NYQ"
    assert _extraer_texto({"currency": "  EUR  "}, ["currency"], "USD") == "EUR"
    assert _extraer_texto({}, ["currency"], "USD") == "USD"
    assert _extraer_texto({"sector": "   "}, ["sector"], "DESCONOCIDO") == "DESCONOCIDO"


def test_se_repara_una_base_de_yfinance_corrupta(tmp_path):
    """Una base SQLite ilegible se borra (con sus auxiliares) para regenerarla.

    Si se deja, yfinance falla en **todas** las consultas y se pierden bolsa,
    divisa y sector. Las bases que si se abren no se tocan.
    """
    import sqlite3

    from dml.data.fundamentales import _reparar_cache_yfinance

    (tmp_path / "cookies.db").write_bytes(b"esto no es una base de datos")
    (tmp_path / "cookies.db-wal").write_bytes(b"x")
    with sqlite3.connect(tmp_path / "tkr-tz.db") as conexion:
        conexion.execute("CREATE TABLE t (x int)")

    _reparar_cache_yfinance(tmp_path)

    assert not (tmp_path / "cookies.db").exists(), "la base corrupta deberia borrarse"
    assert not (tmp_path / "cookies.db-wal").exists(), "los auxiliares tambien"
    assert (tmp_path / "tkr-tz.db").is_file(), "una base sana no se debe tocar"
    # Repetirlo no debe fallar (carpeta ya limpia).
    _reparar_cache_yfinance(tmp_path)
