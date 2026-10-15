# -*- coding: utf-8 -*-
"""Pestana "Renta PER": rentabilidad implicita del PER frente a la TLR (criterio 7).

La Renta PER (earnings yield) es el inverso del PER: indica que rentabilidad
teorica compra cada euro invertido al precio actual, y se compara directamente
con la tasa libre de riesgo (TLR) para decidir si la accion compensa frente a un
bono sin riesgo.

Bloques de la pestana:

1. Tarjetas con la Renta PER de la empresa, la TLR, el spread en puntos basicos
   y el estado del criterio 7.
2. Cuadro de comparacion ``Renta PER`` vs ``TLR`` con las formulas
   ``Renta PER = 1 / PER`` y ``Spread (pb) = (Renta PER - TLR) x 10.000``.
3. Estado del criterio 7 (``self.resultado.criterios``) con su calificacion.
4. Procedencia de cada valor (``fundamentales.ev_per`` y ``tasas.ev_tbill_4w``:
   fuente, metodo, URL y ruta de Investing.com).
5. Grafico de barras de Renta PER frente a la TLR.

Regla del pliego: si el PER falta o no es positivo la Renta PER no es
interpretable; se muestra ``N/D`` con el motivo (:func:`dml.models.fundamentales.renta_per`)
y el criterio 7 se califica 0.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.fundamentales import renta_per
from ..estilos import colores
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.renta_per")

# ---------------------------------------------------------------- formulas
FORMULA_RENTA = "Renta PER = 1 / PER"
FORMULA_SPREAD = "Spread (pb) = (Renta PER - TLR) x 10.000"
FORMULA_DIFERENCIA = "Diferencia = Renta PER - TLR (en tanto por uno)"
FORMULA_CRITERIO = "Criterio 7: Renta PER (1/PER) > TLR"

# ---------------------------------------------------------------- columnas
COLUMNAS_COMPARACION: List[str] = [
    "Indicador",
    "Empresa",
    "TLR (referencia)",
    "Diferencia",
    "Spread (pb)",
    "Resultado",
    "Formula",
]
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

TOOLTIPS_COMPARACION: Dict[str, str] = {
    "Indicador": "Indicador comparado.",
    "Empresa": f"{FORMULA_RENTA}: rentabilidad implicita del precio pagado (earnings yield).",
    "TLR (referencia)": "Tasa libre de riesgo: T-Bill de EE.UU. a 4 semanas (Investing.com / FRED).",
    "Diferencia": FORMULA_DIFERENCIA,
    "Spread (pb)": FORMULA_SPREAD,
    "Resultado": "Lectura de la comparacion: la accion compensa si la Renta PER supera la TLR.",
    "Formula": "Formula exacta del indicador.",
}
TOOLTIPS_CRITERIO: Dict[str, str] = {
    "#": "Numero del criterio en la parrilla de decision del pliego.",
    "Criterio": "Enunciado del criterio.",
    "Optimo": "Sentido en el que el criterio se cumple.",
    "Estado": "CUMPLE (1 punto), NO CUMPLE (0 puntos) o N/D (dato ausente, 0 puntos).",
    "Calificacion": "1 si cumple, 0 si no cumple o si el dato es N/D.",
    "Valor obtenido": "Renta PER de la empresa (1/PER).",
    "Valor de comparacion": "TLR con la que se compara.",
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
    """Formatea el valor de un criterio segun su unidad declarada."""
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


class TabRentaPER(TabConGrafico):
    """Pestana de la Renta PER: 1/PER frente a la TLR (criterio 7)."""

    titulo = "Renta PER"

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
        _titulo(caja, "Renta PER - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para comparar la "
            f"Renta PER ({FORMULA_RENTA}) con la TLR y evaluar el criterio 7.",
        )

    def _subtitulo(self, r: ResultadoAnalisis) -> str:
        """Linea de contexto del analisis mostrado."""
        partes = [f"Ticker {r.ticker}"]
        if r.fundamentales.sector:
            partes.append(f"Sector {r.fundamentales.sector}")
        partes.append(f"Modo {r.modo}")
        partes.append(f"TLR anual {fmt_pct(r.tlr, 2)}")
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

        _titulo(caja, f"Renta PER - {r.ticker}", self._subtitulo(r))
        self._bloque_tarjetas(caja, r)
        self._bloque_comparacion(caja, r)
        self._bloque_criterio(caja, r)
        self._bloque_procedencia(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con la Renta PER, la TLR y el spread en puntos basicos."""
        per_empresa = a_float(r.fundamentales.per)
        renta, nota_renta = renta_per(per_empresa)
        tlr = a_float(r.tlr)
        spread = (renta - tlr) if (renta is not None and tlr is not None) else None
        criterio = _criterio(r, 7)
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "PER empresa": fmt_num(per_empresa, 2),
                "Renta PER (1/PER)": fmt_pct(renta, 2),
                "TLR (tasa libre de riesgo)": fmt_pct(tlr, 2),
                "Diferencia (Renta PER - TLR)": fmt_pct(spread, 2),
                "Spread (puntos basicos)": fmt_num(spread * 10_000.0, 0) if spread is not None else ND,
                "Veredicto": self._veredicto(renta, tlr),
                "Criterio 7": "CUMPLE" if criterio is not None and criterio.cumple else ("NO CUMPLE" if criterio is not None else ND),
                "Bono 10 anos (referencia)": fmt_pct(r.tasas.ust_10y, 2),
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "PER empresa": "PER de la empresa: Precio / EPS. Si es negativo o falta, la Renta PER no existe.",
                "Renta PER (1/PER)": FORMULA_RENTA,
                "TLR (tasa libre de riesgo)": "TLR = T-Bill de EE.UU. a 4 semanas (Investing.com; respaldo FRED DTB4WK).",
                "Diferencia (Renta PER - TLR)": FORMULA_DIFERENCIA,
                "Spread (puntos basicos)": FORMULA_SPREAD,
                "Veredicto": "La accion compensa frente al bono si la Renta PER supera la TLR.",
                "Criterio 7": FORMULA_CRITERIO,
                "Bono 10 anos (referencia)": "Bono del Tesoro de EE.UU. a 10 anos, solo como contexto de tipos.",
            },
            colores={
                "Veredicto": (
                    VERDE if (spread is not None and spread > 0) else (ROJO if spread is not None else AMBAR)
                ),
                "Spread (puntos basicos)": (
                    VERDE if (spread is not None and spread > 0) else (ROJO if spread is not None else AMBAR)
                ),
                "Criterio 7": _color_criterio(criterio),
            },
        )
        caja.addWidget(tarjetas)
        if nota_renta:
            _aviso(caja, f"{nota_renta}; el criterio 7 se califica 0.")
        if tlr is None:
            _aviso(caja, "N/D: no hay TLR disponible; el spread no se puede calcular y el criterio 7 se califica 0.")

    @staticmethod
    def _veredicto(renta: Optional[float], tlr: Optional[float]) -> str:
        """Lectura cualitativa de la comparacion Renta PER vs TLR."""
        if renta is None or tlr is None:
            return ND
        if renta > tlr:
            return "La accion compensa frente a la TLR"
        if renta < tlr:
            return "La TLR supera la Renta PER"
        return "Renta PER igual a la TLR"

    # ---------------------------------------------------------- comparacion
    def _bloque_comparacion(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Cuadro de comparacion Renta PER frente a TLR."""
        _titulo(caja, "Comparacion: Renta PER frente a TLR", f"{FORMULA_RENTA} y {FORMULA_SPREAD}")
        per_empresa = a_float(r.fundamentales.per)
        renta, _ = renta_per(per_empresa)
        tlr = a_float(r.tlr)
        spread = (renta - tlr) if (renta is not None and tlr is not None) else None
        filas: List[Dict[str, Any]] = [
            {
                "Indicador": "Renta PER (1/PER)",
                "Empresa": renta,
                "TLR (referencia)": tlr,
                "Diferencia": spread,
                "Spread (pb)": spread * 10_000.0 if spread is not None else None,
                "Resultado": self._veredicto(renta, tlr),
                "Formula": FORMULA_RENTA,
            }
        ]
        tabla = TablaDML(COLUMNAS_COMPARACION, tooltips_columnas=TOOLTIPS_COMPARACION)
        tabla.cargar_filas(filas, COLUMNAS_COMPARACION)
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Empresa"),
            [fmt_pct(renta, 2) if renta is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("TLR (referencia)"),
            [fmt_pct(tlr, 2) if tlr is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia"),
            [fmt_pct(spread, 2) if spread is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Spread (pb)"),
            [fmt_num(spread * 10_000.0, 0) if spread is not None else None],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # ------------------------------------------------------------- criterio
    def _bloque_criterio(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Estado del criterio 7 de la parrilla de decision."""
        criterio = _criterio(r, 7)
        _titulo(caja, "Criterio 7 de la parrilla", FORMULA_CRITERIO)
        _etiqueta_estado(caja, _texto_criterio(criterio, 7, "Renta PER (1/PER) > TLR"), _color_criterio(criterio))
        filas = [_fila_criterio(criterio, 7, "Renta PER (1/PER) > TLR", "Mayor es mejor")]
        tabla = TablaDML(
            COLUMNAS_CRITERIO,
            colores_condicionales=_color_estado(COLUMNAS_CRITERIO.index("Estado")),
            tooltips_columnas=TOOLTIPS_CRITERIO,
        )
        tabla.cargar_filas(filas, COLUMNAS_CRITERIO)
        unidad = criterio.unidad if criterio is not None else "numero"
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
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # --------------------------------------------------------- procedencia
    def _bloque_procedencia(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Procedencia de cada valor del bloque Renta PER."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada valor.")
        f = r.fundamentales
        ruta_per = _ruta(r, "per")
        ruta_tasa = _ruta(r, "tasa")
        per_empresa = a_float(f.per)
        renta, nota_renta = renta_per(per_empresa)
        tlr = a_float(r.tlr)
        spread = (renta - tlr) if (renta is not None and tlr is not None) else None
        filas: List[Dict[str, Any]] = [
            _fila_origen("PER de la empresa", per_empresa, f.ev_per, ruta_per),
            _fila_origen("Renta PER (1/PER) calculada", renta, Evidence(fuente="Calculado", metodo="calculo", nota=nota_renta or FORMULA_RENTA), ruta_per, nota_renta or ND),
            _fila_origen("TLR (T-Bill 4 semanas)", tlr, r.tasas.ev_tbill_4w, ruta_tasa),
            _fila_origen(
                "Spread frente a la TLR",
                spread,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_DIFERENCIA),
                ruta_tasa,
            ),
            _fila_origen(
                "Spread en puntos basicos",
                spread * 10_000.0 if spread is not None else None,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_SPREAD),
                ruta_tasa,
            ),
            _fila_origen(
                "Bono 10 anos (contexto)",
                a_float(r.tasas.ust_10y),
                r.tasas.ev_ust_10y,
                _ruta(r, "bono10"),
                "Solo como contexto de tipos; el criterio 7 compara contra la TLR a 4 semanas.",
            ),
        ]
        tabla = TablaDML(COLUMNAS_ORIGEN, tooltips_columnas=TOOLTIPS_ORIGEN)
        tabla.cargar_filas(filas, COLUMNAS_ORIGEN)
        _aplicar_formatos(
            tabla,
            COLUMNAS_ORIGEN.index("Valor"),
            [
                fmt_num(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                fmt_pct(filas[1]["Valor"], 2) if a_float(filas[1]["Valor"]) is not None else None,
                fmt_pct(filas[2]["Valor"], 2) if a_float(filas[2]["Valor"]) is not None else None,
                fmt_pct(filas[3]["Valor"], 2) if a_float(filas[3]["Valor"]) is not None else None,
                fmt_num(filas[4]["Valor"], 0) if a_float(filas[4]["Valor"]) is not None else None,
                fmt_pct(filas[5]["Valor"], 2) if a_float(filas[5]["Valor"]) is not None else None,
            ],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: el PER en 'Ratios' de la ficha del valor "
            f"({_texto_ruta(r, 'per', 'PER de la empresa')}) y la TLR en la pagina del T-Bill a 4 semanas "
            f"({_texto_ruta(r, 'tasa', 'tasa libre de riesgo')}). Si el PER es negativo o falta, la Renta PER se "
            "muestra N/D y el criterio 7 se califica 0.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Barras de Renta PER frente a la TLR."""
        _titulo(caja, "Renta PER frente a la TLR", FORMULA_CRITERIO)
        self._grafico = GraficoDML(titulo="Renta PER vs TLR", alto=3.0, ancho=6)
        self._grafico.setMinimumHeight(280)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja las barras de Renta PER y TLR (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            fundamentales = r.fundamentales if r is not None else None
            per_empresa = a_float(fundamentales.per) if fundamentales is not None else None
            renta, _ = renta_per(per_empresa)
            tlr = a_float(r.tlr) if r is not None else None
            etiquetas = ["Renta PER (1/PER)", "TLR (T-Bill 4 semanas)"]
            valores = [renta, tlr]
            paleta_barras = [paleta["acento"], GRIS]
            disponibles = [
                (etiqueta, valor, color)
                for etiqueta, valor, color in zip(etiquetas, valores, paleta_barras)
                if valor is not None
            ]
            if disponibles:
                barras = eje.bar(
                    [etiqueta for etiqueta, _, _ in disponibles],
                    [valor * 100.0 for _, valor, _ in disponibles],
                    color=[color for _, _, color in disponibles],
                    width=0.5,
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
                faltan = [etiqueta for etiqueta, valor in zip(etiquetas, valores) if valor is None]
                if faltan:
                    eje.text(
                        0.02,
                        0.95,
                        "N/D: " + ", ".join(faltan) + " (sin PER positivo o sin TLR no hay comparacion)",
                        transform=eje.transAxes,
                        va="top",
                        fontsize=8,
                        color=AMBAR,
                    )
                tope = max(abs(valor) * 100.0 for _, valor, _ in disponibles) * 1.4 or 1.0
                eje.set_ylim(min(0.0, min(valor * 100.0 for _, valor, _ in disponibles) * 1.4), tope)
                eje.axhline(0.0, color=paleta["borde"], linewidth=0.8)
            else:
                eje.text(
                    0.5,
                    0.5,
                    "N/D: no hay Renta PER ni TLR comparables; el criterio 7 se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            eje.set_ylabel("Rentabilidad anualizada (%)")
            eje.set_title("Renta PER vs TLR")
            eje.grid(True, axis="y", color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar el grafico de Renta PER: %s", exc)
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
