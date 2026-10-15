# -*- coding: utf-8 -*-
"""Pestana "Fuentes y avisos": trazabilidad completa de los datos usados.

Requiere del pliego que **cada** dato muestre su fuente, su URL, la fecha de
consulta, el metodo de obtencion y, si falta, el motivo. Esta pestana pinta ese
registro (:class:`~dml.core.tipos.Fuentes`) y reune en un unico panel todas las
advertencias: las del propio registro, las de las tasas y las de cada resultado.

La ventana principal llama a :meth:`TabFuentes.cargar_fuentes` despues de cada
analisis; :meth:`TabFuentes.cargar` sigue funcionando para que la pestana se
pueda usar como cualquier otra (guarda el ultimo registro recibido).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTableWidgetItem, QWidget

from ...core.tipos import ND, Fuentes, ResultadoAnalisis
from ...core.util import a_float
from ..widgets import AMBAR, GRIS, ROJO, VERDE, EtiquetaAviso, TablaDML
from .base import TabBase

LOG = logging.getLogger("dml.ui.tabs.fuentes")

#: Columnas de la tabla de procedencia (orden del pliego).
COLUMNAS = ["Dato", "Valor", "Fuente", "Metodo", "URL", "Consultado", "Advertencia", "Categoria"]

#: Colores por metodo de obtencion (para localizar de un vistazo los respaldos).
COLORES_METODO: Dict[str, str] = {
    "scraping": VERDE,
    "API": VERDE,
    "respaldo": AMBAR,
    "manual": "#4da3ff",
    "calculo": GRIS,
    "supuesto": AMBAR,
    "demo": "#a06bd6",
    "N/D": ROJO,
}


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


class TabFuentes(TabBase):
    """Tabla de procedencia de los datos y panel unico de avisos."""

    titulo = "Fuentes y avisos"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        #: Ultimo registro de fuentes recibido (via ``cargar_fuentes`` o ``cargar``).
        self.fuentes: Optional[Fuentes] = None

        self.add_titulo(
            "Fuentes y avisos",
            "Procedencia de cada dato: fuente, URL, fecha de consulta y metodo "
            "(Investing.com, respaldo, manual, calculo). Los datos ausentes se muestran como N/D con el motivo.",
        )

        # ---- resumen por metodo -------------------------------------------
        self._badges: Dict[str, QLabel] = {}
        marco = QFrame()
        marco.setFrameShape(QFrame.StyledPanel)
        caja = QHBoxLayout(marco)
        caja.setContentsMargins(10, 8, 10, 8)
        caja.setSpacing(14)
        for clave, etiqueta, color, tip in (
            ("investing", "Investing.com (scraping)", VERDE, "Datos obtenidos por scraping/API en Investing.com."),
            ("respaldo", "Respaldo", AMBAR, "Datos obtenidos de una fuente de respaldo (FRED, Yahoo Finance...)."),
            ("manual", "Manual", "#4da3ff", "Datos introducidos manualmente por el usuario."),
            ("nd", "N/D", ROJO, "Datos sin valor utilizable: se muestran como N/D con el motivo."),
            ("total", "Total", GRIS, "Numero total de registros de procedencia."),
        ):
            etiqueta_widget = QLabel(f"{etiqueta}: 0")
            fuente = QFont()
            fuente.setBold(clave in {"nd", "respaldo"})
            etiqueta_widget.setFont(fuente)
            etiqueta_widget.setStyleSheet(f"color: {color};")
            etiqueta_widget.setToolTip(tip)
            caja.addWidget(etiqueta_widget)
            self._badges[clave] = etiqueta_widget
        caja.addStretch(1)
        self.add(marco)

        # ---- avisos --------------------------------------------------------
        self.add_titulo("Avisos y advertencias", "Registro de fuentes, tasas de referencia y analisis de cada ticker.")
        self._avisos = EtiquetaAviso()
        self.add(self._avisos)

        # ---- tabla de procedencia -----------------------------------------
        self._tabla = TablaDML(
            COLUMNAS,
            tooltips_columnas={
                "Dato": "Nombre legible del dato registrado.",
                "Valor": "Valor usado en el analisis (N/D si no se pudo obtener).",
                "Fuente": "Fuente efectiva del dato.",
                "Metodo": "scraping/API, respaldo, manual, calculo, demo o N/D.",
                "URL": "URL consultada (seleccionable; el tooltip muestra la URL completa).",
                "Consultado": "Fecha y hora ISO de la consulta.",
                "Advertencia": "Motivo por el que el dato falta o aviso asociado.",
                "Categoria": "Agrupacion del dato (tasas, opciones, decision...).",
            },
        )
        self._tabla.setMinimumHeight(320)
        self.add(self._tabla)

        # ---- estado vacio ---------------------------------------------------
        self._estado = EtiquetaAviso()
        self.add(self._estado)

        self._pintar_todo()

    # ------------------------------------------------------------------ API
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Guarda los resultados y repinta la pestana.

        El registro de fuentes no viaja en los resultados, por lo que se
        conserva el ultimo recibido con :meth:`cargar_fuentes`.
        """
        lista = [r for r in (resultados or []) if r is not None]
        self.resultados = lista
        self.resultado = actual if actual is not None else (lista[0] if lista else None)
        self._pintar_todo()

    def cargar_fuentes(self, fuentes: Optional[Fuentes]) -> None:
        """Recibe el registro de procedencia del analisis y repinta la pestana."""
        self.fuentes = fuentes
        self._pintar_todo()

    # --------------------------------------------------------------- pintado
    def _pintar_todo(self) -> None:
        """Repinta badges, tabla de procedencia y panel de avisos."""
        self._pintar_badges()
        self._pintar_tabla()
        self._pintar_avisos()

    def _filas(self) -> List[Dict[str, Any]]:
        """Registros de procedencia como lista de diccionarios."""
        if self.fuentes is None:
            return []
        marco = self.fuentes.como_dataframe()
        if marco is None or marco.empty:
            return []
        return [dict(fila) for fila in marco.to_dict(orient="records")]

    def _pintar_badges(self) -> None:
        """Resume cuantos datos vienen de cada metodo (y cuantos faltan)."""
        fuentes = self.fuentes
        if fuentes is None:
            for clave, widget in self._badges.items():
                widget.setText(f"{_titulo_badge(clave)}: N/D")
            return
        items = fuentes.items
        conteo = {
            "investing": len(fuentes.por_metodo("scraping")),
            "respaldo": len(fuentes.por_metodo("respaldo")),
            "manual": len(fuentes.por_metodo("manual")),
            "nd": len(fuentes.faltantes()),
            "total": len(items),
        }
        for clave, widget in self._badges.items():
            widget.setText(f"{_titulo_badge(clave)}: {conteo.get(clave, 0)}")
        self._badges["nd"].setToolTip(
            "Registros sin valor utilizable"
            + (": " + ", ".join(f.dato for f in fuentes.faltantes()[:12]) if fuentes.faltantes() else " (ninguno)")
        )

    def _pintar_tabla(self) -> None:
        """Pinta la tabla completa de procedencia con la URL seleccionable.

        Se anade una columna oculta ``_orden`` con el numero de registro: las
        tablas de Qt reordenan las filas mientras se rellenan, y asi se puede
        recuperar el orden de insercion del registro de fuentes.
        """
        filas = self._filas()
        tabla = self._tabla
        tabla.setSortingEnabled(False)
        tabla.setColumnCount(len(COLUMNAS) + 1)
        tabla.setHorizontalHeaderLabels(COLUMNAS + ["_orden"])
        tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            metodo = str(fila.get("Metodo") or ND)
            color = COLORES_METODO.get(metodo, GRIS)
            url = str(fila.get("URL") or "")
            advertencia = str(fila.get("Advertencia") or "")
            valor = fila.get("Valor")
            valor_numerico = a_float(valor)
            if valor_numerico is not None:
                texto_valor = f"{valor_numerico:,.4f}"
                dato_orden: Any = valor_numerico
            else:
                texto_valor = str(valor if valor not in (None, "") else ND)
                dato_orden = texto_valor
            celdas = [
                _celda(str(fila.get("Dato") or ND), fila.get("Dato"), color, str(fila.get("Dato") or ND), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(texto_valor, dato_orden, color, "Valor usado en el analisis." if valor_numerico is not None else "N/D: el dato no se pudo obtener.", Qt.AlignRight | Qt.AlignVCenter),
                _celda(str(fila.get("Fuente") or ND), fila.get("Fuente"), color, str(fila.get("Fuente") or ND), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(metodo, metodo, color, f"Metodo de obtencion: {metodo}.", Qt.AlignCenter),
                _celda(url or ND, url, color, url or "N/D: este dato no tiene URL asociada.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(fila.get("Consultado") or ND), fila.get("Consultado"), GRIS, "Fecha y hora ISO de la consulta.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(advertencia or "\u2014", advertencia, AMBAR if advertencia else GRIS, advertencia or "Sin advertencia para este dato.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(fila.get("Categoria") or ND), fila.get("Categoria"), GRIS, "Agrupacion del dato.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(i + 1), i, GRIS, "Orden de registro del dato.", Qt.AlignRight | Qt.AlignVCenter),
            ]
            for j, celda in enumerate(celdas):
                tabla.setItem(i, j, celda)
        tabla.setSortingEnabled(True)
        tabla.sortItems(len(COLUMNAS), Qt.AscendingOrder)
        tabla.setColumnHidden(len(COLUMNAS), True)
        tabla.resizeColumnsToContents()
        # La columna URL debe poder seleccionarse (el tooltip muestra la completa).
        for i in range(tabla.rowCount()):
            item = tabla.item(i, COLUMNAS.index("URL"))
            if item is not None:
                item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)

        if self.fuentes is None:
            self._estado.mostrar(
                [
                    "Todavia no se ha recibido el registro de fuentes: analiza un ticker para ver la procedencia de sus datos.",
                    "Cada dato mostrara aqui su fuente, URL, fecha de consulta, metodo y, si falta, el motivo.",
                ]
            )
        elif not filas:
            self._estado.mostrar(["N/D: el registro de fuentes esta vacio (no se registro ningun dato)."])
        else:
            self._estado.mostrar([])

    def _pintar_avisos(self) -> None:
        """Reune los avisos del registro, de las tasas y de cada resultado."""
        avisos: List[str] = []
        if self.fuentes is not None:
            avisos.extend(self.fuentes.advertencias())
        for resultado in self.resultados or ([self.resultado] if self.resultado is not None else []):
            if resultado is None:
                continue
            etiqueta = resultado.ticker or ND
            avisos.extend(f"[{etiqueta}] {texto}" for texto in (resultado.advertencias or []))
            avisos.extend(f"[{etiqueta}] tasas: {texto}" for texto in getattr(resultado.tasas, "advertencias", []) or [])
        vistas: List[str] = []
        for aviso in avisos:
            if aviso and aviso not in vistas:
                vistas.append(aviso)
        if not vistas:
            vistas = ["Sin avisos: no se registro ninguna advertencia." if self.fuentes is not None else "Todavia no hay avisos: no se ha analizado ningun ticker."]
        self._avisos.mostrar(vistas)


def _titulo_badge(clave: str) -> str:
    """Etiqueta legible de cada contador del resumen."""
    return {
        "investing": "Investing.com (scraping)",
        "respaldo": "Respaldo",
        "manual": "Manual",
        "nd": "N/D",
        "total": "Total",
    }.get(clave, clave)


__all__ = ["TabFuentes"]
