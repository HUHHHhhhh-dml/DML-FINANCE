# -*- coding: utf-8 -*-
"""Panel lateral "Historial de analisis".

Guarda los tickers analizados **en memoria** (y en la cache local de la
aplicacion) para poder recargar todas las pestanas con un clic, sin volver a
descargar datos.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.tipos import ResultadoAnalisis
from ...core.util import fmt_pct

LOG = logging.getLogger("dml.ui.historial")


class PanelHistorial(QWidget):
    """Lista de analisis realizados; al pulsar uno se recarga toda la interfaz.

    Signals:
        seleccionado: indice del analisis elegido.
    """

    seleccionado = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._resultados: List[ResultadoAnalisis] = []
        caja = QVBoxLayout(self)
        caja.setContentsMargins(6, 6, 6, 6)
        caja.setSpacing(6)

        titulo = QLabel("Historial de analisis")
        titulo.setObjectName("titulo")
        caja.addWidget(titulo)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista.setToolTip("Pulsa un analisis para recargar todas las pestanas con sus resultados")
        self.lista.currentRowChanged.connect(self._cambio_fila)
        caja.addWidget(self.lista, 1)

        botones = QHBoxLayout()
        self.boton_limpiar = QPushButton("Limpiar historial")
        self.boton_limpiar.clicked.connect(self.limpiar)
        botones.addWidget(self.boton_limpiar)
        caja.addLayout(botones)

        self.resumen = QLabel("Sin analisis todavia")
        self.resumen.setObjectName("subtitulo")
        self.resumen.setWordWrap(True)
        caja.addWidget(self.resumen)

    # ------------------------------------------------------------------ datos
    def agregar(self, resultado: ResultadoAnalisis) -> int:
        """Anade un analisis (reemplaza el anterior del mismo ticker)."""
        for posicion, existente in enumerate(self._resultados):
            if existente.ticker == resultado.ticker:
                self._resultados[posicion] = resultado
                self._refrescar_item(posicion)
                self.lista.setCurrentRow(posicion)
                return posicion
        self._resultados.append(resultado)
        item = QListWidgetItem(self._texto(resultado))
        item.setToolTip(self._tooltip(resultado))
        self.lista.addItem(item)
        self.lista.setCurrentRow(len(self._resultados) - 1)
        return len(self._resultados) - 1

    def actualizar(self, resultados: List[ResultadoAnalisis]) -> None:
        """Reemplaza la lista completa (por ejemplo tras un recalculo multiple)."""
        self._resultados = list(resultados)
        self.lista.clear()
        for resultado in self._resultados:
            item = QListWidgetItem(self._texto(resultado))
            item.setToolTip(self._tooltip(resultado))
            self.lista.addItem(item)
        if self._resultados:
            self.lista.setCurrentRow(0)

    def limpiar(self) -> None:
        """Vacia el historial en memoria."""
        self._resultados.clear()
        self.lista.clear()
        self.resumen.setText("Sin analisis todavia")

    def resultados(self) -> List[ResultadoAnalisis]:
        """Copia de la lista de resultados guardados."""
        return list(self._resultados)

    def actual(self) -> Optional[ResultadoAnalisis]:
        """Resultado seleccionado, si lo hay."""
        fila = self.lista.currentRow()
        if 0 <= fila < len(self._resultados):
            return self._resultados[fila]
        return None

    # ------------------------------------------------------------------ privado
    def _texto(self, resultado: ResultadoAnalisis) -> str:
        """Texto del elemento de lista."""
        calificacion = fmt_pct(resultado.calificacion, 0) if resultado.calificacion is not None else "N/D"
        marca = " [DEMO]" if resultado.demo else ""
        return f"{resultado.ticker} - {resultado.decision} ({calificacion}){marca}"

    def _tooltip(self, resultado: ResultadoAnalisis) -> str:
        """Tooltip con el resumen del analisis."""
        return (
            f"{resultado.ticker} - {resultado.nombre}\n"
            f"Decision: {resultado.decision}\n"
            f"Fecha: {resultado.fecha_analisis}\n"
            f"Modo: {resultado.modo}\n"
            f"Spot: {resultado.spot if resultado.spot is None else round(resultado.spot, 2)}"
        )

    def _refrescar_item(self, posicion: int) -> None:
        """Actualiza el texto y el tooltip de una fila existente."""
        item = self.lista.item(posicion)
        if item is None:
            return
        resultado = self._resultados[posicion]
        item.setText(self._texto(resultado))
        item.setToolTip(self._tooltip(resultado))

    def _cambio_fila(self, fila: int) -> None:
        """Emite la seleccion y actualiza el resumen inferior."""
        if self._actualizar_resumen(fila):
            self.seleccionado.emit(fila)

    def sincronizar_resumen(self) -> None:
        """Refresca el resumen inferior con la fila seleccionada.

        Hace falta despues de modificar la lista con las senales bloqueadas (por
        ejemplo al anadir varios analisis de golpe), porque entonces
        ``currentRowChanged`` no se emite y el resumen se quedaria con el texto
        del analisis anterior.
        """
        self._actualizar_resumen(self.lista.currentRow())

    def _actualizar_resumen(self, fila: int) -> bool:
        """Escribe el resumen de la fila indicada. Devuelve si la fila es valida."""
        if not (0 <= fila < len(self._resultados)):
            return False
        resultado = self._resultados[fila]
        criterios = resultado.criterios or []
        cumplidos = sum(1 for c in criterios if c.activo and c.cumple)
        activos = sum(1 for c in criterios if c.activo)
        self.resumen.setText(
            f"{resultado.ticker}: {cumplidos}/{activos} criterios activos\n"
            f"Calificacion: {fmt_pct(resultado.calificacion, 1)} - {resultado.decision}"
        )
        return True

    @contextmanager
    def sin_avisar(self) -> Iterator["PanelHistorial"]:
        """Contexto que bloquea la senal ``seleccionado`` al modificar la lista.

        Se usa para rellenar el historial de golpe: sin esto, cada
        ``setCurrentRow`` avisaria a la ventana y esta repintaria las 11 pestanas
        una vez por ticker anadido.
        """
        anterior = self.lista.blockSignals(True)
        try:
            yield self
        finally:
            self.lista.blockSignals(anterior)
            self.sincronizar_resumen()
