# -*- coding: utf-8 -*-
"""Temas claro y oscuro de la aplicacion (hojas de estilo QSS).

El diseno busca un acabado moderno con esquinas redondeadas: tarjetas, botones,
campos, paneles, pestanas, barras de progreso y barras de desplazamiento usan
radios generosos y estados ``hover``/``pressed``/``focus`` visibles.

Notas de mantenimiento
----------------------
* El QSS se aplica a toda la ``QApplication``, asi que **cada regla se evalua en
  cada cambio de tema**: conviene mantenerlo simple y sin selectores innecesarios.
* La plantilla usa ``str.format``: cualquier llave literal debe escribirse doble
  (``{{`` y ``}}``).
* Las claves de :data:`PALETAS` son el contrato con el resto de la interfaz
  (las usan los graficos matplotlib a traves de :func:`colores`).
"""

from __future__ import annotations

from typing import Dict

#: Separador entre bloques del QSS (solo legibilidad).
_SEP = "\n"

#: Colores base de cada tema.
PALETAS: Dict[str, Dict[str, str]] = {
    "oscuro": {
        "fondo": "#1b1f26",
        "fondo_alt": "#232833",
        "panel": "#2a303c",
        "panel_hover": "#333a48",
        "panel_press": "#1f242d",
        "borde": "#3a424e",
        "borde_suave": "#2f3641",
        "texto": "#e8eaed",
        "texto_suave": "#a3acb9",
        "acento": "#4da3ff",
        "acento_hover": "#6fb6ff",
        "acento_press": "#3a8fe0",
        "acento_suave": "#1e3550",
        "verde": "#31c48d",
        "rojo": "#f26d6d",
        "ambar": "#f2b544",
        "entrada": "#171b22",
        "base": "#171b22",
        "seleccion": "#4da3ff",
        "sobre_acento": "#0d1117",
    },
    "claro": {
        "fondo": "#eef1f6",
        "fondo_alt": "#ffffff",
        "panel": "#ffffff",
        "panel_hover": "#f2f5fa",
        "panel_press": "#e4e9f1",
        "borde": "#ccd4e0",
        "borde_suave": "#e2e7ef",
        "texto": "#1b1f24",
        "texto_suave": "#5b6672",
        "acento": "#1668c9",
        "acento_hover": "#1d7de8",
        "acento_press": "#12539f",
        "acento_suave": "#e3eefb",
        "verde": "#1f9d63",
        "rojo": "#c0392b",
        "ambar": "#b8791a",
        "entrada": "#ffffff",
        "base": "#ffffff",
        "seleccion": "#1668c9",
        "sobre_acento": "#ffffff",
    },
}

_QSS = """
/* ---------------------------------------------------------------- base */
/* NO anadir aqui una regla universal para "QWidget": obliga a Qt a recalcular
   el estilo de TODOS los widgets (miles) cada vez que se cambia de tema, y es
   la diferencia entre un cambio instantaneo y otro de un par de segundos. El
   fondo y el color de texto los pone la paleta de la aplicacion (ver
   `aplicar_tema_global`) y el resto se estiliza por tipo de widget. */
QMainWindow, QDialog, QScrollArea, QStackedWidget {{ background-color: {fondo}; }}
QMainWindow > QWidget, QDialog > QWidget {{ background-color: transparent; }}
QToolTip {{
    background-color: {panel};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 6px;
    padding: 5px 7px;
}}

/* --------------------------------------------------------- barra superior */
QToolBar {{
    background-color: {panel};
    border: none;
    border-bottom: 1px solid {borde_suave};
    border-radius: 10px;
    spacing: 6px;
    padding: 6px;
    margin: 4px 6px 0 6px;
}}
QToolBar::separator {{
    background-color: {borde};
    width: 1px;
    margin: 4px 8px;
    border-radius: 1px;
}}

/* ---------------------------------------------------------------- pestanas */
QTabWidget {{ background-color: {fondo}; }}
QTabWidget::pane {{
    border: 1px solid {borde_suave};
    border-radius: 10px;
    background-color: {fondo_alt};
    top: -1px;
    padding: 2px;
}}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background-color: transparent;
    color: {texto_suave};
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 7px 14px;
    margin-right: 3px;
}}
QTabBar::tab:hover {{
    background-color: {panel_hover};
    color: {texto};
}}
QTabBar::tab:selected {{
    background-color: {fondo_alt};
    color: {acento};
    font-weight: bold;
    border-color: {borde_suave};
}}

/* ------------------------------------------------- campos de introduccion */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background-color: {entrada};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 5px 8px;
    min-height: 18px;
    selection-background-color: {seleccion};
    selection-color: {sobre_acento};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover {{ border-color: {acento}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 1px solid {acento};
    background-color: {panel_hover};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {texto_suave};
    background-color: {fondo};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox QAbstractItemView {{
    background-color: {panel};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {acento_suave};
    selection-color: {texto};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 16px;
}}

/* --------------------------------------------------------------- botones */
QPushButton {{
    background-color: {panel};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 18px;
}}
QPushButton:hover {{
    background-color: {panel_hover};
    border-color: {acento};
    color: {acento};
}}
QPushButton:pressed {{ background-color: {panel_press}; }}
QPushButton:disabled {{
    color: {texto_suave};
    background-color: {fondo};
    border-color: {borde_suave};
}}
QPushButton:focus {{ border-color: {acento}; }}
QPushButton#principal {{
    background-color: {acento};
    color: {sobre_acento};
    font-weight: bold;
    border: none;
    padding: 7px 18px;
}}
QPushButton#principal:hover {{ background-color: {acento_hover}; color: {sobre_acento}; }}
QPushButton#principal:pressed {{ background-color: {acento_press}; }}
QPushButton#principal:disabled {{ background-color: {borde}; color: {texto_suave}; }}
QMessageBox QPushButton {{ min-width: 84px; }}

/* -------------------------------------------------------------- casillas */
QCheckBox, QRadioButton {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {borde};
    border-radius: 5px;
    background-color: {entrada};
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {acento}; }}
/* Marca de verificacion dibujada con un SVG en linea (color fijo blanco): es la
   forma de que la casilla se lea igual en el tema claro y en el oscuro sin
   depender de una imagen externa que habria que empaquetar. */
QCheckBox::indicator:checked {{
    background-color: {acento};
    border-color: {acento};
    image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHBhdGggZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmZmZmIiBzdHJva2Utd2lkdGg9IjIuNCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBkPSJNMy42IDguNkw2LjQgMTEuNCAxMi40IDQuOCIvPjwvc3ZnPg==");
}}
QRadioButton::indicator:checked {{
    background-color: {acento};
    border-color: {acento};
    image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PGNpcmNsZSBjeD0iOCIgY3k9IjgiIHI9IjMuNCIgZmlsbD0iI2ZmZmZmZiIvPjwvc3ZnPg==");
}}
QCheckBox::indicator:disabled {{ background-color: {fondo}; border-color: {borde_suave}; }}

/* --------------------------------------------------------------- grupos */
QGroupBox {{
    border: 1px solid {borde_suave};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
    background-color: {panel};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {texto_suave};
    background-color: {panel};
}}

/* --------------------------------------------------------------- tablas */
QTableWidget, QTableView, QTreeWidget, QListWidget {{
    background-color: {fondo_alt};
    alternate-background-color: {fondo};
    gridline-color: {borde_suave};
    border: 1px solid {borde_suave};
    border-radius: 10px;
    padding: 2px;
    selection-background-color: {acento_suave};
    selection-color: {texto};
    outline: none;
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{ padding: 2px 4px; border: none; }}
QTableWidget::item:hover, QListWidget::item:hover {{ background-color: {panel_hover}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background-color: {panel};
    color: {texto_suave};
    border: none;
    border-right: 1px solid {borde_suave};
    border-bottom: 1px solid {borde_suave};
    padding: 6px 8px;
    font-weight: bold;
}}
QHeaderView::section:hover {{ background-color: {panel_hover}; color: {texto}; }}
QTableCornerButton::section {{
    background-color: {panel};
    border: none;
    border-bottom: 1px solid {borde_suave};
}}
QListWidget {{ padding: 4px; }}
QListWidget::item {{ border-radius: 7px; padding: 4px 6px; }}
QListWidget::item:selected {{ background-color: {acento}; color: {sobre_acento}; }}

/* ------------------------------------------------------------ progreso */
QProgressBar {{
    border: 1px solid {borde};
    border-radius: 9px;
    background-color: {entrada};
    text-align: center;
    color: {texto};
    min-height: 20px;
    font-weight: bold;
}}
QProgressBar::chunk {{
    background-color: {acento};
    border-radius: 8px;
    margin: 1px;
}}

/* --------------------------------------------------------- barra estado */
QStatusBar {{
    background-color: {panel};
    color: {texto_suave};
    border-top: 1px solid {borde_suave};
}}
QStatusBar::item {{ border: none; }}

/* ------------------------------------------------------------- paneles */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    font-weight: bold;
    color: {texto_suave};
}}
QDockWidget::title {{
    background-color: {panel};
    border: 1px solid {borde_suave};
    border-radius: 9px;
    padding: 7px 10px;
    margin: 4px 4px 0 4px;
}}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background-color: {borde_suave}; border-radius: 2px; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QSplitter::handle:hover {{ background-color: {acento}; }}

/* ----------------------------------------------------- barras de scroll */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
    border: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px;
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: {borde};
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background-color: {acento}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* -------------------------------------------------------------- etiquetas */
QLabel {{ background: transparent; }}
QLabel#titulo {{ font-size: 15px; font-weight: bold; }}
QLabel#subtitulo {{ color: {texto_suave}; }}
QLabel#valor {{ font-size: 16px; font-weight: bold; }}
QLabel#aviso {{ color: {ambar}; padding: 4px 2px; }}
QFrame#tarjeta {{
    background-color: {panel};
    border: 1px solid {borde_suave};
    border-radius: 10px;
}}
QMenu {{
    background-color: {panel};
    color: {texto};
    border: 1px solid {borde};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {acento_suave}; color: {texto}; }}
QMenu::separator {{ height: 1px; background-color: {borde_suave}; margin: 4px 8px; }}
"""

#: El QSS se construye una vez por tema (evita re-formatear en cada consulta).
_CACHE: Dict[str, str] = {}


def qss(tema: str = "oscuro") -> str:
    """Devuelve la hoja de estilo QSS del tema indicado (``oscuro`` o ``claro``)."""
    clave = tema if tema in PALETAS else "oscuro"
    if clave not in _CACHE:
        _CACHE[clave] = _QSS.format(**PALETAS[clave]).replace(_SEP + _SEP, _SEP)
    return _CACHE[clave]


def colores(tema: str = "oscuro") -> Dict[str, str]:
    """Devuelve la paleta de colores del tema."""
    return dict(PALETAS.get(tema, PALETAS["oscuro"]))
