# -*- coding: utf-8 -*-
"""Pruebas de ``dml.data.tasas``.

El bloque central del pliego es la **conversion descuento -> rendimiento
equivalente de bono**:

.. math:: y = \\frac{365 d}{360 - d t}, \\qquad t = 28

Se comprueba con un caso conocido y con los valores de referencia calculados
exactamente, que ``y > d`` siempre, el tamano de la brecha para tipos cortos
realistas y que la funcion rechaza las combinaciones imposibles (denominador no
positivo) en lugar de devolver un numero sin sentido.

Ademas se prueba ``serie_fred`` y ``obtener_tasas`` **sin red**, sustituyendo
las funciones de descarga con ``monkeypatch``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from dml.core.cache import Cache
from dml.core.tipos import Fuentes, Tasas
from dml.data import proveedores
from dml.data import tasas as modulo_tasas
from dml.data.tasas import (
    CLAVES,
    descuento_a_rendimiento,
    obtener_tasas,
    rendimiento_equivalente_bono,
    resumen_tasas,
    serie_fred,
    serie_tasas_fred,
)

DIAS_TBILL = 28

#: Valores exactos de ``365 * d / (360 - d * 28)`` para tipos de descuento reales.
CASOS_DESCUENTO = [
    (0.0300, 0.030487804878048776),
    (0.0418, 0.042518788862457274),
    (0.0425, 0.043233187480839444),
    (0.0450, 0.04578524836929253),
    (0.0525, 0.05344741025855577),
]


# ==========================================================================
# 1. Conversion descuento -> rendimiento equivalente de bono
# ==========================================================================


def test_conversion_caso_conocido_pinado():
    """``d = 0.0425`` (4,25%) -> ``y = 365 d / (360 - 28 d)``."""
    esperado = 365.0 * 0.0425 / (360.0 - 0.0425 * DIAS_TBILL)
    obtenido = descuento_a_rendimiento(0.0425, dias=28)
    assert obtenido == pytest.approx(esperado, rel=1e-15)
    assert obtenido == pytest.approx(0.043233187480839444, rel=1e-14)
    assert obtenido == pytest.approx(0.04323, abs=1e-5)
    # El alias largo y el corto son exactamente la misma funcion
    assert rendimiento_equivalente_bono(0.0425, dias=28) == pytest.approx(obtenido, rel=1e-15)


@pytest.mark.parametrize(("descuento", "esperado"), CASOS_DESCUENTO)
def test_conversion_valores_exactos(descuento, esperado):
    """Los valores de referencia estan calculados a mano con la formula del pliego."""
    assert descuento_a_rendimiento(descuento, dias=28) == pytest.approx(esperado, rel=1e-14)

@pytest.mark.parametrize(("descuento", "_esperado"), CASOS_DESCUENTO)
def test_el_rendimiento_es_siempre_mayor_que_el_descuento(descuento, _esperado):
    """``y > d`` porque el denominador es menor que 360 y el numerador es 365."""
    y = descuento_a_rendimiento(descuento, dias=28)
    assert y > descuento
    assert descuento_a_rendimiento(0.03, dias=28) > 0.03
    assert descuento_a_rendimiento(0.08, dias=28) > 0.08


@pytest.mark.parametrize(("descuento", "_esperado"), CASOS_DESCUENTO)
def test_la_brecha_es_coherente_con_la_formula(descuento, _esperado):
    """La brecha ``y - d`` crece con el nivel de tipos y coincide con la formula.

    Nota: la brecha que produce la formula del pliego con ``t = 28`` es de unos
    **7-9 puntos base** para tipos cortos realistas (3%-5,25%); los 15-20 pb solo
    aparecerian si se comparase contra una tasa a descuento *sin* convertir la
    base del numerador. La prueba fija el comportamiento real de la formula.
    """
    y = descuento_a_rendimiento(descuento, dias=28)
    brecha_pb = (y - descuento) * 10_000.0
    esperado_pb = (365.0 * descuento / (360.0 - descuento * DIAS_TBILL) - descuento) * 10_000.0
    assert brecha_pb == pytest.approx(esperado_pb, rel=1e-12)
    assert 4.0 < brecha_pb < 10.0, f"brecha inesperada: {brecha_pb:.2f} pb"

    # La brecha es creciente con el nivel de tipos
    brecha_baja = (descuento_a_rendimiento(0.03, 28) - 0.03) * 10_000.0
    brecha_alta = (descuento_a_rendimiento(0.0525, 28) - 0.0525) * 10_000.0
    assert brecha_alta > brecha_baja


def test_la_funcion_no_mezcla_convenciones_en_silencio():
    """Sin base 365/360 explicita no hay conversion: devuelve ``None``.

    * Denominador no positivo (``d >= 360/t``): conversion imposible.
    * Entrada no numerica: ``None``.
    * La base del descuento es un parametro explicito y cambiar la base cambia
      el resultado: nunca se asume una convencion por descuido.
    """
    # d = 360/28 = 12.857 -> denominador nulo
    assert descuento_a_rendimiento(360.0 / 28.0, dias=28) is None
    assert descuento_a_rendimiento(20.0, dias=28) is None
    assert descuento_a_rendimiento(0.5, dias=720) is None

    for valor in (None, float("nan"), float("inf"), "", "N/D", "abc"):
        assert descuento_a_rendimiento(valor, dias=28) is None

    # La convencion es explicita: 360/360 da un resultado distinto y conocido
    y_365 = descuento_a_rendimiento(0.0425, dias=28)
    y_360 = rendimiento_equivalente_bono(0.0425, dias=28, dias_anio=360, base_descuento=360)
    assert y_360 == pytest.approx(360.0 * 0.0425 / (360.0 - 0.0425 * 28), rel=1e-12)
    assert y_360 == pytest.approx(0.042640952035896434, rel=1e-12)
    assert y_365 != pytest.approx(y_360, rel=1e-6)
    assert y_365 > y_360
    # La diferencia entre las dos convenciones es de unos 6 puntos base con t = 28
    assert (y_365 - y_360) * 10_000.0 == pytest.approx(5.922354449430095, rel=1e-9)
    assert 1.0 < (y_365 - y_360) * 10_000.0 < 10.0


def test_conversion_recibe_la_tasa_en_fraccion_no_en_porcentaje():
    """Contrato explicito: la tasa de descuento se pasa en fraccion.

    La funcion **no** convierte porcentajes: ``4.25`` se interpreta como una tasa
    del 425%. Es la conversion a fraccion (``/100``) la que debe haber hecho
    antes la capa de datos, de modo que ninguna convencion se mezcla por
    descuido. Se comprueba con una cadena numerica en fraccion.
    """
    assert descuento_a_rendimiento("0.0425", dias=28) == pytest.approx(
        descuento_a_rendimiento(0.0425, dias=28), rel=1e-12
    )
    # Un valor en tanto por ciento da un resultado muy distinto (y absurdo)
    assert descuento_a_rendimiento("4.25%", dias=28) == pytest.approx(4.25 * 365.0 / (360.0 - 4.25 * 28), rel=1e-12)
    assert descuento_a_rendimiento("4.25%", dias=28) != pytest.approx(descuento_a_rendimiento(0.0425, dias=28), rel=1e-3)


def test_conversion_con_otro_plazo():
    """El plazo ``t`` es un parametro: a mas plazo, mayor brecha."""
    y_28 = descuento_a_rendimiento(0.0425, dias=28)
    y_91 = descuento_a_rendimiento(0.0425, dias=91)
    assert y_91 == pytest.approx(365.0 * 0.0425 / (360.0 - 0.0425 * 91), rel=1e-12)
    assert y_91 > y_28 > 0.0425


# ==========================================================================
# 2. serie_fred sin red (monkeypatch)
# ==========================================================================


def test_serie_fred_reconstruye_la_serie_del_productor(monkeypatch):
    """``serie_fred`` devuelve una ``Series`` indexada por fecha, sin duplicados."""
    indice = pd.date_range("2024-01-01", periods=10, freq="D")

    def productor_sustituto(series_id, timeout=25, reintentos=1, pausa_seg=0.0, **kwargs):
        return pd.Series([4.0 + i * 0.01 for i in range(10)], index=indice)

    # Sin clave de API se usa el CSV publico; ambas rutas se sustituyen.
    monkeypatch.setattr(proveedores, "clave_api", lambda nombre: None)
    monkeypatch.setattr(proveedores, "_csv_fred_publico", productor_sustituto)

    serie = serie_fred("DGS1MO")
    assert serie is not None
    assert len(serie) == 10
    assert serie.index[0] == pd.Timestamp("2024-01-01")
    assert serie.iloc[0] == pytest.approx(4.0)
    assert serie.iloc[-1] == pytest.approx(4.09)


def test_serie_fred_devuelve_none_si_la_fuente_falla(monkeypatch):
    """Si FRED no responde, ``serie_fred`` devuelve ``None`` (nunca lanza)."""

    def falla(*args, **kwargs):
        raise RuntimeError("sin conexion simulada")

    monkeypatch.setattr(proveedores, "_csv_fred_publico", falla)
    monkeypatch.setattr(proveedores, "_json_fred_api", falla)
    monkeypatch.setattr(proveedores, "clave_api", lambda nombre: None)
    assert serie_fred("DGS10") is None


def test_serie_fred_usa_la_cache(cache_dir, monkeypatch):
    """La segunda llamada se sirve de la cache y no vuelve a pedir la serie."""
    indice = pd.date_range("2024-01-01", periods=5, freq="D")
    contador = {"llamadas": 0}

    def productor_sustituto(series_id, timeout=25, reintentos=1, pausa_seg=0.0, **kwargs):
        contador["llamadas"] += 1
        return pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=indice)

    monkeypatch.setattr(proveedores, "clave_api", lambda nombre: None)
    monkeypatch.setattr(proveedores, "_csv_fred_publico", productor_sustituto)

    cache = Cache(cache_dir, ttl_horas=24.0)
    primera = serie_fred("DGS1MO", cache=cache)
    segunda = serie_fred("DGS1MO", cache=cache)
    assert contador["llamadas"] == 1, "la segunda lectura deberia ser un acierto de cache"
    assert primera is not None and segunda is not None
    assert list(primera.values) == pytest.approx(list(segunda.values), rel=1e-12)


# ==========================================================================
# 3. obtener_tasas: cascada de respaldos, todo OFFLINE
# ==========================================================================


@pytest.fixture
def config_tasas() -> dict:
    """Configuracion de datos con la cascada completa pero sin red disponible."""
    return {
        "datos": {
            "cache": True,
            "usar_fred": True,
            "usar_yfinance_tasas": True,
            "usar_manual": False,      # nunca debe pedir datos por consola en las pruebas
            "intentar_investing": True,
            "usar_playwright": True,
            "agregacion_fred": "last",
            "dias_tbill_descuento": 28,
            "investing_urls": {
                "tbill_4w": "https://example.invalid/4w",
                "ust_10y": "https://example.invalid/10y",
                "ust_30y": "https://example.invalid/30y",
            },
            "fred_series": {
                "tbill_4w": "DGS1MO",
                "tbill_4w_descuento": "DTB4WK",
                "ust_10y": "DGS10",
                "ust_30y": "DGS30",
            },
            "yf_series": {"ust_10y": "^TNX", "ust_30y": "^TYX"},
        }
    }


def _fred_falso(series_id, **kwargs):
    """FRED simulado: valores en porcentaje, como los publica la fuente real."""
    if series_id == "DGS1MO":
        indice = pd.date_range("2024-01-31", periods=6, freq="ME")
        return pd.Series([4.20, 4.25, 4.30, 4.30, 4.35, 4.25], index=indice)
    if series_id == "DGS10":
        return pd.Series([4.30, 4.40, 4.50], index=pd.date_range("2024-01-31", periods=3, freq="ME"))
    if series_id == "DGS30":
        return pd.Series([4.80, 4.90, 5.00], index=pd.date_range("2024-01-31", periods=3, freq="ME"))
    if series_id == "DTB4WK":
        # Tasa a descuento (en porcentaje) que hay que convertir
        return pd.Series([4.18, 4.20, 4.22], index=pd.date_range("2024-01-31", periods=3, freq="ME"))
    return None


@pytest.fixture
def sin_fuentes_primarias(monkeypatch):
    """Deja solo FRED disponible: Investing y Yahoo devuelven ``None``."""
    monkeypatch.setattr(modulo_tasas, "scrape_investing", lambda url, config: None)
    monkeypatch.setattr(modulo_tasas, "scrape_investing_playwright", lambda url, config: None)
    monkeypatch.setattr(modulo_tasas, "tasa_yfinance", lambda simbolo, cache=None, config=None: None)
    monkeypatch.setattr(modulo_tasas, "pedir_valor_manual", lambda nombre, config=None: None)


def test_obtener_tasas_usa_fred_como_respaldo(config_tasas, sin_fuentes_primarias, cache_dir, monkeypatch):
    """Sin Investing ni Yahoo, la TLR y los bonos llegan de FRED (respaldo)."""
    monkeypatch.setattr(modulo_tasas, "serie_fred", _fred_falso)
    fuentes = Fuentes()
    cache = Cache(cache_dir, ttl_horas=24.0)

    resultado = obtener_tasas(cache=cache, fuentes=fuentes, config=config_tasas, meses=6)

    assert isinstance(resultado, Tasas)
    assert resultado.tbill_4w == pytest.approx(0.0425, rel=1e-12)
    assert resultado.ust_10y == pytest.approx(0.0450, rel=1e-12)
    assert resultado.ust_30y == pytest.approx(0.0500, rel=1e-12)
    assert resultado.metodo_de("tbill_4w") == "respaldo"
    assert resultado.metodo_de("ust_10y") == "respaldo"
    assert resultado.metodo_de("ust_30y") == "respaldo"
    assert "FRED" in resultado.ev_tbill_4w.fuente
    assert resultado.ev_tbill_4w.ok is True
    assert resultado.tlr == pytest.approx(0.0425, rel=1e-12)

    # La serie mensual queda alineada a fin de mes y recortada a los meses pedidos
    serie = resultado.serie_tbill_mensual
    assert serie is not None
    assert len(serie) == 6
    assert serie.index[-1] == pd.Timestamp("2024-06-30")
    assert serie.index.is_monotonic_increasing
    assert serie.iloc[-1] == pytest.approx(0.0425, rel=1e-12)

    # El registro de procedencia incluye las tres tasas
    assert len(fuentes.por_metodo("respaldo")) == 3
    assert all(etiqueta in [f.dato for f in fuentes.items] for etiqueta in (
        "T-Bill EE.UU. 4 semanas (TLR)", "Bono EE.UU. 10 anios", "Bono EE.UU. 30 anios",
    ))


def test_obtener_tasas_convierte_el_descuento_de_dtb4wk(config_tasas, sin_fuentes_primarias, monkeypatch):
    """Si solo hay ``DTB4WK`` (descuento) se convierte a rendimiento de bono."""
    def fred_solo_descuento(series_id, **kwargs):
        if series_id == "DTB4WK":
            return pd.Series([4.25, 4.25, 4.25], index=pd.date_range("2024-01-31", periods=3, freq="ME"))
        return None

    monkeypatch.setattr(modulo_tasas, "serie_fred", fred_solo_descuento)
    resultado = obtener_tasas(cache=None, fuentes=None, config=config_tasas, meses=6)

    esperado = descuento_a_rendimiento(0.0425, dias=28)
    assert resultado.tbill_4w == pytest.approx(esperado, rel=1e-12)
    assert resultado.tbill_4w > 0.0425
    assert "convertido" in resultado.ev_tbill_4w.nota.lower()
    assert resultado.metodo_de("tbill_4w") == "respaldo"


def test_obtener_tasas_respeta_el_valor_manual(config_tasas, monkeypatch):
    """Un valor manual tiene prioridad y **no** se llama a ninguna fuente."""
    def prohibido(*args, **kwargs):  # pragma: no cover - debe fallar si se llama
        raise AssertionError("no se debe consultar ninguna fuente si hay valor manual")

    monkeypatch.setattr(modulo_tasas, "scrape_investing", prohibido)
    monkeypatch.setattr(modulo_tasas, "scrape_investing_playwright", prohibido)
    monkeypatch.setattr(modulo_tasas, "serie_fred", prohibido)
    monkeypatch.setattr(modulo_tasas, "tasa_yfinance", prohibido)
    monkeypatch.setattr(modulo_tasas, "pedir_valor_manual", prohibido)

    resultado = obtener_tasas(
        cache=None, fuentes=None, config=config_tasas, meses=6,
        manuales={"tbill_4w": 0.0435, "ust_10y": 0.046, "ust_30y": 0.051},
    )
    assert resultado.tbill_4w == pytest.approx(0.0435, rel=1e-12)
    assert resultado.ust_10y == pytest.approx(0.046, rel=1e-12)
    assert resultado.ust_30y == pytest.approx(0.051, rel=1e-12)
    assert all(resultado.metodo_de(clave) == "manual" for clave in CLAVES)


def test_obtener_tasas_sin_fuentes_deja_nd_y_avisa(config_tasas, sin_fuentes_primarias, monkeypatch):
    """Si todo falla, las tasas quedan N/D y se registran advertencias."""
    monkeypatch.setattr(modulo_tasas, "serie_fred", lambda series_id, **kwargs: None)
    resultado = obtener_tasas(cache=None, fuentes=None, config=config_tasas, meses=6)

    assert resultado.tbill_4w is None
    assert resultado.ust_10y is None
    assert resultado.ust_30y is None
    assert all(resultado.metodo_de(clave) == "N/D" for clave in CLAVES)
    assert resultado.ev_tbill_4w.ok is False
    assert len(resultado.advertencias) >= 3
    assert any("N/D" in aviso for aviso in resultado.advertencias)
    assert any("Serie historica mensual de la TLR" in aviso for aviso in resultado.advertencias)
    assert resultado.serie_tbill_mensual is None


def test_resumen_tasas_estructura(config_tasas, sin_fuentes_primarias, monkeypatch):
    """El resumen de la pestana de tasas tiene una fila por tasa."""
    monkeypatch.setattr(modulo_tasas, "serie_fred", _fred_falso)
    resultado = obtener_tasas(cache=None, fuentes=None, config=config_tasas, meses=6)
    filas = resumen_tasas(resultado)
    assert len(filas) == 3
    assert [f["Tasa"] for f in filas] == [
        "T-Bill EE.UU. 4 semanas (TLR)",
        "Bono EE.UU. 10 anios",
        "Bono EE.UU. 30 anios",
    ]
    assert filas[0]["Valor"] == pytest.approx(0.0425, rel=1e-12)
    assert filas[0]["Metodo"] == "respaldo"


def test_serie_tasas_fred_usa_la_cache(cache_dir, monkeypatch):
    """El envoltorio con cache no repite la descarga dentro del mismo dia."""
    contador = {"llamadas": 0}

    def falso(series_id, cache=None, config=None):
        contador["llamadas"] += 1
        return pd.Series([1.0, 2.0], index=pd.date_range("2024-01-31", periods=2, freq="ME"))

    monkeypatch.setattr(modulo_tasas, "serie_fred", falso)
    cache = Cache(cache_dir, ttl_horas=24.0)
    serie_tasas_fred("DGS10", cache=cache, config={})
    serie_tasas_fred("DGS10", cache=cache, config={})
    assert contador["llamadas"] == 1
