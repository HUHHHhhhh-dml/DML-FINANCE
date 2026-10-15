# -*- coding: utf-8 -*-
"""Pruebas de ``dml.core.util`` (coercion numerica, formato y alineacion mensual)
y de ``dml.core.cache`` (aciertos, fallos, caducidad por TTL y limpieza).

Convenios que se comprueban:
* ``None``/``NaN``/``inf`` y textos no numericos se convierten en ``None``, que
  la interfaz pinta como ``N/D``.
* ``normalizar_mensual`` lleva cualquier indice al **ultimo dia del mes**.
* La cache es de disco: una entrada escrita hoy se sirve sin llamar al
  productor; una entrada caducada fuerza un nuevo fallo (miss).
"""

from __future__ import annotations

import json
import math
import time

import numpy as np
import pandas as pd
import pytest

from dml.core.cache import Cache
from dml.core.util import (
    ND,
    a_float,
    fmt_num,
    fmt_pct,
    normalizar_dividend_yield,
    normalizar_mensual,
    truncar_meses,
)

# ==========================================================================
# 1. Coercion numerica: a_float
# ==========================================================================


@pytest.mark.parametrize("valor", [None, float("nan"), float("inf"), float("-inf"), "", "   ", "N/D", "n/d",
                                   "NA", "nan", "null", "-", "--", "abc", "12x"])
def test_a_float_devuelve_none_en_valores_inutilizables(valor):
    """Todo lo que no es un numero utilizable se convierte en ``None`` (N/D)."""
    assert a_float(valor) is None


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (0, 0.0),
        (3, 3.0),
        (-2.5, -2.5),
        (np.int64(7), 7.0),
        (np.float64(1.25), 1.25),
        (True, 1.0),
        (False, 0.0),
        ("2.5", 2.5),
        ("  -0.75  ", -0.75),
        ("1,5", 1.5),          # coma decimal europea
        ("12%", 12.0),         # el simbolo de porcentaje se elimina
        ("3.5%", 3.5),
        ("$1,200.50", 1200.50),  # simbolo monetario y separador de miles
        ("$ 1 000 ", 1000.0),
    ],
)
def test_a_float_convierte_valores_validos(entrada, esperado):
    """Numeros, cadenas numericas y porcentajes se convierten a ``float``."""
    resultado = a_float(entrada)
    assert isinstance(resultado, float)
    assert resultado == pytest.approx(esperado)


def test_a_float_rechaza_nan_e_inf_numericos():
    """``NaN``/``inf`` nunca se propagan: se convierten en ``None``."""
    assert a_float(np.float64("nan")) is None
    assert a_float(np.float64("inf")) is None
    assert a_float(pd.NA) is None
    assert a_float(pd.NaT) is None


def test_a_float_interpreta_la_coma_como_decimal_no_como_miles():
    """Limitacion documentada: una sola coma se interpreta como decimal.

    ``"$1,200"`` (separador de miles anglosajon) se convierte en ``1.2`` porque
    el modulo adopta la convencion europea de coma decimal. La ambiguedad no se
    puede resolver sin conocer la configuracion regional, asi que se fija aqui
    el comportamiento real para que un cambio futuro no pase inadvertido.
    """
    assert a_float("1,200") == pytest.approx(1.2)
    assert a_float("1.200,50") == pytest.approx(1200.5)   # aqui la coma si es decimal


# ==========================================================================
# 2. Formato: fmt_num / fmt_pct y el rotulo N/D
# ==========================================================================


def test_fmt_num_formatea_y_usa_nd():
    """``fmt_num`` agrupa miles y reserva ``N/D`` para valores invalidos."""
    assert fmt_num(1234.5678) == "1,234.5678"
    assert fmt_num(1234.5678, decimales=2) == "1,234.57"
    assert fmt_num(1234.5678, decimales=2, miles=False) == "1234.57"
    assert fmt_num(None) == ND
    assert fmt_num(float("nan")) == ND
    assert fmt_num("texto") == ND
    assert ND == "N/D"


def test_fmt_pct_convierte_fraccion_en_porcentaje():
    """``fmt_pct`` multiplica por 100 y respeta el numero de decimales."""
    assert fmt_pct(0.1234) == "12.34%"
    assert fmt_pct(0.1234, decimales=1) == "12.3%"
    assert fmt_pct(-0.005) == "-0.50%"
    assert fmt_pct(None) == ND


# ==========================================================================
# 3. Dividend yield: fraccion, porcentaje y calculo desde tasa/spot
# ==========================================================================


@pytest.mark.parametrize(
    ("dividend_yield", "dividend_rate", "spot", "esperado"),
    [
        # El campo dividendYield se interpreta SIEMPRE como puntos porcentuales
        (0.025, None, 100.0, 0.00025),
        (2.5, None, 100.0, 0.025),
        (5.0, None, 50.0, 0.05),
        (1.0, None, 100.0, 0.01),
        (1.01, None, 100.0, 0.0101),
        (0.43, None, None, 0.0043),
        # Con dividendo anual y spot se usa la via exacta (tiene prioridad)
        (None, 2.0, 100.0, 0.02),
        (None, 0.8, 40.0, 0.02),
        ("N/D", 3.0, 150.0, 0.02),
        (0.0, 2.0, 100.0, 0.02),
        (2.5, 2.0, 100.0, 0.02),
        ("N/D", 3.0, 0.0, None),
        ("2.5%", None, None, 0.025),
    ],
)
def test_normalizar_dividend_yield(dividend_yield, dividend_rate, spot, esperado):
    """El yield se normaliza siempre a fraccion decimal."""
    resultado = normalizar_dividend_yield(dividend_yield, dividend_rate, spot)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado, rel=1e-12)


def test_normalizar_dividend_yield_prioriza_el_calculo_exacto():
    """``dividend_rate / spot`` gana sobre la magnitud del campo del proveedor.

    Es la regla documentada: calcular con el dividendo anual y el spot es exacto y
    no depende de si el proveedor devuelve fraccion o puntos porcentuales.
    """
    # Un 2,5% de yield con dividendo de 2,5 y spot 100 -> 0,025 por la via exacta
    assert normalizar_dividend_yield(0.025, 2.5, 100.0) == pytest.approx(0.025, rel=1e-12)
    assert normalizar_dividend_yield(999.0, 2.5, 100.0) == pytest.approx(0.025, rel=1e-12)
    # Sin dividendo anual solo queda interpretar el campo como puntos porcentuales
    assert normalizar_dividend_yield(0.025, None, 100.0) == pytest.approx(0.00025, rel=1e-12)


@pytest.mark.parametrize(
    ("dividend_yield", "dividend_rate", "spot"),
    [
        (None, None, 100.0),
        (None, 2.0, 0.0),          # spot no positivo: no se puede dividir
        (None, 2.0, None),
        (None, 2.0, "N/D"),
        (0.0, None, None),
        ("abc", None, 100.0),
    ],
)
def test_normalizar_dividend_yield_devuelve_none_sin_datos(dividend_yield, dividend_rate, spot):
    """Sin yield y sin dividendo/spot utilizables no hay yield que informar."""
    assert normalizar_dividend_yield(dividend_yield, dividend_rate, spot) is None


# ==========================================================================
# 4. Alineacion mensual (fin de mes) y truncado
# ==========================================================================


def test_normalizar_mensual_alinea_al_ultimo_dia_del_mes():
    """Cualquier fecha del mes se lleva al ultimo dia del mes."""
    serie = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2024-01-02", "2024-01-20", "2024-02-05"]))
    normalizada = normalizar_mensual(serie)
    esperado = pd.DatetimeIndex([pd.Timestamp(2024, 1, 1) + pd.offsets.MonthEnd(0),
                                 pd.Timestamp(2024, 2, 1) + pd.offsets.MonthEnd(0)])
    assert normalizada.index.equals(esperado)
    # Ante duplicados del mismo mes se conserva el ULTIMO dato (keep="last")
    assert normalizada.tolist() == [2.0, 3.0]


def test_normalizar_mensual_tolera_cadenas_y_ordena():
    """El indice puede venir como texto desordenado: se convierte, alinea y ordena."""
    serie = pd.Series([10.0, 20.0, 30.0], index=["2024-03-04", "2024-01-15", "2024-02-27"])
    normalizada = normalizar_mensual(serie)
    esperado = pd.DatetimeIndex([
        pd.Timestamp(2024, 1, 1) + pd.offsets.MonthEnd(0),
        pd.Timestamp(2024, 2, 1) + pd.offsets.MonthEnd(0),
        pd.Timestamp(2024, 3, 1) + pd.offsets.MonthEnd(0),
    ])
    assert normalizada.index.equals(esperado)
    assert normalizada.tolist() == [20.0, 30.0, 10.0]
    assert normalizada.index.is_monotonic_increasing


@pytest.mark.parametrize("entrada", [None, pd.Series(dtype="float64")])
def test_normalizar_mensual_devuelve_none_sin_datos(entrada):
    """Una serie vacia o ``None`` no tiene alineacion posible."""
    assert normalizar_mensual(entrada) is None


def test_normalizar_mensual_no_muta_la_serie_original():
    """Se trabaja siempre sobre una copia: la entrada queda intacta."""
    serie = pd.Series([1.0, 2.0], index=pd.to_datetime(["2024-01-02", "2024-02-05"]))
    original = serie.copy()
    normalizar_mensual(serie)
    assert list(serie.index) == list(original.index)
    assert serie.tolist() == original.tolist()


def test_truncar_meses_recorta_los_ultimos_puntos():
    """``truncar_meses`` normaliza y devuelve la cola de la serie."""
    serie = pd.Series(
        range(1, 13),
        index=pd.date_range("2023-01-15", periods=12, freq="MS"),
        dtype="float64",
    )
    recortada = truncar_meses(serie, 5)
    assert len(recortada) == 5
    assert recortada.tolist() == [8.0, 9.0, 10.0, 11.0, 12.0]
    # Todos los puntos caen en el ultimo dia de su mes, en orden creciente
    assert (pd.DatetimeIndex(recortada.index) + pd.offsets.MonthEnd(0)).equals(pd.DatetimeIndex(recortada.index))
    assert recortada.index.is_monotonic_increasing
    assert (recortada.index[1:] - recortada.index[:-1]).days.max() <= 31
    # La cola conserva los cinco ultimos puntos de la serie normalizada
    assert recortada.index.equals(normalizar_mensual(serie).tail(5).index)
    assert truncar_meses(serie, 50).tolist() == serie.astype(float).tolist()
    assert truncar_meses(None, 5) is None
    assert truncar_meses(pd.Series(dtype="float64"), 5) is None


# ==========================================================================
# 5. Cache en disco: acierto, fallo, TTL y limpieza
# ==========================================================================


def _contador():
    """Productor con contador de llamadas, para distinguir hit de miss."""
    estado = {"llamadas": 0}

    def productor():
        estado["llamadas"] += 1
        return {"valor": estado["llamadas"]}

    return estado, productor


def test_cache_primer_fallo_y_segundo_acierto(cache_dir):
    """El primer acceso llama al productor; el segundo se sirve de la cache."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    estado, productor = _contador()

    primera = cache.obtener("precios NVDA", productor)
    assert primera == {"valor": 1}
    assert estado["llamadas"] == 1

    segunda = cache.obtener("precios NVDA", productor)
    assert segunda == {"valor": 1}
    assert estado["llamadas"] == 1, "el segundo acceso debe ser un acierto de cache"

    estadisticas = cache.estadisticas()
    assert estadisticas["aciertos"] == 1
    assert estadisticas["fallos"] == 1
    assert estadisticas["entradas"] == 1
    assert estadisticas["activa"] is True
    assert estadisticas["directorio"] == str(cache_dir)


def test_cache_claves_distintas_no_se_pisan(cache_dir):
    """Cada clave tiene su propio archivo (hash estable)."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    cache.escribir("a", {"x": 1})
    cache.escribir("b", {"x": 2})
    assert cache.leer("a") == (True, {"x": 1})
    assert cache.leer("b") == (True, {"x": 2})
    assert cache.ruta("a") != cache.ruta("b")
    assert cache.ruta("a").name.endswith(".json")
    assert len(cache.inventario()) == 2
    assert {f["Archivo"] for f in cache.inventario()} == {cache.ruta("a").name, cache.ruta("b").name}


def test_cache_clave_inexistente_es_fallo(cache_dir):
    """Leer una clave que no existe no lanza: devuelve ``(False, None)``."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    assert cache.leer("no existe") == (False, None)


def test_cache_ttl_caduca_la_entrada(cache_dir):
    """Una entrada mas antigua que el TTL deja de ser valida (miss)."""
    cache = Cache(cache_dir, ttl_horas=1.0)
    cache.escribir("serie", {"v": 42})
    assert cache.leer("serie") == (True, {"v": 42})

    # Envejecemos el archivo dos horas (mas que el TTL de una hora)
    archivo = cache.ruta("serie")
    antiguo = time.time() - 2 * 3600.0
    import os

    os.utime(archivo, (antiguo, antiguo))

    assert archivo.is_file()
    assert cache.leer("serie") == (False, None)
    estado, productor = _contador()
    assert cache.obtener("serie", productor) == {"valor": 1}
    assert estado["llamadas"] == 1


def test_cache_con_servicio_desactivado_no_guarda_ni_lee(cache_dir):
    """Con ``activa=False`` el productor se llama siempre y no se escribe nada."""
    cache = Cache(cache_dir, ttl_horas=24.0, activa=False)
    estado, productor = _contador()
    assert cache.obtener("k", productor) == {"valor": 1}
    assert cache.obtener("k", productor) == {"valor": 2}
    assert estado["llamadas"] == 2
    assert list(cache_dir.glob("*.json")) == []
    assert cache.estadisticas()["activa"] is False


def test_cache_no_guarda_none(cache_dir):
    """Un fallo temporal de red (``None``) no se cachea 24 horas."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    assert cache.obtener("k", lambda: None) is None
    assert list(cache_dir.glob("*.json")) == []
    assert cache.obtener("k", lambda: {"ok": True}) == {"ok": True}
    assert len(list(cache_dir.glob("*.json"))) == 1


def test_cache_serializa_series_y_dataframes(cache_dir):
    """La cache guarda JSON: las series se reconstruyen via ``json_default``."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    precios = pd.Series([100.0, 110.0], index=pd.to_datetime(["2024-01-31", "2024-02-29"]))
    cache.escribir("precios", precios)

    crudo = json.loads(cache.ruta("precios").read_text(encoding="utf-8"))
    assert crudo["__serie__"] is True
    assert crudo["valores"] == [100.0, 110.0]

    valido, leido = cache.leer("precios")
    assert valido is True
    assert isinstance(leido, dict) and leido["valores"] == [100.0, 110.0]


def test_cache_limpiar_borra_las_entradas(cache_dir):
    """``limpiar`` devuelve cuantas entradas borro y deja la cache vacia."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    for i in range(3):
        cache.escribir(f"clave {i}", {"i": i})
    assert len(list(cache_dir.glob("*.json"))) == 3

    borrados = cache.limpiar()
    assert borrados == 3
    assert list(cache_dir.glob("*.json")) == []
    assert cache.inventario() == []
    assert cache.estadisticas()["entradas"] == 0
    assert cache.limpiar() == 0


def test_cache_estadisticas_cuentan_aciertos_y_fallos(cache_dir):
    """El resumen de uso refleja la secuencia real de accesos."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    cache.obtener("k", lambda: 1)   # fallo
    cache.obtener("k", lambda: 2)   # acierto
    cache.obtener("k", lambda: 3)   # acierto
    cache.obtener("otra", lambda: 4)  # fallo
    estadisticas = cache.estadisticas()
    assert estadisticas["aciertos"] == 2
    assert estadisticas["fallos"] == 2
    assert estadisticas["entradas"] == 2


def test_cache_inventario_informa_tamano_y_edad(cache_dir):
    """El inventario muestra archivo, KB y edad en horas de cada entrada."""
    cache = Cache(cache_dir, ttl_horas=24.0)
    cache.escribir("k", {"dato": "x" * 512})
    filas = cache.inventario()
    assert len(filas) == 1
    fila = filas[0]
    assert set(fila) == {"Archivo", "KB", "Edad (h)"}
    assert fila["Archivo"] == cache.ruta("k").name
    assert fila["KB"] >= 0.0
    assert 0.0 <= fila["Edad (h)"] < 1.0
    assert all(math.isfinite(v) for v in (fila["KB"], fila["Edad (h)"]))


# ==========================================================================
# 5. Carpeta de datos de la aplicacion (nunca debe impedir arrancar)
# ==========================================================================
@pytest.fixture(autouse=True)
def _carpeta_datos_fresca():
    """Olvida la carpeta de datos memorizada antes y despues de cada prueba.

    ``ruta_datos_app`` recuerda su eleccion (para no repetir comprobaciones de
    disco), asi que las pruebas que cambian ``DML_FINANCE_HOME`` tienen que
    invalidarla.
    """
    from dml.core.config import olvidar_ruta_datos_app

    olvidar_ruta_datos_app()
    yield
    olvidar_ruta_datos_app()


def test_ruta_datos_app_usa_la_variable_de_entorno(tmp_path, monkeypatch):
    """``DML_FINANCE_HOME`` manda cuando se puede escribir en ella."""
    from dml.core.config import ruta_datos_app

    destino = tmp_path / "datos"
    monkeypatch.setenv("DML_FINANCE_HOME", str(destino))
    assert ruta_datos_app() == destino
    assert destino.is_dir()


def test_ruta_datos_app_no_lanza_si_la_ruta_es_un_archivo(tmp_path, monkeypatch):
    """Si la carpeta configurada no se puede crear, se usa otra alternativa.

    Es el fallo que dejaba la aplicacion sin arrancar: ``~/.dml_finance`` (o la
    ruta de ``DML_FINANCE_HOME``) no se puede crear o escribir y el
    ``PermissionError`` subia hasta la ventana de error.
    """
    from dml.core.config import ruta_datos_app

    archivo = tmp_path / "soy_un_archivo"
    archivo.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DML_FINANCE_HOME", str(archivo))

    elegida = ruta_datos_app()  # no debe lanzar
    assert elegida != archivo, "no se puede usar un archivo como carpeta de datos"
    assert elegida.is_dir(), f"la alternativa elegida deberia ser una carpeta: {elegida}"


def test_ruta_datos_app_no_lanza_sin_carpeta_personal(tmp_path, monkeypatch):
    """Tampoco falla si ``Path.home()`` no se puede resolver."""
    from dml.core import config as modulo_config

    monkeypatch.delenv("DML_FINANCE_HOME", raising=False)
    monkeypatch.setattr(modulo_config.Path, "home", classmethod(lambda cls: tmp_path / "perfil" / "roto"))
    elegida = modulo_config.ruta_datos_app()
    assert elegida.is_dir(), f"deberia haber una alternativa escribible: {elegida}"


def test_ruta_archivo_datos_devuelve_none_si_no_hay_carpeta(monkeypatch, tmp_path):
    """``ruta_archivo_datos`` devuelve ``None`` en lugar de lanzar."""
    from dml.core.config import ruta_archivo_datos

    archivo = tmp_path / "bloqueado"
    archivo.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DML_FINANCE_HOME", str(archivo))
    # Como hay alternativas (LOCALAPPDATA, temporal), devuelve una ruta valida;
    # lo importante es que nunca propague una excepcion.
    resultado = ruta_archivo_datos("dml-finance.log")
    assert resultado is None or resultado.parent.is_dir()


def test_la_cache_no_impide_arrancar_si_no_hay_carpeta(tmp_path, monkeypatch):
    """``_cache_de`` devuelve ``None`` (sin cache) si no puede preparar la carpeta."""
    from dml.ui import app as modulo_app

    def ruta_prohibida() -> "object":
        raise PermissionError("acceso denegado")

    monkeypatch.setattr(modulo_app, "ruta_datos_app", ruta_prohibida)
    config = {"datos": {"cache": True, "cache_dir": ".dml_cache", "cache_ttl_horas": 24}}
    assert modulo_app._cache_de(config) is None
    # Y con la cache desactivada tampoco se toca el disco.
    assert modulo_app._cache_de({"datos": {"cache": False}}) is None
