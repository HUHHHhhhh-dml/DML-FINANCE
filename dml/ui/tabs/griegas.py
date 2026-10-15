# -*- coding: utf-8 -*-
"""Pestana "Griegas": parametros, primas, griegas, paridad y verificacion por FD.

La pestana presenta el resultado ya calculado por :mod:`dml.models.blackscholes`
(``griegas_call``, ``griegas_put``, ``paridad`` y ``griegas_fd``); no recalcula el
modelo salvo para dibujar la curva de prima y Delta frente al spot, que es
puramente visual. Todas las cifras se leen de los diccionarios del
:class:`~dml.core.tipos.ResultadoAnalisis`; ninguna se inventa.

El import de :mod:`dml.models.blackscholes` es **opcional**: si el modulo o el
helper :func:`prima_vs_spot` no estuvieran disponibles, el grafico se construye
con un bucle propio sobre ``numpy`` y la pestana sigue funcionando.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.tipos import ND, ResultadoAnalisis
from ...core.util import a_float, fmt_num, fmt_pct
from ..widgets import AMBAR, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML, fila_horizontal
from .base import TabBase

LOG = logging.getLogger("dml.ui.tabs.griegas")

# --------------------------------------------------------------------------
# Import opcional del modelo de opciones
# --------------------------------------------------------------------------
try:  # pragma: no cover - depende del estado del repositorio
    from ...models.blackscholes import precio_bsm as _precio_bsm, prima_vs_spot as _prima_vs_spot

    _BS_OK = True
except Exception as _exc:  # pragma: no cover - solo si el modulo falta o falla
    LOG.warning("No se pudo importar dml.models.blackscholes (%s): el grafico usara el bucle propio", _exc)
    _precio_bsm = None  # type: ignore[assignment]
    _prima_vs_spot = None  # type: ignore[assignment]
    _BS_OK = False

# --------------------------------------------------------------------------
# Formateo
# --------------------------------------------------------------------------
#: Griegas y estadisticos: 4 decimales.
_GRIEGA: Callable[[Any], str] = lambda valor: fmt_num(valor, 4)
#: Precios: 2 decimales.
_PRECIO: Callable[[Any], str] = lambda valor: fmt_num(valor, 2)
#: Porcentajes: 2 decimales.
_PORCENTAJE: Callable[[Any], str] = lambda valor: fmt_pct(valor, 2)


def _mixto(decimales: int = 4) -> Callable[[Any], str]:
    """Formateador tolerante: numeros con ``decimales`` y texto tal cual."""

    def formato(valor: Any) -> str:
        if valor is None:
            return ND
        numero = a_float(valor)
        if numero is not None:
            return fmt_num(numero, decimales)
        return str(valor)

    return formato


def _texto(valor: Any, decimales: int = 4) -> str:
    """Formatea un valor numerico (``N/D`` si no es utilizable)."""
    return fmt_num(valor, decimales)


def _tarjeta(valor: Any, decimales: int = 4, porcentaje: bool = False) -> str:
    """Convierte un valor en texto para una tarjeta (nunca ``None``)."""
    numero = a_float(valor)
    if numero is None:
        return str(valor) if isinstance(valor, str) and valor else ND
    return fmt_pct(numero, decimales) if porcentaje else fmt_num(numero, decimales)


# --------------------------------------------------------------------------
# Definicion de la tabla de griegas: (clave, etiqueta, formula, explicacion)
# --------------------------------------------------------------------------
_FILAS_GRIEGAS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "d1",
        "d1",
        "d1 = [ln(S/K) + (b + sigma^2/2) T] / (sigma sqrt(T))",
        "Argumento de la normal del modelo; no es una griega, sino el termino auxiliar del que "
        "dependen todas las demas. Es el mismo para call y put.",
    ),
    (
        "d2",
        "d2",
        "d2 = d1 - sigma sqrt(T)",
        "Segundo argumento de la normal: la d1 desplazada por la desviacion total sigma*sqrt(T).",
    ),
    (
        "prima",
        "Prima",
        "Call = S e^((b-r)T) N(d1) - K e^(-rT) N(d2)  |  Put = K e^(-rT) N(-d2) - S e^((b-r)T) N(-d1)",
        "Valor teorico de la opcion europea (Black-Scholes-Merton generalizado con b = r - q).",
    ),
    (
        "delta",
        "Delta",
        "Call = e^((b-r)T) N(d1)  |  Put = -e^((b-r)T) N(-d1)   [Delta = dP/dS]",
        "Sensibilidad de la prima al spot. Aproximadamente la probabilidad neutral al riesgo de "
        "terminar dentro del dinero.",
    ),
    (
        "gamma",
        "Gamma",
        "Gamma = e^((b-r)T) phi(d1) / (S sigma sqrt(T))   [Gamma = d2P/dS2]",
        "Curvatura de la prima respecto del spot: cuanto cambia el Delta por unidad de spot. "
        "Misma para call y put.",
    ),
    (
        "vega",
        "Vega",
        "Vega = S e^((b-r)T) phi(d1) sqrt(T)   [Vega = dP/dsigma]",
        "Sensibilidad de la prima a un cambio de 1 unidad (100 %) en la volatilidad anual.",
    ),
    (
        "vega_1pct",
        "Vega 1%",
        "Vega 1% = Vega / 100",
        "Cambio de la prima cuando la volatilidad anual se mueve un punto porcentual (0.01).",
    ),
    (
        "theta",
        "Theta",
        "Theta = -dP/dT (por anio)",
        "Sensibilidad de la prima al paso del tiempo de calendario, expresada por anio: derivada "
        "de la prima respecto de T cambiada de signo.",
    ),
    (
        "theta_dia",
        "Theta por dia",
        "Theta dia = Theta / 365",
        "Decaimiento temporal de la prima por dia natural.",
    ),
    (
        "rho",
        "Rho",
        "Rho = dP/dr con q constante (se mueven r y b a la vez)",
        "Sensibilidad de la prima a un cambio de 1 unidad (100 %) en la tasa libre de riesgo r, "
        "manteniendo q constante y por tanto moviendo b = r - q.",
    ),
    (
        "rho_1pct",
        "Rho 1%",
        "Rho 1% = Rho / 100",
        "Cambio de la prima cuando la tasa r se mueve un punto porcentual (0.01).",
    ),
    (
        "elasticidad",
        "Elasticidad (lambda)",
        "Elasticidad = Delta * S / Prima",
        "Apalancamiento de la opcion: variacion porcentual de la prima ante una variacion "
        "porcentual del spot. N/D si la prima es 0.",
    ),
    (
        "vanna",
        "Vanna",
        "Vanna = e^((b-r)T) phi(d1) sqrt(T) [1 - d1/(sigma sqrt(T))] = (Vega/S)[1 - d1/(sigma sqrt(T))]",
        "Derivada cruzada d2P/(dS dsigma): cuanto cambia el Delta al mover la volatilidad. "
        "El signo se invierte en la put.",
    ),
    (
        "vomma",
        "Vomma",
        "Vomma = Vega * d1 * d2 / sigma = dVega/dsigma",
        "Convexidad respecto de la volatilidad: sensibilidad de Vega a la propia volatilidad. "
        "Misma para call y put.",
    ),
    (
        "sensibilidad_b",
        "Sensibilidad a b",
        "dP/db = +T * Prima (call)  |  -T * Prima (put)",
        "Sensibilidad de la prima al costo de mantener b = r - q (por ejemplo, a un cambio del "
        "dividend yield).",
    ),
)

#: Tooltips de las columnas de la tabla de griegas.
_TOOLTIPS_GRIEGAS: Dict[str, str] = {
    "Griega": "Nombre de la griega o del termino del modelo.",
    "Call": "Valor de la griega para la opcion de compra (call) con los parametros mostrados arriba.",
    "Put": "Valor de la griega para la opcion de venta (put) con los parametros mostrados arriba.",
    "Formula": "Formula exacta aplicada por dml.models.blackscholes para obtener el valor.",
}

#: Tooltips de las columnas de la tabla de paridad put-call.
_TOOLTIPS_PARIDAD: Dict[str, str] = {
    "Termino": "Elemento de la identidad de paridad put-call generalizada.",
    "Valor": "Valor numerico del termino, o el resultado de la comprobacion.",
    "Formula": "Expresion algebraica que define el termino.",
    "Nota": "Interpretacion y umbral aplicado.",
}

#: Tooltips de la tabla de verificacion por diferencias finitas.
_TOOLTIPS_FD: Dict[str, str] = {
    "Griega": "Griega contrastada.",
    "Analitico": "Valor devuelto por la formula cerrada de dml.models.blackscholes.",
    "Diferencias finitas": (
        "Aproximacion numerica centrada (delta, gamma, vega, theta, rho y sensibilidad_b) o de "
        "segundo orden (vanna, vomma) con el mismo modelo de precios."
    ),
    "Error relativo": "|analitico - numerico| / max(|analitico|, |numerico|, 1e-12).",
    "OK": "SI si el error relativo esta dentro de la tolerancia (o la diferencia absoluta es despreciable).",
}

#: Tooltips de las columnas de la tabla de parametros.
_TOOLTIPS_PARAMETROS: Dict[str, str] = {
    "Parametro": "Entrada del modelo de opciones.",
    "Valor": "Valor efectivo usado en el calculo (tasas y volatilidad en fraccion anual).",
    "Descripcion": "Significado y convencion aplicada.",
}

#: Tooltips de las columnas de la tabla de primas.
_TOOLTIPS_PRIMAS: Dict[str, str] = {
    "Magnitud": "Termino del modelo: d1, d2 o la prima de cada tipo de opcion.",
    "Valor": "Valor numerico calculado por dml.models.blackscholes.",
    "Detalle": "Formula aplicada y, si falta el dato, el motivo del N/D.",
}

#: Orden canonico de las griegas en la verificacion por diferencias finitas.
_ORDEN_FD: Tuple[str, ...] = ("delta", "gamma", "vega", "theta", "rho", "sensibilidad_b", "vanna", "vomma")


def _reponer_tooltips(tabla: TablaDML, tooltips: Dict[str, str]) -> None:
    """Vuelve a colocar los tooltips de las cabeceras de una tabla DML.

    ``TablaDML.cargar_filas`` reconstruye las cabeceras y pierde sus tooltips;
    esta funcion los restaura columna a columna.
    """
    try:
        tabla.tooltips_columnas = dict(tooltips)
    except Exception:  # pragma: no cover - defensivo
        LOG.debug("No se pudo registrar el diccionario de tooltips")
    for posicion, (_nombre, texto) in enumerate(tooltips.items()):
        item: Optional[QTableWidgetItem] = tabla.horizontalHeaderItem(posicion)
        if item is not None:
            item.setToolTip(texto)


def _colorear_celda(tabla: TablaDML, fila: int, columna: int, color: Optional[str], tooltip: str = "") -> None:
    """Colorea (y opcionalmente documenta) una celda de una tabla DML."""
    celda = tabla.item(fila, columna)
    if celda is None:
        return
    if color:
        celda.setForeground(QBrush(QColor(color)))
    if tooltip:
        celda.setToolTip(tooltip)


class PanelGraficoGriegas(QWidget):
    """Grafico interactivo de prima y Delta frente al spot, con control de rango.

    Guarda los parametros del modelo y redibuja al mover el control de rango o al
    cambiar de tema. Nunca lanza excepciones: si faltan parametros deja un
    mensaje "N/D" en el lienzo.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._params: Dict[str, Any] = {}
        self._tema = "oscuro"
        self.grafico = GraficoDML("Prima y Delta frente al spot", alto=3.4, ancho=7)
        self.grafico.setMinimumHeight(280)
        self.control = QDoubleSpinBox()
        self.control.setRange(25.0, 200.0)
        self.control.setSingleStep(5.0)
        self.control.setDecimals(0)
        self.control.setSuffix(" %")
        self.control.setValue(100.0)
        self.control.setKeyboardTracking(False)
        self.control.setToolTip(
            "Amplitud del eje X alrededor del spot actual: 100 % dibuja el rango "
            "[S*(1-1.00), S*(1+1.00)]. Solo afecta a la visualizacion, no a ningun calculo."
        )
        self.control.valueChanged.connect(self._cambio_rango)
        etiqueta = QLabel("Rango del eje X (± % sobre S)")
        etiqueta.setObjectName("subtitulo")
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(4)
        caja.addWidget(fila_horizontal(etiqueta, self.control))
        caja.addWidget(self.grafico, 1)
        self.dibujar_vacio("N/D: sin parametros del modelo de opciones")

    # ------------------------------------------------------------------- API
    def cargar(self, params: Dict[str, Any], tema: str = "oscuro") -> None:
        """Guarda los parametros del modelo y dibuja las curvas."""
        self._params = dict(params or {})
        self._dibujar(tema)

    def refrescar(self, tema: str = "oscuro") -> None:
        """Redibuja con el tema indicado."""
        self._dibujar(tema)

    def dibujar_vacio(self, mensaje: str, tema: Optional[str] = None) -> None:
        """Deja el lienzo con un mensaje claro en lugar de una curva."""
        self._tema = tema or self._tema
        self.grafico.limpiar()
        eje = self.grafico.ax
        eje.set_xticks([])
        eje.set_yticks([])
        eje.text(0.5, 0.5, mensaje, ha="center", va="center", transform=eje.transAxes, fontsize=9)
        try:
            self.grafico.aplicar_tema(self._tema)
        except Exception as exc:  # pragma: no cover - defensivo
            LOG.debug("No se pudo aplicar el tema al grafico de griegas (%s)", exc)

    # --------------------------------------------------------------- interno
    def _cambio_rango(self, _valor: float) -> None:
        """Redibuja al mover el control de rango (el factor se lee del propio control)."""
        self._dibujar(self._tema)

    @property
    def _factor_rango(self) -> float:
        """Factor de amplitud del eje X (1.0 = +-100 % sobre el spot)."""
        valor = a_float(self.control.value()) or 100.0
        return max(0.1, valor / 100.0)

    def _dibujar(self, tema: str = "oscuro") -> None:
        """Dibuja la prima (eje izquierdo) y el Delta (eje derecho) frente al spot."""
        self._tema = tema
        params = self._params
        S = a_float(params.get("S"))
        K = a_float(params.get("K"))
        T = a_float(params.get("T"))
        r = a_float(params.get("r"))
        q = a_float(params.get("q"))
        b = a_float(params.get("b"))
        sigma = a_float(params.get("sigma"))
        tipo = str(params.get("tipo") or "call").lower()
        if None in (S, K, T, r, q, b, sigma):
            self.dibujar_vacio("N/D: faltan S, K, T, r, q, b o sigma para dibujar la curva", tema)
            return
        assert S is not None and K is not None and T is not None and sigma is not None
        if S <= 0.0 or K <= 0.0 or T <= 0.0 or sigma <= 0.0:
            self.dibujar_vacio("N/D: S, K, T y sigma deben ser estrictamente positivos", tema)
            return
        mitad = max(S * self._factor_rango, 1e-9)
        minimo = max(S - mitad, 1e-9)
        maximo = max(S + mitad, minimo + 1e-9)
        try:
            spots, primas, deltas = self._rejilla(
                minimo, maximo, 121, K, T, r or 0.0, q or 0.0, b or 0.0, sigma, tipo
            )
        except Exception as exc:  # pragma: no cover - defensivo
            LOG.warning("No se pudo construir la rejilla prima/Delta vs spot (%s)", exc)
            self.dibujar_vacio(f"N/D: no se pudo dibujar la curva ({exc})", tema)
            return
        if spots.size == 0:
            self.dibujar_vacio("N/D: no hay modelo de opciones disponible para dibujar", tema)
            return

        self.grafico.limpiar()
        eje = self.grafico.ax
        eje.plot(spots, primas, linewidth=1.8, label=f"Prima {tipo.upper()}")
        eje.set_xlabel("Spot S")
        eje.set_ylabel(f"Prima de la {tipo}")
        eje.grid(True, alpha=0.25)
        eje.axvline(S, color="#f2b544", linewidth=1.2, linestyle="--", label=f"Spot actual = {S:,.2f}")
        eje.axvline(K, color="#8a939f", linewidth=1.2, linestyle=":", label=f"Strike K = {K:,.2f}")

        eje_delta = eje.twinx()
        eje_delta.plot(spots, deltas, linewidth=1.6, color="#4da3ff", label="Delta")
        eje_delta.set_ylabel("Delta")
        eje.set_title("Prima (eje izquierdo) y Delta (eje derecho) frente al spot", fontsize=9)
        lineas, etiquetas = eje.get_legend_handles_labels()
        lineas2, etiquetas2 = eje_delta.get_legend_handles_labels()
        eje.legend(lineas + lineas2, etiquetas + etiquetas2, fontsize=7, loc="best")
        self.grafico.refrescar(tema)

    def _rejilla(
        self,
        minimo: float,
        maximo: float,
        puntos: int,
        K: float,
        T: float,
        r: float,
        q: float,
        b: float,
        sigma: float,
        tipo: str,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(spots, primas, deltas)`` con el helper del modelo o con el respaldo propio."""
        if _prima_vs_spot is not None:
            try:
                spots, primas, deltas = _prima_vs_spot(minimo, maximo, puntos, K, T, r, q, b, sigma, tipo)
                return (
                    np.asarray(spots, dtype=float),
                    np.asarray(primas, dtype=float),
                    np.asarray(deltas, dtype=float),
                )
            except Exception as exc:
                LOG.warning("prima_vs_spot fallo (%s): se usa el bucle propio", exc)
        return self._rejilla_propia(minimo, maximo, puntos, K, T, r, q, b, sigma, tipo)

    @staticmethod
    def _rejilla_propia(
        minimo: float,
        maximo: float,
        puntos: int,
        K: float,
        T: float,
        r: float,
        q: float,
        b: float,
        sigma: float,
        tipo: str,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Respaldo con bucle sobre ``numpy``: prima y Delta por diferencia finita centrada.

        Solo se usa si :func:`prima_vs_spot` no esta disponible. Si tampoco lo
        esta :func:`precio_bsm`, devuelve rejillas vacias (el grafico muestra
        ``N/D`` en lugar de inventar numeros).
        """
        if _precio_bsm is None:
            return np.asarray([]), np.asarray([]), np.asarray([])
        spots = np.linspace(float(minimo), float(maximo), int(puntos), dtype=float)
        primas: List[float] = []
        deltas: List[float] = []
        for spot in spots:
            h = max(float(spot) * 1e-4, 1e-8)
            try:
                prima = _precio_bsm(float(spot), K, T, r, q, b, sigma, tipo)
                arriba = _precio_bsm(float(spot) + h, K, T, r, q, b, sigma, tipo)
                abajo = _precio_bsm(float(spot) - h, K, T, r, q, b, sigma, tipo)
                delta = (arriba - abajo) / (2.0 * h)
            except Exception as exc:  # pragma: no cover - defensivo
                LOG.debug("No se pudo valorar el spot %s (%s)", spot, exc)
                prima, delta = float("nan"), float("nan")
            primas.append(prima)
            deltas.append(delta)
        return spots, np.asarray(primas, dtype=float), np.asarray(deltas, dtype=float)


class TabGriegas(TabBase):
    """Pestana con los parametros, las griegas, la paridad y su verificacion."""

    titulo = "Griegas"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self._tarjetas_parametros = PanelTarjetas(columnas=4)
        self._tabla_parametros = TablaDML(
            ("Parametro", "Valor", "Descripcion"), tooltips_columnas=_TOOLTIPS_PARAMETROS
        )
        self._tabla_primas = TablaDML(("Magnitud", "Valor", "Detalle"), tooltips_columnas=_TOOLTIPS_PRIMAS)
        self._tabla_griegas = TablaDML(("Griega", "Call", "Put", "Formula"), tooltips_columnas=_TOOLTIPS_GRIEGAS)
        self._tabla_paridad = TablaDML(("Termino", "Valor", "Formula", "Nota"), tooltips_columnas=_TOOLTIPS_PARIDAD)
        self._tabla_fd = TablaDML(
            ("Griega", "Analitico", "Diferencias finitas", "Error relativo", "OK"),
            tooltips_columnas=_TOOLTIPS_FD,
        )
        self._panel_grafico = PanelGraficoGriegas()
        self._aviso_modelo = QLabel("")
        self._aviso_modelo.setWordWrap(True)
        self._aviso_modelo.setObjectName("aviso")
        self._aviso_modelo.setVisible(False)
        self._veredicto_fd = QLabel(ND)
        fuente = QFont()
        fuente.setPointSize(12)
        fuente.setBold(True)
        self._veredicto_fd.setFont(fuente)
        self._veredicto_fd.setWordWrap(True)
        self._nota_paridad = QLabel("")
        self._nota_paridad.setWordWrap(True)
        self._nota_paridad.setObjectName("subtitulo")
        #: Acceso comodo a la tabla principal de griegas.
        self.tabla_griegas = self._tabla_griegas
        self._construir()
        self._pintar_vacio()

    # ----------------------------------------------------------------- ayudas
    def _construir(self) -> None:
        """Monta la estructura fija de la pestana (los datos llegan en ``cargar``)."""
        self.add_titulo(
            "Griegas Black-Scholes-Merton",
            "Modelo generalizado con costo de mantener b = r - q:  "
            "Call = S e^((b-r)T) N(d1) - K e^(-rT) N(d2);  Put = K e^(-rT) N(-d2) - S e^((b-r)T) N(-d1).",
        )
        self.add(self._aviso_modelo)

        self.add(QLabel("1. Parametros de entrada"))
        self.add(self._tarjetas_parametros)
        self.add(self.scroll(self._tabla_parametros), 1)

        self.add(QLabel("2. d1, d2 y primas"))
        self.add(self.scroll(self._tabla_primas), 1)

        self.add(QLabel("3. Griegas completas (call y put)"))
        self.add(self.scroll(self._tabla_griegas), 1)

        self.add(QLabel("4. Verificacion de la paridad put-call"))
        self.add(self.scroll(self._tabla_paridad), 1)
        self.add(self._nota_paridad)

        self.add(QLabel("5. Verificacion por diferencias finitas"))
        self.add(self.scroll(self._tabla_fd), 1)
        self.add(self._veredicto_fd)

        self.add(QLabel("6. Prima y Delta frente al spot"))
        self.add(self._panel_grafico, 2)

    # ----------------------------------------------------------------- datos
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta los parametros, las griegas, la paridad y la verificacion.

        Args:
            resultados: todos los analisis disponibles.
            actual: analisis seleccionado; si es ``None`` se usa el primero.
        """
        super().cargar(resultados, actual)
        if self.resultado is None:
            self._pintar_vacio("N/D: todavia no hay ningun analisis cargado.")
            return
        try:
            self._pintar(self.resultado)
        except Exception as exc:  # pragma: no cover - defensivo: nunca romper la pestana
            LOG.exception("No se pudo pintar la pestana de griegas (%s)", exc)
            self._pintar_vacio(f"N/D: no se pudieron presentar las griegas ({exc})")

    def _parametros_efectivos(self, resultado: ResultadoAnalisis) -> Dict[str, Any]:
        """Reune los parametros del modelo a partir del resultado (sin recalcularlo)."""
        call = dict(resultado.griegas_call or {})
        put = dict(resultado.griegas_put or {})
        r = a_float(resultado.tlr)
        if r is None:
            r = self._de_config("r")
        q = a_float(resultado.q)
        if q is None:
            q = self._de_config("q")
        b = a_float(resultado.b)
        if b is None and r is not None and q is not None:
            b = r - q
        sigma = a_float(call.get("sigma"))
        if sigma is None:
            sigma = a_float(put.get("sigma"))
        if sigma is None:
            sigma = self._de_config("sigma")
        if sigma is None:
            sigma = a_float(getattr(getattr(resultado, "riesgo", None), "sigma_anual", None))
        return {
            "S": a_float(resultado.spot),
            "K": a_float(resultado.strike),
            "strike_modo": str(resultado.strike_modo or ND),
            "T": a_float(resultado.T),
            "vencimiento": resultado.vencimiento,
            "r": r,
            "q": q,
            "b": b,
            "sigma": sigma,
            "modo": str(resultado.modo or "estandar"),
            "call": call,
        }

    def _de_config(self, clave: str) -> Optional[float]:
        """Busca un parametro en la configuracion efectiva (puede venir anidada)."""
        for contenedor in (self.config.get("parametros"), self.config.get("general"), self.config):
            if isinstance(contenedor, dict) and clave in contenedor:
                valor = a_float(contenedor.get(clave))
                if valor is not None:
                    return valor
        return None

    def _pintar(self, resultado: ResultadoAnalisis) -> None:
        """Rellena todas las secciones con el resultado seleccionado."""
        params = self._parametros_efectivos(resultado)
        call = dict(resultado.griegas_call or {})
        put = dict(resultado.griegas_put or {})
        self._pintar_aviso_modo(params)
        self._pintar_parametros(params)
        self._pintar_primas(call, put)
        self._pintar_griegas(call, put)
        self._pintar_paridad(dict(resultado.paridad or {}), call, put, params)
        self._pintar_fd(dict(resultado.griegas_fd or {}))
        self._panel_grafico.cargar({**params, "tipo": "call"}, self.tema_actual)

    # ------------------------------------------------------------------ vacio
    def _pintar_vacio(self, motivo: str = "") -> None:
        """Estado "N/D": no hay griegas calculadas (la pestana nunca queda en blanco)."""
        texto = motivo or (
            "N/D: no hay griegas calculadas para este analisis. Se requieren spot, strike, plazo T "
            "y volatilidad anual (sigma) validos."
        )
        self._aviso_modelo.setText(texto)
        self._aviso_modelo.setVisible(True)
        self._tarjetas_parametros.cargar(
            {
                "S (spot)": ND,
                "K (strike)": ND,
                "Modo de strike": ND,
                "T (anios)": ND,
                "Vencimiento": ND,
                "r (TLR anual)": ND,
                "q (dividendos)": ND,
                "b = r - q": ND,
                "sigma anual": ND,
                "Modo del analisis": ND,
                "Forward teorico S e^(bT)": ND,
                "Factor e^((b-r)T)": ND,
            },
            tooltips={clave: texto for clave in (
                "S (spot)", "K (strike)", "Modo de strike", "T (anios)", "Vencimiento", "r (TLR anual)",
                "q (dividendos)", "b = r - q", "sigma anual", "Modo del analisis",
                "Forward teorico S e^(bT)", "Factor e^((b-r)T)",
            )},
            colores={},
        )
        self._tabla_parametros.formateadores = {}
        self._tabla_parametros.cargar_filas([], ["Parametro", "Valor", "Descripcion"])
        _reponer_tooltips(self._tabla_parametros, _TOOLTIPS_PARAMETROS)

        self._tabla_primas.formateadores = {"Valor": _mixto(4)}
        self._tabla_primas.cargar_filas(
            [
                {"Magnitud": "d1", "Valor": None, "Detalle": texto},
                {"Magnitud": "d2", "Valor": None, "Detalle": texto},
                {"Magnitud": "Prima call", "Valor": None, "Detalle": texto},
                {"Magnitud": "Prima put", "Valor": None, "Detalle": texto},
            ],
            ["Magnitud", "Valor", "Detalle"],
        )
        _reponer_tooltips(self._tabla_primas, _TOOLTIPS_PRIMAS)

        self._tabla_griegas.formateadores = {"Call": _GRIEGA, "Put": _GRIEGA}
        self._tabla_griegas.cargar_filas(
            [
                {"Griega": etiqueta, "Call": None, "Put": None, "Formula": formula}
                for _clave, etiqueta, formula, _explicacion in _FILAS_GRIEGAS
            ],
            ["Griega", "Call", "Put", "Formula"],
        )
        _reponer_tooltips(self._tabla_griegas, _TOOLTIPS_GRIEGAS)

        self._tabla_paridad.formateadores = {"Valor": _mixto(4)}
        self._tabla_paridad.cargar_filas([], ["Termino", "Valor", "Formula", "Nota"])
        _reponer_tooltips(self._tabla_paridad, _TOOLTIPS_PARIDAD)

        self._tabla_fd.formateadores = {
            "Analitico": _GRIEGA,
            "Diferencias finitas": _GRIEGA,
            "Error relativo": _GRIEGA,
        }
        self._tabla_fd.cargar_filas([], ["Griega", "Analitico", "Diferencias finitas", "Error relativo", "OK"])
        _reponer_tooltips(self._tabla_fd, _TOOLTIPS_FD)

        self._nota_paridad.setText(texto)
        self._veredicto_fd.setText("N/D: sin verificacion por diferencias finitas.")
        self._veredicto_fd.setStyleSheet(f"color: {ROJO};")
        self._panel_grafico.cargar({}, self.tema_actual)

    # ------------------------------------------------------------- parametros
    def _pintar_aviso_modo(self, params: Dict[str, Any]) -> None:
        """Nota visible de convenciones, con el aviso de ``modo == "excel"`` si aplica."""
        texto = (
            "[ESTÁNDAR] Este build usa el factor e^((b-r)T) multiplicando al spot en Delta, Gamma y "
            "las primas, y descuenta el strike con r (e^(-rT)) en el call y en la put. "
        )
        if str(params.get("modo", "")).lower() == "excel":
            texto += (
                "[MODO EXCEL] La hoja de calculo de referencia usaba e^(-rT) en Delta y Gamma (en "
                "lugar de e^((b-r)T)) y mezclaba r con b al descontar la put; sus cifras pueden "
                "diferir de las de esta pestana, que aplica el estandar."
            )
        self._aviso_modelo.setText(texto)
        self._aviso_modelo.setVisible(True)

    def _pintar_parametros(self, params: Dict[str, Any]) -> None:
        """Tarjetas y tabla con los parametros de entrada del modelo."""
        S, K = params["S"], params["K"]
        T, r, q, b, sigma = params["T"], params["r"], params["q"], params["b"], params["sigma"]
        modo_strike = str(params["strike_modo"] or ND)
        modo_strike_texto = {
            "forward": "forward (K = S e^(bT))",
            "manual": "manual (K introducido a mano)",
        }.get(modo_strike.lower(), modo_strike)
        vencimiento = params["vencimiento"]
        if hasattr(vencimiento, "isoformat"):
            vencimiento_texto = vencimiento.isoformat()
        elif vencimiento:
            vencimiento_texto = str(vencimiento)
        else:
            vencimiento_texto = ND
        forward = self._forward(S, b, T)
        factor = a_float((params.get("call") or {}).get("factor_e_b_r_t")) if params.get("call") else None
        if factor is None and b is not None and r is not None and T is not None:
            exponente = (float(b) - float(r)) * float(T)
            factor = math.exp(exponente) if abs(exponente) < 700.0 else None

        self._tarjetas_parametros.cargar(
            {
                "S (spot)": _tarjeta(S, 2),
                "K (strike)": _tarjeta(K, 2),
                "Modo de strike": modo_strike_texto,
                "T (anios)": _tarjeta(T, 4),
                "Vencimiento": vencimiento_texto,
                "r (TLR anual)": _tarjeta(r, 2, porcentaje=True),
                "q (dividendos)": _tarjeta(q, 2, porcentaje=True),
                "b = r - q": _tarjeta(b, 2, porcentaje=True),
                "sigma anual": _tarjeta(sigma, 2, porcentaje=True),
                "Modo del analisis": str(params["modo"]),
                "Forward teorico S e^(bT)": _tarjeta(forward, 2),
                "Factor e^((b-r)T)": _tarjeta(factor, 6),
            },
            tooltips={
                "S (spot)": "Precio actual del subyacente (S > 0).",
                "K (strike)": "Precio de ejercicio usado en el modelo; su origen se indica en 'Modo de strike'.",
                "Modo de strike": "forward = K tomado como S e^(bT) (strike = forward); manual = K introducido.",
                "T (anios)": "Tiempo al vencimiento en anios (dias hasta el vencimiento / 365).",
                "Vencimiento": "Fecha de vencimiento de la opcion (T ya esta expresado en anios).",
                "r (TLR anual)": "Tasa libre de riesgo anual en capitalizacion continua (TLR de 4 semanas, T-Bill).",
                "q (dividendos)": "Dividend yield anual en fraccion (0.02 = 2 %).",
                "b = r - q": "Costo de mantener: b = r - q (para opciones sobre futuros seria b = 0).",
                "sigma anual": "Volatilidad ANUAL en fraccion (0.35 = 35 %); es la sigma que exige Black-Scholes.",
                "Modo del analisis": "estandar = modelo generalizado; excel = reproduce la hoja de referencia.",
                "Forward teorico S e^(bT)": "Precio forward teorico del subyacente.",
                "Factor e^((b-r)T)": "Factor que multiplica al spot en Delta, Gamma y en las primas.",
            },
            colores={},
        )

        filas = [
            {
                "Parametro": "S (spot)",
                "Valor": _texto(S, 2),
                "Descripcion": "Precio actual del subyacente.",
            },
            {
                "Parametro": "K (strike)",
                "Valor": _texto(K, 2),
                "Descripcion": f"Origen del strike: {modo_strike_texto}.",
            },
            {
                "Parametro": "T (anios)",
                "Valor": _texto(T, 4),
                "Descripcion": f"Tiempo al vencimiento en anios; fecha de vencimiento: {vencimiento_texto}.",
            },
            {
                "Parametro": "r (TLR anual continua)",
                "Valor": fmt_pct(r, 2),
                "Descripcion": "Tasa libre de riesgo anual en capitalizacion continua.",
            },
            {
                "Parametro": "q (dividend yield anual)",
                "Valor": fmt_pct(q, 2),
                "Descripcion": "Rendimiento por dividendos anual en fraccion.",
            },
            {
                "Parametro": "b = r - q",
                "Valor": fmt_pct(b, 2),
                "Descripcion": "Costo de mantener del subyacente.",
            },
            {
                "Parametro": "sigma (ANUAL)",
                "Valor": fmt_pct(sigma, 2),
                "Descripcion": "Volatilidad anual en fraccion, exigida por Black-Scholes.",
            },
            {
                "Parametro": "Forward teorico S e^(bT)",
                "Valor": _texto(forward, 2),
                "Descripcion": "Precio forward teorico; es el strike por defecto en el modo forward.",
            },
            {
                "Parametro": "Factor e^((b-r)T)",
                "Valor": _texto(factor, 6),
                "Descripcion": "Factor multiplicativo del spot en el modelo [ESTÁNDAR].",
            },
            {
                "Parametro": "Modo del analisis",
                "Valor": str(params["modo"]),
                "Descripcion": "estandar = modelo generalizado; excel = hoja de referencia.",
            },
        ]
        self._tabla_parametros.formateadores = {}
        self._tabla_parametros.cargar_filas(filas, ["Parametro", "Valor", "Descripcion"])
        _reponer_tooltips(self._tabla_parametros, _TOOLTIPS_PARAMETROS)

    @staticmethod
    def _forward(S: Optional[float], b: Optional[float], T: Optional[float]) -> Optional[float]:
        """Forward teorico ``S e^(bT)`` sin desbordar."""
        if S is None or b is None or T is None:
            return None
        exponente = float(b) * float(T)
        if abs(exponente) >= 700.0:
            return None
        try:
            return float(S) * math.exp(exponente)
        except (OverflowError, ValueError) as exc:  # pragma: no cover - defensivo
            LOG.debug("No se pudo calcular el forward teorico (%s)", exc)
            return None

    # ----------------------------------------------------------------- primas
    def _pintar_primas(self, call: Dict[str, Any], put: Dict[str, Any]) -> None:
        """Tabla con d1, d2 y las primas de call y put."""
        d1 = a_float(call.get("d1"))
        d2 = a_float(call.get("d2"))
        if d1 is None:
            d1 = a_float(put.get("d1"))
        if d2 is None:
            d2 = a_float(put.get("d2"))
        prima_call = a_float(call.get("prima"))
        prima_put = a_float(put.get("prima"))
        motivos: List[str] = []
        if d1 is None or d2 is None:
            motivos.append("No se pudieron calcular d1/d2 (faltan S, K, T, b o sigma validos).")
        if prima_call is None or prima_put is None:
            motivos.append("No se pudieron valorar las primas con los parametros disponibles.")
        motivo = " ".join(motivos) or "N/D: dato no disponible."
        filas = [
            {
                "Magnitud": "d1",
                "Valor": d1,
                "Detalle": "d1 = [ln(S/K) + (b + sigma^2/2) T] / (sigma sqrt(T)); comun a call y put.",
            },
            {
                "Magnitud": "d2",
                "Valor": d2,
                "Detalle": "d2 = d1 - sigma sqrt(T).",
            },
            {
                "Magnitud": "Prima call",
                "Valor": prima_call,
                "Detalle": "Call = S e^((b-r)T) N(d1) - K e^(-rT) N(d2).",
            },
            {
                "Magnitud": "Prima put",
                "Valor": prima_put,
                "Detalle": "Put = K e^(-rT) N(-d2) - S e^((b-r)T) N(-d1).",
            },
        ]
        self._tabla_primas.formateadores = {"Valor": _mixto(4)}
        self._tabla_primas.cargar_filas(filas, ["Magnitud", "Valor", "Detalle"])
        _reponer_tooltips(self._tabla_primas, _TOOLTIPS_PRIMAS)
        for indice, fila in enumerate(filas):
            for columna in range(self._tabla_primas.columnCount()):
                celda = self._tabla_primas.item(indice, columna)
                if celda is None:
                    continue
                if fila["Valor"] is None:
                    celda.setToolTip(motivo)
                    celda.setForeground(QBrush(QColor(AMBAR)))
                else:
                    celda.setToolTip(f"{fila['Detalle']}  Valor = {_texto(fila['Valor'], 6)}")

    # ---------------------------------------------------------------- griegas
    def _pintar_griegas(self, call: Dict[str, Any], put: Dict[str, Any]) -> None:
        """Tabla completa de griegas con la formula en cada fila."""
        filas: List[Dict[str, Any]] = []
        for clave, etiqueta, formula, explicacion in _FILAS_GRIEGAS:
            filas.append(
                {
                    "Griega": etiqueta,
                    "Call": a_float(call.get(clave)),
                    "Put": a_float(put.get(clave)),
                    "Formula": formula,
                    "_formula": formula,
                    "_explicacion": explicacion,
                }
            )
        self._tabla_griegas.formateadores = {"Call": _GRIEGA, "Put": _GRIEGA}
        self._tabla_griegas.cargar_filas(filas, ["Griega", "Call", "Put", "Formula"])
        _reponer_tooltips(self._tabla_griegas, _TOOLTIPS_GRIEGAS)
        for indice, fila in enumerate(filas):
            for columna in range(self._tabla_griegas.columnCount()):
                celda = self._tabla_griegas.item(indice, columna)
                if celda is None:
                    continue
                if str(fila["Griega"]).lower() in {"d1", "d2"} and columna in {1, 2}:
                    celda.setToolTip(
                        f"{fila['_formula']}. {fila['_explicacion']} (el mismo valor para call y put)"
                    )
                elif celda.text().strip() == ND:
                    celda.setToolTip(f"N/D: dato no disponible. {fila['_formula']}. {fila['_explicacion']}")
                    celda.setForeground(QBrush(QColor(AMBAR)))
                else:
                    celda.setToolTip(f"{fila['_formula']}. {fila['_explicacion']}")

    # ---------------------------------------------------------------- paridad
    def _pintar_paridad(
        self, paridad: Dict[str, Any], call: Dict[str, Any], put: Dict[str, Any], params: Dict[str, Any]
    ) -> None:
        """Tabla de la paridad put-call, su tolerancia y el resultado."""
        prima_call, prima_put = a_float(call.get("prima")), a_float(put.get("prima"))
        c_p = a_float(paridad.get("c_p"))
        if c_p is None and prima_call is not None and prima_put is not None:
            c_p = prima_call - prima_put
        derecha = a_float(paridad.get("forward_descontado"))
        if derecha is None:
            S, K, T = params["S"], params["K"], params["T"]
            r, b = params["r"], params["b"]
            factor = None
            if S is not None and b is not None and r is not None and T is not None:
                exponente = (float(b) - float(r)) * float(T)
                factor = math.exp(exponente) if abs(exponente) < 700.0 else None
            descuento_k = None
            if K is not None and r is not None and T is not None:
                exponente = -float(r) * float(T)
                descuento_k = float(K) * math.exp(exponente) if abs(exponente) < 700.0 else None
            if S is not None and factor is not None and descuento_k is not None:
                derecha = float(S) * factor - descuento_k
        diferencia = a_float(paridad.get("diferencia"))
        if diferencia is None and c_p is not None and derecha is not None:
            diferencia = c_p - derecha
        tolerancia = a_float(paridad.get("tolerancia"))
        ok_crudo = paridad.get("ok")
        cumple: Optional[bool] = bool(ok_crudo) if ok_crudo is not None else None
        if cumple is None and diferencia is not None and tolerancia is not None and derecha is not None:
            cumple = abs(diferencia) <= tolerancia * max(1.0, abs(derecha))
        nota_resultado = (
            "N/D: no hay verificacion de paridad disponible."
            if cumple is None
            else (
                "La paridad se cumple dentro de la tolerancia configurada."
                if cumple
                else "La paridad NO se cumple dentro de la tolerancia configurada."
            )
        )
        filas = [
            {
                "Termino": "Call - Put",
                "Valor": c_p,
                "Formula": "C - P",
                "Nota": "Diferencia de las primas calculadas por el modelo.",
            },
            {
                "Termino": "S e^((b-r)T) - K e^(-rT)",
                "Valor": derecha,
                "Formula": "S e^((b-r)T) - K e^(-rT)",
                "Nota": "Valor teorico de la paridad put-call generalizada.",
            },
            {
                "Termino": "Diferencia (C - P) - [S e^((b-r)T) - K e^(-rT)]",
                "Valor": diferencia,
                "Formula": "(C - P) - (S e^((b-r)T) - K e^(-rT))",
                "Nota": "Error absoluto de la identidad: debe ser practicamente 0.",
            },
            {
                "Termino": "Tolerancia",
                "Valor": tolerancia,
                "Formula": "tolerancia * max(1, |S e^((b-r)T) - K e^(-rT)|)",
                "Nota": "Umbral configurado en el modelo para aceptar la paridad.",
            },
            {
                "Termino": "Resultado",
                "Valor": "CUMPLE" if cumple else ("NO CUMPLE" if cumple is not None else ND),
                "Formula": "|diferencia| <= tolerancia",
                "Nota": nota_resultado,
            },
        ]
        self._tabla_paridad.formateadores = {"Valor": _mixto(4)}
        self._tabla_paridad.cargar_filas(filas, ["Termino", "Valor", "Formula", "Nota"])
        _reponer_tooltips(self._tabla_paridad, _TOOLTIPS_PARIDAD)
        for indice, fila in enumerate(filas):
            color: Optional[str] = None
            tooltip = str(fila["Nota"])
            if fila["Termino"] == "Resultado":
                color = VERDE if cumple else (ROJO if cumple is not None else AMBAR)
                tooltip = f"{nota_resultado} Tolerancia = {_texto(tolerancia, 8)}."
            elif fila["Valor"] is None:
                color = AMBAR
                tooltip = f"N/D: dato no disponible. {fila['Formula']}."
            for columna in range(self._tabla_paridad.columnCount()):
                _colorear_celda(self._tabla_paridad, indice, columna, color, tooltip)

        if cumple is None:
            mensaje = "Paridad put-call C - P = S e^((b-r)T) - K e^(-rT): N/D (no hay verificacion disponible)."
        elif cumple:
            mensaje = (
                f"Paridad put-call C - P = S e^((b-r)T) - K e^(-rT): SE CUMPLE "
                f"(diferencia = {_texto(diferencia, 8)}, tolerancia = {_texto(tolerancia, 8)})."
            )
        else:
            mensaje = (
                f"Paridad put-call C - P = S e^((b-r)T) - K e^(-rT): NO SE CUMPLE "
                f"(diferencia = {_texto(diferencia, 8)}, tolerancia = {_texto(tolerancia, 8)})."
            )
        self._nota_paridad.setText(mensaje)

    # ------------------------------------------------------- diferencias finitas
    def _pintar_fd(self, griegas_fd: Dict[str, Any]) -> None:
        """Tabla de verificacion por diferencias finitas y veredicto global."""
        detalle = griegas_fd.get("detalle") if isinstance(griegas_fd, dict) else None
        tolerancia = a_float(griegas_fd.get("tolerancia")) if isinstance(griegas_fd, dict) else None
        ok_global = griegas_fd.get("ok") if isinstance(griegas_fd, dict) else None
        filas: List[Dict[str, Any]] = []
        if isinstance(detalle, dict) and detalle:
            claves = [clave for clave in _ORDEN_FD if clave in detalle]
            claves += [clave for clave in detalle if clave not in claves]
            for clave in claves:
                datos = detalle.get(clave) or {}
                error = a_float(datos.get("error_relativo"))
                ok = datos.get("ok")
                if ok is None and error is not None and tolerancia is not None:
                    ok = error <= tolerancia
                filas.append(
                    {
                        "Griega": self._nombre_griega(clave),
                        "Analitico": a_float(datos.get("analitico")),
                        "Diferencias finitas": a_float(datos.get("diferencias_finitas")),
                        "Error relativo": error,
                        "OK": "SI" if ok else ("NO" if ok is not None else ND),
                        "_ok": bool(ok) if ok is not None else None,
                    }
                )
        self._tabla_fd.formateadores = {
            "Analitico": _GRIEGA,
            "Diferencias finitas": _GRIEGA,
            "Error relativo": _GRIEGA,
        }
        self._tabla_fd.cargar_filas(filas, ["Griega", "Analitico", "Diferencias finitas", "Error relativo", "OK"])
        _reponer_tooltips(self._tabla_fd, _TOOLTIPS_FD)
        for indice, fila in enumerate(filas):
            estado = fila["_ok"]
            if estado is None:
                color, tooltip = AMBAR, "N/D: sin dato de la verificacion por diferencias finitas."
            elif estado:
                color, tooltip = VERDE, "Coincide con la aproximacion numerica dentro de la tolerancia."
            else:
                color, tooltip = ROJO, "REVISAR: la formula analitica y la diferencia finita no coinciden."
            for columna in range(self._tabla_fd.columnCount()):
                _colorear_celda(self._tabla_fd, indice, columna, color, tooltip)

        if not filas:
            self._veredicto_fd.setText("N/D: no hay verificacion por diferencias finitas disponible.")
            self._veredicto_fd.setStyleSheet(f"color: {ROJO};")
            return
        aciertos = sum(1 for fila in filas if fila["_ok"])
        correcto = bool(ok_global) if ok_global is not None else aciertos == len(filas)
        texto = (
            f"Veredicto: {aciertos} de {len(filas)} griegas coinciden con su aproximacion por diferencias "
            f"finitas (tolerancia = {_texto(tolerancia, 6)}). "
            + ("Verificacion CORRECTA." if correcto else "Revisar las griegas marcadas con NO.")
        )
        self._veredicto_fd.setText(texto)
        self._veredicto_fd.setStyleSheet(f"color: {VERDE if correcto else ROJO};")

    @staticmethod
    def _nombre_griega(clave: str) -> str:
        """Nombre legible de una griega a partir de su clave."""
        for clave_fila, etiqueta, _formula, _explicacion in _FILAS_GRIEGAS:
            if clave_fila == clave:
                return etiqueta
        return str(clave)

    # -------------------------------------------------------------------- tema
    def refrescar_tema(self, tema: str) -> None:
        """Aplica el tema al grafico y lo redibuja (nunca lanza excepciones).

        Si el grafico ya esta pintado con ese tema no se vuelve a dibujar la curva
        de primas y Delta.
        """
        if not self._refrescar_graficos(tema, self._panel_grafico):
            return
        try:
            self._panel_grafico.refrescar(tema)
        except Exception as exc:  # pragma: no cover - defensivo
            LOG.debug("No se pudo refrescar el grafico de griegas (%s)", exc)
        self._graficos_al_dia(tema)


__all__ = ["TabGriegas", "PanelGraficoGriegas"]
