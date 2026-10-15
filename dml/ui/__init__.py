# -*- coding: utf-8 -*-
"""Interfaz de escritorio PySide6 de DML-FINANCE.

Organizacion:

* :mod:`~dml.ui.ventana_principal` - ventana principal, barra superior, pestanas.
* :mod:`~dml.ui.worker`            - hilos de descarga y calculo (QThread).
* :mod:`~dml.ui.widgets`          - widgets reutilizables (tablas, graficos, tarjetas).
* :mod:`~dml.ui.estilos`          - temas oscuro y claro (QSS).
* :mod:`~dml.ui.tabs`             - una pestana por bloque del pliego.

Ningun modulo de este paquete contiene logica financiera: todo se delega en
:mod:`dml.analisis` y :mod:`dml.models`.
"""

from __future__ import annotations

__all__ = ["crear_app", "ejecutar"]


def crear_app(argv=None):
    """Crea (o reutiliza) la ``QApplication`` con el estilo de la aplicacion."""
    from .app import crear_app as _crear_app

    return _crear_app(argv)


def ejecutar(argv=None, demo: bool = False, tickers=None, config=None, tema=None, marca=None) -> int:
    """Arranca la interfaz grafica y devuelve el codigo de salida.

    Args:
        argv: argumentos para Qt.
        demo: arranca con datos ficticios (DEMO), sin conexion.
        tickers: tickers que se analizan automaticamente al abrir.
        config: configuracion efectiva.
        tema: fuerza el tema inicial (``oscuro`` o ``claro``).
        marca: archivo donde escribir el marcador de arranque (diagnostico).
    """
    from .app import ejecutar as _ejecutar

    return _ejecutar(argv=argv, demo=demo, tickers=tickers, config=config, tema=tema, marca=marca)
