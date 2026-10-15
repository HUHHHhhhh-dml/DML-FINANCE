# -*- coding: utf-8 -*-
"""Pestana "Price to FCF": capitalizacion sobre flujo de caja libre y criterio 4.

Bloques de la pestana:

1. Tarjetas con el Price to FCF de la empresa y del sector, la diferencia, la
   capitalizacion, el flujo de caja libre y el estado del criterio 4.
2. Cuadro de comparacion ``Price to FCF empresa`` vs ``sector`` (menor es mejor)
   con la formula ``Capitalizacion / FCF`` en el tooltip.
3. Bloque de auditoria: capitalizacion, FCF, el multiplo recalculado como
   ``Capitalizacion / FCF`` (:func:`dml.models.fundamentales.price_to_fcf`) y su
   desviacion frente al valor declarado por el proveedor.
4. Estado del criterio 4 (``self.resultado.criterios``) con su calificacion.
5. Procedencia de cada valor (``fundamentales.ev_p_fcf`` y
   ``ev_p_fcf_sector``: fuente, metodo, URL y ruta de Investing.com).
6. Grafico de barras comparando los dos multiplos.

Regla del pliego: si el flujo de caja libre no es positivo (o falta la
capitalizacion) el multiplo no es interpretable: se muestra ``N/D`` con el
motivo y el criterio 4 se califica 0.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.fundamentales import price_to_fcf
from ..estilos import colores
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.pfcf")

# ---------------------------------------------------------------- formulas
FORMULA_PFCF = "Price to FCF = Capitalizacion bursatil / Free Cash Flow"
FORMULA_PFCF_ACCION = "Price to FCF = Precio / FCF por accion (mismo cociente)"
FORMULA_DIFERENCIA = "Diferencia = Price to FCF empresa - Price to FCF sector"
FORMULA_DIFERENCIA_REL = "Diferencia relativa = (P/FCF empresa - P/FCF sector) / P/FCF sector"
FORMULA_CRITERIO = "Criterio 4: Price to FCF empresa < Price to FCF sector (menor es mejor)"

# ---------------------------------------------------------------- columnas
COLUMNAS_COMPARACION: List[str] = [
    "Indicador",
    "Empresa",
    "Sector (comparable)",
    "Diferencia",
    "Diferencia relativa",
    "Resultado",
    "Formula",
]
COLUMNAS_AUDITORIA: List[str] = ["Componente", "Valor", "Formula", "Nota"]
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
    "Indicador": "Multiplo comparado.",
    "Empresa": f"{FORMULA_PFCF}. Es el multiplo de la empresa analizada.",
    "Sector (comparable)": "Multiplo de referencia del sector (mediana de pares o config.yaml).",
    "Diferencia": FORMULA_DIFERENCIA,
    "Diferencia relativa": FORMULA_DIFERENCIA_REL,
    "Resultado": "Lectura de la comparacion: menor es mejor.",
    "Formula": "Formula exacta del indicador.",
}
TOOLTIPS_AUDITORIA: Dict[str, str] = {
    "Componente": "Componente del calculo del multiplo.",
    "Valor": "Valor del componente (importe o veces, segun la fila).",
    "Formula": FORMULA_PFCF,
    "Nota": "Comprobacion del multiplo y motivo cuando el dato es N/D.",
}
TOOLTIPS_CRITERIO: Dict[str, str] = {
    "#": "Numero del criterio en la parrilla de decision del pliego.",
    "Criterio": "Enunciado del criterio.",
    "Optimo": "Sentido en el que el criterio se cumple.",
    "Estado": "CUMPLE (1 punto), NO CUMPLE (0 puntos) o N/D (dato ausente, 0 puntos).",
    "Calificacion": "1 si cumple, 0 si no cumple o si el dato es N/D.",
    "Valor obtenido": "Price to FCF de la empresa.",
    "Valor de comparacion": "Price to FCF de referencia del sector.",
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


class TabPFCF(TabConGrafico):
    """Pestana del multiplo Price to FCF: empresa frente a sector (criterio 4)."""

    titulo = "Price to FCF"

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
        _titulo(caja, "Price to FCF - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para comparar el "
            f"Price to FCF de la empresa con el del sector ({FORMULA_PFCF}) y evaluar el criterio 4.",
        )

    def _subtitulo(self, r: ResultadoAnalisis) -> str:
        """Linea de contexto del analisis mostrado."""
        partes = [f"Ticker {r.ticker}"]
        if r.fundamentales.sector:
            partes.append(f"Sector {r.fundamentales.sector}")
        partes.append(f"Modo {r.modo}")
        if r.moneda:
            partes.append(f"Divisa {r.moneda}")
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

        _titulo(caja, f"Price to FCF - {r.ticker}", self._subtitulo(r))
        self._bloque_tarjetas(caja, r)
        self._bloque_comparacion(caja, r)
        self._bloque_auditoria(caja, r)
        self._bloque_criterio(caja, r)
        self._bloque_procedencia(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con el multiplo de la empresa, el del sector y sus insumos."""
        f = r.fundamentales
        p_fcf = a_float(f.p_fcf)
        p_fcf_sector = a_float(f.p_fcf_sector)
        diferencia = (p_fcf - p_fcf_sector) if (p_fcf is not None and p_fcf_sector is not None) else None
        relativa = (
            (p_fcf - p_fcf_sector) / p_fcf_sector if (p_fcf is not None and p_fcf_sector not in (None, 0)) else None
        )
        criterio = _criterio(r, 4)
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "Price to FCF empresa": fmt_num(p_fcf, 2),
                "Price to FCF sector": fmt_num(p_fcf_sector, 2),
                "Diferencia": fmt_num(diferencia, 2),
                "Diferencia relativa": fmt_pct(relativa, 2),
                "Veredicto": self._veredicto(p_fcf, p_fcf_sector),
                "Capitalizacion bursatil": _moneda(f.market_cap, r.moneda, 0),
                "Free cash flow": _moneda(f.free_cash_flow, r.moneda, 0),
                "Criterio 4": "CUMPLE" if criterio is not None and criterio.cumple else ("NO CUMPLE" if criterio is not None else ND),
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "Price to FCF empresa": f"{FORMULA_PFCF}.",
                "Price to FCF sector": "Multiplo de referencia del sector (mediana de pares o config.yaml).",
                "Diferencia": FORMULA_DIFERENCIA,
                "Diferencia relativa": FORMULA_DIFERENCIA_REL,
                "Veredicto": "Menor es mejor: por debajo del sector se considera mas barata.",
                "Capitalizacion bursatil": "Capitalizacion bursatil usada como numerador del multiplo.",
                "Free cash flow": "Flujo de caja libre usado como denominador del multiplo.",
                "Criterio 4": FORMULA_CRITERIO,
            },
            colores={
                "Veredicto": (
                    VERDE if (diferencia is not None and diferencia < 0) else (ROJO if diferencia is not None else AMBAR)
                ),
                "Criterio 4": _color_criterio(criterio),
            },
        )
        caja.addWidget(tarjetas)
        fcf = a_float(f.free_cash_flow)
        if fcf is None:
            _aviso(
                caja,
                "N/D: no hay flujo de caja libre (FCF); el multiplo no se puede calcular ni auditar y el criterio 4 "
                "se califica 0.",
            )
        elif fcf <= 0:
            _aviso(
                caja,
                f"N/D: el flujo de caja libre no es positivo ({_moneda(fcf, r.moneda, 0)}). Un multiplo negativo no "
                "tiene interpretacion y el criterio 4 se califica 0.",
            )
        if a_float(f.market_cap) is None:
            _aviso(caja, "N/D: no hay capitalizacion bursatil; no se puede auditar el cociente Capitalizacion / FCF.")

    @staticmethod
    def _veredicto(p_fcf: Optional[float], p_fcf_sector: Optional[float]) -> str:
        """Lectura cualitativa de la comparacion de multiplos (menor es mejor)."""
        if p_fcf is None or p_fcf_sector is None:
            return ND
        if p_fcf < p_fcf_sector:
            return "Mas barata que el sector"
        if p_fcf > p_fcf_sector:
            return "Mas cara que el sector"
        return "En linea con el sector"

    # ---------------------------------------------------------- comparacion
    def _bloque_comparacion(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Cuadro de comparacion empresa frente a sector."""
        _titulo(caja, "Comparacion: Price to FCF empresa frente a sector", f"{FORMULA_PFCF} (menor es mejor)")
        f = r.fundamentales
        p_fcf = a_float(f.p_fcf)
        p_fcf_sector = a_float(f.p_fcf_sector)
        diferencia = (p_fcf - p_fcf_sector) if (p_fcf is not None and p_fcf_sector is not None) else None
        relativa = (
            (p_fcf - p_fcf_sector) / p_fcf_sector if (p_fcf is not None and p_fcf_sector not in (None, 0)) else None
        )
        filas: List[Dict[str, Any]] = [
            {
                "Indicador": "Price to FCF (Capitalizacion / FCF)",
                "Empresa": p_fcf,
                "Sector (comparable)": p_fcf_sector,
                "Diferencia": diferencia,
                "Diferencia relativa": relativa,
                "Resultado": self._veredicto(p_fcf, p_fcf_sector),
                "Formula": FORMULA_PFCF,
            }
        ]
        tabla = TablaDML(COLUMNAS_COMPARACION, tooltips_columnas=TOOLTIPS_COMPARACION)
        tabla.cargar_filas(filas, COLUMNAS_COMPARACION)
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Empresa"),
            [fmt_num(p_fcf, 2) if p_fcf is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Sector (comparable)"),
            [fmt_num(p_fcf_sector, 2) if p_fcf_sector is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia"),
            [fmt_num(diferencia, 2) if diferencia is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia relativa"),
            [fmt_pct(relativa, 2) if relativa is not None else None],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # ---------------------------------------------------------- auditoria
    def _bloque_auditoria(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Auditoria del cociente: capitalizacion, FCF y multiplo recalculado."""
        _titulo(
            caja,
            "Auditoria del multiplo",
            f"Se muestran los dos insumos para poder comprobar a mano {FORMULA_PFCF}.",
        )
        f = r.fundamentales
        market_cap = a_float(f.market_cap)
        fcf = a_float(f.free_cash_flow)
        comprobado, nota_comprobado = price_to_fcf(market_cap, fcf, r.spot, None)
        p_fcf = a_float(f.p_fcf)
        desviacion = None
        if comprobado not in (None, 0) and p_fcf is not None:
            desviacion = (p_fcf - comprobado) / comprobado
        filas: List[Dict[str, Any]] = [
            {
                "Componente": "Capitalizacion bursatil (market cap)",
                "Valor": market_cap,
                "Formula": "Capitalizacion = precio x acciones en circulacion",
                "Nota": "Numerador del multiplo." if market_cap is not None else "N/D: no hay capitalizacion disponible; el criterio 4 se califica 0.",
            },
            {
                "Componente": "Free cash flow (FCF)",
                "Valor": fcf,
                "Formula": "FCF = flujo de caja operativo - inversiones en capital",
                "Nota": (
                    "Denominador del multiplo."
                    if (fcf is not None and fcf > 0)
                    else "N/D: el FCF no es positivo o falta; el multiplo no es interpretable y el criterio 4 se califica 0."
                ),
            },
            {
                "Componente": "Price to FCF de comprobacion",
                "Valor": comprobado,
                "Formula": FORMULA_PFCF,
                "Nota": nota_comprobado or "Calculado con los dos insumos anteriores.",
            },
            {
                "Componente": "Price to FCF declarado por el proveedor",
                "Valor": p_fcf,
                "Formula": FORMULA_PFCF,
                "Nota": f"Tambien puede venir como {FORMULA_PFCF_ACCION}.",
            },
            {
                "Componente": "Desviacion del declarado frente al comprobado",
                "Valor": desviacion,
                "Formula": "(P/FCF declarado - P/FCF comprobado) / P/FCF comprobado",
                "Nota": (
                    "Sin desviacion apreciable."
                    if (desviacion is not None and abs(desviacion) < 0.01)
                    else (
                        "N/D: no se puede comparar (falta el declarado o el comprobado)."
                        if desviacion is None
                        else "Aviso: el proveedor usa otra definicion de FCF o de capitalizacion."
                    )
                ),
            },
        ]
        tabla = TablaDML(COLUMNAS_AUDITORIA, tooltips_columnas=TOOLTIPS_AUDITORIA)
        tabla.cargar_filas(filas, COLUMNAS_AUDITORIA)
        _aplicar_formatos(
            tabla,
            COLUMNAS_AUDITORIA.index("Valor"),
            [
                _moneda(market_cap, r.moneda, 0) if market_cap is not None else None,
                _moneda(fcf, r.moneda, 0) if fcf is not None else None,
                fmt_num(comprobado, 2) if comprobado is not None else None,
                fmt_num(p_fcf, 2) if p_fcf is not None else None,
                fmt_pct(desviacion, 2) if desviacion is not None else None,
            ],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # ------------------------------------------------------------- criterio
    def _bloque_criterio(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Estado del criterio 4 de la parrilla de decision."""
        criterio = _criterio(r, 4)
        _titulo(caja, "Criterio 4 de la parrilla", FORMULA_CRITERIO)
        _etiqueta_estado(
            caja,
            _texto_criterio(criterio, 4, "Price to FCF empresa < sector"),
            _color_criterio(criterio),
        )
        filas = [_fila_criterio(criterio, 4, "Price to FCF empresa < Price to FCF sector", "Menor es mejor")]
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
        """Procedencia de cada valor del bloque Price to FCF."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada valor.")
        f = r.fundamentales
        ruta_ratios = _ruta(r, "per")
        comprobado, nota_comprobado = price_to_fcf(a_float(f.market_cap), a_float(f.free_cash_flow), r.spot, None)
        filas: List[Dict[str, Any]] = [
            _fila_origen("Price to FCF de la empresa", a_float(f.p_fcf), f.ev_p_fcf, ruta_ratios),
            _fila_origen("Price to FCF del sector", a_float(f.p_fcf_sector), f.ev_p_fcf_sector, ruta_ratios),
            _fila_origen(
                "Capitalizacion bursatil",
                a_float(f.market_cap),
                None,
                ruta_ratios,
                "N/D: el resultado no conserva el registro de procedencia de la capitalizacion; consulta la pestana Fuentes.",
            ),
            _fila_origen(
                "Free cash flow",
                a_float(f.free_cash_flow),
                None,
                ruta_ratios,
                "N/D: el resultado no conserva el registro de procedencia del FCF; consulta la pestana Fuentes.",
            ),
            _fila_origen(
                "Price to FCF de comprobacion (Capitalizacion / FCF)",
                comprobado,
                Evidence(fuente="Calculado", metodo="calculo", nota=nota_comprobado or FORMULA_PFCF),
                ruta_ratios,
            ),
        ]
        tabla = TablaDML(COLUMNAS_ORIGEN, tooltips_columnas=TOOLTIPS_ORIGEN)
        tabla.cargar_filas(filas, COLUMNAS_ORIGEN)
        _aplicar_formatos(
            tabla,
            COLUMNAS_ORIGEN.index("Valor"),
            [
                fmt_num(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                fmt_num(filas[1]["Valor"], 2) if a_float(filas[1]["Valor"]) is not None else None,
                _moneda(filas[2]["Valor"], r.moneda, 0) if a_float(filas[2]["Valor"]) is not None else None,
                _moneda(filas[3]["Valor"], r.moneda, 0) if a_float(filas[3]["Valor"]) is not None else None,
                fmt_num(filas[4]["Valor"], 2) if a_float(filas[4]["Valor"]) is not None else None,
            ],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: 'Ratios' de la ficha del valor "
            f"({_texto_ruta(r, 'per', 'ratios y multiplos')}); la capitalizacion y el FCF aparecen en 'Finanzas' "
            "(estado de flujos de efectivo). Si el FCF no es positivo el multiplo se muestra N/D y el criterio 4 "
            "se califica 0.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Barras comparando el Price to FCF de la empresa y del sector."""
        _titulo(caja, "Price to FCF empresa frente a sector", f"{FORMULA_PFCF} (menor es mejor)")
        self._grafico = GraficoDML(titulo="Price to FCF", alto=3.0, ancho=6)
        self._grafico.setMinimumHeight(280)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja las dos barras de Price to FCF (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            fundamentales = r.fundamentales if r is not None else None
            p_fcf = a_float(fundamentales.p_fcf) if fundamentales is not None else None
            p_fcf_sector = a_float(fundamentales.p_fcf_sector) if fundamentales is not None else None
            fcf = a_float(fundamentales.free_cash_flow) if fundamentales is not None else None
            etiquetas = ["P/FCF empresa", "P/FCF sector"]
            valores = [p_fcf, p_fcf_sector]
            paleta_barras = [paleta["acento"], GRIS]
            disponibles = [
                (etiqueta, valor, color)
                for etiqueta, valor, color in zip(etiquetas, valores, paleta_barras)
                if valor is not None
            ]
            if disponibles:
                barras = eje.bar(
                    [etiqueta for etiqueta, _, _ in disponibles],
                    [valor for _, valor, _ in disponibles],
                    color=[color for _, _, color in disponibles],
                    width=0.5,
                )
                for barra, (_, valor, _) in zip(barras, disponibles):
                    eje.text(
                        barra.get_x() + barra.get_width() / 2.0,
                        barra.get_height(),
                        fmt_num(valor, 2),
                        ha="center",
                        va="bottom",
                        fontsize=9,
                        color=paleta["texto"],
                    )
                faltan = [etiqueta for etiqueta, valor in zip(etiquetas, valores) if valor is None]
                if faltan:
                    eje.text(
                        0.02,
                        0.95,
                        "N/D: " + ", ".join(faltan) + " (multiplo no interpretable o no disponible)",
                        transform=eje.transAxes,
                        va="top",
                        fontsize=8,
                        color=AMBAR,
                    )
                eje.set_ylim(0.0, max(valor for _, valor, _ in disponibles) * 1.25)
            else:
                eje.text(
                    0.5,
                    0.5,
                    "N/D: no hay Price to FCF de la empresa ni del sector; el criterio 4 se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            if fcf is not None and fcf <= 0:
                eje.text(
                    0.02,
                    0.80,
                    f"Aviso: FCF no positivo ({fmt_num(fcf, 0)}): el multiplo no es interpretable.",
                    transform=eje.transAxes,
                    va="top",
                    fontsize=8,
                    color=ROJO,
                )
            eje.set_ylabel("Veces (x)")
            eje.set_title("Price to FCF empresa vs sector")
            eje.grid(True, axis="y", color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar el grafico de Price to FCF: %s", exc)
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
