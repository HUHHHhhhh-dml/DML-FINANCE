# -*- coding: utf-8 -*-
"""Pestanas de la ventana principal, una por bloque del pliego.

Cada modulo expone una clase que hereda de :class:`~dml.ui.tabs.base.TabBase` y
solo se encarga de presentar. La logica financiera vive en :mod:`dml.models` y la
orquestacion en :mod:`dml.analisis`.
"""

from __future__ import annotations

__all__ = [
    "base",
    "principal",
    "econometrico",
    "griegas",
    "capm",
    "per",
    "eps",
    "pfcf",
    "renta_per",
    "rdr",
    "bonos",
    "fuentes",
]
