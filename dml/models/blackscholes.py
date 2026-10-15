# -*- coding: utf-8 -*-
"""Black-Scholes-Merton generalizado (con costo de mantener ``b``), griegas y verificaciones.

Modelo
------
Sea ``S`` el spot, ``K`` el strike, ``T`` el vencimiento en anios, ``r`` la tasa
libre de riesgo, ``q`` el dividend yield y ``sigma`` la volatilidad **anual**.
El costo de mantener es ``b = r - q`` (para una opcion sobre un futuro
``b = 0``; sobre una divisa ``b = r - r_f``). Con ``f = e^{(b - r)T}``:

* ``d1 = [ln(S/K) + (b + sigma^2/2) T] / (sigma sqrt(T))``, ``d2 = d1 - sigma sqrt(T)``
* ``Forward = S e^{bT}``
* ``Call = S f N(d1) - K e^{-rT} N(d2)``
* ``Put  = K e^{-rT} N(-d2) - S f N(-d1)``

Todas las griegas usan el factor ``f = e^{(b-r)T}`` multiplicando al termino de
spot y la tasa ``r`` (no ``b``) al descontar el strike. La prima de la *put*
descuenta con ``r`` y **no** con ``b`` (el libro de referencia de Excel
descuenta el spot de la put con ``e^{-rT}``, lo que rompe la paridad; aqui se usa
el estandar).

Convenciones de las griegas
---------------------------
Sea ``P`` la prima (call o put) y ``phi = phi(d1)`` la densidad normal estandar.

* ``Delta   = dP/dS``
* ``Gamma   = d2P/dS2 = f phi / (S sigma sqrt(T))``
* ``Vega    = dP/dsigma = S f phi sqrt(T)`` (misma para call y put)
* ``Theta   = dP/dt`` con ``t`` el **tiempo de calendario** (el que avanza), por
  lo que ``Theta = - dP/dT``; se devuelve **por anio** y ademas ``theta_dia = theta/365``.
* ``Rho     = dP/dr`` manteniendo **q constante**, es decir moviendo ``r`` y ``b``
  a la vez (``b = r - q``). Es la convencion que usa la comprobacion por
  diferencias finitas de :func:`verificar_griegas_fd`.
* ``Elasticidad`` (lambda) ``= Delta * S / P``; ``None`` si la prima es 0 o la
  opcion no vale nada.
* ``Vanna   = d2P/(dS dsigma) = dDelta/dsigma``; con ``Vega = S f phi sqrt(T)``
  y ``d1`` derivable respecto de ``sigma`` (``dd1/dsigma = -d2/sigma``):

  ``Vanna = f phi sqrt(T) [1 - d1 / (sigma sqrt(T))]``
         ``= (Vega / S) [1 - d1 / (sigma sqrt(T))]``
         ``= -f phi d2 / sigma``

  **misma para el call y para la put**: la paridad put-call
  ``C - P = S e^{(b-r)T} - K e^{-rT}`` tiene lado derecho independiente de ``S`` y
  de ``sigma``, luego ``d2C/(dS dsigma) = d2P/(dS dsigma)``. (El prototipo
  cambiaba el signo en la put; la diferencia finita de segundo orden lo desmiente.)
* ``Vomma  = d2P/dsigma2 = dVega/dsigma = Vega * d1 * d2 / sigma``
  (misma para call y put). El prototipo usaba ``vega * d1 * d2 / sigma``, que es
  esta misma expresion: se conserva y se verifica con una segunda diferencia
  finita de vega.
* ``Sensibilidad_b = dP/db = T S f N(d1) = T Delta S`` para el call y
  ``= -T S f N(-d1) = T Delta_put S`` para la put. (El prototipo devolvia ``T P``,
  que omite la dependencia de ``f = e^{(b-r)T}`` respecto de ``b`` y por tanto no
  coincide con la derivada; la verificacion por diferencias finitas lo confirma.)

El modulo degrada con elegancia si ``scipy`` no esta disponible (usa ``erf`` de
la libreria estandar) y nunca usa ``except:`` desnudo.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from ..core.util import a_float

LOG = logging.getLogger("dml.blackscholes")

__all__ = [
    "norm_cdf",
    "norm_pdf",
    "d1_d2",
    "precio_forward",
    "precio_bsm",
    "griegas",
    "verificar_paridad",
    "verificar_griegas_fd",
    "td1_ds",
    "prima_vs_spot",
]

try:  # pragma: no cover - depende del entorno
    from scipy.stats import norm as _scipy_norm

    _SCIPY_OK = True
except Exception as _exc:  # pragma: no cover - solo si falta scipy
    LOG.warning("scipy no disponible (%s): se usan las funciones de la libreria estandar", _exc)
    _scipy_norm = None
    _SCIPY_OK = False

#: |sigma*sqrt(T)| por debajo del cual se usan las formas limite (sigma o T -> 0+).
_EPS_SIGMA_T = 1e-8
#: Denominadores relativos por debajo de los cuales se prefiere devolver None.
_EPS_DIV = 1e-300
_SQRT_2 = math.sqrt(2.0)
_SQRT_2PI = math.sqrt(2.0 * math.pi)
_SIGMA_FD_REL = 1e-3
_EXP_MAX = 700.0  # math.log(sys.float_info.max) ~ 709.78


# --------------------------------------------------------------------------- #
# Utilidades numericas internas
# --------------------------------------------------------------------------- #
def _finito(valor: Any, alterno: Optional[float] = 0.0) -> Optional[float]:
    """Devuelve ``valor`` como ``float`` finito o ``alterno`` si no es utilizable."""
    f = a_float(valor)
    return alterno if f is None else f


def _exp_seguro(x: float) -> float:
    """``e^x`` sin desbordar: devuelve ``inf``/``0.0`` en lugar de lanzar error."""
    if math.isnan(x):
        return float("nan")
    if x > _EXP_MAX:
        return float("inf")
    if x < -_EXP_MAX:
        return 0.0
    try:
        return math.exp(x)
    except OverflowError:  # pragma: no cover - proteccion defensiva
        return float("inf") if x > 0 else 0.0


def _exp_producto(a: float, x: float) -> float:
    """``a * e^x`` resolviendo el caso limite ``0 * inf`` (que debe ser 0)."""
    if a == 0.0:
        return 0.0
    e = _exp_seguro(x)
    if math.isinf(e):
        return math.copysign(float("inf"), a)
    return a * e


def _norm_cdf_np(x: Any) -> Any:
    """CDF normal estandar vectorizada.

    Usa ``scipy.stats.norm.cdf`` cuando esta disponible; si no, recurre a la
    ``erf`` vectorizada de numpy (sin bucles de Python).
    """
    if _SCIPY_OK and _scipy_norm is not None:
        return _scipy_norm.cdf(x)
    xa = np.asarray(x, dtype=float)
    return 0.5 * (1.0 + np.vectorize(math.erf)(xa / _SQRT_2))


def _cdf_segura_np(x: Any) -> Any:
    """CDF vectorizada tolerante a ``inf``/``NaN`` sin desbordar en ``erf``."""
    xa = np.asarray(x, dtype=float)
    finito = np.isfinite(xa)
    x_clip = np.clip(np.where(finito, xa, 0.0), -40.0, 40.0)
    cdf = np.asarray(_norm_cdf_np(x_clip), dtype=float)
    limite = np.where(xa > 0.0, 1.0, 0.0)
    return np.where(finito, cdf, limite)


def _phi_sobre_sigma(d1: float, raiz_t: float, sigma: float) -> float:
    """``phi(d1) / (sigma sqrt(T))``, factor de ``Gamma``, sin ``0/0``.

    ``Gamma = f phi(d1) / (S sigma sqrt(T))``. El exponente se calcula como
    ``-(d1^2)/2`` con ``d1^2/sqrt(2)`` para que ``math.exp`` no desborde ni
    produzca ``0/0`` cuando ``sigma sqrt(T) -> 0`` (el limite es 0 porque
    ``phi(d1) -> 0`` mucho mas rapido que ``1/(sigma sqrt(T)) -> inf``).
    """
    sig_t = sigma * raiz_t
    if sig_t <= 0.0:
        return 0.0
    if math.isnan(d1):
        return 0.0
    if math.isinf(d1):
        return 0.0
    z = d1 / _SQRT_2
    return math.exp(-z * z) / (sig_t * _SQRT_2PI)


def _prima_call(d1: float, d2: float, S: float, desc_k: float, factor: float) -> float:
    """``S f N(d1) - K e^{-rT} N(d2)``."""
    return S * factor * norm_cdf(d1) - desc_k * norm_cdf(d2)


def _prima_put(d1: float, d2: float, S: float, desc_k: float, factor: float) -> float:
    """``K e^{-rT} N(-d2) - S f N(-d1)``."""
    return desc_k * norm_cdf(-d2) - S * factor * norm_cdf(-d1)


def _prima_limite(tipo: str, S: float, desc_k: float, factor: float) -> float:
    """Prima en el limite ``sigma sqrt(T) -> 0`` (payoff determinista descontado)."""
    if tipo.lower() == "call":
        return max(S * factor - desc_k, 0.0)
    return max(desc_k - S * factor, 0.0)


# --------------------------------------------------------------------------- #
# Distribucion normal estandar
# --------------------------------------------------------------------------- #
def norm_cdf(x: float) -> float:
    """CDF de la normal estandar ``N(x)``.

    Usa ``scipy.stats.norm.cdf`` si esta disponible y, en su defecto,
    ``math.erf``. Nunca lanza excepciones: ``-inf -> 0``, ``inf -> 1``.
    """
    x = float(x)
    if math.isnan(x):
        return float("nan")
    if math.isinf(x):
        return 1.0 if x > 0 else 0.0
    if _SCIPY_OK and _scipy_norm is not None:
        try:
            return float(_scipy_norm.cdf(x))
        except Exception as exc:  # pragma: no cover - proteccion defensiva
            LOG.debug("scipy.stats.norm.cdf fallo (%s): se usa erf", exc)
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def norm_pdf(x: float) -> float:
    """Densidad de la normal estandar ``phi(x)`` (nunca lanza excepciones)."""
    x = float(x)
    if math.isnan(x):
        return float("nan")
    if math.isinf(x):
        return 0.0
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# --------------------------------------------------------------------------- #
# Parametros y precios
# --------------------------------------------------------------------------- #
def d1_d2(S: float, K: float, T: float, b: float, sigma: float) -> Tuple[float, float]:
    """Calcula ``(d1, d2)`` del BSM generalizado con costo de mantener ``b``.

    Args:
        S: precio del subyacente (``S > 0``).
        K: strike (``K > 0``).
        T: vencimiento en anios (``T > 0``).
        b: costo de mantener, ``b = r - q``.
        sigma: volatilidad anual (``sigma > 0``).

    Returns:
        Tupla ``(d1, d2)`` con ``d2 = d1 - sigma sqrt(T)``.

    Raises:
        ValueError: si ``S <= 0``, ``K <= 0``, ``T <= 0`` o ``sigma <= 0``.
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise ValueError(
            "Parametros invalidos en BSM: se requiere S>0, K>0, T>0 y sigma>0 "
            f"(recibido S={S}, K={K}, T={T}, sigma={sigma})"
        )
    log_sk = math.log(S / K)
    if not math.isfinite(log_sk):
        log_sk = math.copysign(_EXP_MAX, log_sk)
    raiz_t = math.sqrt(T)
    sig_t = sigma * raiz_t
    if sig_t > 0.0:
        numerador = log_sk + (b + 0.5 * sigma * sigma) * T
        d1 = numerador / sig_t
        return d1, d1 - sig_t
    # Limite sigma sqrt(T) -> 0: d1, d2 -> +-inf segun sign(ln(S/K) + bT).
    try:
        deriva = (b + 0.5 * sigma * sigma) * T
    except OverflowError:  # pragma: no cover - proteccion defensiva
        deriva = math.copysign(float("inf"), b)
    signo = math.copysign(1.0, log_sk + deriva) if (log_sk + deriva) != 0.0 else -1.0
    return (signo * float("inf"), signo * float("inf"))


def precio_forward(S: float, b: float, T: float) -> float:
    """Precio forward teorico ``S e^{bT}``.

    Args:
        S: precio del subyacente.
        b: costo de mantener, ``b = r - q``.
        T: vencimiento en anios.

    Returns:
        Forward teorico. Devuelve ``inf`` (no lanza) si ``bT`` desborda.
    """
    s = _finito(S)
    bb = _finito(b)
    t = _finito(T)
    if s is None or bb is None or t is None:
        raise ValueError("precio_forward requiere S, b y T numericos y finitos")
    return _exp_producto(s, bb * t)


def precio_bsm(
    S: float, K: float, T: float, r: float, q: float, b: float, sigma: float, tipo: str = "call"
) -> float:
    """Prima de una opcion europea con el BSM generalizado.

    ``Call = S e^{(b-r)T} N(d1) - K e^{-rT} N(d2)``
    ``Put  = K e^{-rT} N(-d2) - S e^{(b-r)T} N(-d1)``

    La put descuenta el strike con ``r`` y el spot con ``e^{(b-r)T}``; nunca con
    ``e^{-rT}`` (error del prototipo/libro de referencia).

    Args:
        S: precio del subyacente.
        K: strike.
        T: vencimiento en anios.
        r: tasa libre de riesgo.
        q: dividend yield (informativo: se usa a traves de ``b``).
        b: costo de mantener, habitualmente ``r - q``.
        sigma: volatilidad anual.
        tipo: ``"call"`` o ``"put"``.

    Returns:
        Prima de la opcion.

    Raises:
        ValueError: si ``S<=0``, ``K<=0``, ``T<=0`` o ``sigma<=0``.
    """
    tipo_norm = str(tipo).strip().lower()
    d1, d2 = d1_d2(S, K, T, b, sigma)
    factor = _exp_seguro((b - r) * T)
    desc_k = K * _exp_seguro(-r * T)
    if not math.isfinite(d1):
        return _prima_limite(tipo_norm, S, desc_k, factor)
    if tipo_norm == "call":
        return _prima_call(d1, d2, S, desc_k, factor)
    return _prima_put(d1, d2, S, desc_k, factor)


# --------------------------------------------------------------------------- #
# Griegas
# --------------------------------------------------------------------------- #
def griegas(
    S: float, K: float, T: float, r: float, q: float, b: float, sigma: float, tipo: str = "call"
) -> Dict[str, Optional[float]]:
    """Griegas completas del BSM generalizado para call y put.

    Devuelve el diccionario con las claves ``prima, d1, d2, delta, gamma, vega,
    vega_1pct, theta, theta_dia, rho, rho_1pct, elasticidad, vanna, vomma,
    sensibilidad_b, factor_e_b_r_t``.

    Formulas (``f = e^{(b-r)T}``, ``phi = phi(d1)``, misma ``sigma`` para call y put):

    * ``delta = f N(d1)`` (call) / ``-f N(-d1)`` (put)
    * ``gamma = f phi / (S sigma sqrt(T))``
    * ``vega  = S f phi sqrt(T)``
    * ``vanna = f phi sqrt(T) [1 - d1/(sigma sqrt(T))] = (vega/S)[1 - d1/(sigma sqrt(T))]``
      (misma para call y put: ``dd1/dsigma = -d2/sigma`` y la paridad put-call
      tiene lado derecho independiente de ``S`` y ``sigma``)
    * ``vomma = vega * d1 * d2 / sigma``
    * ``theta = -dP/dT`` (por anio; ``theta_dia = theta/365``)
    * ``rho   = dP/dr`` con ``q`` constante (se mueven ``r`` y ``b`` juntos)
    * ``sensibilidad_b = dP/db = T S f N(d1) = T delta S`` (call) /
      ``-T S f N(-d1) = T delta_put S`` (put)
    * ``elasticidad = delta * S / prima`` o ``None`` si la prima es 0

    Args:
        S: precio del subyacente.
        K: strike.
        T: vencimiento en anios.
        r: tasa libre de riesgo.
        q: dividend yield (``b = r - q``; solo se usa a traves de ``b``).
        b: costo de mantener.
        sigma: volatilidad anual.
        tipo: ``"call"`` o ``"put"``.

    Returns:
        Diccionario de griegas. ``elasticidad`` puede ser ``None``.

    Raises:
        ValueError: si ``S<=0``, ``K<=0``, ``T<=0`` o ``sigma<=0``.
    """
    tipo_norm = str(tipo).strip().lower()
    es_call = tipo_norm == "call"
    d1, d2 = d1_d2(S, K, T, b, sigma)
    factor = _exp_seguro((b - r) * T)
    desc_k = K * _exp_seguro(-r * T)
    raiz_t = math.sqrt(T)
    sig_t = sigma * raiz_t
    phi = norm_pdf(d1) if math.isfinite(d1) else 0.0

    salida: Dict[str, Optional[float]] = {
        "prima": None,
        "d1": _finito(d1, None),
        "d2": _finito(d2, None),
        "delta": 0.0,
        "gamma": 0.0,
        "vega": 0.0,
        "vega_1pct": 0.0,
        "theta": 0.0,
        "theta_dia": 0.0,
        "rho": 0.0,
        "rho_1pct": 0.0,
        "elasticidad": None,
        "vanna": 0.0,
        "vomma": 0.0,
        "sensibilidad_b": 0.0,
        "factor_e_b_r_t": _finito(factor, None),
    }

    if sig_t <= _EPS_SIGMA_T:
        # Limite sigma sqrt(T) -> 0: la opcion es determinista.
        dentro = (S * factor - desc_k) > 0.0
        prima = _prima_limite(tipo_norm, S, desc_k, factor)
        if es_call:
            delta = factor if dentro else 0.0
            rho = T * desc_k * (0.0 if dentro else 1.0)
            sens_b = T * S * delta
        else:
            delta = -factor if not dentro else 0.0
            rho = -T * desc_k * (1.0 if dentro else 0.0)
            sens_b = T * S * delta
        salida.update(
            {
                "prima": _finito(prima),
                "delta": _finito(delta),
                "gamma": 0.0,
                "vega": 0.0,
                "vega_1pct": 0.0,
                "theta": 0.0,
                "theta_dia": 0.0,
                "rho": _finito(rho),
                "rho_1pct": _finito(rho / 100.0),
                "vanna": 0.0,
                "vomma": 0.0,
                "sensibilidad_b": _finito(sens_b),
            }
        )
        if prima != 0.0:
            salida["elasticidad"] = _finito(delta * S / prima, None)
        return salida

    # --- camino general -----------------------------------------------------
    phi_sigma = _phi_sobre_sigma(d1, raiz_t, sigma)
    gamma = _finito(factor * phi_sigma / S)
    vega = _finito(S * factor * phi * raiz_t)
    vanna = _finito(factor * phi * raiz_t * (1.0 - d1 / sig_t))
    vomma = _finito(vega * d1 * d2 / sigma)
    nd1 = norm_cdf(d1)
    nd2 = norm_cdf(d2)
    descuento_spot = S * factor

    if es_call:
        prima = descuento_spot * nd1 - desc_k * nd2
        delta = factor * nd1
        theta = (
            -S * factor * phi * sigma / (2.0 * raiz_t)
            - (b - r) * descuento_spot * nd1
            - r * desc_k * nd2
        )
        rho = T * desc_k * nd2
        sens_b = T * S * delta
    else:
        prima = desc_k * norm_cdf(-d2) - descuento_spot * norm_cdf(-d1)
        delta = -factor * norm_cdf(-d1)
        theta = (
            -S * factor * phi * sigma / (2.0 * raiz_t)
            + (b - r) * descuento_spot * norm_cdf(-d1)
            + r * desc_k * norm_cdf(-d2)
        )
        rho = -T * desc_k * norm_cdf(-d2)
        sens_b = T * S * delta

    salida.update(
        {
            "prima": _finito(prima),
            "delta": _finito(delta),
            "gamma": gamma,
            "vega": vega,
            "vega_1pct": _finito(vega / 100.0),
            "theta": _finito(theta),
            "theta_dia": _finito(theta / 365.0),
            "rho": _finito(rho),
            "rho_1pct": _finito(rho / 100.0),
            "vanna": vanna,
            "vomma": vomma,
            "sensibilidad_b": _finito(sens_b),
        }
    )
    prima_f = a_float(prima)
    if prima_f is None or abs(prima_f) <= _EPS_DIV:
        salida["elasticidad"] = None
    else:
        lambda_ = delta * S / prima_f
        salida["elasticidad"] = _finito(lambda_, None)
    return salida


# --------------------------------------------------------------------------- #
# Verificaciones
# --------------------------------------------------------------------------- #
def verificar_paridad(
    S: float, K: float, T: float, r: float, q: float, b: float, sigma: float, tolerancia: float = 1e-6
) -> Dict[str, Any]:
    """Comprueba la paridad put-call generalizada.

    ``C - P = S e^{(b-r)T} - K e^{-rT}``

    Args:
        S, K, T, r, q, b, sigma: parametros del modelo.
        tolerancia: tolerancia absoluta (se admite tambien el error relativo).

    Returns:
        Diccionario con ``call, put, c_p, forward_descontado, diferencia,
        tolerancia, ok``.
    """
    call = precio_bsm(S, K, T, r, q, b, sigma, "call")
    put = precio_bsm(S, K, T, r, q, b, sigma, "put")
    izquierda = call - put
    derecha = S * _exp_seguro((b - r) * T) - K * _exp_seguro(-r * T)
    diferencia = izquierda - derecha
    umbral = tolerancia * max(1.0, abs(derecha))
    return {
        "call": call,
        "put": put,
        "c_p": izquierda,
        "forward_descontado": derecha,
        "diferencia": diferencia,
        "tolerancia": tolerancia,
        "ok": abs(diferencia) <= umbral,
    }


def _error_relativo(analitico: Optional[float], numerico: Optional[float]) -> Tuple[float, bool]:
    """Error relativo (o absoluto si ambos valores son despreciables)."""
    if analitico is None or numerico is None:
        return (float("inf"), False)
    escala = max(abs(analitico), abs(numerico), 1e-12)
    return (abs(analitico - numerico) / escala, True)


def verificar_griegas_fd(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    b: float,
    sigma: float,
    tipo: str = "call",
    tolerancia: float = 1e-3,
) -> Dict[str, Any]:
    """Contrasta las griegas analiticas con diferencias finitas centradas.

    Convenciones de las diferencias finitas:

    * ``delta``, ``gamma``: respecto de ``S``.
    * ``vega``: respecto de ``sigma``.
    * ``theta``: ``- dP/dT`` (derivada respecto del tiempo de calendario).
    * ``rho``: se mueven ``r`` y ``b`` a la vez (``q`` constante, ``b = r - q``).
    * ``sensibilidad_b``: respecto de ``b``.
    * ``vanna``: diferencia finita de segundo orden mixta ``d2P/(dS dsigma)``.
    * ``vomma``: segunda diferencia finita respecto de ``sigma`` (``d2P/dsigma2``).

    Args:
        S, K, T, r, q, b, sigma: parametros del modelo.
        tipo: ``"call"`` o ``"put"``.
        tolerancia: tolerancia del error relativo.

    Returns:
        ``{"detalle": {griega: {"analitico", "diferencias_finitas",
        "error_relativo", "ok"}}, "tolerancia": ..., "ok": ...}``.
    """
    h_rel = 1e-5
    h_s = S * h_rel
    h_sig = sigma * _SIGMA_FD_REL
    h_t = max(T * h_rel, 1e-8)
    h_r = max(abs(r) * h_rel, 1e-5)
    h_b = max(abs(b) * h_rel, 1e-4)

    def precio(**kw: float) -> float:
        p = {"S": S, "K": K, "T": T, "r": r, "q": q, "b": b, "sigma": sigma}
        p.update(kw)
        return precio_bsm(p["S"], p["K"], p["T"], p["r"], p["q"], p["b"], p["sigma"], tipo)

    g = griegas(S, K, T, r, q, b, sigma, tipo)

    pruebas: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    pruebas["delta"] = (g["delta"], (precio(S=S + h_s) - precio(S=S - h_s)) / (2.0 * h_s))
    pruebas["gamma"] = (g["gamma"], (precio(S=S + h_s) - 2.0 * precio() + precio(S=S - h_s)) / (h_s * h_s))
    pruebas["vega"] = (g["vega"], (precio(sigma=sigma + h_sig) - precio(sigma=sigma - h_sig)) / (2.0 * h_sig))
    pruebas["theta"] = (
        g["theta"],
        -((precio(T=T + h_t) - precio(T=T - h_t)) / (2.0 * h_t)) if T > h_t else -((precio(T=T + h_t) - precio()) / h_t),
    )
    pruebas["rho"] = (
        g["rho"],
        (
            precio_bsm(S, K, T, r + h_r, q, b + h_r, sigma, tipo)
            - precio_bsm(S, K, T, r - h_r, q, b - h_r, sigma, tipo)
        )
        / (2.0 * h_r),
    )
    pruebas["sensibilidad_b"] = (g["sensibilidad_b"], (precio(b=b + h_b) - precio(b=b - h_b)) / (2.0 * h_b))
    # Segundo orden: vanna = d2P/(dS dsigma) con dos diferencias centradas simples.
    pruebas["vanna"] = (
        g["vanna"],
        (precio(S=S + h_s, sigma=sigma + h_sig) - precio(S=S + h_s, sigma=sigma - h_sig)
         - precio(S=S - h_s, sigma=sigma + h_sig) + precio(S=S - h_s, sigma=sigma - h_sig))
        / (4.0 * h_s * h_sig),
    )
    # Vomma: segunda diferencia respecto de sigma (equivalente a dVega/dsigma).
    pruebas["vomma"] = (
        g["vomma"],
        (precio(sigma=sigma + h_sig) - 2.0 * precio() + precio(sigma=sigma - h_sig)) / (h_sig * h_sig),
    )
    LOG.debug(
        "verificacion griegas FD tipo=%s: vega=%.6g, vega_fd=%.6g, vomma=%.6g, vomma_2a_dif=%.6g",
        tipo,
        a_float(g["vega"]) or 0.0,
        a_float(pruebas["vega"][1]) or 0.0,
        a_float(g["vomma"]) or 0.0,
        a_float(pruebas["vomma"][1]) or 0.0,
    )

    detalle: Dict[str, Any] = {}
    todo_ok = True
    for nombre, (analitico, numerico) in pruebas.items():
        error, comparable = _error_relativo(analitico, numerico)
        escala = max(abs(analitico or 0.0), 1e-8)
        diff = abs((analitico or 0.0) - (numerico or 0.0))
        ok = comparable and (error <= tolerancia or diff <= 1e-8 * escala)
        todo_ok = todo_ok and ok
        detalle[nombre] = {
            "analitico": analitico,
            "diferencias_finitas": numerico,
            "error_relativo": error,
            "ok": ok,
        }
    return {"detalle": detalle, "tolerancia": tolerancia, "ok": todo_ok}


# --------------------------------------------------------------------------- #
# Utilidades para la interfaz
# --------------------------------------------------------------------------- #
def td1_ds(tipo: str = "call") -> Callable[[float], float]:
    """Devuelve ``Delta`` como funcion del spot ``S`` (para graficar Delta vs S).

    Args:
        tipo: ``"call"`` o ``"put"``.

    Returns:
        ``f(S, K, T, r, q, b, sigma) -> delta``, con ``S`` posicional y el resto
        por palabra clave.

    Example:
        >>> curva = td1_ds("call")
        >>> curva(100.0, K=100.0, T=1.0, r=0.05, q=0.0, b=0.05, sigma=0.2)
        0.6368...
    """
    tipo_norm = str(tipo).strip().lower()

    def delta_vs_spot(S: float, K: float, T: float, r: float, q: float, b: float, sigma: float) -> float:
        """Delta de la opcion para un spot dado (resto de parametros fijos)."""
        valor = griegas(S, K, T, r, q, b, sigma, tipo_norm)["delta"]
        return a_float(valor) or 0.0

    return delta_vs_spot


def prima_vs_spot(
    S_min: float,
    S_max: float,
    n: int,
    K: float,
    T: float,
    r: float,
    q: float,
    b: float,
    sigma: float,
    tipo: str = "call",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rejilla de primas y deltas frente al spot para el grafico de la interfaz.

    Totalmente vectorizado con ``numpy`` + ``scipy.stats.norm`` (o ``erf``
    vectorizado si falta scipy): no hay ningun bucle de Python.

    Args:
        S_min: spot minimo (``> 0``).
        S_max: spot maximo (``> S_min``).
        n: numero de puntos de la rejilla (``>= 2``).
        K, T, r, q, b, sigma: parametros del modelo.
        tipo: ``"call"`` o ``"put"``.

    Returns:
        ``(spots, primas, deltas)``, tres ``numpy.ndarray`` de longitud ``n``.

    Raises:
        ValueError: si los parametros no permiten construir la rejilla
            (``S_min <= 0``, ``S_max <= S_min``, ``n < 2``, ``K <= 0``,
            ``T <= 0``, ``sigma <= 0``).
    """
    s_min = a_float(S_min)
    s_max = a_float(S_max)
    k_f = a_float(K)
    t_f = a_float(T)
    r_f = a_float(r)
    q_f = a_float(q)
    b_f = a_float(b)
    sigma_f = a_float(sigma)
    if s_min is None or s_max is None or k_f is None or t_f is None:
        raise ValueError("prima_vs_spot requiere S_min, S_max, K y T numericos y finitos")
    if r_f is None or q_f is None or b_f is None or sigma_f is None:
        raise ValueError("prima_vs_spot requiere r, q, b y sigma numericos y finitos")
    if s_min <= 0 or s_max <= s_min or int(n) < 2 or k_f <= 0 or t_f <= 0 or sigma_f <= 0:
        raise ValueError(
            "prima_vs_spot requiere S_min>0, S_max>S_min, n>=2, K>0, T>0 y sigma>0 "
            f"(recibido S_min={s_min}, S_max={s_max}, n={n}, K={k_f}, T={t_f}, sigma={sigma_f})"
        )

    es_call = str(tipo).strip().lower() == "call"
    spots = np.linspace(float(s_min), float(s_max), int(n), dtype=float)
    raiz_t = math.sqrt(float(t_f))
    factor = _exp_seguro((float(b_f) - float(r_f)) * float(t_f))
    desc_k = float(k_f) * _exp_seguro(-float(r_f) * float(t_f))
    sig_t = float(sigma_f) * raiz_t

    log_sk = np.log(spots / float(k_f))
    deriva = (float(b_f) + 0.5 * float(sigma_f) ** 2) * float(t_f)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        d1 = (log_sk + deriva) / sig_t
        d2 = d1 - sig_t
        if sig_t > _EPS_SIGMA_T:
            nd1 = _cdf_segura_np(d1)
            nd2 = _cdf_segura_np(d2)
        else:
            nd1 = (log_sk + deriva > 0.0).astype(float)
            nd2 = nd1
        if es_call:
            primas = spots * factor * nd1 - desc_k * nd2
            deltas = factor * nd1
        else:
            primas = desc_k * (1.0 - nd2) - spots * factor * (1.0 - nd1)
            deltas = -factor * (1.0 - nd1)
    primas = np.nan_to_num(primas, nan=0.0, posinf=float("inf"), neginf=0.0)
    deltas = np.nan_to_num(deltas, nan=0.0, posinf=1.0, neginf=-1.0)
    return spots, primas, deltas
