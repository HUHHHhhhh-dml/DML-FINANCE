# -*- coding: utf-8 -*-
"""Pestana "RDR": Rendimiento sobre Riesgo (Rend_CAPM frente a la sigma) y criterio 8.

Bloques de la pestana:

1. Tarjetas con el ``Rend_CAPM``, el riesgo (sigma anual), el cociente
   ``Rend_CAPM / Riesgo``, su diferencia y el estado del criterio 8.
2. Cuadro de comparacion ``Rendimiento`` vs ``Riesgo`` con la formula
   ``RDR = Rend_CAPM / Riesgo`` y la regla del criterio
   (``Rend_CAPM > sigma anual``) en el tooltip.
3. Bloque de riesgo completo: tabla de :func:`dml.models.riesgo.tabla_riesgo`
   (sigma mensual y anual, varianza total, sistematica y no sistematica,
   VaR 95 % y 99 %, Sharpe, Treynor y maxima caida) con una explicacion en el
   tooltip de cada fila.
4. Estado del criterio 8 (``self.resultado.criterios``) con su calificacion.
5. Nota visible de ``riesgo.nota_sigma``: explica el convenio
   mensual/anual de la volatilidad y el aviso del modo ``excel``.
6. Grafico de barras: rendimiento frente a riesgo y los niveles de VaR.

Ningun dato se inventa: si falta el rendimiento o la sigma se muestra ``N/D`` con
el motivo y el criterio 8 se califica 0.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.fundamentales import rdr
from ...models.riesgo import tabla_riesgo
from ..estilos import colores
from ..widgets import AMBAR, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.rdr")

# ---------------------------------------------------------------- formulas
FORMULA_RDR = "RDR = Rend_CAPM / Riesgo (sigma anual)"
FORMULA_DIFERENCIA = "Diferencia = Rend_CAPM - Riesgo (sigma anual)"
FORMULA_CRITERIO = "Criterio 8: RDR - Rend_CAPM > Riesgo (desviacion estandar anual)"
FORMULA_SIGMA = "sigma_anual = sigma_mensual x SQRT(12) [ESTANDAR]"

# ---------------------------------------------------------------- columnas
COLUMNAS_COMPARACION: List[str] = [
    "Indicador",
    "Rendimiento (Rend_CAPM)",
    "Riesgo (sigma anual)",
    "Cociente Rend/Riesgo",
    "Diferencia",
    "Resultado",
    "Formula",
]
COLUMNAS_RIESGO: List[str] = ["Metrica", "Valor", "Formula"]
COLUMNAS_CRITERIO: List[str] = [
    "#",
    "Criterio",
    "Optimo",
    "Estado",
    "Calificacion",
    "Valor obtenido",
    "Valor de comparacion",
    "Fuente",
    "Ruta Investing",
    "Nota",
]
COLUMNAS_ORIGEN: List[str] = ["Dato", "Valor", "Fuente", "Metodo", "URL", "Ruta Investing", "Nota"]

#: Explicacion (tooltip) de cada fila de la tabla de riesgo.
EXPLICACION_RIESGO: Dict[str, str] = {
    "Sigma mensual": (
        "Desviacion tipica MUESTRAL (ddof=1) de los rendimientos mensuales de la accion: "
        "STDEV.S(rendimientos mensuales)."
    ),
    "Sigma anual": (
        f"{FORMULA_SIGMA}. Es la medida de riesgo que usa el criterio 8 y la que entra en Black-Scholes. "
        "En modo excel se informa la sigma mensual sin anualizar y queda avisado en la nota."
    ),
    "Riesgo total (varianza)": (
        "Varianza muestral de los rendimientos mensuales: VAR.S(rendimientos de la accion). Se expresa en tanto "
        "por uno al cuadrado, no en porcentaje."
    ),
    "Riesgo sistematico": (
        "Parte de la varianza que explica el mercado: Beta^2 x VAR.S(rendimientos del mercado). No es "
        "diversificable."
    ),
    "Riesgo no sistematico": (
        "Riesgo diversificable: varianza total - riesgo sistematico (nunca negativo)."
    ),
    "VaR 95%": (
        "VaR parametrico mensual al 95 %: mu + NORM.S.INV(0,05) x sigma_mensual. Se informa como rendimiento "
        "(normalmente negativo): perdida esperada en un mes malo de cada 20."
    ),
    "VaR 99%": (
        "VaR parametrico mensual al 99 %: mu + NORM.S.INV(0,01) x sigma_mensual (perdida esperada en un mes malo "
        "de cada 100)."
    ),
    "Sharpe": (
        "Rentabilidad por unidad de riesgo total: (R anual - TLR) / sigma anual. R anual = media mensual x 12."
    ),
    "Treynor": (
        "Rentabilidad por unidad de riesgo sistematico: (R anual - TLR) / Beta."
    ),
    "Maxima caida": (
        "Peor caida desde un maximo previo: MIN((P - MAX acumulado) / MAX acumulado). Es el riesgo de la serie "
        "de precios, no del rendimiento mensual."
    ),
}

#: Unidad de cada metrica de riesgo (para formatear su valor).
UNIDADES_RIESGO: Dict[str, str] = {
    "Sigma mensual": "porcentaje",
    "Sigma anual": "porcentaje",
    "Riesgo total (varianza)": "numero",
    "Riesgo sistematico": "numero",
    "Riesgo no sistematico": "numero",
    "VaR 95%": "porcentaje",
    "VaR 99%": "porcentaje",
    "Sharpe": "numero",
    "Treynor": "numero",
    "Maxima caida": "porcentaje",
}

TOOLTIPS_COMPARACION: Dict[str, str] = {
    "Indicador": "Indicador comparado.",
    "Rendimiento (Rend_CAPM)": "Rendimiento esperado por el CAPM: TLR + Beta x PRH (ver pestana CAPM).",
    "Riesgo (sigma anual)": f"Volatilidad anual de la accion. {FORMULA_SIGMA}.",
    "Cociente Rend/Riesgo": FORMULA_RDR,
    "Diferencia": FORMULA_DIFERENCIA,
    "Resultado": FORMULA_CRITERIO,
    "Formula": "Formula exacta del indicador.",
}
TOOLTIPS_RIESGO: Dict[str, str] = {
    "Metrica": "Metrica de riesgo calculada sobre los rendimientos mensuales; cada fila tiene su explicacion.",
    "Valor": "Valor de la metrica (porcentaje, tanto por uno o ratio segun la fila).",
    "Formula": "Formula exacta con la que se calcula la metrica.",
}
TOOLTIPS_CRITERIO: Dict[str, str] = {
    "#": "Numero del criterio en la parrilla de decision del pliego.",
    "Criterio": "Enunciado del criterio.",
    "Optimo": "Sentido en el que el criterio se cumple.",
    "Estado": "CUMPLE (1 punto), NO CUMPLE (0 puntos) o N/D (dato ausente, 0 puntos).",
    "Calificacion": "1 si cumple, 0 si no cumple o si el dato es N/D.",
    "Valor obtenido": "Rend_CAPM (rendimiento esperado).",
    "Valor de comparacion": "Riesgo: sigma anual de los rendimientos.",
    "Fuente": "Origen declarado del dato del criterio.",
    "Ruta Investing": "Pagina de Investing.com donde comprobar el dato a mano.",
    "Nota": "Motivo cuando el dato es N/D y la nota de la parrilla.",
}
TOOLTIPS_ORIGEN: Dict[str, str] = {
    "Dato": "Dato mostrado.",
    "Valor": "Valor del dato (formato segun su naturaleza).",
    "Fuente": "Fuente declarada del dato.",
    "Metodo": "API, scraping, respaldo, manual, demo o calculo.",
    "URL": "URL consultada o ruta equivalente de Investing.com.",
    "Ruta Investing": "Pagina de Investing.com donde localizar el dato a mano.",
    "Nota": "Observaciones y motivo cuando el dato es N/D.",
}

SIMBOLOS: Dict[str, str] = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "MXN": "MX$",
    "ARS": "$",
}


# --------------------------------------------------------------------------
# Utilidades locales de la pestana.
# --------------------------------------------------------------------------


def _simbolo(moneda: str = "USD") -> str:
    """Simbolo de la divisa (``$`` si se desconoce)."""
    return SIMBOLOS.get(str(moneda or "USD").upper(), "$")


def _moneda(valor: Any, moneda: str = "USD", decimales: int = 2) -> str:
    """Formatea un importe con el simbolo de la divisa (``N/D`` si falta)."""
    return fmt_moneda(valor, decimales, _simbolo(moneda))


def _titulo(caja: QVBoxLayout, texto: str, subtitulo: str = "") -> QLabel:
    """Anade un titulo (y un subtitulo opcional) a una caja vertical."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("titulo")
    caja.addWidget(etiqueta)
    if subtitulo:
        sub = QLabel(subtitulo)
        sub.setObjectName("subtitulo")
        sub.setWordWrap(True)
        caja.addWidget(sub)
    return etiqueta


def _aviso(caja: QVBoxLayout, texto: str) -> QLabel:
    """Anade una etiqueta de aviso seleccionable con ajuste de linea."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("aviso")
    etiqueta.setWordWrap(True)
    etiqueta.setTextInteractionFlags(Qt.TextSelectableByMouse)
    caja.addWidget(etiqueta)
    return etiqueta


def _etiqueta_estado(caja: QVBoxLayout, texto: str, color: str) -> QLabel:
    """Etiqueta de estado coloreada (CUMPLE / NO CUMPLE / N/D)."""
    etiqueta = QLabel(texto)
    etiqueta.setWordWrap(True)
    etiqueta.setStyleSheet(f"color: {color}; font-weight: bold;")
    etiqueta.setTextInteractionFlags(Qt.TextSelectableByMouse)
    caja.addWidget(etiqueta)
    return etiqueta


def _criterio(resultado: ResultadoAnalisis, numero: int) -> Optional[Criterio]:
    """Devuelve el criterio ``numero`` de la parrilla, o ``None`` si no existe."""
    for criterio in resultado.criterios:
        if criterio.numero == numero:
            return criterio
    return None


def _ruta(resultado: ResultadoAnalisis, clave: str) -> str:
    """URL de Investing.com registrada para ``clave`` (``N/D`` si no hay)."""
    rutas = resultado.ruta_investing or {}
    return str(rutas.get(clave, "") or "")


def _texto_ruta(resultado: ResultadoAnalisis, clave: str, etiqueta: str) -> str:
    """Texto de la ruta de Investing.com, con ``N/D`` si no esta registrada."""
    url = _ruta(resultado, clave)
    if not url:
        return f"N/D: ruta de Investing.com no disponible ({etiqueta})"
    return f"{etiqueta}: {url}"


def _fila_origen(dato: str, valor: Any, ev: Optional[Evidence], ruta: str = "", nota: str = "") -> Dict[str, Any]:
    """Fila de la tabla de procedencia de un dato."""
    evidencia = ev if ev is not None else Evidence()
    return {
        "Dato": dato,
        "Valor": valor,
        "Fuente": evidencia.fuente or ND,
        "Metodo": evidencia.metodo or ND,
        "URL": evidencia.url or ruta or ND,
        "Ruta Investing": ruta or ND,
        "Nota": evidencia.nota or nota or ND,
    }


def _fila_criterio(criterio: Optional[Criterio], numero: int, nombre: str, optimo: str) -> Dict[str, Any]:
    """Fila de la tabla de estado de un criterio de la parrilla."""
    if criterio is None:
        return {
            "#": numero,
            "Criterio": nombre,
            "Optimo": optimo,
            "Estado": ND,
            "Calificacion": None,
            "Valor obtenido": None,
            "Valor de comparacion": None,
            "Fuente": ND,
            "Ruta Investing": ND,
            "Nota": f"N/D: el criterio {numero} no esta en la parrilla (no se pudo evaluar); se califica 0",
        }
    return {
        "#": criterio.numero,
        "Criterio": criterio.nombre or nombre,
        "Optimo": criterio.optimo or optimo,
        "Estado": "CUMPLE" if criterio.cumple else "NO CUMPLE",
        "Calificacion": criterio.calificacion,
        "Valor obtenido": criterio.valor,
        "Valor de comparacion": criterio.comparacion,
        "Fuente": criterio.fuente or ND,
        "Ruta Investing": criterio.ruta or ND,
        "Nota": criterio.nota or ND,
    }


def _color_estado(indice: int) -> Callable[[int, int, Any], Optional[str]]:
    """Colores condicionales de la columna de estado (verde/rojo/ambar)."""

    def _color(fila: int, columna: int, valor: Any) -> Optional[str]:
        if columna != indice:
            return None
        texto = str(valor if valor is not None else "").strip().upper()
        if texto in {"CUMPLE", "SI"}:
            return VERDE
        if texto in {"NO CUMPLE", "NO"}:
            return ROJO
        return AMBAR

    return _color


def _color_criterio(criterio: Optional[Criterio]) -> str:
    """Color del estado de un criterio (ambar si no se pudo evaluar)."""
    if criterio is None:
        return AMBAR
    return VERDE if criterio.cumple else ROJO


def _texto_criterio(criterio: Optional[Criterio], numero: int, nombre: str) -> str:
    """Texto del estado del criterio para la etiqueta destacada."""
    if criterio is None:
        return f"Criterio {numero} - {nombre}: N/D (el criterio no esta en la parrilla y se califica 0)."
    estado = "CUMPLE" if criterio.cumple else "NO CUMPLE"
    detalle = f" - {criterio.nota}" if criterio.nota else ""
    return f"Criterio {numero} - {criterio.nombre or nombre}: {estado} (calificacion {criterio.calificacion}/1){detalle}"


def _formato_unidad(valor: Any, unidad: str, moneda: str = "USD") -> Optional[str]:
    """Formatea el valor de un criterio o metrica segun su unidad declarada."""
    if valor is None:
        return None
    if isinstance(valor, str) and valor.strip() in {"", ND}:
        return None
    if unidad == "porcentaje":
        return fmt_pct(valor, 2)
    if unidad == "moneda":
        return _moneda(valor, moneda, 2)
    if unidad == "texto":
        return str(valor)
    return fmt_num(valor, 4)


def _aplicar_formatos(tabla: TablaDML, columna: int, textos: Sequence[Optional[str]]) -> None:
    """Reescribe una columna con un texto por fila (``None`` deja la celda ``N/D``)."""
    for fila, texto in enumerate(textos):
        if texto is None:
            continue
        celda = tabla.item(fila, columna)
        if celda is None:
            celda = QTableWidgetItem(texto)
            tabla.setItem(fila, columna, celda)
        else:
            celda.setText(texto)
        celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)


class TabRDR(TabConGrafico):
    """Pestana del RDR: rendimiento esperado frente al riesgo (criterio 8)."""

    titulo = "RDR"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self._grafico: Optional[GraficoDML] = None
        self._mostrar_vacio()

    # ------------------------------------------------------------------ API
    # --------------------------------------------------------------- pintado
    def _limpiar(self) -> None:
        """Vacia la caja de la pestana antes de repintarla."""
        while self._caja.count():
            elemento = self._caja.takeAt(0)
            widget = elemento.widget() if elemento is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._grafico = None

    def _mostrar_vacio(self) -> None:
        """Estado vacio: no hay ningun analisis cargado."""
        contenedor = QWidget()
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.setSpacing(8)
        self.add(contenedor, 1)
        _titulo(caja, "RDR - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para comparar el "
            f"Rend_CAPM con el riesgo ({FORMULA_RDR}) y evaluar el criterio 8.",
        )

    def _subtitulo(self, r: ResultadoAnalisis) -> str:
        """Linea de contexto del analisis mostrado."""
        partes = [f"Ticker {r.ticker}"]
        partes.append(f"Modo {r.modo}")
        partes.append(f"Rend_CAPM {fmt_pct(r.rend_capm, 2)}")
        partes.append(f"Sigma anual {fmt_pct(r.riesgo.sigma_anual, 2)}")
        if r.demo:
            partes.append("MODO DEMO: datos ficticios")
        return " | ".join(partes)

    def _construir(self, r: ResultadoAnalisis) -> None:
        """Construye todos los bloques de la pestana."""
        contenedor = QWidget()
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.setSpacing(8)
        self.add(contenedor, 1)

        _titulo(caja, f"RDR - {r.ticker}", self._subtitulo(r))
        self._bloque_nota_sigma(caja, r)
        self._bloque_tarjetas(caja, r)
        self._bloque_comparacion(caja, r)
        self._bloque_riesgo(caja, r)
        self._bloque_criterio(caja, r)
        self._bloque_procedencia(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------- nota de la sigma
    def _bloque_nota_sigma(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Nota visible del convenio de la volatilidad (mensual vs anual)."""
        nota = (r.riesgo.nota_sigma or "").strip()
        if nota:
            _aviso(caja, f"Convenio de la volatilidad: {nota}")
        else:
            _aviso(
                caja,
                "N/D: el bloque de riesgo no deja nota del convenio de la sigma; se asume la sigma anual "
                f"({FORMULA_SIGMA}) y el criterio 8 se califica 0 si falta la sigma.",
            )
        if r.modo == "excel":
            _aviso(
                caja,
                "[MODO EXCEL] Aviso visible: la sigma de riesgo es MENSUAL y NO se anualiza, mientras que el "
                "Rend_CAPM se construye con magnitudes mensuales (TLR/12 y PRH mensual). La comparacion del "
                "criterio 8 es interna al modo, pero no es homogenea con el modo estandar: cambia a modo estandar "
                "para comparar un rendimiento y un riesgo anuales.",
            )

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con el rendimiento, el riesgo y su cociente."""
        riesgo = r.riesgo
        sigma = a_float(riesgo.sigma_anual)
        rendimiento = a_float(r.rend_capm)
        cociente, diferencia, nota_rdr = rdr(rendimiento, sigma)
        criterio = _criterio(r, 8)
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "Rend_CAPM": fmt_pct(rendimiento, 2),
                "Riesgo (sigma anual)": fmt_pct(sigma, 2),
                "Cociente Rend/Riesgo": fmt_num(cociente, 4),
                "Diferencia (Rend - Riesgo)": fmt_pct(diferencia, 2),
                "Veredicto": self._veredicto(rendimiento, sigma),
                "Criterio 8": "CUMPLE" if criterio is not None and criterio.cumple else ("NO CUMPLE" if criterio is not None else ND),
                "Sigma mensual": fmt_pct(riesgo.sigma_mensual, 2),
                "Maxima caida": fmt_pct(riesgo.max_drawdown, 2),
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "Rend_CAPM": "Rendimiento esperado por el CAPM: TLR + Beta x PRH (ver pestana CAPM).",
                "Riesgo (sigma anual)": f"Volatilidad de la accion. {FORMULA_SIGMA}.",
                "Cociente Rend/Riesgo": FORMULA_RDR,
                "Diferencia (Rend - Riesgo)": FORMULA_DIFERENCIA,
                "Veredicto": FORMULA_CRITERIO,
                "Criterio 8": FORMULA_CRITERIO,
                "Sigma mensual": "Desviacion tipica muestral (ddof=1) de los rendimientos mensuales.",
                "Maxima caida": EXPLICACION_RIESGO["Maxima caida"],
            },
            colores={
                "Cociente Rend/Riesgo": (
                    VERDE if (cociente is not None and cociente > 1.0) else (ROJO if cociente is not None else AMBAR)
                ),
                "Veredicto": (
                    VERDE
                    if (rendimiento is not None and sigma is not None and rendimiento > sigma)
                    else (ROJO if (rendimiento is not None and sigma is not None) else AMBAR)
                ),
                "Criterio 8": _color_criterio(criterio),
            },
        )
        caja.addWidget(tarjetas)
        if nota_rdr:
            _aviso(caja, f"{nota_rdr}; el criterio 8 se califica 0.")

    @staticmethod
    def _veredicto(rendimiento: Optional[float], riesgo: Optional[float]) -> str:
        """Lectura cualitativa de la comparacion rendimiento-riesgo."""
        if rendimiento is None or riesgo is None:
            return ND
        if rendimiento > riesgo:
            return "El rendimiento compensa el riesgo"
        if rendimiento < riesgo:
            return "El riesgo supera el rendimiento esperado"
        return "Rendimiento igual al riesgo"

    # ---------------------------------------------------------- comparacion
    def _bloque_comparacion(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Cuadro de comparacion Rend_CAPM frente a la sigma anual."""
        _titulo(caja, "Comparacion: Rend_CAPM frente a Riesgo (sigma anual)", FORMULA_CRITERIO)
        rendimiento = a_float(r.rend_capm)
        sigma = a_float(r.riesgo.sigma_anual)
        cociente, diferencia, _ = rdr(rendimiento, sigma)
        filas: List[Dict[str, Any]] = [
            {
                "Indicador": "RDR (Rendimiento sobre Riesgo)",
                "Rendimiento (Rend_CAPM)": rendimiento,
                "Riesgo (sigma anual)": sigma,
                "Cociente Rend/Riesgo": cociente,
                "Diferencia": diferencia,
                "Resultado": self._veredicto(rendimiento, sigma),
                "Formula": FORMULA_RDR,
            }
        ]
        tabla = TablaDML(COLUMNAS_COMPARACION, tooltips_columnas=TOOLTIPS_COMPARACION)
        # ordenar=False: se reescribe la columna "Valor" por indice mas abajo, y
        # ordenar antes de escribir cruzaria cada valor con otra fila.
        tabla.cargar_filas(filas, COLUMNAS_COMPARACION, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Rendimiento (Rend_CAPM)"),
            [fmt_pct(rendimiento, 2) if rendimiento is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Riesgo (sigma anual)"),
            [fmt_pct(sigma, 2) if sigma is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Cociente Rend/Riesgo"),
            [fmt_num(cociente, 4) if cociente is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia"),
            [fmt_pct(diferencia, 2) if diferencia is not None else None],
        )
        tabla.reactivar_ordenacion()   # ya con el texto definitivo en cada celda
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # ----------------------------------------------------------- tabla riesgo
    def _bloque_riesgo(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tabla completa de metricas de riesgo con tooltip explicativo por fila."""
        _titulo(
            caja,
            "Metricas de riesgo",
            "Calculadas sobre los rendimientos mensuales; cada fila lleva su explicacion en el tooltip.",
        )
        try:
            datos = tabla_riesgo(r.riesgo)
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo construir la tabla de riesgo: %s", exc)
            _aviso(caja, f"N/D: no se pudo construir la tabla de riesgo ({exc}); el criterio 8 se califica 0.")
            return
        registros = datos.to_dict(orient="records") if datos is not None else []
        tabla = TablaDML(COLUMNAS_RIESGO, tooltips_columnas=TOOLTIPS_RIESGO)
        # ordenar=False por lo mismo: el formateo de "Valor" depende de la metrica
        # de su fila y se aplica despues, por indice.
        tabla.cargar_filas(registros, COLUMNAS_RIESGO, ordenar=False)
        nombres = [str(fila.get("Metrica", "")) for fila in registros]
        _aplicar_formatos(
            tabla,
            COLUMNAS_RIESGO.index("Valor"),
            [
                _formato_unidad(fila.get("Valor"), UNIDADES_RIESGO.get(nombre, "numero"), r.moneda)
                for nombre, fila in zip(nombres, registros)
            ],
        )
        tabla.reactivar_ordenacion()   # ya con el texto definitivo en cada celda
        self._tooltips_riesgo(tabla, COLUMNAS_RIESGO.index("Metrica"), COLUMNAS_RIESGO.index("Valor"))
        self._ajustar_alto(tabla, filas_maximas=12)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Lectura: la sigma anual mide el riesgo total, el VaR la perdida esperada en un mes malo y Sharpe/Treynor "
            "la rentabilidad por unidad de riesgo (total y sistematico). Los valores N/D no se calculan con datos "
            "inventados: si el criterio depende de ellos se califica 0.",
        )

    @staticmethod
    def _tooltips_riesgo(tabla: TablaDML, columna_metrica: int, columna_valor: int) -> None:
        """Coloca la explicacion de cada metrica en el tooltip de toda su fila."""
        for fila in range(tabla.rowCount()):
            celda = tabla.item(fila, columna_metrica)
            nombre = celda.text() if celda is not None else ""
            explicacion = EXPLICACION_RIESGO.get(
                nombre, "Metrica de riesgo calculada sobre los rendimientos mensuales de la accion."
            )
            texto = f"{nombre}: {explicacion}"
            valor = tabla.item(fila, columna_valor)
            if valor is not None and valor.text().strip() in {"", ND}:
                texto += " N/D: el valor no se pudo calcular; el criterio que dependa de el se califica 0."
            for columna in range(tabla.columnCount()):
                celda_fila = tabla.item(fila, columna)
                if celda_fila is not None:
                    celda_fila.setToolTip(texto)

    # ------------------------------------------------------------- criterio
    def _bloque_criterio(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Estado del criterio 8 de la parrilla de decision."""
        criterio = _criterio(r, 8)
        _titulo(caja, "Criterio 8 de la parrilla", FORMULA_CRITERIO)
        _etiqueta_estado(
            caja,
            _texto_criterio(criterio, 8, "RDR: Rend_CAPM > Riesgo (sigma anual)"),
            _color_criterio(criterio),
        )
        filas = [_fila_criterio(criterio, 8, "RDR: Rend_CAPM > Riesgo (desviacion estandar anual)", "Mayor es mejor")]
        tabla = TablaDML(
            COLUMNAS_CRITERIO,
            colores_condicionales=_color_estado(COLUMNAS_CRITERIO.index("Estado")),
            tooltips_columnas=TOOLTIPS_CRITERIO,
        )
        tabla.cargar_filas(filas, COLUMNAS_CRITERIO, ordenar=False)
        unidad = criterio.unidad if criterio is not None else "porcentaje"
        _aplicar_formatos(
            tabla,
            COLUMNAS_CRITERIO.index("Valor obtenido"),
            [_formato_unidad(filas[0]["Valor obtenido"], unidad, r.moneda)],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_CRITERIO.index("Valor de comparacion"),
            [_formato_unidad(filas[0]["Valor de comparacion"], unidad, r.moneda)],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # --------------------------------------------------------- procedencia
    def _bloque_procedencia(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Procedencia de cada valor del bloque RDR."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada valor.")
        beta_usada = a_float(r.beta_cov) if a_float(r.beta_cov) is not None else a_float(r.beta_ols)
        ruta_capm = _ruta(r, "capm") or _ruta(r, "beta")
        ruta_tasa = _ruta(r, "tasa")
        filas: List[Dict[str, Any]] = [
            _fila_origen(
                "Rend_CAPM",
                a_float(r.rend_capm),
                Evidence(fuente="Calculado", metodo="calculo", nota="TLR + Beta x PRH (pestana CAPM)."),
                ruta_capm,
            ),
            _fila_origen(
                "Beta usada",
                beta_usada,
                Evidence(fuente="Calculado", metodo="calculo", nota="Beta por covarianza; si falta, la de la regresion MCO."),
                ruta_capm,
            ),
            _fila_origen(
                "TLR (T-Bill 4 semanas)",
                a_float(r.tlr),
                r.tasas.ev_tbill_4w,
                ruta_tasa,
            ),
            _fila_origen(
                "Sigma anual (riesgo)",
                a_float(r.riesgo.sigma_anual),
                Evidence(fuente="Calculado", metodo="calculo", nota=r.riesgo.nota_sigma or FORMULA_SIGMA),
                ruta_capm,
            ),
            _fila_origen(
                "Sigma mensual",
                a_float(r.riesgo.sigma_mensual),
                Evidence(
                    fuente="Calculado",
                    metodo="calculo",
                    nota="Desviacion tipica muestral (ddof=1) de los rendimientos mensuales.",
                ),
                ruta_capm,
            ),
            _fila_origen(
                "Cociente Rend/Riesgo",
                rdr(a_float(r.rend_capm), a_float(r.riesgo.sigma_anual))[0],
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_RDR),
                ruta_capm,
            ),
            _fila_origen(
                "Diferencia Rend - Riesgo",
                rdr(a_float(r.rend_capm), a_float(r.riesgo.sigma_anual))[1],
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_DIFERENCIA),
                ruta_capm,
            ),
        ]
        tabla = TablaDML(COLUMNAS_ORIGEN, tooltips_columnas=TOOLTIPS_ORIGEN)
        tabla.cargar_filas(filas, COLUMNAS_ORIGEN, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_ORIGEN.index("Valor"),
            [
                fmt_pct(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                fmt_num(filas[1]["Valor"], 4) if a_float(filas[1]["Valor"]) is not None else None,
                fmt_pct(filas[2]["Valor"], 2) if a_float(filas[2]["Valor"]) is not None else None,
                fmt_pct(filas[3]["Valor"], 2) if a_float(filas[3]["Valor"]) is not None else None,
                fmt_pct(filas[4]["Valor"], 2) if a_float(filas[4]["Valor"]) is not None else None,
                fmt_num(filas[5]["Valor"], 4) if a_float(filas[5]["Valor"]) is not None else None,
                fmt_pct(filas[6]["Valor"], 2) if a_float(filas[6]["Valor"]) is not None else None,
            ],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: la Beta publicada y el precio en la ficha del valor "
            f"({_texto_ruta(r, 'beta', 'ficha del valor')}) y la TLR en la pagina del T-Bill a 4 semanas "
            f"({_texto_ruta(r, 'tasa', 'tasa libre de riesgo')}). El Rend_CAPM, la sigma y el RDR son calculos del "
            "programa a partir de ellos.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Barras de rendimiento, riesgo y niveles de VaR."""
        _titulo(
            caja,
            "Rendimiento frente a riesgo",
            "El rendimiento y el riesgo estan anualizados; los VaR son rendimientos mensuales (parametricos).",
        )
        self._grafico = GraficoDML(titulo="RDR", alto=3.4, ancho=7)
        self._grafico.setMinimumHeight(320)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja las barras de rendimiento, riesgo y VaR (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            riesgo = r.riesgo if r is not None else None
            rendimiento = a_float(r.rend_capm) if r is not None else None
            sigma = a_float(riesgo.sigma_anual) if riesgo is not None else None
            var95 = a_float(riesgo.var_95) if riesgo is not None else None
            var99 = a_float(riesgo.var_99) if riesgo is not None else None
            etiquetas = ["Rend_CAPM (anual)", "Riesgo sigma (anual)", "VaR 95% (mensual)", "VaR 99% (mensual)"]
            valores = [rendimiento, sigma, var95, var99]
            colores_barras = [VERDE, ROJO, AMBAR, AMBAR]
            disponibles = [
                (etiqueta, valor, color)
                for etiqueta, valor, color in zip(etiquetas, valores, colores_barras)
                if valor is not None
            ]
            if disponibles:
                barras = eje.bar(
                    [etiqueta for etiqueta, _, _ in disponibles],
                    [valor * 100.0 for _, valor, _ in disponibles],
                    color=[color for _, _, color in disponibles],
                    width=0.55,
                )
                for barra, (_, valor, _) in zip(barras, disponibles):
                    eje.text(
                        barra.get_x() + barra.get_width() / 2.0,
                        barra.get_height(),
                        fmt_pct(valor, 2),
                        ha="center",
                        va="bottom" if valor >= 0 else "top",
                        fontsize=9,
                        color=paleta["texto"],
                    )
                faltan = [
                    etiqueta for etiqueta, valor in zip(etiquetas, valores) if valor is None
                ]
                if faltan:
                    eje.text(
                        0.02,
                        0.98,
                        "N/D: " + ", ".join(faltan) + " (no calculable con los datos disponibles)",
                        transform=eje.transAxes,
                        va="top",
                        fontsize=8,
                        color=AMBAR,
                    )
                minimo = min(0.0, min(valor * 100.0 for _, valor, _ in disponibles) * 1.35)
                maximo = max(max(valor * 100.0 for _, valor, _ in disponibles) * 1.30, 1.0)
                eje.set_ylim(minimo, maximo)
                eje.axhline(0.0, color=paleta["borde"], linewidth=0.8)
            else:
                eje.text(
                    0.5,
                    0.5,
                    "N/D: no hay Rend_CAPM ni sigma de riesgo; el criterio 8 se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            eje.set_ylabel("Rendimiento / riesgo (%)")
            eje.set_title("Rend_CAPM frente a riesgo y VaR")
            eje.grid(True, axis="y", color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar el grafico de RDR: %s", exc)
            eje.text(0.5, 0.5, f"N/D: no se pudo dibujar el grafico ({exc})", transform=eje.transAxes, ha="center", va="center", fontsize=8, color=ROJO)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()

    # ---------------------------------------------------------------- ayudas
    @staticmethod
    def _ajustar_alto(tabla: TablaDML, filas_maximas: int = 10) -> None:
        """Fija un alto razonable: la tabla se desplaza si tiene mas filas."""
        filas = max(tabla.rowCount(), 1)
        alto = min(filas, filas_maximas) * 30 + 40
        tabla.setMinimumHeight(alto)
