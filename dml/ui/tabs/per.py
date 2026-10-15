# -*- coding: utf-8 -*-
"""Pestana "PER": PER de la empresa frente al del sector y criterio 1.

La pestana muestra, en este orden:

1. Tarjetas con el PER de la empresa, el del sector, la diferencia (absoluta y
   relativa), el veredicto (mas barata / mas cara) y el estado del criterio 1.
2. Cuadro de comparacion ``PER empresa`` vs ``PER sector`` con la formula
   ``PER = Precio / EPS`` en el tooltip de cada columna.
3. Estado del criterio 1 de la parrilla (``self.resultado.criterios``), con su
   calificacion y la nota del motivo cuando no se puede evaluar.
4. Procedencia de cada valor (``fundamentales.ev_per`` y ``ev_per_sector``:
   fuente, metodo, URL y ruta de Investing.com) y una comprobacion del PER
   recalculado como ``Spot / EPS``.
5. Grafico de barras comparando los dos PER.

Regla del pliego: un PER negativo (empresa con perdidas) o ausente se muestra
como ``N/D`` con el motivo y el criterio se califica 0; nunca se inventa un
multiplo.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.fundamentales import per_valor
from ..estilos import colores
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.per")

# ---------------------------------------------------------------- formulas
FORMULA_PER = "PER = Precio / EPS"
FORMULA_DIFERENCIA = "Diferencia = PER empresa - PER sector"
FORMULA_DIFERENCIA_REL = "Diferencia relativa = (PER empresa - PER sector) / PER sector"
FORMULA_CRITERIO = "Criterio 1: PER empresa < PER sector (menor es mejor)"

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
    "Empresa": f"Valor de la empresa analizada. {FORMULA_PER}.",
    "Sector (comparable)": "PER de referencia del sector (mediana de pares o multiplo de config.yaml).",
    "Diferencia": FORMULA_DIFERENCIA,
    "Diferencia relativa": FORMULA_DIFERENCIA_REL,
    "Resultado": "Lectura de la comparacion: mas barata o mas cara que el sector.",
    "Formula": "Formula exacta del indicador.",
}
TOOLTIPS_CRITERIO: Dict[str, str] = {
    "#": "Numero del criterio en la parrilla de decision del pliego.",
    "Criterio": "Enunciado del criterio.",
    "Optimo": "Sentido en el que el criterio se cumple.",
    "Estado": "CUMPLE (1 punto), NO CUMPLE (0 puntos) o N/D (dato ausente, 0 puntos).",
    "Calificacion": "1 si cumple, 0 si no cumple o si el dato es N/D.",
    "Valor obtenido": "Valor del indicador en la empresa.",
    "Valor de comparacion": "Valor contra el que se compara (sector o umbral).",
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
        return (
            f"Criterio {numero} - {nombre}: N/D (el criterio no esta en la parrilla y se califica 0)."
        )
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


def _per_utilizable(valor: Any) -> Optional[float]:
    """PER interpretable: positivo y no nulo (un PER negativo no es comparable)."""
    numero = a_float(valor)
    if numero is None or numero <= 0:
        return None
    return numero


def _nota_per(valor: Any) -> str:
    """Motivo por el que el PER no es interpretable (cadena vacia si lo es)."""
    numero = a_float(valor)
    if numero is None:
        return "N/D: el PER de la empresa no esta disponible; el criterio 1 se califica 0"
    if numero <= 0:
        return (
            f"N/D: el PER es negativo o nulo ({fmt_num(numero, 2)}) porque la empresa presenta perdidas; "
            "no es comparable con el multiplo del sector y el criterio 1 se califica 0"
        )
    return ""


class TabPER(TabConGrafico):
    """Pestana del multiplo PER: empresa frente a sector y criterio 1."""

    titulo = "PER"

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
        _titulo(caja, "PER - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para comparar el "
            f"PER de la empresa con el del sector ({FORMULA_PER}) y evaluar el criterio 1.",
        )

    def _subtitulo(self, r: ResultadoAnalisis) -> str:
        """Linea de contexto del analisis mostrado."""
        partes = [f"Ticker {r.ticker}"]
        if r.fundamentales.sector:
            partes.append(f"Sector {r.fundamentales.sector}")
        if r.fundamentales.industria:
            partes.append(r.fundamentales.industria)
        partes.append(f"Modo {r.modo}")
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

        _titulo(caja, f"PER - {r.ticker}", self._subtitulo(r))
        self._bloque_tarjetas(caja, r)
        self._bloque_comparacion(caja, r)
        self._bloque_criterio(caja, r)
        self._bloque_procedencia(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con el multiplo de la empresa y del sector."""
        f = r.fundamentales
        per_empresa = _per_utilizable(f.per)
        per_sector = _per_utilizable(f.per_sector)
        diferencia = None
        relativa = None
        if per_empresa is not None and per_sector is not None:
            diferencia = per_empresa - per_sector
            if per_sector != 0:
                relativa = (per_empresa - per_sector) / per_sector
        veredicto = self._veredicto(per_empresa, per_sector)
        criterio = _criterio(r, 1)
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "PER empresa": fmt_num(per_empresa, 2),
                "PER sector": fmt_num(per_sector, 2),
                "Diferencia": fmt_num(diferencia, 2),
                "Diferencia relativa": fmt_pct(relativa, 2),
                "Veredicto": veredicto,
                "Criterio 1": "CUMPLE" if criterio is not None and criterio.cumple else ("NO CUMPLE" if criterio is not None else ND),
                "Renta PER (1/PER)": fmt_pct(1.0 / per_empresa, 2) if per_empresa else ND,
                "Sector declarado": f.sector or ND,
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "PER empresa": f"{FORMULA_PER}. Un PER negativo o ausente se muestra como N/D.",
                "PER sector": "PER de referencia del sector (mediana de pares o multiplo de config.yaml).",
                "Diferencia": FORMULA_DIFERENCIA,
                "Diferencia relativa": FORMULA_DIFERENCIA_REL,
                "Veredicto": "Mas barata / mas cara que el sector segun el PER (menor es mejor).",
                "Criterio 1": FORMULA_CRITERIO,
                "Renta PER (1/PER)": "Renta PER = 1 / PER (rentabilidad implicita del precio pagado).",
                "Sector declarado": "Sector con el que se compara la empresa.",
            },
            colores={
                "Veredicto": (
                    VERDE if (diferencia is not None and diferencia < 0) else (ROJO if diferencia is not None else AMBAR)
                ),
                "Criterio 1": _color_criterio(criterio),
            },
        )
        caja.addWidget(tarjetas)
        nota = _nota_per(f.per)
        if nota:
            _aviso(caja, nota)
        if per_sector is None:
            _aviso(caja, "N/D: no hay PER de referencia del sector; el criterio 1 se califica 0.")

    @staticmethod
    def _veredicto(per_empresa: Optional[float], per_sector: Optional[float]) -> str:
        """Lectura cualitativa de la comparacion de multiplos."""
        if per_empresa is None or per_sector is None:
            return ND
        if per_empresa < per_sector:
            return "Mas barata que el sector"
        if per_empresa > per_sector:
            return "Mas cara que el sector"
        return "En linea con el sector"

    # ---------------------------------------------------------- comparacion
    def _bloque_comparacion(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Cuadro de comparacion empresa frente a sector."""
        _titulo(caja, "Comparacion: PER empresa frente a PER sector", f"{FORMULA_PER} (menor es mejor)")
        f = r.fundamentales
        per_empresa = _per_utilizable(f.per)
        per_sector = _per_utilizable(f.per_sector)
        diferencia = (per_empresa - per_sector) if (per_empresa is not None and per_sector is not None) else None
        relativa = (
            (per_empresa - per_sector) / per_sector if (per_empresa is not None and per_sector not in (None, 0)) else None
        )
        filas: List[Dict[str, Any]] = [
            {
                "Indicador": "PER (Precio / BPA)",
                "Empresa": per_empresa,
                "Sector (comparable)": per_sector,
                "Diferencia": diferencia,
                "Diferencia relativa": relativa,
                "Resultado": self._veredicto(per_empresa, per_sector),
                "Formula": FORMULA_PER,
            }
        ]
        tabla = TablaDML(COLUMNAS_COMPARACION, tooltips_columnas=TOOLTIPS_COMPARACION)
        tabla.cargar_filas(filas, COLUMNAS_COMPARACION)
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Empresa"),
            [fmt_num(per_empresa, 2) if per_empresa is not None else None],
        )
        _aplicar_formatos(
            tabla,
            COLUMNAS_COMPARACION.index("Sector (comparable)"),
            [fmt_num(per_sector, 2) if per_sector is not None else None],
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

    # ------------------------------------------------------------- criterio
    def _bloque_criterio(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Estado del criterio 1 de la parrilla de decision."""
        criterio = _criterio(r, 1)
        _titulo(caja, "Criterio 1 de la parrilla", FORMULA_CRITERIO)
        _etiqueta_estado(caja, _texto_criterio(criterio, 1, "PER empresa < PER sector"), _color_criterio(criterio))
        filas = [_fila_criterio(criterio, 1, "PER empresa < PER sector", "Menor es mejor")]
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
        """Procedencia de cada valor y comprobacion del PER recalculado."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada valor.")
        f = r.fundamentales
        ruta_per = _ruta(r, "per")
        per_comprobado, nota_comprobado = per_valor(r.spot, f.eps)
        filas: List[Dict[str, Any]] = [
            _fila_origen("PER de la empresa", _per_utilizable(f.per), f.ev_per, ruta_per),
            _fila_origen("PER del sector (comparable)", _per_utilizable(f.per_sector), f.ev_per_sector, ruta_per),
            _fila_origen(
                "PER de comprobacion (Spot / EPS)",
                per_comprobado,
                Evidence(
                    fuente="Calculado",
                    metodo="calculo",
                    nota=nota_comprobado or f"Comprobacion del multiplo con {FORMULA_PER}.",
                ),
                ruta_per,
            ),
            _fila_origen(
                "Precio (spot) usado en la comprobacion",
                r.spot,
                None,
                ruta_per,
                "N/D: el resultado no conserva el registro de procedencia del spot; consulta la pestana Fuentes.",
            ),
            _fila_origen("EPS usado en la comprobacion", a_float(f.eps), f.ev_eps, ruta_per),
            _fila_origen(
                "Interpretacion del PER de la empresa",
                "SI" if _per_utilizable(f.per) is not None else ND,
                Evidence(
                    fuente="Calculado",
                    metodo="calculo",
                    nota=_nota_per(f.per)
                    or "PER positivo: interpretable y comparable con el multiplo del sector.",
                ),
                ruta_per,
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
                fmt_num(filas[2]["Valor"], 2) if a_float(filas[2]["Valor"]) is not None else None,
                _moneda(filas[3]["Valor"], r.moneda, 2) if a_float(filas[3]["Valor"]) is not None else None,
                _moneda(filas[4]["Valor"], r.moneda, 2) if a_float(filas[4]["Valor"]) is not None else None,
                fmt_num(filas[5]["Valor"], 2) if a_float(filas[5]["Valor"]) is not None else None,
            ],
        )
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: 'Ratios' de la ficha del valor "
            f"({_texto_ruta(r, 'per', 'PER de la empresa')}); el PER del sector se contrasta con la mediana de "
            "los pares del sector o con el multiplo de referencia de config.yaml. Si el PER de la empresa es "
            "negativo (perdidas) se muestra N/D y el criterio 1 se califica 0.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Barras comparando el PER de la empresa y el del sector."""
        _titulo(
            caja,
            "PER empresa frente a PER sector",
            f"{FORMULA_PER}; el sector se dibuja solo si hay multiplo de referencia.",
        )
        self._grafico = GraficoDML(titulo="PER", alto=3.0, ancho=6)
        self._grafico.setMinimumHeight(280)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja las dos barras de PER (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            fundamentales = r.fundamentales if r is not None else None
            per_empresa = _per_utilizable(fundamentales.per) if fundamentales is not None else None
            per_sector = _per_utilizable(fundamentales.per_sector) if fundamentales is not None else None
            etiquetas = ["PER empresa", "PER sector"]
            valores = [per_empresa, per_sector]
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
                        "N/D: " + ", ".join(faltan) + " (no interpretable o no disponible)",
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
                    "N/D: no hay PER de la empresa ni del sector; el criterio 1 se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            eje.set_ylabel("Veces (x)")
            eje.set_title("PER empresa vs PER sector")
            eje.grid(True, axis="y", color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar el grafico de PER: %s", exc)
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
