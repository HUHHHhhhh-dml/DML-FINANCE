# -*- coding: utf-8 -*-
"""DML-FINANCE: analizador cuantitativo de acciones con parrilla de decision.

Paquete modular:

* :mod:`dml.core`   - configuracion, tipos compartidos, cache y registro de fuentes.
* :mod:`dml.data`   - obtencion de datos (yfinance, Investing.com, FRED, respaldos, DEMO).
* :mod:`dml.models` - calculos financieros (rendimientos, Beta, CAPM, MCO, riesgo, BSM, parrilla).
* :mod:`dml.export` - exportacion opcional a Excel con formulas reales.
* :mod:`dml.ui`     - interfaz de escritorio PySide6 (pestanas, hilos, graficos).

La logica de negocio no depende de Qt: puede probarse sin interfaz grafica.
"""

from __future__ import annotations

__all__ = ["__version__", "VERSION_UI"]

__version__ = "2.0.0"
VERSION_UI = "DML-FINANCE 2.0.0"
