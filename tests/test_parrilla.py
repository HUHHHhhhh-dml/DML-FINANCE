# -*- coding: utf-8 -*-
"""Pruebas de ``dml.models.parrilla``: los 12 criterios y la regla de decision.

Se construyen tres escenarios completos sobre :class:`ResultadoAnalisis`:

* **Todo cumple**: calificacion ``1.0`` y decision ``COMPRAR``.
* **Todo falla**: calificacion ``0.0`` y decision ``NO INVERTIR``.
* **Intermedio**: 8 de 12 -> ``MANTENER``.

Ademas se comprueba que desactivar criterios promedia solo sobre los activos y
que un dato ``N/D`` (por ejemplo un PER negativo) califica 0 con nota.
"""

from __future__ import annotations

import pandas as pd
import pytest

from dml.core.config import cargar_config
from dml.core.tipos import (
    Estados,
    Fundamental,
    MetricasRiesgo,
    ResultadoAnalisis,
    ResultadoOLS,
    TablaTicker,
    Tasas,
)
from dml.models.parrilla import (
    TOTAL_CRITERIOS,
    aplicar_activos,
    calcular_calificacion,
    construir_parrilla,
    decision_desde_calificacion,
    resumen_parrilla,
    tabla_criterios,
)


# --------------------------------------------------------------------------
# Constructores de resultados sinteticos
# --------------------------------------------------------------------------
def _ols_sintetico(r2: float = 0.95) -> ResultadoOLS:
    """Resultado OLS minimo con el R2 que se quiera evaluar."""
    return ResultadoOLS(n=60, metodo="statsmodels", r2=r2, p_pendiente=0.0001, durbin_watson=1.9)


def _resultado_base(
    *,
    spot: float = 95.0,
    tlr: float = 0.04,
    rend_capm: float = 0.085,
    sigma_anual: float = 0.20,
    strike: float = 100.0,
    delta_call: float = 0.60,
    per: float | None = 20.0,
    per_sector: float | None = 30.0,
    eps: float | None = 3.0,
    eps_forecast: float | None = 2.5,
    p_fcf: float | None = 25.0,
    p_fcf_sector: float | None = 35.0,
    beta_cov: float | None = 0.90,
    macd_senal: str = "Buy",
    r2: float = 0.95,
    trg_valor: float = 0.01,
) -> ResultadoAnalisis:
    """Construye un ``ResultadoAnalisis`` completo y coherente para la parrilla.

    Con los valores por defecto se cumplen **los 12 criterios**.
    """
    precios = pd.Series([80.0 + i for i in range(60)], index=pd.date_range("2019-01-31", periods=60, freq="ME"))
    fundamentales = Fundamental(
        sector="Technology",
        per=per,
        per_sector=per_sector,
        eps=eps,
        eps_forecast=eps_forecast,
        p_fcf=p_fcf,
        p_fcf_sector=p_fcf_sector,
        dividend_rate=1.0,
        dividend_yield=0.005,
        market_cap=1e11,
        free_cash_flow=4e9,
        beta_publicada=1.3,
        nombre="Synthetic Corp",
        bolsa="NASDAQ",
    )
    riesgo = MetricasRiesgo(
        sigma_mensual=sigma_anual / (12 ** 0.5),
        sigma_anual=sigma_anual,
        riesgo_total=(sigma_anual ** 2) / 12.0,
        riesgo_sistematico=((sigma_anual ** 2) / 12.0) * 0.6,
        riesgo_no_sistematico=((sigma_anual ** 2) / 12.0) * 0.4,
        var_95=-0.09,
        var_99=-0.13,
        sharpe=0.30,
        treynor=0.05,
        max_drawdown=-0.20,
    )
    return ResultadoAnalisis(
        ticker="TEST",
        fecha_analisis="2024-05-17 10:00:00",
        modo="estandar",
        nombre="Synthetic Corp",
        bolsa="NASDAQ",
        moneda="USD",
        sector="Technology",
        spot=spot,
        precios=precios,
        indice_nombre="^GSPC",
        indice_precios=precios * 0.1,
        tabla=TablaTicker(index=precios.index, precio=list(precios.values)),
        fundamentales=fundamentales,
        tasas=Tasas(tbill_4w=tlr, ust_10y=0.045, ust_30y=0.05),
        tlr=tlr,
        tlr_mensual_valor=tlr / 12.0,
        beta_cov=beta_cov,
        beta_ols=beta_cov,
        beta_publicada=1.3,
        prh=0.05,
        prh_mensual_promedio=0.05 / 12.0,
        rend_capm=rend_capm,
        precio_objetivo=spot * (1.0 + rend_capm),
        trg_valor=trg_valor,
        precio_proyectado_trg=spot * (1.0 + trg_valor) ** 12,   # se recalcula en los escenarios que lo necesitan
        ols=_ols_sintetico(r2),
        riesgo=riesgo,
        q=0.005,
        b=tlr - 0.005,
        T=1.0,
        strike=strike,
        strike_modo="forward",
        griegas_call={"delta": delta_call},
        griegas_put={"delta": delta_call - 1.0},
        paridad={"ok": True},
        griegas_fd={"ok": True},
        macd_senal=macd_senal,
        macd_detalle="Histograma positivo y creciente",
        macd_datos=None,
        estados=Estados(),
    )


@pytest.fixture
def resultado_todo_cumple() -> ResultadoAnalisis:
    """Resultado con los 12 criterios cumpliendose.

    Los parametros son coherentes entre si: con ``spot = 95`` y
    ``strike = 98`` el forward (``95 e^{0.04} = 98,88``) queda por encima del spot
    (criterio 11) y la Delta de Black-Scholes con ``sigma = 8%`` vale ``0.5602``
    (criterio 12); ademas ``Rend_CAPM = 8,5% > sigma anual = 8%`` (criterio 8) y
    la proyeccion por TRG (``95 x 1,005^12 = 100,85``) supera el umbral
    ``spot x (1 + TLR + 1%) = 99,75`` (criterio 10).
    """
    resultado = _resultado_base(
        spot=95.0,
        strike=98.0,
        sigma_anual=0.08,
        delta_call=0.5602,
        rend_capm=0.085,
        trg_valor=0.005,
    )
    resultado.precio_proyectado_trg = 95.0 * 1.005 ** 12
    return resultado


@pytest.fixture
def resultado_todo_falla() -> ResultadoAnalisis:
    """Resultado que no cumple ningun criterio."""
    resultado = _resultado_base(
        spot=120.0,
        strike=50.0,                      # spot > forward -> criterio 11 falla
        delta_call=0.10,                  # Delta <= 0.50 -> criterio 12 falla
        rend_capm=0.01,                   # CAPM < TLR y < sigma -> criterios 5 y 8 fallan
        sigma_anual=0.30,
        per=40.0, per_sector=15.0,        # PER peor que el sector -> criterio 1 falla
        eps=1.0, eps_forecast=3.0,        # EPS por debajo del estimado -> criterio 2 falla
        p_fcf=40.0, p_fcf_sector=12.0,    # P/FCF peor que el sector -> criterio 4 falla
        beta_cov=1.80,                    # Beta por encima del maximo -> criterio 6 falla
        macd_senal="Sell",                # tecnico en venta -> criterio 3 falla
        r2=0.10,                          # R2 bajo -> criterio 9 falla
    )
    resultado.precio_proyectado_trg = 100.0   # <- spot * (1 + TLR + 1%) = 126.0 -> criterio 10 falla
    return resultado


@pytest.fixture
def resultado_intermedio() -> ResultadoAnalisis:
    """Resultado con 8 de 12 criterios (fallan 2, 3, 6 y 8)."""
    resultado = _resultado_base(
        spot=120.0,
        strike=150.0,          # los precios siguen subiendo: forward por encima del spot
        delta_call=0.52,       # Delta > 0.50 con K = 150 y sigma = 35% (criterio 12 cumple)
        sigma_anual=0.35,      # RDR: Rend_CAPM 0.085 < sigma 0.35 -> criterio 8 falla
        eps=1.0, eps_forecast=3.0,   # EPS por debajo del estimado -> criterio 2 falla
        beta_cov=1.80,               # Beta por encima del maximo -> criterio 6 falla
        macd_senal="Sell",           # tecnico en venta -> criterio 3 falla
    )
    resultado.precio_proyectado_trg = 120.0 * 1.01 ** 12
    return resultado


# ==========================================================================
# 1. Estructura de la parrilla
# ==========================================================================


def test_parrilla_tiene_doce_criterios_numerados(resultado_todo_cumple, config_default):
    """``construir_parrilla`` devuelve los 12 criterios numerados 1..12."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)
    assert TOTAL_CRITERIOS == 12
    assert len(criterios) == 12
    assert [c.numero for c in criterios] == list(range(1, 13))
    assert all(c.nombre for c in criterios)
    assert all(c.fuente for c in criterios)
    assert all(c.calificacion in (0, 1) for c in criterios)
    assert all(c.activo for c in criterios)


def test_parrilla_sin_config_usa_los_valores_por_defecto(resultado_todo_cumple):
    """Sin configuracion explicita se aplican los umbrales por defecto."""
    criterios = construir_parrilla(resultado_todo_cumple)
    assert len(criterios) == 12
    beta = next(c for c in criterios if c.numero == 6)
    assert beta.comparacion == pytest.approx(1.10)
    assert "1.10" in beta.nombre


# ==========================================================================
# 2. Los tres escenarios completos
# ==========================================================================


def test_escenario_todo_cumple_da_comprar(resultado_todo_cumple, config_default):
    """Los 12 criterios cumplidos -> calificacion 1.0 y COMPRAR."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)
    fallidos = [c.nombre for c in criterios if not c.cumple]
    assert fallidos == [], f"criterios inesperadamente incumplidos: {fallidos}"

    calificacion, decision = calcular_calificacion(criterios, config_default)
    assert calificacion == pytest.approx(1.0)
    assert decision == "COMPRAR"
    assert sum(c.calificacion for c in criterios) == 12


def test_escenario_todo_falla_da_no_invertir(resultado_todo_falla, config_default):
    """Ningun criterio cumplido -> calificacion 0.0 y NO INVERTIR."""
    criterios = construir_parrilla(resultado_todo_falla, config_default)
    cumplidos = [c.nombre for c in criterios if c.cumple]
    assert cumplidos == [], f"criterios inesperadamente cumplidos: {cumplidos}"

    calificacion, decision = calcular_calificacion(criterios, config_default)
    assert calificacion == pytest.approx(0.0)
    assert decision == "NO INVERTIR"
    assert sum(c.calificacion for c in criterios) == 0


def test_escenario_intermedio_da_mantener(resultado_intermedio, config_default):
    """Ocho de doce criterios -> calificacion 2/3 y MANTENER."""
    criterios = construir_parrilla(resultado_intermedio, config_default)
    fallidos = sorted(c.numero for c in criterios if not c.cumple)
    assert fallidos == [2, 3, 6, 8], f"fallos inesperados: {fallidos}"

    calificacion, decision = calcular_calificacion(criterios, config_default)
    assert calificacion == pytest.approx(8.0 / 12.0)
    assert decision == "MANTENER"
    assert 0.40 <= calificacion <= 0.70


# ==========================================================================
# 3. Regla de decision y promediado de criterios activos
# ==========================================================================


@pytest.mark.parametrize(
    ("calificacion", "decision"),
    [
        (1.0, "COMPRAR"),
        (0.71, "COMPRAR"),
        (0.70, "MANTENER"),   # el umbral de compra es estricto (>
        (0.55, "MANTENER"),
        (0.40, "MANTENER"),   # el umbral de mantener es inclusivo (>=
        (0.39, "NO INVERTIR"),
        (0.0, "NO INVERTIR"),
        (None, "N/D"),
    ],
)
def test_decision_desde_calificacion(calificacion, decision):
    """Bordes de la regla de decision del pliego."""
    assert decision_desde_calificacion(calificacion) == decision


def test_calificacion_promedia_solo_los_criterios_activos(resultado_intermedio, config_default):
    """Al desactivar los criterios incumplidos la calificacion sube a 1.0."""
    criterios = construir_parrilla(resultado_intermedio, config_default)
    calificacion_12, decision_12 = calcular_calificacion(criterios, config_default)
    assert calificacion_12 == pytest.approx(8.0 / 12.0)
    assert decision_12 == "MANTENER"

    # Se desactivan los cuatro criterios incumplidos (2, 3, 6 y 8)
    aplicar_activos(criterios, {2: False, 3: False, 6: False, 8: False})
    activos = [c for c in criterios if c.activo]
    assert len(activos) == 8
    calificacion, decision = calcular_calificacion(criterios, config_default)
    assert calificacion == pytest.approx(1.0)
    assert decision == "COMPRAR"


def test_desactivar_un_criterio_cumplido_baja_la_calificacion(resultado_todo_cumple, config_default):
    """El promedio se recalcula sobre los activos, no sobre los 12 fijos."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)
    aplicar_activos(criterios, {1: False, 2: False, 3: False})
    activos = [c for c in criterios if c.activo]
    assert len(activos) == 9
    # 9 criterios cumplidos de 9 activos
    calificacion, decision = calcular_calificacion(criterios, config_default)
    assert calificacion == pytest.approx(1.0)
    assert decision == "COMPRAR"

    # Si uno de los activos no cumple, la calificacion es 8/9
    activos[0].cumple = False
    activos[0].calificacion = 0
    calificacion2, _ = calcular_calificacion(criterios, config_default)
    assert calificacion2 == pytest.approx(8.0 / 9.0)


def test_parrilla_sin_criterios_activos_no_tiene_calificacion(resultado_todo_cumple, config_default):
    """Sin criterios activos la calificacion es ``None`` y la decision ``N/D``."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)
    aplicar_activos(criterios, {n: False for n in range(1, 13)})
    assert all(not c.activo for c in criterios)
    assert calcular_calificacion(criterios, config_default) == (None, "N/D")


def test_aplicar_activos_ignora_numeros_ausentes(resultado_todo_cumple, config_default):
    """Los criterios cuyo numero no aparece en el mapa siguen activos."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)
    aplicar_activos(criterios, {5: False})
    assert next(c for c in criterios if c.numero == 5).activo is False
    assert next(c for c in criterios if c.numero == 6).activo is True


# ==========================================================================
# 4. N/D => 0 puntos con nota (PER negativo y demas huecos)
# ==========================================================================


def test_per_negativo_califica_cero_con_nota(config_default):
    """Un PER negativo (perdidas) da N/D: 0 puntos y nota explicativa."""
    resultado = _resultado_base(per=-15.0, per_sector=30.0)
    criterios = construir_parrilla(resultado, config_default)

    criterio1 = next(c for c in criterios if c.numero == 1)
    assert criterio1.calificacion == 0
    assert criterio1.cumple is False
    assert "PER negativo" in criterio1.nota

    # La Renta PER (criterio 7) tampoco es calculable con PER negativo
    criterio7 = next(c for c in criterios if c.numero == 7)
    assert criterio7.calificacion == 0
    assert criterio7.cumple is False
    assert "N/D" in criterio7.nota


def test_datos_ausentes_califican_cero_con_nota(config_default):
    """Sin PER, EPS, P/FCF ni MACD los criterios afectados valen 0 y lo anotan."""
    resultado = _resultado_base(
        per=None, per_sector=None, eps=None, eps_forecast=None, p_fcf=None, p_fcf_sector=None, macd_senal="N/D"
    )
    criterios = construir_parrilla(resultado, config_default)

    for numero in (1, 2, 3, 4, 7):
        criterio = next(c for c in criterios if c.numero == numero)
        assert criterio.calificacion == 0, criterio.nombre
        assert criterio.cumple is False, criterio.nombre
        assert criterio.nota, f"el criterio {numero} deberia explicar el motivo"
        assert criterio.valor == "N/D" or criterio.comparacion == "N/D" or "N/D" in str(criterio.nota)


def test_riesgo_y_ols_ausentes_califican_cero(config_default):
    """Sin sigma anual ni R2 los criterios 8 y 9 valen 0 con nota."""
    resultado = _resultado_base()
    resultado.riesgo = MetricasRiesgo()   # sigma_anual = None
    resultado.ols = None
    criterios = construir_parrilla(resultado, config_default)

    criterio8 = next(c for c in criterios if c.numero == 8)
    criterio9 = next(c for c in criterios if c.numero == 9)
    assert criterio8.calificacion == 0 and "N/D" in criterio8.nota
    assert criterio9.calificacion == 0 and "N/D" in criterio9.nota


def test_criterio_tecnico_macd_neutral_cumple(config_default):
    """La senal Neutral cumple el criterio tecnico (solo Sell lo incumple)."""
    criterios_neutral = construir_parrilla(_resultado_base(macd_senal="Neutral"), config_default)
    assert next(c for c in criterios_neutral if c.numero == 3).cumple is True
    criterios_sell = construir_parrilla(_resultado_base(macd_senal="Sell"), config_default)
    assert next(c for c in criterios_sell if c.numero == 3).cumple is False


# ==========================================================================
# 5. Utilidades de presentacion
# ==========================================================================


def test_tabla_y_resumen_de_la_parrilla(resultado_todo_cumple, config_default):
    """Las utilidades de presentacion no pierden informacion."""
    criterios = construir_parrilla(resultado_todo_cumple, config_default)

    filas = tabla_criterios(criterios)
    assert len(filas) == 12
    assert set(filas[0]) >= {"#", "Criterio", "Cumple", "Calificacion", "Activo", "Nota"}
    assert all(fila["Cumple"] == "SI" for fila in filas)

    resumen = resumen_parrilla(criterios)
    assert resumen["total"] == 12
    assert resumen["activos"] == 12
    assert resumen["cumplidos"] == 12
    assert resumen["fallidos"] == 0


def test_decision_con_umbrales_personalizados(resultado_todo_cumple):
    """Los umbrales de decision son parametros de configuracion."""
    criterios = construir_parrilla(resultado_todo_cumple)
    calificacion, _ = calcular_calificacion(criterios, {"decision": {"comprar_min": 1.5, "mantener_min": 0.1}})
    assert calificacion == pytest.approx(1.0)
    assert decision_desde_calificacion(calificacion, comprar_min=1.5, mantener_min=0.1) == "MANTENER"


def test_criterios_usan_la_configuracion_del_proyecto():
    """Los umbrales salen de ``config['umbrales']``."""
    config = cargar_config(None)
    assert config["umbrales"]["beta_max"] == pytest.approx(1.10)
    config_estricta = {**config, "umbrales": {**config["umbrales"], "beta_max": 1.00}}

    resultado_holgada = _resultado_base(beta_cov=0.95)
    assert next(c for c in construir_parrilla(resultado_holgada, config) if c.numero == 6).cumple is True
    assert next(c for c in construir_parrilla(resultado_holgada, config_estricta) if c.numero == 6).cumple is True

    resultado_limite = _resultado_base(beta_cov=1.05)
    assert next(c for c in construir_parrilla(resultado_limite, config) if c.numero == 6).cumple is True
    assert next(c for c in construir_parrilla(resultado_limite, config_estricta) if c.numero == 6).cumple is False
