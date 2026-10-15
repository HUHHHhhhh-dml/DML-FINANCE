# -*- coding: utf-8 -*-
"""Pruebas de ``dml.models.blackscholes`` (BSM generalizado).

Se verifica:

* El caso de manual ``S=100, K=100, T=1, r=0.05, q=0, sigma=0.20``:
  call ~ 10.4506, put ~ 5.5735, delta_call ~ 0.6368.
* La paridad put-call generalizada ``C - P = S e^{(b-r)T} - K e^{-rT}`` con
  error absoluto menor que ``1e-10`` en varios juegos de parametros.
* **Todas** las griegas contra diferencias finitas centradas con error relativo
  menor que ``1e-3`` (el modulo devuelve ese detalle ya calculado).
* El comportamiento con ``K`` igual al forward teorico.
* Parametros invalidos: ``ValueError``.
"""

from __future__ import annotations

import math

import pytest

from dml.models.blackscholes import (
    d1_d2,
    griegas,
    norm_cdf,
    norm_pdf,
    precio_bsm,
    precio_forward,
    verificar_griegas_fd,
    verificar_paridad,
)

# Caso de manual
S, K, T, R, Q, SIGMA = 100.0, 100.0, 1.0, 0.05, 0.0, 0.20
B = R - Q  # costo de mantener
RAIZ_2 = math.sqrt(2.0)

#: Juegos de parametros para las comprobaciones cruzadas
CASOS = [
    (100.0, 100.0, 1.0, 0.05, 0.00, 0.20),
    (100.0, 95.0, 0.75, 0.04, 0.02, 0.35),
    (50.0, 60.0, 2.0, 0.03, 0.01, 0.45),
    (250.0, 200.0, 0.25, 0.06, 0.03, 0.15),
]


# ==========================================================================
# 1. Caso de manual
# ==========================================================================


def test_precio_call_y_put_caso_de_manual():
    """Valores de referencia del modelo de Black-Scholes-Merton."""
    call = precio_bsm(S, K, T, R, Q, B, SIGMA, "call")
    put = precio_bsm(S, K, T, R, Q, B, SIGMA, "put")
    assert call == pytest.approx(10.4506, abs=1e-4)
    assert put == pytest.approx(5.5735, abs=1e-4)
    # Formula explicita con la normal estandar
    d1 = (math.log(S / K) + (B + SIGMA ** 2 / 2.0) * T) / (SIGMA * math.sqrt(T))
    d2 = d1 - SIGMA * math.sqrt(T)
    esperado_call = S * math.exp((B - R) * T) * norm_cdf(d1) - K * math.exp(-R * T) * norm_cdf(d2)
    esperado_put = K * math.exp(-R * T) * norm_cdf(-d2) - S * math.exp((B - R) * T) * norm_cdf(-d1)
    assert call == pytest.approx(esperado_call, rel=1e-12)
    assert put == pytest.approx(esperado_put, rel=1e-12)


def test_d1_d2_caso_de_manual():
    """``d1`` y ``d2`` con la formula del modelo."""
    d1, d2 = d1_d2(S, K, T, B, SIGMA)
    d1_esperado = (math.log(S / K) + (B + SIGMA ** 2 / 2.0) * T) / (SIGMA * math.sqrt(T))
    assert d1 == pytest.approx(d1_esperado, rel=1e-12)
    assert d1 == pytest.approx(0.35, abs=1e-3)
    assert d2 == pytest.approx(d1 - SIGMA * math.sqrt(T), rel=1e-12)


def test_delta_call_caso_de_manual():
    """``delta_call = N(d1)`` ~ 0.6368 en el caso de manual."""
    griegas_call = griegas(S, K, T, R, Q, B, SIGMA, "call")
    d1, _ = d1_d2(S, K, T, B, SIGMA)
    assert griegas_call["delta"] == pytest.approx(norm_cdf(d1), rel=1e-12)
    assert griegas_call["delta"] == pytest.approx(0.6368, abs=1e-4)
    # Sin dividendos la delta de la put es la del call menos 1
    griegas_put = griegas(S, K, T, R, Q, B, SIGMA, "put")
    assert griegas_call["delta"] - griegas_put["delta"] == pytest.approx(1.0, abs=1e-12)


def test_gamma_vega_theta_rho_caso_de_manual():
    """Gamma, vega, theta y rho con sus formulas explicitas."""
    g = griegas(S, K, T, R, Q, B, SIGMA, "call")
    d1, _ = d1_d2(S, K, T, B, SIGMA)
    phi = norm_pdf(d1)
    assert g["gamma"] == pytest.approx(phi / (S * SIGMA * math.sqrt(T)), rel=1e-12)
    assert g["vega"] == pytest.approx(S * phi * math.sqrt(T), rel=1e-12)
    assert g["vega_1pct"] == pytest.approx(g["vega"] / 100.0, rel=1e-12)
    assert g["theta"] < 0.0
    assert g["theta_dia"] == pytest.approx(g["theta"] / 365.0, rel=1e-12)
    assert g["rho"] > 0.0
    assert g["rho_1pct"] == pytest.approx(g["rho"] / 100.0, rel=1e-12)
    assert g["prima"] == pytest.approx(10.4506, abs=1e-4)


def test_gamma_y_vega_iguales_en_call_y_put():
    """Gamma, vega y vomma no dependen del tipo; la vanna tampoco cambia de signo.

    ``vanna = d2P/(dS dsigma)`` es la misma magnitud con el mismo signo para la
    call y la put (lo confirma la diferencia finita mixta que calcula
    :func:`verificar_griegas_fd`).
    """
    call = griegas(S, K, T, R, Q, B, SIGMA, "call")
    put = griegas(S, K, T, R, Q, B, SIGMA, "put")
    assert call["gamma"] == pytest.approx(put["gamma"], rel=1e-12)
    assert call["vega"] == pytest.approx(put["vega"], rel=1e-12)
    assert call["vomma"] == pytest.approx(put["vomma"], rel=1e-12)
    assert call["vanna"] == pytest.approx(put["vanna"], rel=1e-12)
    assert call["vanna"] == pytest.approx(-0.28143026018770345, rel=1e-12)


def test_elasticidad_es_delta_por_spot_entre_prima():
    """``elasticidad = delta * S / prima``."""
    g = griegas(S, K, T, R, Q, B, SIGMA, "call")
    assert g["elasticidad"] == pytest.approx(g["delta"] * S / g["prima"], rel=1e-9)


# ==========================================================================
# 2. Paridad put-call
# ==========================================================================


@pytest.mark.parametrize(("s", "k", "t", "r", "q", "sigma"), CASOS)
def test_paridad_put_call_menor_que_1e_10(s, k, t, r, q, sigma):
    """``C - P = S e^{(b-r)T} - K e^{-rT}`` con error despreciable."""
    b = r - q
    paridad = verificar_paridad(s, k, t, r, q, b, sigma)
    assert paridad["ok"] is True
    assert paridad["diferencia"] == pytest.approx(0.0, abs=1e-10)
    esperado = s * math.exp((b - r) * t) - k * math.exp(-r * t)
    assert paridad["c_p"] == pytest.approx(esperado, rel=1e-12)
    assert paridad["forward_descontado"] == pytest.approx(esperado, rel=1e-12)


def test_paridad_identidad_cerrada():
    """Comprobacion directa de la identidad, sin pasar por el diccionario."""
    s, k, t, r, q, sigma = 100.0, 95.0, 0.75, 0.04, 0.02, 0.35
    b = r - q
    call = precio_bsm(s, k, t, r, q, b, sigma, "call")
    put = precio_bsm(s, k, t, r, q, b, sigma, "put")
    esperado = s * math.exp((b - r) * t) - k * math.exp(-r * t)
    assert (call - put) == pytest.approx(esperado, abs=1e-10)
    assert esperado == pytest.approx(6.318868273197978, rel=1e-12)


def test_paridad_con_costo_de_mantenimiento_nulo():
    """Opcion sobre futuro (``b = 0``): la paridad sigue cumpliendose."""
    paridad = verificar_paridad(100.0, 100.0, 1.0, 0.05, 0.0, 0.0, 0.25)
    assert paridad["ok"] is True
    assert paridad["diferencia"] == pytest.approx(0.0, abs=1e-10)
    # Con b = 0 la call y la put sobre el forward valen lo mismo si K = F
    assert paridad["call"] == pytest.approx(paridad["put"], rel=1e-9)


def test_paridad_exige_sigma_positivo():
    """``sigma = 0`` no es un parametro valido del modelo: ``ValueError``."""
    with pytest.raises(ValueError):
        verificar_paridad(100.0, 100.0, 1.0, 0.05, 0.0, 0.05, 0.0)
    with pytest.raises(ValueError):
        precio_bsm(100.0, 100.0, 1.0, 0.05, 0.0, 0.05, 0.0, "call")


# ==========================================================================
# 3. Griegas contra diferencias finitas
# ==========================================================================


@pytest.mark.parametrize(("s", "k", "t", "r", "q", "sigma"), CASOS)
@pytest.mark.parametrize("tipo", ["call", "put"])
def test_griegas_contra_diferencias_finitas(s, k, t, r, q, sigma, tipo):
    """Todas las griegas dentro de 1e-3 de error relativo (salvo sigma = 0)."""
    if sigma <= 0.0:
        pytest.skip("con sigma = 0 no hay griegas que contrastar por diferencias finitas")
    b = r - q
    control = verificar_griegas_fd(s, k, t, r, q, b, sigma, tipo, tolerancia=1e-3)
    assert control["ok"] is True, control["detalle"]
    esperadas = {"delta", "gamma", "vega", "theta", "rho", "sensibilidad_b", "vanna", "vomma"}
    assert esperadas <= set(control["detalle"])
    for nombre, datos in control["detalle"].items():
        assert datos["ok"] is True, f"{nombre}: {datos}"
        assert datos["error_relativo"] <= 1e-3, f"{nombre} fuera de tolerancia: {datos}"


def test_griegas_diferencia_finita_manual_de_delta():
    """Contraste independiente de la delta con una diferencia centrada simple."""
    h = S * 1e-5
    numerico = (precio_bsm(S + h, K, T, R, Q, B, SIGMA, "call")
                - precio_bsm(S - h, K, T, R, Q, B, SIGMA, "call")) / (2.0 * h)
    analitico = griegas(S, K, T, R, Q, B, SIGMA, "call")["delta"]
    assert analitico == pytest.approx(numerico, rel=1e-5)


def test_sensibilidad_b_es_la_derivada_de_la_prima():
    """``dP/db = T x (prima del activo subyacente)`` con el signo de cada tipo.

    Para la call es ``T S e^{(b-r)T} N(d1)`` y para la put ``-T S e^{(b-r)T} N(-d1)``.
    """
    call = griegas(S, K, T, R, Q, B, SIGMA, "call")
    put = griegas(S, K, T, R, Q, B, SIGMA, "put")
    d1, _ = d1_d2(S, K, T, B, SIGMA)
    factor = math.exp((B - R) * T)
    assert call["sensibilidad_b"] == pytest.approx(T * S * factor * norm_cdf(d1), rel=1e-12)
    assert put["sensibilidad_b"] == pytest.approx(-T * S * factor * norm_cdf(-d1), rel=1e-12)
    assert call["sensibilidad_b"] > 0.0
    assert put["sensibilidad_b"] < 0.0
    # Nota: el docstring del modulo escribe ``T * prima``; con b != r la derivada
    # real es la del activo subyacente que se comprueba arriba.
    assert abs(call["sensibilidad_b"]) > abs(T * call["prima"])


# ==========================================================================
# 4. Forward
# ==========================================================================


def test_precio_forward_sin_costo_de_mantenimiento():
    """``S e^{bT}`` con ``b = 0`` es el propio spot."""
    assert precio_forward(100.0, 0.0, 1.0) == pytest.approx(100.0, rel=1e-12)


def test_precio_forward_con_tasa_y_dividendo():
    """``S e^{bT}`` con ``b = r - q``."""
    assert precio_forward(100.0, 0.05, 1.0) == pytest.approx(100.0 * math.exp(0.05), rel=1e-12)
    assert precio_forward(100.0, 0.05 - 0.02, 0.5) == pytest.approx(100.0 * math.exp(0.015), rel=1e-12)


def test_k_igual_al_forward_reproduce_el_valor_intrinseco_descontado():
    """Con ``K = Forward`` la call vale ``S f (N(d1) - N(d2))``."""
    b = R - Q
    forward = precio_forward(S, b, T)
    d1, d2 = d1_d2(S, forward, T, b, SIGMA)
    esperado = S * math.exp((b - R) * T) * (norm_cdf(d1) - norm_cdf(d2))
    assert precio_bsm(S, forward, T, R, Q, b, SIGMA, "call") == pytest.approx(esperado, rel=1e-12)

    paridad = verificar_paridad(S, forward, T, R, Q, b, SIGMA)
    assert paridad["ok"] is True
    assert paridad["forward_descontado"] == pytest.approx(
        S * math.exp((b - R) * T) - forward * math.exp(-R * T), rel=1e-12
    )


def test_precio_forward_con_parametros_no_convertibles():
    """Entradas no numericas no rompen la funcion.

    ``None`` y el texto no numerico se tratan como 0 por ``_finito`` (documentado
    en el modulo: ``precio_forward`` nunca lanza por datos ausentes).
    """
    assert precio_forward(None, 0.05, 1.0) == pytest.approx(0.0, abs=1e-12)
    assert precio_forward("abc", 0.05, 1.0) == pytest.approx(0.0, abs=1e-12)


# ==========================================================================
# 5. Parametros invalidos
# ==========================================================================


@pytest.mark.parametrize(
    ("s", "k", "t", "sigma"),
    [
        (0.0, 100.0, 1.0, 0.2),      # S = 0
        (-100.0, 100.0, 1.0, 0.2),   # S < 0
        (100.0, 0.0, 1.0, 0.2),      # K = 0
        (100.0, -50.0, 1.0, 0.2),    # K < 0
        (100.0, 100.0, 0.0, 0.2),    # T = 0
        (100.0, 100.0, -1.0, 0.2),   # T < 0
        (100.0, 100.0, 1.0, 0.0),    # sigma = 0
        (100.0, 100.0, 1.0, -0.2),   # sigma < 0
    ],
)
def test_d1_d2_parametros_invalidos(s, k, t, sigma):
    """``d1_d2`` exige ``S>0, K>0, T>0, sigma>0``."""
    with pytest.raises(ValueError):
        d1_d2(s, k, t, B, sigma)


@pytest.mark.parametrize("tipo", ["call", "put"])
def test_precio_y_griegas_propagan_el_valueerror(tipo):
    """``precio_bsm`` y ``griegas`` rechazan los mismos parametros invalidos."""
    with pytest.raises(ValueError):
        precio_bsm(100.0, 100.0, 0.0, R, Q, B, SIGMA, tipo)
    with pytest.raises(ValueError):
        griegas(100.0, 100.0, 1.0, R, Q, B, -0.1, tipo)


def test_tipo_de_opcion_desconocido_se_trata_como_put():
    """Cualquier ``tipo`` distinto de ``call`` se evalua como put."""
    assert precio_bsm(S, K, T, R, Q, B, SIGMA, "PUT") == pytest.approx(
        precio_bsm(S, K, T, R, Q, B, SIGMA, "put"), rel=1e-12
    )
    assert precio_bsm(S, K, T, R, Q, B, SIGMA, "otro") == pytest.approx(
        precio_bsm(S, K, T, R, Q, B, SIGMA, "put"), rel=1e-12
    )
