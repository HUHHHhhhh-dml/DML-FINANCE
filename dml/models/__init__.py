# -*- coding: utf-8 -*-
"""Modelos financieros de DML-FINANCE.

Cada submodulo es independiente de la interfaz grafica: se puede importar y
probar sin Qt.

* :mod:`~dml.models.rendimientos`  - rendimientos simples, logaritmicos y TRG.
* :mod:`~dml.models.capm`          - Beta, prima de riesgo, CAPM y precio objetivo.
* :mod:`~dml.models.econometria`   - MCO de precio ~ periodo y diagnostico.
* :mod:`~dml.models.riesgo`        - volatilidad, VaR, Sharpe, Treynor, drawdown.
* :mod:`~dml.models.blackscholes`  - BSM generalizado, griegas y verificaciones.
* :mod:`~dml.models.tecnicos`      - MACD(12,26,9) y su clasificacion.
* :mod:`~dml.models.fundamentales` - PER, Renta PER, Price to FCF, RDR.
* :mod:`~dml.models.parrilla`      - parrilla de decision de 12 criterios.
* :mod:`~dml.models.parametros`    - resolucion de los parametros efectivos.
"""

from __future__ import annotations

from .rendimientos import (
    media_geometrica,
    rendimientos_logaritmicos,
    rendimientos_simples,
    serie_tlr_mensual,
    tlr_mensual,
    trg,
)
from .capm import (
    beta_covarianza,
    beta_ols,
    precio_objetivo_capm,
    precio_proyectado_trg,
    prima_riesgo_excel,
    prima_riesgo_mercado,
    rendimiento_capm,
)
from .riesgo import max_drawdown, metricas_riesgo, var_parametrico
from .econometria import (
    interpretar as interpretar_ols,
    ols_econometrico,
    pruebas_residuos,
    tabla_residuos,
)
from .tecnicos import calcular_macd, clasificar_macd
from .fundamentales import per_valor, price_to_fcf, rdr, renta_per
from .parrilla import (
    aplicar_activos,
    calcular_calificacion,
    config_con_overrides,
    construir_parrilla,
    decision_desde_calificacion,
    resumen_parrilla,
    tabla_criterios,
)
from .parametros import anios_entre, fecha_vencimiento, parametros_efectivos, strike_objetivo

__all__ = [
    "media_geometrica",
    "rendimientos_logaritmicos",
    "rendimientos_simples",
    "serie_tlr_mensual",
    "tlr_mensual",
    "trg",
    "beta_covarianza",
    "beta_ols",
    "precio_objetivo_capm",
    "precio_proyectado_trg",
    "prima_riesgo_excel",
    "prima_riesgo_mercado",
    "rendimiento_capm",
    "max_drawdown",
    "metricas_riesgo",
    "var_parametrico",
    "ols_econometrico",
    "tabla_residuos",
    "pruebas_residuos",
    "interpretar_ols",
    "calcular_macd",
    "clasificar_macd",
    "per_valor",
    "price_to_fcf",
    "rdr",
    "renta_per",
    "calcular_calificacion",
    "construir_parrilla",
    "decision_desde_calificacion",
    "aplicar_activos",
    "config_con_overrides",
    "resumen_parrilla",
    "tabla_criterios",
    "parametros_efectivos",
    "anios_entre",
    "fecha_vencimiento",
    "strike_objetivo",
]
