# -*- coding: utf-8 -*-
"""Pestana "EPS": beneficio por accion actual frente al estimado y criterio 2.

Bloques de la pestana:

1. Tarjetas con el EPS actual, el EPS estimado (forecast), la diferencia
   absoluta y relativa, la sorpresa y el estado del criterio 2.
2. Cuadro de comparacion ``EPS actual`` vs ``EPS estimado`` con la formula
   ``Diferencia = EPS actual - EPS estimado`` y la relativa
   ``(EPS actual - EPS estimado) / |EPS estimado|`` en el tooltip.
3. Estado del criterio 2 (``self.resultado.criterios``) con su calificacion.
4. Procedencia de cada valor (``fundamentales.ev_eps`` y ``ev_eps_forecast``:
   fuente, metodo, URL y ruta de Investing.com).
5. Grafico de barras comparando el EPS actual con el estimado.

Regla del pliego: si falta el EPS estimado (o cualquiera de los dos) se muestra
``N/D`` con el motivo y el criterio 2 se califica 0; nunca se inventa un valor.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ..estilos import colores
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.eps")

# ---------------------------------------------------------------- formulas
FORMULA_DIFERENCIA = "Diferencia = EPS actual - EPS estimado (forecast)"
FORMULA_DIFERENCIA_REL = "Diferencia relativa = (EPS actual - EPS estimado) / |EPS estimado|"
FORMULA_SORPRESA = "Sorpresa positiva si EPS actual >= EPS estimado (forecast)"
FORMULA_CRITERIO = "Criterio 2: EPS actual >= EPS estimado (forecast)"

# ---------------------------------------------------------------- columnas
COLUMNAS_COMPARACION: List[str] = [
    "Indicador",
    "Empresa",
    "Estimado (forecast)",
    "Diferencia",
    "Diferencia relativa",
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
    "Empresa": "EPS actual (beneficio por accion de los ultimos 12 meses).",
    "Estimado (forecast)": "EPS estimado por los analistas para el mismo periodo.",
    "Diferencia": FORMULA_DIFERENCIA,
    "Diferencia relativa": FORMULA_DIFERENCIA_REL,
    "Resultado": FORMULA_SORPRESA,
    "Formula": "Formula exacta del indicador.",
}
TOOLTIPS_CRITERIO: Dict[str, str] = {
    "#": "Numero del criterio en la parrilla de decision del pliego.",
    "Criterio": "Enunciado del criterio.",
    "Optimo": "Sentido en el que el criterio se cumple.",
    "Estado": "CUMPLE (1 punto), NO CUMPLE (0 puntos) o N/D (dato ausente, 0 puntos).",
    "Calificacion": "1 si cumple, 0 si no cumple o si el dato es N/D.",
    "Valor obtenido": "EPS actual de la empresa.",
    "Valor de comparacion": "EPS estimado (forecast).",
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


class TabEPS(TabConGrafico):
    """Pestana del beneficio por accion: actual frente a estimado (criterio 2)."""

    titulo = "EPS"

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
        _titulo(caja, "EPS - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para comparar el "
            f"EPS actual con el estimado y evaluar el criterio 2.",
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

        _titulo(caja, f"EPS - {r.ticker}", self._subtitulo(r))
        self._bloque_tarjetas(caja, r)
        self._bloque_comparacion(caja, r)
        self._bloque_criterio(caja, r)
        self._bloque_procedencia(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con el EPS actual, el estimado y la sorpresa."""
        f = r.fundamentales
        eps_actual = a_float(f.eps)
        eps_estimado = a_float(f.eps_forecast)
        diferencia, relativa = self._diferencias(eps_actual, eps_estimado)
        criterio = _criterio(r, 2)
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "EPS actual": _moneda(eps_actual, r.moneda, 2),
                "EPS estimado (forecast)": _moneda(eps_estimado, r.moneda, 2),
                "Diferencia": _moneda(diferencia, r.moneda, 2),
                "Diferencia relativa": fmt_pct(relativa, 2),
                "Sorpresa": self._sorpresa(eps_actual, eps_estimado),
                "Criterio 2": "CUMPLE" if criterio is not None and criterio.cumple else ("NO CUMPLE" if criterio is not None else ND),
                "Precio (spot) de referencia": _moneda(r.spot, r.moneda, 2),
                "Sector declarado": f.sector or ND,
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "EPS actual": "Beneficio por accion de los ultimos 12 meses (trailing EPS).",
                "EPS estimado (forecast)": "Beneficio por accion estimado por los analistas (forward EPS).",
                "Diferencia": FORMULA_DIFERENCIA,
                "Diferencia relativa": FORMULA_DIFERENCIA_REL,
                "Sorpresa": FORMULA_SORPRESA,
                "Criterio 2": FORMULA_CRITERIO,
                "Precio (spot) de referencia": "Spot usado para el PER y el CAPM (contexto de la sorpresa).",
                "Sector declarado": "Sector de la empresa segun el proveedor de datos.",
            },
            colores={
                "Sorpresa": (
                    VERDE
                    if (eps_actual is not None and eps_estimado is not None and eps_actual >= eps_estimado)
                    else (ROJO if (eps_actual is not None and eps_estimado is not None) else AMBAR)
                ),
                "Criterio 2": _color_criterio(criterio),
            },
        )
        caja.addWidget(tarjetas)
        if eps_estimado is None:
            _aviso(
                caja,
                "N/D: no hay EPS estimado (forecast) para este ticker; la sorpresa no se puede calcular y el "
                "criterio 2 se califica 0.",
            )
        if eps_actual is None:
            _aviso(
                caja,
                "N/D: no hay EPS actual para este ticker; la diferencia y la sorpresa no se pueden calcular y el "
                "criterio 2 se califica 0.",
            )

    @staticmethod
    def _diferencias(eps_actual: Optional[float], eps_estimado: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        """Diferencia absoluta y relativa entre el EPS actual y el estimado.

        La relativa se calcula sobre el valor absoluto del estimado para que el
        signo indique si el actual queda por encima (positivo) o por debajo.
        """
        if eps_actual is None or eps_estimado is None:
            return None, None
        diferencia = eps_actual - eps_estimado
        if eps_estimado == 0:
            return diferencia, None
        return diferencia, diferencia / abs(eps_estimado)

    @staticmethod
    def _sorpresa(eps_actual: Optional[float], eps_estimado: Optional[float]) -> str:
        """Lectura cualitativa de la sorpresa de resultados."""
        if eps_actual is None or eps_estimado is None:
            return ND
        if eps_actual >= eps_estimado:
            return "Sorpresa positiva (actual >= estimado)"
        return "Por debajo del estimado (actual < estimado)"

    # ---------------------------------------------------------- comparacion
    def _bloque_comparacion(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Cuadro de comparacion EPS actual frente a estimado."""
        _titulo(caja, "Comparacion: EPS actual frente a EPS estimado", FORMULA_DIFERENCIA)
        f = r.fundamentales
        eps_actual = a_float(f.eps)
        eps_estimado = a_float(f.eps_forecast)
        diferencia, relativa = self._diferencias(eps_actual, eps_estimado)
        filas: List[Dict[str, Any]] = [
            {
                "Indicador": "EPS (beneficio por accion)",
                "Empresa": eps_actual,
                "Estimado (forecast)": eps_estimado,
                "Diferencia": diferencia,
                "Diferencia relativa": relativa,
                "Resultado": self._sorpresa(eps_actual, eps_estimado),
                "Formula": FORMULA_DIFERENCIA,
            }
        ]
        tabla = TablaDML(COLUMNAS_COMPARACION, tooltips_columnas=TOOLTIPS_COMPARACION)
        # ordenar=False: los valores se escriben despues por indice (fila 0 =
        # empresa), y ordenar antes de escribirlos los pondria en otra fila.
        tabla.cargar_filas(filas, COLUMNAS_COMPARACION, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Empresa"),
            [_moneda(eps_actual, r.moneda, 2) if eps_actual is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Estimado (forecast)"),
            [_moneda(eps_estimado, r.moneda, 2) if eps_estimado is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia"),
            [_moneda(diferencia, r.moneda, 2) if diferencia is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Diferencia relativa"),
            [fmt_pct(relativa, 2) if relativa is not None else None],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # ------------------------------------------------------------- criterio
    def _bloque_criterio(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Estado del criterio 2 de la parrilla de decision."""
        criterio = _criterio(r, 2)
        _titulo(caja, "Criterio 2 de la parrilla", FORMULA_CRITERIO)
        _etiqueta_estado(caja, _texto_criterio(criterio, 2, "EPS actual >= EPS estimado"), _color_criterio(criterio))
        filas = [_fila_criterio(criterio, 2, "EPS actual >= EPS estimado (forecast)", "Mayor o igual es mejor")]
        tabla = TablaDML(
            COLUMNAS_CRITERIO,
            colores_condicionales=_color_estado(COLUMNAS_CRITERIO.index("Estado")),
            tooltips_columnas=TOOLTIPS_CRITERIO,
        )
        tabla.cargar_filas(filas, COLUMNAS_CRITERIO, ordenar=False)
        unidad = criterio.unidad if criterio is not None else "numero"
        _aplicar_formatos(
            tabla,
            COLUMNAS_CRITERIO.index("Valor obtenido"),
            [_moneda(filas[0]["Valor obtenido"], r.moneda, 2) if a_float(filas[0]["Valor obtenido"]) is not None else _formato_unidad(filas[0]["Valor obtenido"], unidad, r.moneda)],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_CRITERIO.index("Valor de comparacion"),
            [_moneda(filas[0]["Valor de comparacion"], r.moneda, 2) if a_float(filas[0]["Valor de comparacion"]) is not None else _formato_unidad(filas[0]["Valor de comparacion"], unidad, r.moneda)],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

    # --------------------------------------------------------- procedencia
    def _bloque_procedencia(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Procedencia de cada valor del bloque EPS."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada valor.")
        f = r.fundamentales
        ruta_eps = _ruta(r, "eps")
        filas: List[Dict[str, Any]] = [
            _fila_origen("EPS actual (trailing)", a_float(f.eps), f.ev_eps, ruta_eps),
            _fila_origen("EPS estimado (forecast)", a_float(f.eps_forecast), f.ev_eps_forecast, ruta_eps),
            _fila_origen(
                "Diferencia (calculada)",
                self._diferencias(a_float(f.eps), a_float(f.eps_forecast))[0],
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_DIFERENCIA),
                ruta_eps,
            ),
            _fila_origen(
                "Diferencia relativa (calculada)",
                self._diferencias(a_float(f.eps), a_float(f.eps_forecast))[1],
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_DIFERENCIA_REL),
                ruta_eps,
            ),
            _fila_origen(
                "Sorpresa (calculada)",
                self._sorpresa(a_float(f.eps), a_float(f.eps_forecast)),
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_SORPRESA),
                ruta_eps,
            ),
            _fila_origen(
                "PER de la empresa (contexto)",
                a_float(f.per),
                f.ev_per,
                _ruta(r, "per"),
                "Contexto: el PER usa el EPS y el precio; su detalle esta en la pestana PER.",
            ),
        ]
        tabla = TablaDML(COLUMNAS_ORIGEN, tooltips_columnas=TOOLTIPS_ORIGEN)
        tabla.cargar_filas(filas, COLUMNAS_ORIGEN, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_ORIGEN.index("Valor"),
            [
                _moneda(filas[0]["Valor"], r.moneda, 2) if a_float(filas[0]["Valor"]) is not None else None,
                _moneda(filas[1]["Valor"], r.moneda, 2) if a_float(filas[1]["Valor"]) is not None else None,
                _moneda(filas[2]["Valor"], r.moneda, 2) if a_float(filas[2]["Valor"]) is not None else None,
                fmt_pct(filas[3]["Valor"], 2) if a_float(filas[3]["Valor"]) is not None else None,
                None,
                fmt_num(filas[5]["Valor"], 2) if a_float(filas[5]["Valor"]) is not None else None,
            ],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: 'Beneficios' (earnings) de la ficha del valor "
            f"({_texto_ruta(r, 'eps', 'EPS actual y estimado')}). El EPS estimado es el consenso de analistas del "
            "proximo ejercicio; si no esta disponible se muestra N/D y el criterio 2 se califica 0.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Barras comparando el EPS actual y el estimado."""
        _titulo(caja, "EPS actual frente a EPS estimado", FORMULA_SORPRESA)
        self._grafico = GraficoDML(titulo="EPS", alto=3.0, ancho=6)
        self._grafico.setMinimumHeight(280)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja las dos barras de EPS (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            fundamentales = r.fundamentales if r is not None else None
            moneda = r.moneda if r is not None else "USD"
            eps_actual = a_float(fundamentales.eps) if fundamentales is not None else None
            eps_estimado = a_float(fundamentales.eps_forecast) if fundamentales is not None else None
            etiquetas = ["EPS actual", "EPS estimado"]
            valores = [eps_actual, eps_estimado]
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
                        _moneda(valor, moneda, 2),
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
                        "N/D: " + ", ".join(faltan) + " (no disponible: la sorpresa no se puede calcular)",
                        transform=eje.transAxes,
                        va="top",
                        fontsize=8,
                        color=AMBAR,
                    )
                tope = max(abs(valor) for _, valor, _ in disponibles) * 1.4 or 1.0
                eje.set_ylim(min(0.0, min(valor for _, valor, _ in disponibles) * 1.4), tope)
                eje.axhline(0.0, color=paleta["borde"], linewidth=0.8)
            else:
                eje.text(
                    0.5,
                    0.5,
                    "N/D: no hay EPS actual ni estimado; el criterio 2 se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            eje.set_ylabel(f"Beneficio por accion ({_simbolo(moneda)})")
            eje.set_title("EPS actual vs EPS estimado")
            eje.grid(True, axis="y", color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar el grafico de EPS: %s", exc)
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
