# -*- coding: utf-8 -*-
"""Modelo econometrico MCO (Precio ~ periodo) y diagnostico de residuos.

El ajuste reproduce la funcion ``RSQ(precio, periodo)`` de la hoja
*Econometrico* del Excel de referencia: se regresa el precio sobre el indice de
tiempo ``x = 1..n`` por Minimos Cuadrados Ordinarios (MCO/OLS) y se anade la
bateria completa de estadisticos de diagnostico.

Que se calcula
--------------
* Coeficientes (intercepto y pendiente), errores estandar, estadisticos ``t`` y
  p-values bilaterales.
* ``R^2``, ``R^2`` ajustado, estadistico ``F`` de la regresion y su p-value.
* Error estandar de la regresion: ``se_regresion = sqrt(SSE / (n - 2))``.
* Durbin-Watson, Jarque-Bera y Breusch-Pagan sobre los residuos.
* Intervalo de **prediccion** al 95% para ``x0 = n + meses_pronostico``::

      se_pred = se_regresion * sqrt(1 + 1/n + (x0 - xbar)^2 / Sxx)
      li/ls   = pronostico -/+ t(0.975, n - 2) * se_pred

* Veredicto de confiabilidad ``Alta``/``Media``/``Baja`` a partir de una
  puntuacion documentada de 0 a 6 puntos (ver :func:`ols_econometrico`).

Degradacion elegante
--------------------
``statsmodels`` y ``scipy`` son **opcionales**. Si falta ``statsmodels`` el MCO
se calcula con numpy (:func:`_ols_numpy`); si falta ``scipy``, las funciones de
supervivencia y los cuantiles usan implementaciones propias
(:func:`chi2_sf`, :func:`f_sf`, :func:`t_critico`) basadas en la funcion beta y
gamma incompletas regularizadas y en la expansion de Cornish-Fisher (la misma
que aplica ``TINV`` en Excel). Los p-values de esos respaldos coinciden con
``scipy`` en el orden de ``1e-10`` relativo. La primera vez que se usa cada
respaldo se emite un ``warning`` por el logger ``dml.econometria``.

Este modulo nunca lanza excepciones por datos de entrada invalidos: devuelve
``None`` o un resultado con valores ``NaN`` (que la interfaz pinta como ``N/D``).
"""

from __future__ import annotations

import logging
import math
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..core.tipos import ND, ResultadoOLS
from ..core.util import a_float

LOG = logging.getLogger("dml.econometria")

# --------------------------------------------------------------------------
# Dependencias opcionales: el modulo degrada con elegancia si faltan.
# --------------------------------------------------------------------------
try:  # pragma: no cover - depende del entorno
    import statsmodels.api as sm  # type: ignore
    from statsmodels.stats.stattools import jarque_bera as _sm_jarque_bera  # type: ignore
    from statsmodels.stats.diagnostic import het_breuschpagan as _sm_breusch_pagan  # type: ignore
except Exception:  # pragma: no cover
    sm = None  # type: ignore
    _sm_jarque_bera = None  # type: ignore
    _sm_breusch_pagan = None  # type: ignore

try:  # pragma: no cover - depende del entorno
    from scipy import stats as sps  # type: ignore
except Exception:  # pragma: no cover
    sps = None  # type: ignore

__all__ = [
    "MIN_OBSERVACIONES",
    "R2_MIN_POR_DEFECTO",
    "UMBRAL_P_POR_DEFECTO",
    "breusch_pagan",
    "chi2_sf",
    "durbin_watson",
    "f_sf",
    "interpretar",
    "jarque_bera",
    "jp_texto",
    "ols_econometrico",
    "pruebas_residuos",
    "t_critico",
    "tabla_residuos",
    "z_normal",
]

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

#: Numero minimo de observaciones para ajustar el MCO (n - 2 grados de libertad).
MIN_OBSERVACIONES = 5

#: Umbral de R^2 usado por defecto para el veredicto de confiabilidad.
R2_MIN_POR_DEFECTO = 0.70

#: Umbral de significacion usado por defecto para la pendiente.
UMBRAL_P_POR_DEFECTO = 0.05

#: Banda de Durbin-Watson considerada "sin autocorrelacion aparente".
DW_MIN, DW_MAX = 1.5, 2.5

#: Nivel de confianza del intervalo de prediccion (cuantil 0.975 de la t).
CUANTIL_PRONOSTICO = 0.975

#: Campos escalares que toda estimacion debe rellenar con un valor utilizable.
_CAMPOS_NUCLEO: Tuple[str, ...] = (
    "intercepto",
    "pendiente",
    "se_intercepto",
    "se_pendiente",
    "t_intercepto",
    "t_pendiente",
    "p_intercepto",
    "p_pendiente",
    "r2",
    "r2_ajustado",
    "f_stat",
    "f_pvalue",
    "se_regresion",
)

#: Avisos de respaldo ya emitidos (para no repetir el mismo ``warning``).
_AVISOS_EMITIDOS: set = set()


def _avisar_una_vez(clave: str, mensaje: str, *args: Any) -> None:
    """Emite un ``warning`` como maximo una vez por ``clave``.

    Args:
        clave: identificador del respaldo (p. ej. ``"sin_statsmodels"``).
        mensaje: mensaje con formato ``%`` para :mod:`logging`.
        *args: argumentos del mensaje.
    """
    if clave in _AVISOS_EMITIDOS:
        return
    _AVISOS_EMITIDOS.add(clave)
    LOG.warning(mensaje, *args)


# --------------------------------------------------------------------------
# Coercion numerica interna
# --------------------------------------------------------------------------


def _a_flotante(valor: Any) -> Optional[float]:
    """Convierte ``valor`` en ``float`` admitiendo ``inf`` (pero no ``NaN``).

    Se diferencia de :func:`dml.core.util.a_float` en que un infinito es un
    resultado legitimo de algunos estadisticos (por ejemplo ``F`` con ajuste
    perfecto), mientras que ``NaN`` siempre significa "no calculable".
    """
    if valor is None:
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _a_array(valores: Any) -> np.ndarray:
    """Convierte una secuencia en ``ndarray`` float descartando valores invalidos.

    Usa :func:`dml.core.util.a_float` para cada elemento, de modo que ``None``,
    ``NaN``, ``inf``, cadenas vacias y objetos no numericos se descartan en
    lugar de propagarse.
    """
    if valores is None:
        return np.asarray([], dtype=float)
    if isinstance(valores, np.ndarray):
        candidatos = valores.ravel().tolist()
    elif isinstance(valores, pd.Series):
        candidatos = valores.tolist()
    else:
        try:
            candidatos = list(valores)
        except TypeError:
            candidatos = [valores]
    limpios = [f for f in (a_float(v) for v in candidatos) if f is not None]
    return np.asarray(limpios, dtype=float)


def _division_segura(numerador: float, denominador: float) -> float:
    """Division que devuelve ``NaN`` o ``+/-inf`` en lugar de lanzar excepcion."""
    num, den = float(numerador), float(denominador)
    if den == 0.0:
        if num == 0.0 or math.isnan(num):
            return float("nan")
        return math.copysign(float("inf"), num)
    try:
        return num / den
    except (ZeroDivisionError, OverflowError):  # pragma: no cover - defensivo
        return float("nan")


def _es_finito(valor: Any) -> bool:
    """True si ``valor`` (escalar o secuencia) es finito en todos sus elementos."""
    if valor is None:
        return False
    if isinstance(valor, (int, float, np.floating, np.integer)):
        return math.isfinite(float(valor))
    try:
        arr = np.asarray(valor, dtype=float)
    except (TypeError, ValueError):
        return False
    return bool(arr.size) and bool(np.all(np.isfinite(arr)))


# --------------------------------------------------------------------------
# Funciones especiales: respaldos sin scipy
# --------------------------------------------------------------------------
#
# Se implementan la funcion gamma incompleta y la funcion beta incompleta
# regularizadas con las series y fracciones continuas de *Numerical Recipes*
# (6.2 y 6.4). Con ellas se obtienen p-values exactos de t, F y chi-cuadrado sin
# depender de scipy, en lugar de aproximar con la normal.


def _gser(a: float, x: float, itmax: int = 300, eps: float = 3.0e-16) -> float:
    """Serie de la funcion gamma incompleta regularizada ``P(a, x)`` (x < a + 1)."""
    if x <= 0.0:
        return 0.0
    ap = a
    suma = 1.0 / a
    delta = suma
    for _ in range(itmax):
        ap += 1.0
        delta *= x / ap
        suma += delta
        if abs(delta) < abs(suma) * eps:
            break
    return float(suma * math.exp(-x + a * math.log(x) - math.lgamma(a)))


def _gcf(a: float, x: float, itmax: int = 300, eps: float = 3.0e-16) -> float:
    """Fraccion continua de la gamma incompleta ``Q(a, x)`` (x >= a + 1)."""
    tiny = 1.0e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b if b != 0.0 else 1.0 / tiny
    h = d
    for i in range(1, itmax + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return float(math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def _gammaq(a: float, x: float) -> float:
    """Funcion gamma incompleta regularizada ``Q(a, x)`` (supervivencia)."""
    if a <= 0.0 or x < 0.0:
        return float("nan")
    if x == 0.0:
        return 1.0
    if x < a + 1.0:
        return float(1.0 - _gser(a, x))
    return _gcf(a, x)


def _betacf(a: float, b: float, x: float, itmax: int = 300, eps: float = 3.0e-16) -> float:
    """Fraccion continua de la beta incompleta (Numerical Recipes, 6.4)."""
    tiny = 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return float(h)


def _betainc(a: float, b: float, x: float) -> float:
    """Funcion beta incompleta regularizada ``I_x(a, b)``."""
    if a <= 0.0 or b <= 0.0 or x < 0.0 or x > 1.0:
        return float("nan")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    factor = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return float(factor * _betacf(a, b, x) / a)
    return float(1.0 - factor * _betacf(b, a, 1.0 - x) / b)


def _t_sf(t: float, gl: float) -> float:
    """Supervivencia ``P(T > t)`` de la t de Student con ``gl`` grados de libertad."""
    tv, glv = _a_flotante(t), _a_flotante(gl)
    if tv is None or glv is None or glv <= 0.0:
        return float("nan")
    if tv == 0.0:
        return 0.5
    if math.isinf(tv):
        return 0.0 if tv > 0 else 1.0
    beta = _betainc(glv / 2.0, 0.5, glv / (glv + tv * tv))
    if math.isnan(beta):
        return float("nan")
    return float(0.5 * beta if tv > 0 else 1.0 - 0.5 * beta)


def _p_value_bilateral(t: float, gl: float) -> float:
    """p-value bilateral de un estadistico ``t`` (``2 * P(T > |t|)``)."""
    tv = _a_flotante(t)
    if tv is None:
        return float("nan")
    if sps is not None:
        try:
            return float(2.0 * sps.t.sf(abs(tv), gl))
        except Exception as exc:  # pragma: no cover - depende de scipy
            _avisar_una_vez("scipy_t", "scipy fallo al calcular el p-value de la t (%s); se usa el respaldo propio", exc)
    return float(2.0 * _t_sf(abs(tv), gl))


def z_normal(p: float) -> float:
    """Cuantil de la normal estandar ``N(0, 1)`` sin depender de scipy.

    Args:
        p: probabilidad acumulada en ``(0, 1)``.

    Returns:
        El cuantil ``z`` tal que ``P(Z <= z) = p``; ``NaN`` si ``p`` no es
        numerico, ``-inf`` si ``p <= 0`` y ``+inf`` si ``p >= 1``.
    """
    pv = a_float(p)
    if pv is None:
        return float("nan")
    if pv <= 0.0:
        return float("-inf")
    if pv >= 1.0:
        return float("inf")
    try:
        return float(NormalDist().inv_cdf(pv))
    except Exception as exc:  # pragma: no cover - defensivo
        LOG.warning("No se pudo calcular el cuantil normal (%s)", exc)
        return float("nan")


def t_critico(gl: int, p: float = CUANTIL_PRONOSTICO) -> float:
    """Cuantil de la t de Student con ``gl`` grados de libertad.

    Usa scipy si esta disponible; si no, la expansion de Cornish-Fisher, que es
    la misma distribucion que aplica ``TINV`` en la hoja de Excel. La expansion
    es asintotica: su error es del orden de ``1e-3`` para ``gl >= 5`` y crece
    con pocos grados de libertad.

    Args:
        gl: grados de libertad (``n - 2`` en el MCO simple).
        p: probabilidad acumulada; ``0.975`` para el intervalo al 95%.

    Returns:
        El cuantil pedido o ``NaN`` si los argumentos no son validos.
    """
    glv, pv = _a_flotante(gl), a_float(p)
    if glv is None or pv is None or glv <= 0.0 or not 0.0 < pv < 1.0:
        return float("nan")
    if sps is not None:
        try:
            return float(sps.t.ppf(pv, glv))
        except Exception as exc:  # pragma: no cover - depende de scipy
            _avisar_una_vez("scipy_tppf", "scipy fallo al calcular el cuantil t (%s); se usa Cornish-Fisher", exc)
    else:
        _avisar_una_vez(
            "sin_scipy_tcritico",
            "scipy no disponible: los cuantiles t usan la expansion de Cornish-Fisher (equivalente a TINV de Excel)",
        )
    try:
        z = NormalDist().inv_cdf(pv)
        g1 = (z ** 3 + z) / 4.0
        g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96.0
        g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384.0
        g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160.0
        return float(z + g1 / glv + g2 / glv ** 2 + g3 / glv ** 3 + g4 / glv ** 4)
    except Exception as exc:  # pragma: no cover - defensivo
        LOG.warning("No se pudo calcular el cuantil t con gl=%s (%s)", gl, exc)
        return float("nan")


def chi2_sf(x: float, gl: float) -> float:
    """Supervivencia ``P(X > x)`` de una chi-cuadrado con ``gl`` grados de libertad.

    Con scipy ausente se usa la gamma incompleta regularizada ``Q(gl/2, x/2)``
    implementada en este modulo, valida para cualquier ``gl`` positivo (no solo
    ``1`` y ``2``).

    Args:
        x: valor del estadistico (``>= 0``).
        gl: grados de libertad (``> 0``).

    Returns:
        El p-value de la cola superior, ``0.0`` si ``x`` es infinito y ``NaN``
        si los argumentos no son validos.
    """
    xv, glv = _a_flotante(x), _a_flotante(gl)
    if xv is None or glv is None or xv < 0.0 or glv <= 0.0:
        return float("nan")
    if math.isinf(xv):
        return 0.0
    if sps is not None:
        try:
            return float(sps.chi2.sf(xv, glv))
        except Exception as exc:  # pragma: no cover - depende de scipy
            _avisar_una_vez("scipy_chi2", "scipy fallo al calcular la chi-cuadrado (%s); se usa el respaldo propio", exc)
    else:
        _avisar_una_vez(
            "sin_scipy_chi2",
            "scipy no disponible: los p-values de chi-cuadrado usan la gamma incompleta propia",
        )
    return _gammaq(glv / 2.0, xv / 2.0)


def f_sf(f: float, gl1: float, gl2: float) -> float:
    """Supervivencia ``P(F > f)`` de una F de Snedecor con ``(gl1, gl2)`` grados.

    Es el respaldo propio del p-value de la ``F`` de la regresion. Se usa, entre
    otros casos, cuando ``statsmodels`` devuelve ``NaN`` en ``f_pvalue`` con
    ajustes casi perfectos (``R^2`` ~ 1 y ``SSE`` ~ 0).

    Args:
        f: valor del estadistico (``>= 0``).
        gl1: grados de libertad del numerador (``1`` en el MCO simple).
        gl2: grados de libertad del denominador (``n - 2``).

    Returns:
        El p-value de la cola superior; ``0.0`` si ``f`` es infinito y ``NaN``
        si los argumentos no son validos.
    """
    fv, d1, d2 = _a_flotante(f), _a_flotante(gl1), _a_flotante(gl2)
    if d1 is None or d2 is None or d1 <= 0.0 or d2 <= 0.0:
        return float("nan")
    if fv is None or fv < 0.0:
        return float("nan")
    if math.isinf(fv):
        return 0.0
    if sps is not None:
        try:
            return float(sps.f.sf(fv, d1, d2))
        except Exception as exc:  # pragma: no cover - depende de scipy
            _avisar_una_vez("scipy_f", "scipy fallo al calcular la F (%s); se usa el respaldo propio", exc)
    else:
        _avisar_una_vez(
            "sin_scipy_f",
            "scipy no disponible: los p-values de la F usan la beta incompleta propia",
        )
    return _betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * fv))


# --------------------------------------------------------------------------
# Diagnostico de residuos
# --------------------------------------------------------------------------


def durbin_watson(residuos: Sequence[float]) -> float:
    """Estadistico Durbin-Watson de autocorrelacion de primer orden.

    ``DW = sum((e_t - e_{t-1})^2) / sum(e_t^2)``. El contraste no tiene
    p-value asociado; se interpreta por bandas: valores proximos a ``2``
    indican ausencia de autocorrelacion, por debajo de ``1.5`` autocorrelacion
    positiva y por encima de ``2.5`` autocorrelacion negativa.

    Args:
        residuos: residuos del MCO en orden cronologico.

    Returns:
        El estadistico, o ``NaN`` si hay menos de dos residuos o todos son cero
        (caso de ajuste perfecto).
    """
    r = _a_array(residuos)
    if r.size < 2:
        return float("nan")
    denominador = float(np.sum(r ** 2))
    if denominador == 0.0:
        return float("nan")
    return float(np.sum(np.diff(r) ** 2) / denominador)


def jarque_bera(residuos: Sequence[float]) -> Tuple[float, float]:
    """Contraste de normalidad Jarque-Bera sobre los residuos.

    ``JB = n/6 * (S^2 + K^2/4)``, con ``S`` la asimetria y ``K`` el exceso de
    curtosis calculados con los momentos poblacionales (``ddof = 0``), que es
    la definicion clasica y la que aplica ``statsmodels``. El estadistico se
    contrasta con una chi-cuadrado de 2 grados de libertad.

    Se prefiere la implementacion de ``statsmodels`` cuando esta disponible;
    si no, se usa la propia (identica, con la chi-cuadrado de respaldo).

    Args:
        residuos: residuos del MCO.

    Returns:
        Tupla ``(estadistico, p-value)``; ``(NaN, NaN)`` si hay menos de cuatro
        residuos o si su desviacion tipica es nula.
    """
    r = _a_array(residuos)
    if r.size < 4:
        return float("nan"), float("nan")
    if _sm_jarque_bera is not None:
        try:
            jb, jb_p, _asimetria, _curtosis = _sm_jarque_bera(r)
            return float(jb), float(jb_p)
        except Exception as exc:
            _avisar_una_vez(
                "jb_statsmodels", "Jarque-Bera de statsmodels fallo (%s); se usa el calculo propio", exc
            )
    desviacion = float(np.std(r, ddof=0))
    if desviacion == 0.0:
        return float("nan"), float("nan")
    z = (r - float(np.mean(r))) / desviacion
    asimetria = float(np.mean(z ** 3))
    curtosis_exceso = float(np.mean(z ** 4) - 3.0)
    n = int(r.size)
    jb = n / 6.0 * (asimetria ** 2 + curtosis_exceso ** 2 / 4.0)
    return float(jb), chi2_sf(jb, 2)


def breusch_pagan(residuos: Sequence[float], x: Sequence[float]) -> Tuple[float, float]:
    """Contraste de heterocedasticidad Breusch-Pagan.

    Se contrasta si la varianza de los residuos depende del periodo: se
    regresan los residuos al cuadrado sobre ``x`` y se forma el multiplicador de
    Lagrange ``LM = n * R^2`` del ajuste auxiliar, que se compara con una
    chi-cuadrado con 1 grado de libertad (un unico regresor).

    Se prefiere la implementacion de ``statsmodels`` cuando esta disponible
    (variante estudentizada de Koenker, la que usa por defecto
    ``het_breuschpagan``); si no, se usa la version clasica propia descrita
    arriba.

    Args:
        residuos: residuos del MCO.
        x: regresor de la regresion auxiliar (el indice de tiempo ``1..n``).

    Returns:
        Tupla ``(estadistico, p-value)``; ``(NaN, NaN)`` si hay menos de cinco
        observaciones utiles o el ajuste auxiliar no es posible.
    """
    r, xv = _a_array(residuos), _a_array(x)
    n = int(min(r.size, xv.size))
    if n < MIN_OBSERVACIONES:
        return float("nan"), float("nan")
    r, xv = r[:n], xv[:n]
    if _sm_breusch_pagan is not None and sm is not None:
        try:
            exog = sm.add_constant(xv, has_constant="add")
            lm, lm_p, _f, _f_p = _sm_breusch_pagan(r, exog)
            if _es_finito(lm):
                return float(lm), float(lm_p)
        except Exception as exc:
            _avisar_una_vez(
                "bp_statsmodels", "Breusch-Pagan de statsmodels fallo (%s); se usa el calculo propio", exc
            )
    ajuste = _ols_numpy(r ** 2, xv, n)
    if ajuste is None:
        return float("nan"), float("nan")
    lm = float(n) * float(ajuste["r2"])
    return float(lm), chi2_sf(lm, 1)


# --------------------------------------------------------------------------
# Estimacion MCO
# --------------------------------------------------------------------------


def _ols_statsmodels(y: np.ndarray, x: np.ndarray, n: int) -> Optional[Dict[str, Any]]:
    """Ajusta el MCO con ``statsmodels`` y devuelve el nucleo de estadisticos.

    Args:
        y: variable dependiente (precios).
        x: regresor (indice de tiempo ``1..n``).
        n: numero de observaciones.

    Returns:
        Diccionario con los campos escalares, ``residuos`` y ``ajustados``, o
        ``None`` si ``statsmodels`` no esta disponible o falla el ajuste.

    Note:
        Si ``statsmodels`` devuelve ``NaN`` en ``f_pvalue`` (ajuste casi
        perfecto, ``SSE`` ~ 0), el p-value se recalcula con :func:`f_sf`.
    """
    if sm is None:
        return None
    try:
        modelo = sm.OLS(y, sm.add_constant(x)).fit()
        resid = np.asarray(modelo.resid, dtype=float)
        ajustados = np.asarray(modelo.fittedvalues, dtype=float)
        f_stat = _a_flotante(modelo.fvalue)
        f_p = _a_flotante(modelo.f_pvalue)
        if f_stat is None:
            f_stat = float("nan")
        if f_p is None:  # statsmodels devuelve nan con ajustes casi perfectos
            f_p = f_sf(f_stat, 1, n - 2)
            LOG.debug("f_pvalue de statsmodels no finito (F = %s): recalculado con f_sf", f_stat)
        mse_resid = _a_flotante(modelo.mse_resid)
        se_reg = float(math.sqrt(mse_resid)) if mse_resid is not None and mse_resid >= 0.0 else float("nan")
        return {
            "intercepto": float(modelo.params[0]),
            "pendiente": float(modelo.params[1]),
            "se_intercepto": float(modelo.bse[0]),
            "se_pendiente": float(modelo.bse[1]),
            "t_intercepto": float(modelo.tvalues[0]),
            "t_pendiente": float(modelo.tvalues[1]),
            "p_intercepto": float(modelo.pvalues[0]),
            "p_pendiente": float(modelo.pvalues[1]),
            "r2": float(modelo.rsquared),
            "r2_ajustado": float(modelo.rsquared_adj),
            "f_stat": f_stat,
            "f_pvalue": f_p,
            "se_regresion": se_reg,
            "residuos": resid,
            "ajustados": ajustados,
        }
    except Exception as exc:
        LOG.warning("statsmodels no pudo ajustar el MCO (%s); se usa el calculo propio con numpy", exc)
        return None


def _ols_numpy(y: np.ndarray, x: np.ndarray, n: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """MCO simple con numpy (respaldo si ``statsmodels`` no esta disponible).

    Calcula exactamente los mismos campos que :func:`_ols_statsmodels`, con los
    p-values de la ``t`` obtenidos por la beta incompleta de este modulo, de
    modo que ambas rutas son intercambiables.

    Args:
        y: variable dependiente (precios).
        x: regresor (indice de tiempo ``1..n``).
        n: numero de observaciones; si es ``None`` se deduce de ``len(y)``.

    Returns:
        Diccionario con el nucleo de estadisticos, ``residuos`` y ``ajustados``,
        o ``None`` si la serie no permite el ajuste (longitud insuficiente o
        regresor constante).
    """
    yv = np.asarray(y, dtype=float).ravel()
    xv = np.asarray(x, dtype=float).ravel()
    m = int(len(yv)) if n is None else int(n)
    if m < 3 or len(xv) != len(yv) or m != len(yv):
        return None
    x_media = float(np.mean(xv))
    y_media = float(np.mean(yv))
    sxx = float(np.sum((xv - x_media) ** 2))
    if sxx <= 0.0:
        return None
    pendiente = float(np.sum((xv - x_media) * (yv - y_media)) / sxx)
    intercepto = float(y_media - pendiente * x_media)
    ajustados = intercepto + pendiente * xv
    resid = yv - ajustados
    gl = m - 2
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((yv - y_media) ** 2))
    ssr = max(sst - sse, 0.0)  # la resta puede dar un negativo minimo por redondeo
    se_reg = float(math.sqrt(sse / gl)) if sse > 0.0 else 0.0
    se_pen = _division_segura(se_reg, math.sqrt(sxx))
    se_int = se_reg * math.sqrt(1.0 / m + x_media ** 2 / sxx)
    t_pen = _division_segura(pendiente, se_pen)
    t_int = _division_segura(intercepto, se_int)
    p_pen = _p_value_bilateral(t_pen, gl)
    p_int = _p_value_bilateral(t_int, gl)
    r2 = float(1.0 - sse / sst) if sst > 0.0 else 0.0
    r2_aj = float(1.0 - (1.0 - r2) * (m - 1) / gl)
    f_stat = _division_segura(ssr, sse / gl) if sse > 0.0 else float("inf")
    f_p = f_sf(f_stat, 1, gl)
    return {
        "intercepto": intercepto,
        "pendiente": pendiente,
        "se_intercepto": float(se_int),
        "se_pendiente": float(se_pen),
        "t_intercepto": float(t_int),
        "t_pendiente": float(t_pen),
        "p_intercepto": float(p_int),
        "p_pendiente": float(p_pen),
        "r2": r2,
        "r2_ajustado": r2_aj,
        "f_stat": float(f_stat),
        "f_pvalue": float(f_p),
        "se_regresion": float(se_reg),
        "residuos": resid,
        "ajustados": np.asarray(ajustados, dtype=float),
    }


def _normalizar_nucleo(nucleo: Dict[str, Any], y: np.ndarray, x: np.ndarray, n: int) -> Dict[str, Any]:
    """Completa con el calculo propio los campos no finitos del ajuste principal.

    Con ajustes degenerados (por ejemplo una serie perfectamente lineal) algunas
    librerias devuelven ``NaN`` en errores estandar, ``t`` o p-values. En ese
    caso se sustituyen por los del respaldo numpy, que resuelve ``0/0`` con
    criterios explicitos (``t = +/-inf`` y por tanto ``p = 0``).

    Args:
        nucleo: diccionario devuelto por el ajuste principal.
        y: variable dependiente.
        x: regresor.
        n: numero de observaciones.

    Returns:
        El mismo diccionario, completado si hacia falta.
    """
    faltantes = [campo for campo in _CAMPOS_NUCLEO if not _es_finito(nucleo.get(campo))]
    for campo in ("residuos", "ajustados"):
        if not _es_finito(nucleo.get(campo)):
            faltantes.append(campo)
    if not faltantes:
        return nucleo
    respaldo = _ols_numpy(y, x, n)
    if respaldo is None:
        return nucleo
    LOG.warning(
        "Estadisticos no finitos en el ajuste principal (%s): se completan con el calculo propio", ", ".join(faltantes)
    )
    for campo in faltantes:
        nucleo[campo] = respaldo[campo]
    return nucleo


def _intervalo_pronostico(
    intercepto: float, pendiente: float, se_regresion: float, x: np.ndarray, n: int, meses_pronostico: int
) -> Tuple[float, float, float]:
    """Intervalo de **prediccion** al 95% para ``x0 = n + meses_pronostico``.

    Se usa el intervalo de prediccion de una observacion futura (no el de la
    media condicional), tal como la formula de la hoja *Econometrico*::

        se_pred = se_regresion * sqrt(1 + 1/n + (x0 - xbar)^2 / Sxx)
        li/ls   = pronostico -/+ t(0.975, n - 2) * se_pred

    Args:
        intercepto: termino independiente estimado.
        pendiente: pendiente estimada.
        se_regresion: error estandar de la regresion.
        x: regresor del ajuste (``1..n``).
        n: numero de observaciones.
        meses_pronostico: meses a proyectar desde el final de la serie.

    Returns:
        Tupla ``(pronostico, limite_inferior, limite_superior)``. Con un ajuste
        perfecto (``se_regresion == 0``) el intervalo degenera en un punto
        (``li == pronostico == ls``), que es el resultado correcto.
    """
    x0 = float(n + int(meses_pronostico))
    x_media = float(np.mean(x))
    sxx = float(np.sum((x - x_media) ** 2))
    centro = float(intercepto) + float(pendiente) * x0
    if not math.isfinite(centro):
        return centro, float("nan"), float("nan")
    if sxx <= 0.0 or not math.isfinite(se_regresion) or se_regresion <= 0.0:
        return centro, centro, centro
    varianza = 1.0 + 1.0 / float(n) + (x0 - x_media) ** 2 / sxx
    se_pred = float(se_regresion) * math.sqrt(max(varianza, 0.0))
    t_crit = t_critico(n - 2)
    if not math.isfinite(t_crit):
        t_crit = abs(z_normal(CUANTIL_PRONOSTICO))
    margen = abs(float(t_crit) * se_pred)
    return centro, centro - margen, centro + margen


def _evaluar_veredicto(
    r2: float, p_pendiente: float, dw: float, jb_p: float, r2_min: float, umbral_p: float
) -> Tuple[str, str, int, List[str]]:
    """Puntuacion de confiabilidad del modelo (0 a 6 puntos) y su justificacion.

    Reglas documentadas:

    * ``R^2 >= r2_min``: +2 puntos.
    * pendiente significativa (``p < umbral_p``): +2 puntos.
    * ``1.5 <= Durbin-Watson <= 2.5``: +1 punto.
    * residuos normales (Jarque-Bera ``p > 0.05``): +1 punto.

    Veredicto: ``>= 4`` puntos -> ``Alta``; ``>= 2`` -> ``Media``; si no, ``Baja``.

    Args:
        r2: coeficiente de determinacion.
        p_pendiente: p-value de la pendiente.
        dw: estadistico Durbin-Watson.
        jb_p: p-value de Jarque-Bera.
        r2_min: umbral de ``R^2``.
        umbral_p: umbral de significacion de la pendiente.

    Returns:
        Tupla ``(veredicto, justificacion, puntuacion, motivos)``.
    """
    motivos: List[str] = []
    puntuacion = 0

    if math.isfinite(r2) and r2 >= r2_min:
        puntuacion += 2
        motivos.append(f"R2 = {r2:.3f} >= {r2_min:.2f} (+2)")
    else:
        motivos.append(f"R2 = {jp_texto(r2)} < {r2_min:.2f} (+0)")

    if p_pendiente is not None and not math.isnan(p_pendiente) and p_pendiente < umbral_p:
        puntuacion += 2
        motivos.append(f"pendiente significativa (p = {p_pendiente:.4f} < {umbral_p:.2f}) (+2)")
    else:
        motivos.append(f"pendiente NO significativa (p = {jp_texto(p_pendiente)}) (+0)")

    if dw is not None and not math.isnan(dw) and DW_MIN <= dw <= DW_MAX:
        puntuacion += 1
        motivos.append(f"Durbin-Watson = {dw:.2f} en [{DW_MIN:.1f}, {DW_MAX:.1f}] (+1)")
    else:
        motivos.append(f"Durbin-Watson = {jp_texto(dw)} fuera de [{DW_MIN:.1f}, {DW_MAX:.1f}] (+0)")

    if jb_p is not None and not math.isnan(jb_p) and jb_p > 0.05:
        puntuacion += 1
        motivos.append(f"residuos normales (Jarque-Bera p = {jb_p:.4f} > 0.05) (+1)")
    else:
        motivos.append(f"residuos no normales (Jarque-Bera p = {jp_texto(jb_p)}) (+0)")

    if puntuacion >= 4:
        veredicto = "Alta"
    elif puntuacion >= 2:
        veredicto = "Media"
    else:
        veredicto = "Baja"
    justificacion = f"Confiabilidad {veredicto} ({puntuacion}/6): " + "; ".join(motivos) + "."
    return veredicto, justificacion, puntuacion, motivos


def ols_econometrico(
    precios: pd.Series, meses_pronostico: int = 12, r2_min: float = 0.70, umbral_p: float = 0.05
) -> Optional[ResultadoOLS]:
    """Regresion MCO de Precio sobre el indice de tiempo ``1..n`` y diagnostico.

    Equivale a ``RSQ(precio, periodo)`` del Excel de referencia pero con la
    bateria completa de estadisticos: coeficientes, errores estandar, ``t``,
    p-values, ``R^2``, ``R^2`` ajustado, ``F``, error estandar de la regresion,
    Durbin-Watson, Jarque-Bera, Breusch-Pagan y pronostico con intervalo de
    prediccion al 95%.

    Se usa ``statsmodels`` cuando esta importable (``metodo = "statsmodels"``) y
    el respaldo numpy (:func:`_ols_numpy`) en caso contrario
    (``metodo = "numpy"``); ambas rutas rellenan exactamente los mismos campos.
    Si ``statsmodels`` devuelve ``NaN`` en el p-value de la ``F`` (ajuste casi
    perfecto) se recalcula con :func:`f_sf`.

    El veredicto de confiabilidad se obtiene de una puntuacion de 0 a 6:

    * ``R^2 >= r2_min``: +2 puntos.
    * pendiente significativa (``p < umbral_p``): +2 puntos.
    * ``1.5 <= Durbin-Watson <= 2.5``: +1 punto.
    * residuos normales (Jarque-Bera ``p > 0.05``): +1 punto.

    ``>= 4`` puntos -> ``Alta``, ``>= 2`` -> ``Media``, si no -> ``Baja``.

    Args:
        precios: serie mensual de precios ordenada cronologicamente.
        meses_pronostico: meses a proyectar desde el final de la serie.
        r2_min: umbral de ``R^2`` para el veredicto (por defecto ``0.70``).
        umbral_p: umbral de significacion de la pendiente (por defecto ``0.05``).

    Returns:
        Un :class:`~dml.core.tipos.ResultadoOLS` con todos los campos
        poblados, o ``None`` si la serie no tiene al menos
        :data:`MIN_OBSERVACIONES` observaciones validas o no es convertible.
    """
    if precios is None:
        LOG.warning("No hay precios para el MCO")
        return None
    try:
        serie = pd.Series(precios)
    except Exception as exc:
        LOG.warning("La serie de precios no es convertible (%s)", exc)
        return None
    y = _a_array(serie)
    n = int(y.size)
    if n < MIN_OBSERVACIONES:
        LOG.warning("Serie demasiado corta para el MCO (%s observaciones; se requieren %s)", n, MIN_OBSERVACIONES)
        return None

    mp = a_float(meses_pronostico)
    mp_int = 12 if mp is None else int(mp)
    if mp_int < 0:
        LOG.warning("meses_pronostico negativo (%s): se usa 0", mp_int)
        mp_int = 0
    r2_umbral = a_float(r2_min)
    r2_umbral = R2_MIN_POR_DEFECTO if r2_umbral is None else float(r2_umbral)
    p_umbral = a_float(umbral_p)
    p_umbral = UMBRAL_P_POR_DEFECTO if p_umbral is None else float(p_umbral)

    x = np.arange(1, n + 1, dtype=float)

    nucleo: Optional[Dict[str, Any]] = None
    metodo = "statsmodels"
    if sm is not None:
        nucleo = _ols_statsmodels(y, x, n)
    if nucleo is None:
        metodo = "numpy"
        if sm is None:
            _avisar_una_vez(
                "sin_statsmodels",
                "statsmodels no disponible: el MCO se calcula con el respaldo numpy",
            )
        nucleo = _ols_numpy(y, x, n)
    if nucleo is None:
        LOG.warning("No se pudo ajustar el MCO (regresor degenerado)")
        return None
    if metodo == "statsmodels":
        nucleo = _normalizar_nucleo(nucleo, y, x, n)

    resid = np.asarray(nucleo["residuos"], dtype=float)
    ajustados = np.asarray(nucleo["ajustados"], dtype=float)

    dw = durbin_watson(resid)
    jb_stat, jb_p = jarque_bera(resid)
    bp_stat, bp_p = breusch_pagan(resid, x)
    pronostico, li, ls = _intervalo_pronostico(
        float(nucleo["intercepto"]), float(nucleo["pendiente"]), float(nucleo["se_regresion"]), x, n, mp_int
    )
    veredicto, justificacion, _puntuacion, _motivos = _evaluar_veredicto(
        float(nucleo["r2"]), float(nucleo["p_pendiente"]), dw, jb_p, r2_umbral, p_umbral
    )

    return ResultadoOLS(
        n=n,
        metodo=metodo,
        intercepto=float(nucleo["intercepto"]),
        pendiente=float(nucleo["pendiente"]),
        se_intercepto=float(nucleo["se_intercepto"]),
        se_pendiente=float(nucleo["se_pendiente"]),
        t_intercepto=float(nucleo["t_intercepto"]),
        t_pendiente=float(nucleo["t_pendiente"]),
        p_intercepto=float(nucleo["p_intercepto"]),
        p_pendiente=float(nucleo["p_pendiente"]),
        r2=float(nucleo["r2"]),
        r2_ajustado=float(nucleo["r2_ajustado"]),
        f_stat=float(nucleo["f_stat"]),
        f_pvalue=float(nucleo["f_pvalue"]),
        se_regresion=float(nucleo["se_regresion"]),
        durbin_watson=float(dw),
        jarque_bera=float(jb_stat),
        jarque_bera_p=float(jb_p),
        breusch_pagan=float(bp_stat),
        breusch_pagan_p=float(bp_p),
        residuos=[float(v) for v in resid],
        ajustados=[float(v) for v in ajustados],
        periodos=[int(v) for v in x],
        precios=[float(v) for v in y],
        meses_pronostico=mp_int,
        pronostico_precio=float(pronostico),
        pronostico_li=float(li),
        pronostico_ls=float(ls),
        veredicto=veredicto,
        justificacion=justificacion,
    )


# --------------------------------------------------------------------------
# Presentacion de resultados
# --------------------------------------------------------------------------


def jp_texto(valor: Any) -> str:
    """Formatea de forma segura un p-value o un estadistico que puede ser ``NaN``."""
    v = a_float(valor)
    if v is None:
        return ND
    return f"{v:.4f}"


def tabla_residuos(ols: ResultadoOLS) -> pd.DataFrame:
    """Tabla de residuos y valores ajustados por periodo.

    Envoltorio fino de :meth:`dml.core.tipos.ResultadoOLS.como_dataframe_residuos`
    para poder llamarlo desde la interfaz sin conocer el tipo de datos.

    Args:
        ols: resultado del MCO.

    Returns:
        ``DataFrame`` con las columnas *Periodo*, *Precio observado*,
        *Precio ajustado* y *Residuo*; vacio (con esas columnas) si ``ols`` es
        ``None``.
    """
    if ols is None:
        return pd.DataFrame(columns=["Periodo", "Precio observado", "Precio ajustado", "Residuo"])
    try:
        return ols.como_dataframe_residuos()
    except Exception as exc:  # pragma: no cover - defensivo
        LOG.warning("No se pudo construir la tabla de residuos (%s)", exc)
        return pd.DataFrame(columns=["Periodo", "Precio observado", "Precio ajustado", "Residuo"])


def _texto_jarque_bera(p: float) -> str:
    """Interpretacion en espanol del contraste de normalidad."""
    if p is None or math.isnan(p):
        return "No calculable (residuos degenerados o serie demasiado corta)."
    if p > 0.05:
        return f"Residuos compatibles con la normalidad (p = {p:.4f} > 0.05)."
    return f"Se rechaza la normalidad de los residuos (p = {p:.4f} <= 0.05)."


def _texto_breusch_pagan(p: float) -> str:
    """Interpretacion en espanol del contraste de heterocedasticidad."""
    if p is None or math.isnan(p):
        return "No calculable (residuos degenerados o serie demasiado corta)."
    if p > 0.05:
        return f"Varianza de los residuos compatible con la homocedasticidad (p = {p:.4f} > 0.05)."
    return f"Indicios de heterocedasticidad: la varianza de los residuos depende del periodo (p = {p:.4f} <= 0.05)."


def _texto_durbin_watson(dw: float) -> str:
    """Interpretacion por bandas del estadistico Durbin-Watson (sin p-value)."""
    if dw is None or math.isnan(dw):
        return "No calculable (residuos nulos o serie demasiado corta)."
    if dw < DW_MIN:
        return f"Durbin-Watson = {dw:.3f} < {DW_MIN:.1f}: posible autocorrelacion positiva (el contraste no tiene p-value)."
    if dw > DW_MAX:
        return f"Durbin-Watson = {dw:.3f} > {DW_MAX:.1f}: posible autocorrelacion negativa (el contraste no tiene p-value)."
    return f"Durbin-Watson = {dw:.3f} dentro de [{DW_MIN:.1f}, {DW_MAX:.1f}]: sin autocorrelacion aparente."


def pruebas_residuos(ols: ResultadoOLS) -> pd.DataFrame:
    """Resumen de los contrastes sobre los residuos del MCO.

    Incluye Jarque-Bera (normalidad), Breusch-Pagan (heterocedasticidad) y
    Durbin-Watson (autocorrelacion). Durbin-Watson se interpreta por bandas y
    **no** tiene p-value, por lo que esa celda queda como ``NaN``.

    Args:
        ols: resultado del MCO.

    Returns:
        ``DataFrame`` con las columnas *Prueba*, *Estadistico*, *p-value* e
        *Interpretacion*.
    """
    if ols is None:
        return pd.DataFrame(columns=["Prueba", "Estadistico", "p-value", "Interpretacion"])
    filas = [
        {
            "Prueba": "Jarque-Bera (normalidad)",
            "Estadistico": float(ols.jarque_bera),
            "p-value": float(ols.jarque_bera_p),
            "Interpretacion": _texto_jarque_bera(ols.jarque_bera_p),
        },
        {
            "Prueba": "Breusch-Pagan (heterocedasticidad)",
            "Estadistico": float(ols.breusch_pagan),
            "p-value": float(ols.breusch_pagan_p),
            "Interpretacion": _texto_breusch_pagan(ols.breusch_pagan_p),
        },
        {
            "Prueba": "Durbin-Watson (autocorrelacion)",
            "Estadistico": float(ols.durbin_watson),
            "p-value": float("nan"),
            "Interpretacion": _texto_durbin_watson(ols.durbin_watson),
        },
    ]
    return pd.DataFrame(filas, columns=["Prueba", "Estadistico", "p-value", "Interpretacion"])


def interpretar(ols: ResultadoOLS) -> Dict[str, Any]:
    """Traduce el resultado del MCO a banderas booleanas para la parrilla.

    Los umbrales son los de por defecto del proyecto (``R^2 >= 0.70``,
    ``p < 0.05``), porque :class:`~dml.core.tipos.ResultadoOLS` no almacena los
    umbrales con los que se calculo el veredicto.

    Args:
        ols: resultado del MCO.

    Returns:
        Diccionario con al menos ``r2_supera_umbral``,
        ``pendiente_significativa``, ``residuos_autocorrelacionados``,
        ``residuos_normales``, ``heterocedasticidad`` y ``veredicto``. Si
        ``ols`` es ``None`` todas las banderas son ``False`` y el veredicto es
        ``N/D``.
    """
    if ols is None:
        return {
            "disponible": False,
            "r2_supera_umbral": False,
            "pendiente_significativa": False,
            "residuos_autocorrelacionados": False,
            "residuos_normales": False,
            "heterocedasticidad": False,
            "veredicto": ND,
            "justificacion": "Sin modelo econometrico: no hay suficientes datos.",
        }
    r2 = _a_flotante(ols.r2)
    p_pen = _a_flotante(ols.p_pendiente)
    dw = _a_flotante(ols.durbin_watson)
    jb_p = _a_flotante(ols.jarque_bera_p)
    bp_p = _a_flotante(ols.breusch_pagan_p)
    return {
        "disponible": True,
        "r2_supera_umbral": bool(r2 is not None and r2 >= R2_MIN_POR_DEFECTO),
        "pendiente_significativa": bool(p_pen is not None and p_pen < UMBRAL_P_POR_DEFECTO),
        "residuos_autocorrelacionados": bool(dw is not None and not (DW_MIN <= dw <= DW_MAX)),
        "residuos_normales": bool(jb_p is not None and jb_p > 0.05),
        "heterocedasticidad": bool(bp_p is not None and bp_p < 0.05),
        "veredicto": ols.veredicto or ND,
        "justificacion": ols.justificacion,
        "r2": r2,
        "p_pendiente": p_pen,
        "durbin_watson": dw,
        "jarque_bera_p": jb_p,
        "breusch_pagan_p": bp_p,
    }
