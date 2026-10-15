# -*- coding: utf-8 -*-
"""Widgets reutilizables de la interfaz: tablas, tarjetas, graficos y avisos.

Todos los widgets de este modulo son genericos: no conocen ninguna formula
financiera, solo pintan los datos que reciben de :mod:`dml.analisis`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.tipos import ND
from ..core.util import fmt_num, fmt_pct

# --------------------------------------------------------------------------
# Colores (independientes del tema para que las tablas se lean siempre)
# --------------------------------------------------------------------------

VERDE = "#31c48d"
ROJO = "#f26d6d"
AMBAR = "#f2b544"
GRIS = "#8a939f"


def _item(valor: Any, color: Optional[str] = None, tooltip: str = "", negrita: bool = False) -> QTableWidgetItem:
    """Crea un item de tabla con texto formateado, color y tooltip."""
    if isinstance(valor, float):
        texto = fmt_num(valor, 4)
    elif valor is None:
        texto = ND
    else:
        texto = str(valor)
    celda = QTableWidgetItem(texto)
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        celda.setForeground(QBrush(QColor(color)))
    if tooltip:
        celda.setToolTip(tooltip)
    if negrita:
        fuente = QFont()
        fuente.setBold(True)
        celda.setFont(fuente)
    # Se guarda el valor original para ordenar numericamente, no por texto.
    celda.setData(Qt.UserRole, valor)
    return celda


class TablaDML(QTableWidget):
    """Tabla con ordenacion, copiado (Ctrl+C), redimensionado y colores.

    Args:
        columnas: nombres de las columnas.
        formateadores: mapa ``{columna: callable(valor) -> str}`` opcional para
            pintar porcentajes o importes.
        colores_condicionales: callable ``(fila, columna, valor) -> color|None``.
    """

    def __init__(
        self,
        columnas: Optional[Sequence[str]] = None,
        parent: Optional[QWidget] = None,
        formateadores: Optional[Dict[str, Callable[[Any], str]]] = None,
        colores_condicionales: Optional[Callable[[int, int, Any], Optional[str]]] = None,
        tooltips_columnas: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(0, len(columnas) if columnas else 0, parent)
        self.formateadores: Dict[str, Callable[[Any], str]] = dict(formateadores or {})
        self.colores_condicionales = colores_condicionales
        self.tooltips_columnas = dict(tooltips_columnas or {})
        if columnas:
            self.setColumnCount(len(columnas))
            self.setHorizontalHeaderLabels([str(c) for c in columnas])
            for posicion, nombre in enumerate(columnas):
                if nombre in self.tooltips_columnas:
                    item = self.horizontalHeaderItem(posicion)
                    if item is not None:
                        item.setToolTip(self.tooltips_columnas[nombre])
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.setWordWrap(False)
        copiar = QAction("Copiar", self)
        copiar.setShortcut("Ctrl+C")
        copiar.triggered.connect(self.copiar_seleccion)
        self.addAction(copiar)

    # ------------------------------------------------------------------ datos
    def cargar_filas(self, filas: Sequence[Dict[str, Any]], columnas: Optional[Sequence[str]] = None) -> None:
        """Rellena la tabla a partir de una lista de diccionarios."""
        if columnas:
            self.setColumnCount(len(columnas))
            self.setHorizontalHeaderLabels([str(c) for c in columnas])
        elif filas:
            self.setColumnCount(len(filas[0]))
            self.setHorizontalHeaderLabels([str(c) for c in filas[0].keys()])
        nombres = [self.horizontalHeaderItem(i).text() for i in range(self.columnCount())]
        self.setSortingEnabled(False)
        self.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            for j, nombre in enumerate(nombres):
                valor = fila.get(nombre)
                self._poner(i, j, valor, nombre)
        self.setSortingEnabled(True)
        self.resizeColumnsToContents()

    def cargar_dataframe(self, df: Optional[pd.DataFrame]) -> None:
        """Rellena la tabla a partir de un ``DataFrame`` (indice incluido como columna)."""
        if df is None or df.empty:
            self.setRowCount(0)
            return
        datos = df.reset_index()
        primera = datos.columns[0]
        if primera in {"index", "Fecha"} and primera not in df.columns:
            datos = datos.rename(columns={primera: "Fecha"})
        self.cargar_filas(datos.to_dict(orient="records"), [str(c) for c in datos.columns])

    def _poner(self, fila: int, columna: int, valor: Any, nombre_columna: str) -> None:
        """Coloca un valor aplicando formato y color condicional."""
        formateador = self.formateadores.get(nombre_columna)
        color = self.colores_condicionales(fila, columna, valor) if self.colores_condicionales else None
        if formateador is not None and valor is not None:
            texto = formateador(valor)
            celda = QTableWidgetItem(texto)
            celda.setData(Qt.UserRole, valor)
            celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if color:
                celda.setForeground(QBrush(QColor(color)))
        else:
            celda = _item(valor, color=color or (AMBAR if valor is None else None))
            if valor is None:
                celda.setToolTip("N/D: dato no disponible")
        self.setItem(fila, columna, celda)

    def marcar_fila(self, fila: int, color: Optional[str]) -> None:
        """Colorea el fondo de una fila completa (para el resaltado de decision)."""
        for columna in range(self.columnCount()):
            celda = self.item(fila, columna)
            if celda is None:
                celda = QTableWidgetItem("")
                self.setItem(fila, columna, celda)
            if color:
                celda.setBackground(QBrush(QColor(color)))

    # --------------------------------------------------------------- portapapeles
    def copiar_seleccion(self) -> None:
        """Copia la seleccion al portapapeles en formato TSV (pegable en Excel)."""
        indices = self.selectedIndexes()
        if not indices:
            return
        filas = sorted({i.row() for i in indices})
        columnas = sorted({i.column() for i in indices})
        lineas: List[str] = []
        for fila in filas:
            celdas: List[str] = []
            for columna in columnas:
                item = self.item(fila, columna)
                celdas.append(item.text() if item is not None else "")
            lineas.append("\t".join(celdas))
        QGuiApplication.clipboard().setText("\n".join(lineas))


def tabla_rapida(
    encabezados: Sequence[str], filas: Sequence[Sequence[Any]], tooltips_columnas: Optional[Dict[str, str]] = None
) -> TablaDML:
    """Crea una tabla ya rellena a partir de encabezados y filas."""
    tabla = TablaDML(list(encabezados), tooltips_columnas=tooltips_columnas)
    tabla.setSortingEnabled(False)
    tabla.setRowCount(len(filas))
    for i, fila in enumerate(filas):
        for j, valor in enumerate(fila):
            tabla._poner(i, j, valor, encabezados[j])
    tabla.setSortingEnabled(True)
    tabla.resizeColumnsToContents()
    return tabla


# --------------------------------------------------------------------------
# Tarjetas y paneles
# --------------------------------------------------------------------------


class Tarjeta(QFrame):
    """Tarjeta con un titulo y un valor grande (usada en la pestana Principal)."""

    def __init__(self, titulo: str, valor: str = ND, tooltip: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("tarjeta")  # esquinas redondeadas definidas en estilos.py
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 8, 10, 8)
        caja.setSpacing(2)
        self._titulo = QLabel(titulo)
        self._titulo.setObjectName("subtitulo")
        self._valor = QLabel(valor)
        self._valor.setObjectName("valor")
        caja.addWidget(self._titulo)
        caja.addWidget(self._valor)
        if tooltip:
            self.setToolTip(tooltip)

    def set_valor(self, valor: Any, color: Optional[str] = None, tooltip: str = "") -> None:
        """Actualiza el valor mostrado (con ``N/D`` si es ``None``).

        El tamano y el peso de la fuente los fija el QSS (``QLabel#valor``) y el
        color se aplica con la paleta del widget: asignar un ``styleSheet`` nuevo
        en cada actualizacion obligaba a Qt a volver a resolver el estilo de la
        tarjeta entera cada vez que se repintaba el analisis.
        """
        if valor is None:
            texto = ND
        elif isinstance(valor, float):
            texto = fmt_num(valor, 4)
        else:
            texto = str(valor)
        self._valor.setText(texto)
        if color:
            paleta = QPalette(self._valor.palette())
            paleta.setColor(QPalette.WindowText, QColor(color))
            self._valor.setPalette(paleta)
        if tooltip:
            self.setToolTip(tooltip)
            self._valor.setToolTip(tooltip)


class PanelTarjetas(QWidget):
    """Parrilla de tarjetas rellenada a partir de un diccionario ``{titulo: valor}``."""

    def __init__(self, columnas: int = 4, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._columnas = max(1, columnas)
        self._caja = QGridLayout(self)
        self._caja.setContentsMargins(6, 6, 6, 6)
        self._caja.setSpacing(6)
        self._tarjetas: Dict[str, Tarjeta] = {}

    def cargar(self, valores: Dict[str, Any], tooltips: Optional[Dict[str, str]] = None, colores: Optional[Dict[str, str]] = None) -> None:
        """Crea o actualiza las tarjetas con los valores indicados."""
        while self._caja.count():
            elemento = self._caja.takeAt(0)
            widget = elemento.widget()
            if widget is not None:
                widget.deleteLater()
        self._tarjetas.clear()
        tooltips = tooltips or {}
        colores = colores or {}
        for posicion, (titulo, valor) in enumerate(valores.items()):
            tarjeta = Tarjeta(titulo, tooltip=tooltips.get(titulo, ""))
            tarjeta.set_valor(valor, colores.get(titulo), tooltips.get(titulo, ""))
            self._caja.addWidget(tarjeta, posicion // self._columnas, posicion % self._columnas)
            self._tarjetas[titulo] = tarjeta


class EtiquetaAviso(QLabel):
    """Etiqueta de aviso/advertencia con icono textual y ajuste de linea."""

    def __init__(self, texto: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(texto, parent)
        self.setWordWrap(True)
        self.setObjectName("aviso")
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def mostrar(self, mensajes: Sequence[str]) -> None:
        """Muestra una lista de avisos (o los oculta si esta vacia)."""
        if not mensajes:
            self.setText("")
            self.setVisible(False)
            return
        self.setText("\n".join(f"⚠ {m}" for m in mensajes))
        self.setVisible(True)


class PanelIndicadorDecision(QFrame):
    """Indicador grande con la calificacion y la decision final."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(12, 10, 12, 10)
        self._decision = QLabel("N/D")
        fuente = QFont()
        fuente.setPointSize(26)
        fuente.setBold(True)
        self._decision.setFont(fuente)
        self._decision.setAlignment(Qt.AlignCenter)
        self._calificacion = QLabel("Calificacion: N/D")
        self._calificacion.setAlignment(Qt.AlignCenter)
        self._detalle = QLabel("")
        self._detalle.setAlignment(Qt.AlignCenter)
        self._detalle.setObjectName("subtitulo")
        caja.addWidget(self._decision)
        caja.addWidget(self._calificacion)
        caja.addWidget(self._detalle)

    def cargar(self, decision: str, calificacion: Optional[float], criterios: int = 0, cumplidos: int = 0) -> None:
        """Pinta la decision con el color de la regla del pliego."""
        colores = {"COMPRAR": VERDE, "MANTENER": AMBAR, "NO INVERTIR": ROJO}
        color = colores.get(str(decision).upper(), GRIS)
        self._decision.setText(str(decision).upper())
        self._decision.setStyleSheet(f"color: {color};")
        texto = fmt_pct(calificacion, 1) if calificacion is not None else ND
        self._calificacion.setText(f"Calificacion: {texto}")
        self._detalle.setText(f"{cumplidos} de {criterios} criterios activos cumplidos")


# --------------------------------------------------------------------------
# Graficos matplotlib embebidos
# --------------------------------------------------------------------------


def _importar_canvas():
    """Importa ``FigureCanvasQTAgg`` (aislado para poder probar sin Qt)."""
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure

    return FigureCanvas, Figure


class GraficoDML(QWidget):
    """Lienzo matplotlib embebido con soporte de tema oscuro/claro.

    Expone ``ax`` (ejes principales) para que cada pestana dibuje lo que
    necesite, y ``limpiar()`` para empezar de cero.
    """

    def __init__(self, titulo: str = "", alto: int = 3, ancho: int = 6, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        FigureCanvas, Figure = _importar_canvas()
        self.figura = Figure(figsize=(ancho, alto), tight_layout=True)
        self.canvas = FigureCanvas(self.figura)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figura.add_subplot(111)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(self.canvas)
        self._titulo = titulo
        #: Ultimo tema aplicado; se usa para no repintar dos veces el mismo tema.
        self._tema_aplicado: Optional[str] = None
        self.aplicar_tema("oscuro")

    def limpiar(self) -> None:
        """Limpia el lienzo dejando un unico eje principal.

        Al vaciar la figura se pierden los colores del tema, asi que se invalida
        la marca de "tema ya aplicado" para que el siguiente
        :meth:`refrescar` vuelva a pintarlo.
        """
        self.figura.clear()
        self.ax = self.figura.add_subplot(111)
        self._tema_aplicado = None

    def tema_es(self, tema: str) -> bool:
        """True si el lienzo ya esta pintado con ese tema."""
        return self._tema_aplicado == tema

    def aplicar_tema(self, tema: str) -> None:
        """Ajusta el color de fondo y de las etiquetas al tema activo.

        El repintado se **programa** (``draw_idle``) en lugar de ejecutarse en el
        acto: al cambiar de tema se recorren varios graficos seguidos y conviene
        dejar que Qt los agrupe en un unico repintado del lienzo. Si al llegar el
        repintado el widget esta oculto, Qt lo pospone hasta que se muestre.
        """
        from .estilos import colores

        paleta = colores(tema)
        self._tema_aplicado = tema
        self.figura.set_facecolor(paleta["fondo_alt"])
        for eje in self.figura.get_axes():
            eje.set_facecolor(paleta["fondo_alt"])
            eje.tick_params(colors=paleta["texto_suave"], labelsize=8)
            eje.xaxis.label.set_color(paleta["texto"])
            eje.yaxis.label.set_color(paleta["texto"])
            eje.title.set_color(paleta["texto"])
            for lado in eje.spines.values():
                lado.set_color(paleta["borde"])
            leyenda = eje.get_legend()
            if leyenda is not None:
                leyenda.get_frame().set_facecolor(paleta["panel"])
                for texto in leyenda.get_texts():
                    texto.set_color(paleta["texto"])
        self.canvas.draw_idle()

    def refrescar(self, tema: str = "oscuro", forzar: bool = False) -> None:
        """Redibuja el grafico aplicando el tema (salvo si ya estaba aplicado)."""
        if not forzar and self.tema_es(tema):
            return
        self.aplicar_tema(tema)


# --------------------------------------------------------------------------
# Controles de parametros
# --------------------------------------------------------------------------


def giro_decimal(
    minimo: float = -1e6,
    maximo: float = 1e6,
    paso: float = 0.001,
    decimales: int = 4,
    valor: Optional[float] = None,
    sufijo: str = "",
    tooltip: str = "",
) -> QDoubleSpinBox:
    """Crea un ``QDoubleSpinBox`` configurado para valores financieros.

    Admite el estado "vacio" (``None``) mediante un valor centinela: si el
    usuario no toca el control, el valor del modelo se conserva.
    """
    caja = QDoubleSpinBox()
    caja.setRange(minimo, maximo)
    caja.setSingleStep(paso)
    caja.setDecimals(decimales)
    caja.setKeyboardTracking(False)
    if sufijo:
        caja.setSuffix(sufijo)
    if tooltip:
        caja.setToolTip(tooltip)
    if valor is not None:
        caja.setValue(float(valor))
    return caja


def casilla(texto: str, marcada: bool = True, tooltip: str = "") -> QCheckBox:
    """Crea una casilla con tooltip."""
    caja = QCheckBox(texto)
    caja.setChecked(bool(marcada))
    if tooltip:
        caja.setToolTip(tooltip)
    return caja


def fila_horizontal(*widgets: QWidget, separacion: int = 8) -> QWidget:
    """Agrupa widgets en una fila horizontal."""
    contenedor = QWidget()
    caja = QHBoxLayout(contenedor)
    caja.setContentsMargins(0, 0, 0, 0)
    caja.setSpacing(separacion)
    for widget in widgets:
        caja.addWidget(widget)
    return contenedor


def paleta_qt(tema: str = "oscuro") -> QPalette:
    """Construye la ``QPalette`` del tema.

    La paleta aporta los colores base (fondo, texto, seleccion) **sin** obligar a
    Qt a recalcular el estilo de cada widget, que es lo caro de
    ``QApplication.setStyleSheet``. El QSS se encarga de lo que la paleta no cubre
    (bordes, radios, estados ``hover``).
    """
    from .estilos import colores

    c = colores(tema)
    paleta = QPalette()
    paleta.setColor(QPalette.Window, QColor(c["fondo"]))
    paleta.setColor(QPalette.WindowText, QColor(c["texto"]))
    paleta.setColor(QPalette.Base, QColor(c["base"]))
    paleta.setColor(QPalette.AlternateBase, QColor(c["fondo_alt"]))
    paleta.setColor(QPalette.Text, QColor(c["texto"]))
    paleta.setColor(QPalette.PlaceholderText, QColor(c["texto_suave"]))
    paleta.setColor(QPalette.Button, QColor(c["panel"]))
    paleta.setColor(QPalette.ButtonText, QColor(c["texto"]))
    paleta.setColor(QPalette.ToolTipBase, QColor(c["panel"]))
    paleta.setColor(QPalette.ToolTipText, QColor(c["texto"]))
    paleta.setColor(QPalette.Highlight, QColor(c["acento"]))
    paleta.setColor(QPalette.HighlightedText, QColor(c["sobre_acento"]))
    paleta.setColor(QPalette.Link, QColor(c["acento"]))
    for grupo in (QPalette.Disabled,):
        paleta.setColor(grupo, QPalette.WindowText, QColor(c["texto_suave"]))
        paleta.setColor(grupo, QPalette.Text, QColor(c["texto_suave"]))
        paleta.setColor(grupo, QPalette.ButtonText, QColor(c["texto_suave"]))
    return paleta


def aplicar_tema_global(app: Optional[QApplication], tema: str) -> None:
    """Aplica el tema a toda la aplicacion (paleta + hoja de estilo).

    Se aplican las dos cosas por este orden:

    1. La **paleta**: cubre el fondo y el color de texto de cualquier widget,
       incluidas las vistas internas que el QSS no puede alcanzar (el ``viewport``
       de una tabla, el menu contextual de un encabezado, las vistas de un
       ``QComboBox``). Es instantanea.
    2. La **hoja de estilo**: define bordes, radios y estados. Evita a proposito
       una regla universal ``QWidget``, que forzaria a Qt a recalcular el estilo
       de los miles de widgets de la ventana en cada cambio de tema.
    """
    from .estilos import qss

    objetivo = app or QApplication.instance()
    if objetivo is None:
        return
    objetivo.setPalette(paleta_qt(tema))
    objetivo.setStyleSheet(qss(tema))


# --------------------------------------------------------------------------
# Icono de la aplicacion
# --------------------------------------------------------------------------

#: Nombres buscados, en orden, para el icono de la ventana y de la barra de tareas.
ARCHIVOS_ICONO = ("icono.ico", "icono.png", "DML-Icon.png")


def ruta_icono() -> Optional[str]:
    """Devuelve la ruta del icono de la aplicacion, o ``None`` si no se encuentra.

    Busca en ``recursos/`` (junto al ejecutable) y en el directorio temporal de
    PyInstaller (``sys._MEIPASS``), de modo que el mismo codigo funciona en
    Python y en el ``.exe``.
    """
    import sys

    candidatas = []
    if getattr(sys, "frozen", False):  # empaquetado con PyInstaller
        candidatas.append(Path(getattr(sys, "_MEIPASS", "")) / "recursos")
        candidatas.append(Path(sys.executable).resolve().parent / "recursos")
    from ..core.config import directorio_aplicacion

    candidatas.append(directorio_aplicacion() / "recursos")
    for carpeta in candidatas:
        for nombre in ARCHIVOS_ICONO:
            ruta = carpeta / nombre
            if ruta.is_file():
                return str(ruta)
    return None


def icono_app() -> Optional[QIcon]:
    """Carga el icono de la aplicacion (``None`` si no hay ninguno disponible)."""
    ruta = ruta_icono()
    if not ruta:
        return None
    icono = QIcon(ruta)
    return None if icono.isNull() else icono


def aplicar_icono(objetivo: Optional[QWidget]) -> None:
    """Coloca el icono de DML-FINANCE en una ventana o en la aplicacion."""
    icono = icono_app()
    if icono is None:
        return
    if objetivo is None:
        aplicacion = QApplication.instance()
        if aplicacion is not None:
            aplicacion.setWindowIcon(icono)
        return
    objetivo.setWindowIcon(icono)
