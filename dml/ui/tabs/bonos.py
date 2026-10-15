# -*- coding: utf-8 -*-
"""Pestana "Bonos y tasas": las tres tasas de referencia y su procedencia.

Contenido:

1. Tabla de las tres tasas (T-Bill 4 semanas = TLR, bono 10 anios, bono 30
   anios) con el valor en porcentaje, el **metodo realmente usado**
   (``scraping`` = Investing.com, ``respaldo`` = FRED/Yahoo, ``manual``,
   ``demo``) y la URL de la fuente.
2. Distintivo por tasa cuando el valor es de respaldo ("Respaldo: FRED" /
   "Respaldo: Yahoo Finance ...").
3. Tabla de diferencias en puntos base entre Investing.com y el respaldo,
   con la nota de que una tasa a **descuento** nunca se mezcla con un
   rendimiento equivalente de bono sin convertir (la brecha tipica es de 15-20
   pb y por encima de 25 pb se resalta en rojo).
4. Grafico del historico mensual (TLR y, si existe, 10 y 30 anios).
5. Notas sobre la conversion ``y = 365 * d / (360 - d * 28)`` y sobre por que
   ``^IRX`` (T-Bill a 13 semanas) **no** se usa como TLR de 4 semanas.

La pestana tolera ``resultado is None`` (estado vacio) y series ``None`` (sin
grafico, con mensaje informativo) sin fallar.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.dates as mdates
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTableWidgetItem, QWidget

from ...core.tipos import ND, Evidence, ResultadoAnalisis, Tasas
from ...core.util import a_float, fmt_num
from ..widgets import AMBAR, GRIS, ROJO, VERDE, EtiquetaAviso, GraficoDML, TablaDML
from .base import TabBase

LOG = logging.getLogger("dml.ui.tabs.bonos")

#: Intentamos el resumen ya formateado de la capa de datos; si no esta, se
#: construyen las filas aqui a partir de ``resultado.tasas``.
try:  # pragma: no cover - depende del estado del paquete
    from ...data.tasas import resumen_tasas as _resumen_tasas
except Exception:  # noqa: BLE001 - degradacion controlada sin la capa de datos
    _resumen_tasas = None

#: Claves de las tres tasas y su etiqueta legible.
CLAVES: Tuple[str, ...] = ("tbill_4w", "ust_10y", "ust_30y")
ETIQUETAS: Dict[str, str] = {
    "tbill_4w": "T-Bill EE.UU. 4 semanas (TLR)",
    "ust_10y": "Bono EE.UU. 10 anios",
    "ust_30y": "Bono EE.UU. 30 anios",
}

#: Metodo -> (texto mostrado, color).
METODOS: Dict[str, Tuple[str, str]] = {
    "scraping": ("Investing.com (scraping)", VERDE),
    "investing": ("Investing.com (scraping)", VERDE),
    "API": ("API", VERDE),
    "respaldo": ("Respaldo", AMBAR),
    "fred": ("Respaldo: FRED", AMBAR),
    "yahoo": ("Respaldo: Yahoo Finance", AMBAR),
    "manual": ("Manual", "#4da3ff"),
    "demo": ("DEMO (datos ficticios)", "#a06bd6"),
    "calculo": ("Calculo", GRIS),
    "N/D": ("N/D: sin dato", ROJO),
}

#: Series mensuales por clave (para el grafico) y su color.
SERIES: Dict[str, Tuple[str, str]] = {
    "tbill_4w": ("serie_tbill_mensual", "#31c48d"),
    "ust_10y": ("serie_10y_mensual", "#4da3ff"),
    "ust_30y": ("serie_30y_mensual", "#f2b544"),
}

NOTA_CONVERSION = (
    "Conversion descuento -> rendimiento: y = 365 x d / (360 - d x 28), donde d es la tasa de descuento "
    "anualizada del T-Bill (base 360) y 28 el plazo en dias. Se aplica solo cuando la unica fuente disponible "
    "era el T-Bill a descuento (DTB4WK) de FRED: una tasa a descuento NUNCA se mezcla con los rendimientos "
    "equivalentes de bono de Investing.com sin convertir antes, porque la diferencia ronda los 15-20 puntos base."
)

NOTA_IRX = (
    "^IRX es el T-Bill a 13 semanas (3 meses) y por eso NO se usa como TLR de 4 semanas: el plazo no coincide "
    "con el exigido por el pliego. Solo se admiten Yahoo Finance ^TNX (10 anios) y ^TYX (30 anios) como respaldo "
    "de sus bonos, y FRED DGS1MO (o DTB4WK convertido) como respaldo del T-Bill de 4 semanas."
)

NOTA_DIFERENCIAS = (
    "Una tasa a descuento nunca debe mezclarse con un rendimiento equivalente de bono sin convertir: la brecha "
    "tipica entre ambas es de 15-20 puntos base. Se resaltan en rojo las diferencias por encima de 25 pb."
)


def _texto_tasa(valor: Optional[float], decimales: int = 4) -> str:
    """Tasa en fraccion mostrada como porcentaje con 2-4 decimales."""
    numero = a_float(valor)
    if numero is None:
        return ND
    return f"{numero * 100.0:.{decimales}f}%"


def _metodo_legible(metodo: str) -> Tuple[str, str]:
    """Texto y color del metodo de obtencion de una tasa."""
    return METODOS.get(str(metodo or ND), (str(metodo or ND), GRIS))


def _fuente_de(evidence: Optional[Evidence], metodo: str, url: str) -> str:
    """Fuente efectiva de una tasa (Evidence primero, luego el metodo)."""
    if evidence is not None and evidence.fuente:
        return evidence.fuente
    asociados = {
        "respaldo": "FRED / Yahoo Finance",
        "scraping": "Investing.com",
        "investing": "Investing.com",
        "manual": "Introducido manualmente",
        "demo": "DEMO (datos ficticios)",
    }
    return asociados.get(str(metodo or ""), ND)


def _celda(texto: str, dato: Any = None, color: Optional[str] = None, tooltip: str = "", alineacion: Any = None) -> QTableWidgetItem:
    """Crea una celda con valor de ordenacion, color y tooltip."""
    item = QTableWidgetItem(str(texto))
    item.setData(Qt.UserRole, dato if dato is not None else texto)
    if color:
        item.setForeground(QBrush(QColor(color)))
    if tooltip:
        item.setToolTip(tooltip)
    if alineacion is not None:
        item.setTextAlignment(alineacion)
    return item


class TabBonos(TabBase):
    """Tasas de referencia: valor, metodo, respaldo, diferencias e historico."""

    titulo = "Bonos y tasas"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)

        self.add_titulo(
            "Bonos y tasas de referencia",
            "TLR = T-Bill de EE.UU. a 4 semanas; se anaden el bono a 10 y a 30 anios. "
            "Se muestra el metodo realmente usado para cada tasa (Investing.com, respaldo, manual o demo).",
        )

        # ---- distintivos de respaldo --------------------------------------
        marco = QWidget()
        caja = QHBoxLayout(marco)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(12)
        self._badges: Dict[str, QLabel] = {}
        for clave in CLAVES:
            etiqueta = QLabel(f"{ETIQUETAS[clave]}: {ND}")
            etiqueta.setObjectName("subtitulo")
            etiqueta.setWordWrap(True)
            caja.addWidget(etiqueta)
            self._badges[clave] = etiqueta
        caja.addStretch(1)
        self.add(marco)

        # ---- tabla de las tres tasas --------------------------------------
        self.add_titulo("Tasas de referencia", "Valor en porcentaje, metodo usado y URL de la fuente.")
        self._tabla = TablaDML(
            ["Tasa", "Valor", "Metodo", "Fuente", "URL"],
            tooltips_columnas={
                "Tasa": "Instrumento de referencia.",
                "Valor": "Tasa anual en porcentaje (fraccion x 100).",
                "Metodo": "scraping = Investing.com; respaldo = FRED/Yahoo; manual; demo.",
                "Fuente": "Fuente efectiva del dato.",
                "URL": "URL consultada (tooltip con la direccion completa).",
            },
        )
        self._tabla.setMinimumHeight(150)
        self.add(self._tabla)

        # ---- diferencias entre fuentes -------------------------------------
        self.add_titulo(
            "Diferencias entre fuentes",
            "Investing.com frente al respaldo, en puntos base. " + NOTA_DIFERENCIAS,
        )
        self._tabla_dif = TablaDML(
            ["Tasa", "Investing.com", "Respaldo", "Diferencia (pb)", "Fuente del respaldo", "Nota"],
            tooltips_columnas={
                "Investing.com": "Valor de Investing.com en porcentaje.",
                "Respaldo": "Valor de la fuente de respaldo en porcentaje (FRED / Yahoo Finance).",
                "Diferencia (pb)": "Diferencia en puntos base; se resalta en rojo por encima de 25 pb.",
                "Fuente del respaldo": "Fuente de respaldo usada para la comparacion.",
                "Nota": NOTA_DIFERENCIAS,
            },
        )
        self._tabla_dif.setMinimumHeight(150)
        self.add(self._tabla_dif)
        self._nota_dif = EtiquetaAviso()
        self._nota_dif.mostrar([NOTA_DIFERENCIAS])
        self.add(self._nota_dif)

        # ---- historico mensual ---------------------------------------------
        self.add_titulo("Historico mensual", "Serie mensual de la TLR y, cuando estan disponibles, de los bonos a 10 y 30 anios.")
        self._aviso_grafico = EtiquetaAviso()
        self.add(self._aviso_grafico)
        self._grafico = GraficoDML(titulo="Tasas mensuales", alto=4, ancho=9)
        self.add(self._grafico)

        # ---- notas metodologicas -------------------------------------------
        self.add_titulo("Notas metodologicas", "Reglas del pliego sobre la conversion y el respaldo de las tasas.")
        self._notas = EtiquetaAviso()
        self.add(self._notas)

        # ---- advertencias ---------------------------------------------------
        self.add_titulo("Advertencias", "Avisos registrados al obtener las tasas.")
        self._avisos = EtiquetaAviso()
        self.add(self._avisos)

        # Estado del grafico (para redibujarlo al cambiar de tema).
        self._series: Dict[str, pd.Series] = {}

        self.cargar([], None)

    # ------------------------------------------------------------------ API
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta las tasas del resultado actual (o el estado vacio)."""
        lista = [r for r in (resultados or []) if r is not None]
        self.resultados = lista
        self.resultado = actual if actual is not None else (lista[0] if lista else None)
        tasas = self.resultado.tasas if self.resultado is not None else None
        self._pintar(resultado=self.resultado, tasas=tasas)

    def refrescar_tema(self, tema: str) -> None:
        """Redibuja el historico mensual con la paleta del tema indicado."""
        self.tema_actual = tema
        if self._tema_graficado == tema:
            return
        try:
            self._dibujar_grafico()
            self._grafico.refrescar(tema)
            self._graficos_al_dia(tema)
        except Exception:  # pragma: no cover - defensivo
            LOG.debug("No se pudo refrescar el grafico de tasas con el tema %s", tema)

    # --------------------------------------------------------------- pintado
    def _pintar(self, resultado: Optional[ResultadoAnalisis], tasas: Optional[Tasas]) -> None:
        """Repinta todos los bloques de la pestana."""
        if tasas is None:
            self._pintar_vacio()
            return
        self._pintar_tasas(tasas)
        self._pintar_diferencias(tasas)
        self._pintar_grafico(tasas)
        self._pintar_advertencias(tasas)
        self._notas.mostrar([NOTA_CONVERSION, NOTA_IRX])

    def _pintar_tasas(self, tasas: Tasas) -> None:
        """Tabla de las tres tasas con metodo y URL."""
        filas = self._filas_resumen(tasas)
        tabla = self._tabla
        tabla.setSortingEnabled(False)
        tabla.setColumnCount(6)
        tabla.setHorizontalHeaderLabels(["Tasa", "Valor", "Metodo", "Fuente", "URL", "_orden"])
        tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            clave = str(fila.get("_clave") or "")
            valor = a_float(fila.get("Valor"))
            metodo = str(fila.get("Metodo") or ND)
            texto_metodo, color = _metodo_legible(metodo)
            evidence = self._evidence(tasas, clave)
            url = str(fila.get("URL") or (evidence.url if evidence is not None else "") or "")
            fuente = str(fila.get("Fuente") or _fuente_de(evidence, metodo, url))
            tooltip_valor = f"{ETIQUETAS.get(clave, clave)}: {_texto_tasa(valor)}"
            if valor is None:
                tooltip_valor += " | N/D: no se pudo obtener de ninguna fuente (Investing.com, FRED, Yahoo o manual)."
            if evidence is not None and evidence.nota:
                tooltip_valor += f" | {evidence.nota}"
            tooltip_metodo = texto_metodo
            if evidence is not None and evidence.consultado:
                tooltip_metodo += f" | Consultado: {evidence.consultado}"
            celdas = [
                _celda(ETIQUETAS.get(clave, str(fila.get("Tasa") or ND)), clave, color, ETIQUETAS.get(clave, ""), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(_texto_tasa(valor), valor, color, tooltip_valor, Qt.AlignRight | Qt.AlignVCenter),
                _celda(texto_metodo, metodo, color, tooltip_metodo, Qt.AlignLeft | Qt.AlignVCenter),
                _celda(fuente or ND, fuente, color, fuente or ND, Qt.AlignLeft | Qt.AlignVCenter),
                _celda(url or ND, url, color, url or "N/D: sin URL para este dato.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(i + 1), i, GRIS, "Orden del pliego: TLR, 10 anios, 30 anios.", Qt.AlignRight | Qt.AlignVCenter),
            ]
            for j, celda in enumerate(celdas):
                tabla.setItem(i, j, celda)
        tabla.setSortingEnabled(True)
        # La columna oculta de orden recupera la secuencia del pliego (TLR, 10 y
        # 30 anios), que la tabla pierde al reordenar las filas mientras se pintan.
        tabla.sortItems(5, Qt.AscendingOrder)
        tabla.setColumnHidden(5, True)
        tabla.resizeColumnsToContents()
        for i in range(tabla.rowCount()):
            item = tabla.item(i, 4)
            if item is not None:
                item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self._pintar_badges(tasas)

    def _pintar_badges(self, tasas: Tasas) -> None:
        """Distintivo por tasa: valor, metodo efectivo y "Respaldo: ..." cuando toca."""
        for clave in CLAVES:
            evidence = self._evidence(tasas, clave)
            metodo = tasas.metodo_de(clave)
            texto_metodo, color = _metodo_legible(metodo)
            valor = _texto_tasa(a_float(getattr(tasas, clave, None)))
            etiqueta = f"{ETIQUETAS[clave]}: {valor} \u00b7 {texto_metodo}"
            if evidence is not None and evidence.es_respaldo:
                fuente = evidence.fuente or "Respaldo"
                color = AMBAR
                etiqueta = f"{ETIQUETAS[clave]}: {valor} \u00b7 Respaldo: {fuente}"
            elif a_float(getattr(tasas, clave, None)) is None:
                color = ROJO
                etiqueta = f"{ETIQUETAS[clave]}: {ND} \u00b7 sin fuente disponible"
            widget = self._badges.get(clave)
            if widget is None:
                continue
            widget.setText(etiqueta)
            widget.setStyleSheet(f"color: {color};")
            detalles = [f"Metodo: {texto_metodo}"]
            if evidence is not None:
                if evidence.fuente:
                    detalles.append(f"Fuente: {evidence.fuente}")
                if evidence.consultado:
                    detalles.append(f"Consultado: {evidence.consultado}")
                if evidence.url:
                    detalles.append(f"URL: {evidence.url}")
                if evidence.nota:
                    detalles.append(f"Nota: {evidence.nota}")
            widget.setToolTip(" | ".join(detalles))

    def _filas_resumen(self, tasas: Tasas) -> List[Dict[str, Any]]:
        """Filas de la tabla de tasas: usa ``resumen_tasas`` si esta disponible."""
        if _resumen_tasas is not None:
            try:
                filas = [dict(fila) for fila in _resumen_tasas(tasas)]
            except Exception as exc:  # pragma: no cover - defensivo
                LOG.warning("resumen_tasas fallo (%s): se construyen las filas localmente", exc)
                filas = []
            if filas:
                for posicion, fila in enumerate(filas):
                    fila["_clave"] = CLAVES[posicion] if posicion < len(CLAVES) else ""
                    fila.setdefault("Fuente", "")
                    fila.setdefault("URL", "")
                return filas
        return [
            {
                "_clave": clave,
                "Tasa": ETIQUETAS[clave],
                "Valor": a_float(getattr(tasas, clave, None)),
                "Metodo": tasas.metodo_de(clave),
                "Fuente": self._evidence(tasas, clave).fuente if self._evidence(tasas, clave) is not None else "",
                "URL": self._evidence(tasas, clave).url if self._evidence(tasas, clave) is not None else "",
            }
            for clave in CLAVES
        ]

    @staticmethod
    def _evidence(tasas: Optional[Tasas], clave: str) -> Optional[Evidence]:
        """Evidence asociada a una tasa."""
        if tasas is None:
            return None
        return {
            "tbill_4w": tasas.ev_tbill_4w,
            "ust_10y": tasas.ev_ust_10y,
            "ust_30y": tasas.ev_ust_30y,
        }.get(clave)

    def _pintar_diferencias(self, tasas: Tasas) -> None:
        """Tabla de diferencias en puntos base frente al respaldo."""
        filas: List[Dict[str, Any]] = []
        for clave in CLAVES:
            evidence = self._evidence(tasas, clave)
            metodo = tasas.metodo_de(clave)
            valor = a_float(getattr(tasas, clave, None))
            pb = a_float((tasas.diferencias_pb or {}).get(clave))
            principal: Optional[float] = None
            respaldo: Optional[float] = None
            if metodo in {"scraping", "investing"}:
                principal = valor
                if pb is not None:
                    respaldo = valor - (pb / 10_000.0) if valor is not None else None
            elif metodo == "respaldo":
                respaldo = valor
            nombre_respaldo = ""
            if evidence is not None and evidence.es_respaldo:
                nombre_respaldo = evidence.fuente or "Respaldo"
            elif clave == "tbill_4w":
                nombre_respaldo = "FRED (DGS1MO; o DTB4WK convertido: y = 365d/(360-d*28))"
            elif clave in {"ust_10y", "ust_30y"}:
                nombre_respaldo = "FRED / Yahoo Finance"
            nota = NOTA_DIFERENCIAS
            if pb is not None and abs(pb) > 25.0:
                nota = (
                    f"Diferencia de {pb:+.1f} pb (> 25 pb): revisa que no se este mezclando una tasa a descuento "
                    "con un rendimiento equivalente de bono sin convertir. " + NOTA_DIFERENCIAS
                )
            filas.append(
                {
                    "Tasa": ETIQUETAS[clave],
                    "Investing.com": principal,
                    "Respaldo": respaldo,
                    "Diferencia (pb)": pb,
                    "Fuente del respaldo": nombre_respaldo or ND,
                    "Nota": nota,
                }
            )
        tabla = self._tabla_dif
        tabla.setSortingEnabled(False)
        tabla.setColumnCount(7)
        tabla.setHorizontalHeaderLabels(["Tasa", "Investing.com", "Respaldo", "Diferencia (pb)", "Fuente del respaldo", "Nota", "_orden"])
        tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            pb = fila.get("Diferencia (pb)")
            destacar = pb is not None and abs(float(pb)) > 25.0
            color = ROJO if destacar else (GRIS if pb is None else VERDE)
            nota = str(fila.get("Nota") or NOTA_DIFERENCIAS)
            if pb is None:
                nota = "N/D: no hay respaldo comparable para esta tasa (o el valor principal no vino de Investing.com). " + nota
            celdas = [
                _celda(str(fila.get("Tasa")), fila.get("Tasa"), color, str(fila.get("Tasa")), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(_texto_tasa(fila.get("Investing.com")), fila.get("Investing.com"), color, "Valor de Investing.com.", Qt.AlignRight | Qt.AlignVCenter),
                _celda(_texto_tasa(fila.get("Respaldo")), fila.get("Respaldo"), color, "Valor de la fuente de respaldo (FRED / Yahoo Finance).", Qt.AlignRight | Qt.AlignVCenter),
                _celda(fmt_num(pb, 2) if pb is not None else ND, pb, color, nota, Qt.AlignRight | Qt.AlignVCenter),
                _celda(str(fila.get("Fuente del respaldo")), fila.get("Fuente del respaldo"), color, str(fila.get("Fuente del respaldo")), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(nota, nota, color, nota, Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(i + 1), i, GRIS, "Orden del pliego: TLR, 10 anios, 30 anios.", Qt.AlignRight | Qt.AlignVCenter),
            ]
            for j, celda in enumerate(celdas):
                tabla.setItem(i, j, celda)
        tabla.setSortingEnabled(True)
        tabla.sortItems(6, Qt.AscendingOrder)
        tabla.setColumnHidden(6, True)
        tabla.resizeColumnsToContents()
        self._nota_dif.setVisible(True)

    # --------------------------------------------------------------- grafico
    def _pintar_grafico(self, tasas: Tasas) -> None:
        """Prepara las series disponibles y dibuja el historico mensual."""
        self._series = {}
        for clave, (atributo, _color) in SERIES.items():
            serie = getattr(tasas, atributo, None)
            if isinstance(serie, pd.Series) and len(serie.dropna()) > 0:
                self._series[clave] = serie.dropna()
        avisos: List[str] = []
        if not self._series:
            avisos.append("N/D: no hay series mensuales disponibles (la TLR historica no se pudo obtener).")
        else:
            ausentes = [ETIQUETAS[clave] for clave in CLAVES if clave not in self._series]
            if ausentes:
                avisos.append("N/D: sin serie mensual para " + ", ".join(ausentes) + ".")
        self._aviso_grafico.mostrar(avisos)
        self._dibujar_grafico()
        self._grafico.refrescar(self.tema_actual)
        self._graficos_al_dia(self.tema_actual)

    def _dibujar_grafico(self) -> None:
        """Dibuja las series mensuales convirtiendo fracciones a porcentaje."""
        grafico = self._grafico
        grafico.limpiar()
        eje = grafico.ax
        if not self._series:
            eje.text(
                0.5,
                0.5,
                "N/D: sin series mensuales de tasas",
                ha="center",
                va="center",
                transform=eje.transAxes,
            )
            eje.set_xticks([])
            eje.set_yticks([])
            return
        for clave, serie in self._series.items():
            _atributo, color = SERIES[clave]
            eje.plot(
                serie.index,
                serie.to_numpy(dtype="float64") * 100.0,
                color=color,
                linewidth=1.5,
                label=ETIQUETAS[clave],
            )
        eje.set_title("Tasas de referencia de EE.UU. (mensual)")
        eje.set_xlabel("Fecha")
        eje.set_ylabel("Tasa anual (%)")
        eje.grid(True, alpha=0.25)
        eje.xaxis.set_major_locator(mdates.AutoDateLocator())
        eje.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        for etiqueta in eje.get_xticklabels():
            etiqueta.set_rotation(30)
            etiqueta.set_horizontalalignment("right")
        eje.legend(loc="best", fontsize=8)

    # --------------------------------------------------------------- avisos
    def _pintar_advertencias(self, tasas: Tasas) -> None:
        """Panel con las advertencias de las tasas (y el aviso DEMO si aplica)."""
        avisos = list(tasas.advertencias or [])
        for clave in CLAVES:
            if a_float(getattr(tasas, clave, None)) is None:
                avisos.append(f"{ETIQUETAS[clave]}: N/D (ni Investing.com, ni FRED/Yahoo, ni captura manual).")
        if self.resultado is not None and self.resultado.demo:
            avisos.insert(0, "MODO DEMO: las tasas mostradas son ficticias.")
        self._avisos.mostrar(avisos or ["Sin advertencias registradas al obtener las tasas."])

    # ---------------------------------------------------------- estado vacio
    def _pintar_vacio(self) -> None:
        """Estado vacio: no hay analisis cargado."""
        for clave, etiqueta in self._badges.items():
            etiqueta.setText(f"{ETIQUETAS[clave]}: {ND}")
        for tabla, columnas in (
            (self._tabla, ["Tasa", "Valor", "Metodo", "Fuente", "URL", "_orden"]),
            (
                self._tabla_dif,
                ["Tasa", "Investing.com", "Respaldo", "Diferencia (pb)", "Fuente del respaldo", "Nota", "_orden"],
            ),
        ):
            tabla.setSortingEnabled(False)
            tabla.setColumnCount(len(columnas))
            tabla.setHorizontalHeaderLabels(columnas)
            tabla.setRowCount(0)
            tabla.setColumnHidden(len(columnas) - 1, True)
            tabla.setSortingEnabled(True)
        self._series = {}
        self._aviso_grafico.mostrar(["N/D: no hay datos de tasas; analiza un ticker para verlas."])
        self._notas.mostrar([NOTA_CONVERSION, NOTA_IRX])
        self._nota_dif.mostrar([NOTA_DIFERENCIAS])
        self._avisos.mostrar(["N/D: no hay datos suficientes; todavia no se ha analizado ningun ticker."])
        self._dibujar_grafico()

    def _badges_visibles(self, visible: bool) -> None:
        """Muestra u oculta los distintivos de respaldo."""
        for etiqueta in self._badges.values():
            etiqueta.setVisible(visible)


__all__ = ["TabBonos"]
