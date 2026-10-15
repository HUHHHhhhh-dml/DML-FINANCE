# -*- coding: utf-8 -*-
"""Exportacion **opcional** del analisis a un libro Excel (``.xlsx``).

Este modulo contiene el unico punto de la aplicacion que escribe un fichero:
:func:`exportar_excel`. Solo se ejecuta cuando el usuario pulsa el boton
"Exportar a Excel"; importarlo no crea ni modifica nada en disco.

Caracteristicas
---------------
* Replica las pestanas de la interfaz como hojas de calculo, en el orden
  ``Principal``, ``Econometrico``, ``Griegas``, ``CAPM``, ``PER``, ``EPS``,
  ``Price to FCF``, ``Renta PER``, ``RDR``, ``Bonos y tasas`` y
  ``Fuentes y avisos``.
* Con ``con_formulas=True`` las magnitudes derivadas se escriben como
  **formulas reales de Excel** que referencian las celdas de entrada (Beta,
  CAPM, precio objetivo, PER, Renta PER, RDR, Black-Scholes y sus griegas y
  los 12 criterios de la parrilla). Con ``con_formulas=False`` se escriben los
  valores ya calculados en Python.
* Las celdas de entrada van en azul (``Font(color="0000CC")``) y **cada celda
  de formula lleva un comentario** que explica la formula.
* Todo dato ausente se escribe como la cadena ``"N/D"``: nunca queda una celda
  vacia en lugar de un dato que falta.
* Si ``imagenes`` mapea una clave (``principal``, ``econometrico``, ``griegas``
  ...) a un PNG existente, se inserta en la hoja correspondiente; una ruta
  ausente o invalida solo genera un aviso en el registro.

Nota importante sobre los nombres de funcion
--------------------------------------------
openpyxl escribe el texto de la formula *literalmente* dentro del ``.xlsx``.
El formato OOXML exige el prefijo ``_xlfn.`` para las funciones posteriores a
Excel 2007: si se escribe ``=NORM.S.DIST(x,TRUE)`` sin ese prefijo, Excel
muestra ``#NAME?`` (y el error pasa desapercibido porque openpyxl no valida la
formula). Por eso :func:`_fx` antepone el prefijo a las funciones modernas
(``NORM.S.DIST`` -> ``_xlfn.NORM.S.DIST``, ``STDEV.S`` -> ``_xlfn.STDEV.S``);
**Excel 2010+ y LibreOffice Calc muestran y evaluan la formula sin el
prefijo**. Por eso se usa ``NORM.S.DIST(x,TRUE)`` (Excel 2010+) en lugar de
``NORMSDIST``. El resto de funciones empleadas (COVAR, VAR, SLOPE, INTERCEPT,
RSQ, STEYX, AVERAGE, EXP, LN, SQRT, IF, IFERROR, TDIST, CHIDIST, FDIST, ...)
existen desde Excel 2007 y no necesitan prefijo.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from ..core.tipos import (
    Criterio,
    Fuentes,
    ND,
    ResultadoAnalisis,
    ResultadoOLS,
    TablaTicker,
    Tasas,
)
from ..core.util import a_float, a_serie, ahora_iso, normalizar_mensual

LOG = logging.getLogger("dml.export")

# --------------------------------------------------------------------------
# Import tolerante de openpyxl: el modulo debe poder importarse aunque la
# dependencia opcional no este instalada (la aplicacion arranca sin Excel).
# --------------------------------------------------------------------------
try:  # pragma: no cover - depende del entorno de ejecucion
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.drawing.image import Image as _XLImage
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    _OPENPYXL_DISPONIBLE = True
    _ERROR_OPENPYXL = ""
except Exception as _exc:  # pragma: no cover - entorno sin openpyxl
    Workbook = None  # type: ignore[assignment]
    Comment = None  # type: ignore[assignment]
    _XLImage = None  # type: ignore[assignment]
    CellIsRule = None  # type: ignore[assignment]
    Alignment = Border = Font = PatternFill = Side = None  # type: ignore[assignment]
    get_column_letter = None  # type: ignore[assignment]
    _OPENPYXL_DISPONIBLE = False
    _ERROR_OPENPYXL = str(_exc)
    LOG.warning("openpyxl no disponible (%s): la exportacion a Excel fallara con un error claro", _exc)

# --------------------------------------------------------------------------
# Import opcional (y perezoso) del modelo Black-Scholes-Merton.
# Otro modulo del proyecto puede no existir todavia: nunca debe romper la
# importacion de este modulo ni la exportacion.
# --------------------------------------------------------------------------
try:  # pragma: no cover - depende del resto del proyecto
    from ..models.blackscholes import griegas as _bsm_griegas  # type: ignore[attr-defined]
    from ..models.blackscholes import precio_bsm as _bsm_precio  # type: ignore[attr-defined]

    _BSM_DISPONIBLE = True
except Exception as _exc_bsm:  # pragma: no cover - modulo aun no escrito
    _bsm_griegas = None  # type: ignore[assignment]
    _bsm_precio = None  # type: ignore[assignment]
    _BSM_DISPONIBLE = False
    LOG.debug("dml.models.blackscholes no disponible (%s): se usaran los valores del resultado", _exc_bsm)


# --------------------------------------------------------------------------
# Orden de hojas y constantes de presentacion
# --------------------------------------------------------------------------

ORDEN_HOJAS: Tuple[str, ...] = (
    "Principal",
    "Econometrico",
    "Griegas",
    "CAPM",
    "PER",
    "EPS",
    "Price to FCF",
    "Renta PER",
    "RDR",
    "Bonos y tasas",
    "Fuentes y avisos",
)

#: Claves aceptadas en ``imagenes`` -> nombre de la hoja donde se insertan.
CLAVES_IMAGENES: Dict[str, str] = {
    "principal": "Principal",
    "resumen": "Principal",
    "econometrico": "Econometrico",
    "economic": "Econometrico",
    "ols": "Econometrico",
    "griegas": "Griegas",
    "bsm": "Griegas",
    "capm": "CAPM",
    "per": "PER",
    "eps": "EPS",
    "fcf": "Price to FCF",
    "price_to_fcf": "Price to FCF",
    "renta_per": "Renta PER",
    "rdr": "RDR",
    "bonos": "Bonos y tasas",
    "tasas": "Bonos y tasas",
    "fuentes": "Fuentes y avisos",
    "avisos": "Fuentes y avisos",
}

# Formatos numericos (Excel)
FMT_PRECIO = "#,##0.00"
FMT_PCT = "0.00%"
FMT_PCT4 = "0.0000%"
FMT_NUM = "0.0000"
FMT_NUM2 = "0.00"
FMT_INT = "0"
FMT_FECHA = "yyyy-mm-dd"
FMT_PB = "#,##0.00"
FMT_CIENTIFICO = "0.00E+00"

#: Formato por unidad declarada en :class:`dml.core.tipos.Criterio`.
FMT_POR_UNIDAD: Dict[str, str] = {
    "porcentaje": FMT_PCT,
    "moneda": FMT_PRECIO,
    "numero": FMT_NUM,
    "texto": FMT_NUM,
}

#: Funciones posteriores a Excel 2007 que el formato OOXML guarda con prefijo.
FUNCIONES_MODERNAS: Dict[str, str] = {
    "NORM.S.DIST": "_xlfn.NORM.S.DIST",
    "NORM.S.INV": "_xlfn.NORM.S.INV",
    "STDEV.S": "_xlfn.STDEV.S",
    "STDEV.P": "_xlfn.STDEV.P",
}

#: Especificacion de los 12 criterios de la parrilla:
#: ``numero -> (comparacion, clave del valor, clave de la comparacion)``.
ESPECIFICACIONES_CRITERIOS: Dict[int, Tuple[str, str, str]] = {
    1: ("menor", "per_valor", "per_sector"),
    2: ("mayor_igual", "eps", "eps_forecast"),
    3: ("texto_distinto", "macd", "sell"),
    4: ("menor", "pfcf", "pfcf_sector"),
    5: ("mayor", "rend_capm", "tlr"),
    6: ("menor", "beta_cov", "beta_max"),
    7: ("mayor", "renta_per", "renta_per_sector"),
    8: ("mayor", "rend_capm", "riesgo"),
    9: ("mayor", "r2", "r2_min"),
    10: ("mayor", "proyeccion_trg", "umbral_trg"),
    11: ("menor", "spot", "strike"),
    12: ("mayor", "delta_call", "delta_call_min"),
}

#: Claves cuyo valor de comparacion procede de :class:`dml.core.tipos.Params`.
CLAVES_PARAMS: Dict[str, str] = {
    "beta_max": "beta_max",
    "r2_min": "r2_min",
    "delta_call_min": "delta_call_min",
}

if _OPENPYXL_DISPONIBLE:  # pragma: no branch - constante de importacion
    F_AZUL = Font(color="0000CC")            # datos de entrada
    F_NEGRO = Font(color="000000")           # formulas / valores calculados
    F_BOLD = Font(bold=True)
    F_TITULO = Font(bold=True, color="FFFFFF", size=12)
    F_CAB = Font(bold=True, color="1F3864")
    FILL_TITULO = PatternFill("solid", fgColor="1F3864")
    FILL_CAB = PatternFill("solid", fgColor="D9E1F2")
    FILL_INPUT = PatternFill("solid", fgColor="FFF7E6")
    FILL_OK = PatternFill("solid", fgColor="C6EFCE")
    FILL_NO = PatternFill("solid", fgColor="FFC7CE")
    FILL_AVISO = PatternFill("solid", fgColor="FFEB9C")
    FILL_ND = PatternFill("solid", fgColor="F2F2F2")
    FILL_DECISION = {
        "COMPRAR": PatternFill("solid", fgColor="00B050"),
        "MANTENER": PatternFill("solid", fgColor="FFC000"),
        "NO INVERTIR": PatternFill("solid", fgColor="C00000"),
    }
    BORDE = Border(
        left=Side(style="thin", color="BFBFBF"),
        right=Side(style="thin", color="BFBFBF"),
        top=Side(style="thin", color="BFBFBF"),
        bottom=Side(style="thin", color="BFBFBF"),
    )
else:  # pragma: no cover - entorno sin openpyxl
    F_AZUL = F_NEGRO = F_BOLD = F_TITULO = F_CAB = None
    FILL_TITULO = FILL_CAB = FILL_INPUT = FILL_OK = FILL_NO = FILL_AVISO = FILL_ND = None
    FILL_DECISION = {}
    BORDE = None


# ==========================================================================
# Utilidades de valores y formulas
# ==========================================================================


def _numero(valor: Any) -> Optional[float]:
    """Convierte ``valor`` en ``float`` finito o devuelve ``None``.

    Args:
        valor: cualquier objeto (numero, cadena, ``None``, ``NaN``...).

    Returns:
        El valor numerico o ``None`` si el dato no es utilizable.
    """
    return a_float(valor)


def _texto_nd(valor: Any) -> Any:
    """Devuelve ``valor`` o la cadena ``N/D`` cuando el dato falta.

    Se considera que un dato falta si es ``None``, ``NaN`` o una cadena vacia.
    """
    if valor is None:
        return ND
    if isinstance(valor, float) and math.isnan(valor):
        return ND
    if isinstance(valor, str):
        return valor if valor.strip() else ND
    try:
        if not isinstance(valor, (list, tuple, dict, pd.Series, pd.DataFrame)) and pd.isna(valor):
            return ND
    except (TypeError, ValueError):  # pragma: no cover - tipos exoticos
        pass
    return valor


def _es_nd(valor: Any) -> bool:
    """True si el valor se representa como ``N/D`` en la hoja."""
    return isinstance(valor, str) and valor.strip() == ND


def _texto_para_ancho(valor: Any) -> str:
    """Representacion textual usada para calcular el ancho de columna."""
    if valor is None:
        return ""
    return str(valor)


def _primero(diccionario: Optional[Dict[str, Any]], claves: Iterable[str]) -> Any:
    """Primer valor presente (no ``None``) de ``claves`` dentro del diccionario."""
    if not diccionario:
        return None
    for clave in claves:
        if clave in diccionario and diccionario[clave] is not None:
            return diccionario[clave]
    return None


def _fx(formula: Optional[str]) -> Optional[str]:
    """Adapta una formula al formato interno del ``.xlsx``.

    Antepone el prefijo ``_xlfn.`` a las funciones posteriores a Excel 2007
    (``NORM.S.DIST``, ``STDEV.S``...), tal y como exige OOXML. Sin ese prefijo
    Excel mostraria ``#NAME?``. La expresion regular no vuelve a prefijar una
    funcion ya prefijada (el caracter anterior seria ``.``).

    Args:
        formula: texto de la formula (``"=..."``) o ``None``.

    Returns:
        La formula lista para escribir, o ``None`` si la entrada era ``None``.
    """
    if not formula:
        return formula
    for moderno, interno in FUNCIONES_MODERNAS.items():
        formula = re.sub(
            r"(?<![A-Za-z0-9_.])" + re.escape(moderno) + r"\(",
            interno + "(",
            formula,
        )
    return formula


def _ref(hoja: str, col: int, fila: int) -> str:
    """Referencia a una celda de otra hoja, con el nombre entrecomillado.

    Args:
        hoja: nombre de la hoja (puede contener espacios).
        col: numero de columna (1 = A).
        fila: numero de fila.

    Returns:
        Cadena del tipo ``'Price to FCF'!D5``.
    """
    if get_column_letter is None:  # pragma: no cover - sin openpyxl
        return ""
    return f"'{hoja}'!{get_column_letter(col)}{fila}"


def _formula_cumple(tipo: str, fila: int, col_valor: int = 4, col_comparacion: int = 5) -> str:
    """Formula ``=IF(...)`` de la columna "¿Cumple?" de la parrilla.

    Args:
        tipo: ``menor``, ``mayor``, ``mayor_igual`` o ``texto_distinto``.
        fila: fila de la parrilla.
        col_valor: columna del valor obtenido.
        col_comparacion: columna de la comparacion.

    Returns:
        La formula de Excel que devuelve ``"SI"``/``"NO"``.
    """
    if get_column_letter is None:  # pragma: no cover - sin openpyxl
        return "N/D"
    v = f"{get_column_letter(col_valor)}{fila}"
    c = f"{get_column_letter(col_comparacion)}{fila}"
    if tipo == "texto_distinto":
        return f'=IF(OR({v}="Sell",{v}="{ND}",{v}=""),"NO","SI")'
    if tipo == "mayor":
        return f'=IF(AND(ISNUMBER({v}),ISNUMBER({c})),IF({v}>{c},"SI","NO"),"NO")'
    if tipo == "mayor_igual":
        return f'=IF(AND(ISNUMBER({v}),ISNUMBER({c})),IF({v}>={c},"SI","NO"),"NO")'
    return f'=IF(AND(ISNUMBER({v}),ISNUMBER({c})),IF({v}<{c},"SI","NO"),"NO")'


# ==========================================================================
# Escritor de hojas
# ==========================================================================


class _Hoja:
    """Envoltorio de una hoja de openpyxl con los estilos y contadores de DML.

    Centraliza el estilo de las celdas (entradas en azul, formulas con
    comentario, ``N/D`` sombreado), el ancho automatico de columnas, el panel
    congelado y el autofiltro de las tablas.

    Attributes:
        ws: hoja de openpyxl subyacente.
        con_formulas: si es ``True`` las magnitudes derivadas se escriben como
            formulas de Excel; si es ``False``, como valores calculados.
        n_formulas: numero de celdas de formula escritas.
        n_nd: numero de celdas escritas con ``N/D``.
    """

    def __init__(self, ws: Any, con_formulas: bool) -> None:
        self.ws = ws
        self.con_formulas = con_formulas
        self.n_formulas = 0
        self.n_nd = 0
        self._autofiltro: Optional[str] = None
        self._congelar: Optional[str] = None

    # -- propiedades ------------------------------------------------------
    @property
    def nombre(self) -> str:
        """Nombre de la hoja."""
        return str(self.ws.title)

    # -- primitivas -------------------------------------------------------
    def celda(
        self,
        fila: int,
        col: int,
        valor: Any,
        *,
        tipo: str = "texto",
        fmt: Optional[str] = None,
        negrita: bool = False,
        fill: Any = None,
        wrap: bool = False,
        comentario: Optional[str] = None,
        centrado: bool = False,
    ) -> Any:
        """Escribe una celda aplicando el estilo correspondiente a ``tipo``.

        Args:
            fila: fila (1-based).
            col: columna (1-based).
            valor: valor a escribir; si es ``None``/``NaN`` se escribe ``N/D``.
            tipo: ``input`` (azul, dato de entrada), ``formula`` (con
                comentario), ``valor`` (calculado en Python) o ``texto``.
            fmt: formato numerico de Excel.
            negrita: si la celda va en negrita.
            fill: relleno explicito (si no se indica, se deduce del tipo).
            wrap: ajustar el texto a la celda.
            comentario: comentario/tooltip de la celda.
            centrado: centrar horizontalmente el contenido.

        Returns:
            La celda de openpyxl ya escrita.
        """
        celda = self.ws.cell(row=fila, column=col)
        es_formula = tipo == "formula"
        if not es_formula:
            valor = _texto_nd(valor)
            if _es_nd(valor):
                self.n_nd += 1
        celda.value = valor
        if tipo == "input":
            celda.font = Font(color="0000CC", bold=negrita)
            celda.fill = fill if fill is not None else FILL_INPUT
        elif tipo == "formula":
            self.n_formulas += 1
            celda.font = Font(color="000000", bold=negrita)
            if fill is not None:
                celda.fill = fill
        elif tipo == "valor":
            celda.font = Font(bold=negrita, color="000000")
            if fill is not None:
                celda.fill = fill
            elif _es_nd(valor):
                celda.fill = FILL_ND
        else:
            color = "FFFFFF" if fill is FILL_TITULO else "000000"
            celda.font = Font(bold=negrita, color=color)
            if fill is not None:
                celda.fill = fill
            elif _es_nd(valor):
                celda.fill = FILL_ND
        if fmt:
            celda.number_format = fmt
        if wrap or centrado:
            celda.alignment = Alignment(
                wrap_text=wrap, vertical="top" if wrap else "center", horizontal="center" if centrado else None
            )
        if comentario:
            self._comentario(celda, comentario)
        return celda

    def _comentario(self, celda: Any, texto: str) -> None:
        """Adjunta un comentario/tooltip a una celda (nunca lanza excepcion)."""
        if Comment is None:  # pragma: no cover - sin openpyxl
            return
        try:
            nota = Comment(str(texto), "DML Finance")
            nota.width = 340
            nota.height = 150
            celda.comment = nota
        except Exception as exc:  # pragma: no cover - proteccion defensiva
            LOG.debug("No se pudo anotar la celda %s: %s", celda.coordinate, exc)

    # -- azucar sintactico ------------------------------------------------
    def texto(self, fila: int, col: int, valor: Any, **kw: Any) -> Any:
        """Escribe una celda de texto (o ``N/D`` si falta el dato)."""
        return self.celda(fila, col, valor, tipo="texto", **kw)

    def entrada(self, fila: int, col: int, valor: Any, **kw: Any) -> Any:
        """Escribe una celda de **entrada** (fuente azul sobre fondo crema)."""
        return self.celda(fila, col, valor, tipo="input", **kw)

    def valor(self, fila: int, col: int, valor: Any, **kw: Any) -> Any:
        """Escribe un valor calculado en Python (fuente negra)."""
        return self.celda(fila, col, valor, tipo="valor", **kw)

    def formula(
        self,
        fila: int,
        col: int,
        formula: Optional[str],
        *,
        alternativo: Any = None,
        fmt: Optional[str] = None,
        comentario: str = "",
        negrita: bool = False,
        fill: Any = None,
        wrap: bool = False,
    ) -> Any:
        """Escribe una formula de Excel (o su valor si ``con_formulas`` es falso).

        Args:
            fila: fila de la celda.
            col: columna de la celda.
            formula: formula de Excel empezando por ``=``; ``None`` para forzar
                la escritura del valor alternativo (por ejemplo si faltan datos).
            alternativo: valor calculado en Python que se usa cuando
                ``con_formulas`` es ``False`` o cuando no hay formula.
            fmt: formato numerico.
            comentario: explicacion de la formula (obligatoria en la practica:
                si no se indica se usa el propio texto de la formula).
            negrita: celda en negrita.
            fill: relleno explicito.
            wrap: ajustar texto.

        Returns:
            La celda escrita.
        """
        if self.con_formulas and formula:
            texto = _fx(formula)
            assert texto is not None  # _fx solo devuelve None si la entrada lo era
            return self.celda(
                fila,
                col,
                texto,
                tipo="formula",
                fmt=fmt,
                negrita=negrita,
                fill=fill,
                wrap=wrap,
                comentario=comentario or f"Formula: {texto}",
            )
        celda = self.celda(fila, col, alternativo, tipo="valor", fmt=fmt, negrita=negrita, fill=fill, wrap=wrap)
        if comentario:
            self._comentario(celda, f"{comentario} (valor calculado en Python)")
        return celda

    # -- estructuras ------------------------------------------------------
    def titulo(self, fila: int, texto: str, col_ini: int = 1, col_fin: int = 10) -> None:
        """Escribe un titulo de seccion con fondo oscuro sobre celdas fusionadas."""
        self.ws.merge_cells(start_row=fila, start_column=col_ini, end_row=fila, end_column=col_fin)
        celda = self.ws.cell(row=fila, column=col_ini)
        celda.value = texto
        celda.font = F_TITULO
        celda.fill = FILL_TITULO
        celda.alignment = Alignment(vertical="center")
        if Comment is not None:
            self._comentario(celda, texto)

    def cabecera(self, fila: int, valores: Sequence[Any], col_ini: int = 1) -> None:
        """Escribe la fila de cabecera de una tabla (relleno + borde)."""
        for i, valor in enumerate(valores):
            celda = self.ws.cell(row=fila, column=col_ini + i)
            celda.value = _texto_nd(valor)
            celda.font = F_CAB
            celda.fill = FILL_CAB
            celda.border = BORDE
            celda.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

    def nota(self, fila: int, texto: str, col_ini: int = 1, col_fin: int = 10, negrita: bool = False) -> None:
        """Escribe una nota de texto fusionada a lo ancho de la tabla."""
        self.ws.merge_cells(start_row=fila, start_column=col_ini, end_row=fila, end_column=col_fin)
        celda = self.ws.cell(row=fila, column=col_ini)
        celda.value = _texto_nd(texto)
        celda.font = Font(bold=negrita, color="000000")
        celda.alignment = Alignment(wrap_text=True, vertical="top")

    def autofiltro(self, fila_cab: int, col_ini: int, col_fin: int, fila_fin: int) -> None:
        """Registra el autofiltro de la primera tabla de la hoja.

        Excel admite un unico autofiltro por hoja; si hay varios bloques
        (varios tickers) se aplica al primero.
        """
        if get_column_letter is None:  # pragma: no cover - sin openpyxl
            return
        if self._autofiltro is not None or fila_fin <= fila_cab:
            return
        ini = f"{get_column_letter(col_ini)}{fila_cab}"
        fin = f"{get_column_letter(col_fin)}{fila_fin}"
        self._autofiltro = f"{ini}:{fin}"

    def congelar(self, celda: str) -> None:
        """Fija el panel congelado de la hoja (por ejemplo ``"A3"``).

        Excel admite un unico panel congelado por hoja: se conserva el primero
        que se solicita (el del primer bloque, que es el que el usuario ve al
        abrir el libro con varios tickers).
        """
        if self._congelar is None:
            self._congelar = celda

    def colorear_semaforo(self, rango: str, si: str = "SI", no: str = "NO") -> None:
        """Anade formato condicional verde/rojo a un rango de celdas SI/NO."""
        if CellIsRule is None:  # pragma: no cover - sin openpyxl
            return
        try:
            self.ws.conditional_formatting.add(
                rango, CellIsRule(operator="equal", formula=[f'"{si}"'], fill=FILL_OK)
            )
            self.ws.conditional_formatting.add(
                rango, CellIsRule(operator="equal", formula=[f'"{no}"'], fill=FILL_NO)
            )
            self.ws.conditional_formatting.add(
                rango, CellIsRule(operator="equal", formula=[f'"{ND}"'], fill=FILL_ND)
            )
        except Exception as exc:  # pragma: no cover - proteccion defensiva
            LOG.debug("No se pudo aplicar el formato condicional a %s: %s", rango, exc)

    def anchos_automaticos(self, minimo: int = 10, maximo: int = 58) -> None:
        """Ajusta el ancho de cada columna al contenido mas largo.

        Las celdas de formula no ensanchan la columna (su texto no es
        representativo del resultado) y las celdas fusionadas se ignoran para
        que los titulos largos no deformen la primera columna.
        """
        if get_column_letter is None:  # pragma: no cover - sin openpyxl
            return
        anclas = {(rango.min_row, rango.min_col) for rango in self.ws.merged_cells.ranges}
        largos: Dict[int, int] = {}
        for fila in self.ws.iter_rows():
            for celda in fila:
                if celda.value is None or (celda.row, celda.column) in anclas:
                    continue
                if str(celda.value).startswith("="):
                    largo = 12
                elif isinstance(celda.value, str):
                    largo = max((len(parte) for parte in celda.value.split("\n")), default=0)
                elif isinstance(celda.value, (int, float)) and not isinstance(celda.value, bool):
                    largo = len(f"{celda.value:,.4f}") + 2
                else:
                    largo = len(_texto_para_ancho(celda.value))
                if largo > largos.get(celda.column, 0):
                    largos[celda.column] = largo
        for col, largo in largos.items():
            self.ws.column_dimensions[get_column_letter(col)].width = float(max(minimo, min(maximo, largo + 2)))

    def cerrar(self, filtro: bool = True, anchos: bool = True) -> None:
        """Aplica el panel congelado, el autofiltro y el ancho automatico."""
        if self._congelar:
            self.ws.freeze_panes = self._congelar
        if filtro and self._autofiltro:
            self.ws.auto_filter.ref = self._autofiltro
        if anchos:
            self.anchos_automaticos()


# ==========================================================================
# Preparacion de datos de entrada
# ==========================================================================

COLUMNAS_MENSUAL: Tuple[str, ...] = (
    "Precio",
    "Indice",
    "TLR_anual",
    "R_Accion",
    "R_Mercado",
    "TLR_mensual",
    "PRH_mensual",
)


def _tabla_mensual(r: ResultadoAnalisis) -> pd.DataFrame:
    """Rejilla mensual del ticker usada por la hoja ``CAPM``.

    Toma como fuente principal :attr:`ResultadoAnalisis.tabla` y, si viene
    vacia, reconstruye la rejilla desde ``precios``, ``indice_precios`` y
    ``tasas.serie_tbill_mensual``. Siempre devuelve las mismas columnas.

    Args:
        r: resultado del analisis de un ticker.

    Returns:
        ``DataFrame`` con ``Fecha, Precio, Indice, TLR_anual, R_Accion,
        R_Mercado, TLR_mensual, PRH_mensual`` ordenado por fecha.
    """
    tabla: Optional[TablaTicker] = r.tabla
    base: Optional[pd.DataFrame] = None

    if tabla is not None and len(list(tabla.precio)) > 0:
        try:
            n = len(list(tabla.precio))
            base = pd.DataFrame(
                {
                    "Fecha": list(tabla.index) if len(list(tabla.index)) == n else list(range(n)),
                    "Precio": list(tabla.precio),
                    "Indice": list(tabla.indice) if len(list(tabla.indice)) == n else [None] * n,
                    "TLR_anual": list(tabla.tlr_anual) if len(list(tabla.tlr_anual)) == n else [None] * n,
                }
            )
        except Exception as exc:  # pragma: no cover - datos inconsistentes
            LOG.warning("Tabla mensual de %s inconsistente (%s): se reconstruye desde las series", r.ticker, exc)
            base = None

    if base is None:
        precios = a_serie(r.precios)
        if precios is None or len(precios) == 0:
            return pd.DataFrame(columns=list(COLUMNAS_MENSUAL) + ["Fecha"], index=pd.RangeIndex(0))
        serie = pd.Series(list(precios.values), index=pd.to_datetime(list(precios.index)), dtype="float64")
        base = pd.DataFrame({"Precio": serie})
        indice = a_serie(r.indice_precios)
        if indice is not None and len(indice) > 0:
            indice = pd.Series(
                list(indice.values), index=pd.to_datetime(list(indice.index)), dtype="float64"
            )
            base = base.join(indice.rename("Indice"), how="left")
        tlr = normalizar_mensual(r.tasas.serie_tbill_mensual)
        if tlr is not None and len(tlr) > 0:
            base = base.join(tlr.rename("TLR_anual"), how="left")
        base = base.reset_index().rename(columns={"index": "Fecha"})

    base["Fecha"] = pd.to_datetime(base["Fecha"], errors="coerce")
    base = base.dropna(subset=["Fecha"]).sort_values("Fecha")
    for columna in ("Precio", "Indice", "TLR_anual"):
        if columna not in base.columns:
            base[columna] = None
        base[columna] = pd.to_numeric(base[columna], errors="coerce")
    if base.empty:
        return pd.DataFrame(columns=list(COLUMNAS_MENSUAL) + ["Fecha"], index=pd.RangeIndex(0))
    if base["TLR_anual"].isna().all() and r.tlr is not None:
        base["TLR_anual"] = float(r.tlr)
    else:
        base["TLR_anual"] = base["TLR_anual"].ffill().bfill()
    base = base.dropna(subset=["Precio"]).reset_index(drop=True)

    base["R_Accion"] = base["Precio"].pct_change()
    base["R_Mercado"] = base["Indice"].pct_change()
    base["TLR_mensual"] = base["TLR_anual"] / 12.0
    # PRH mensual = rendimiento de la ACCION - TLR mensual, exactamente igual que
    # la columna homonima de la tabla del analisis (dml/analisis.py). Estaba
    # calculada con el rendimiento del MERCADO, de modo que la misma hoja mezclaba
    # dos definiciones distintas de PRH (la columna y su promedio).
    base["PRH_mensual"] = base["R_Accion"] - base["TLR_mensual"]
    return base


def _llamar_bsm(funcion: Any, argumentos: Dict[str, float], b: float, tipo: str) -> Any:
    """Invoca una funcion de :mod:`dml.models.blackscholes` tolerando su firma.

    El modulo es opcional y su firma puede variar (con o sin ``b`` y ``tipo``,
    por palabras clave o por posicion). Se prueban las variantes conocidas y,
    si ninguna encaja, se devuelve ``None`` sin propagar la excepcion.

    Args:
        funcion: ``precio_bsm`` o ``griegas``.
        argumentos: ``S``, ``K``, ``T``, ``r``, ``q`` y ``sigma``.
        b: coste de mantenimiento ``r - q``.
        tipo: ``"call"`` o ``"put"``.

    Returns:
        Lo que devuelva la funcion o ``None``.
    """
    intentos = (
        lambda: funcion(**{**argumentos, "b": b, "tipo": tipo}),
        lambda: funcion(**{**argumentos, "b": b}),
        lambda: funcion(**argumentos),
        lambda: funcion(
            argumentos["S"], argumentos["K"], argumentos["T"], argumentos["r"], argumentos["q"], b,
            argumentos["sigma"], tipo,
        ),
        lambda: funcion(
            argumentos["S"], argumentos["K"], argumentos["T"], argumentos["r"], argumentos["q"],
            argumentos["sigma"],
        ),
    )
    for intento in intentos:
        try:
            return intento()
        except TypeError:
            continue
        except Exception as exc:  # pragma: no cover - datos invalidos
            LOG.debug("blackscholes rechazo los argumentos (%s): %s", type(exc).__name__, exc)
            return None
    return None


def _python_bsm(
    S: Optional[float],
    K: Optional[float],
    T: Optional[float],
    r: Optional[float],
    q: Optional[float],
    sigma: Optional[float],
    b: Optional[float] = None,
) -> Optional[Tuple[Dict[str, float], Dict[str, float]]]:
    """Calcula las griegas de la call y de la put con el modulo BSM del proyecto.

    El modulo :mod:`dml.models.blackscholes` es opcional: si no existe, si su
    firma no encaja o si los datos son invalidos, se devuelve ``None`` y la
    exportacion continua con los valores que ya vengan en el resultado.

    Args:
        S: spot.
        K: strike.
        T: vencimiento en anios.
        r: tasa libre de riesgo anual.
        q: dividend yield anual.
        sigma: volatilidad anual.
        b: coste de mantenimiento; por defecto ``r - q``.

    Returns:
        ``(griegas_call, griegas_put)`` o ``None`` si el modulo no esta disponible.
    """
    precio_bsm, funcion_griegas = _bsm_precio, _bsm_griegas
    if precio_bsm is None or funcion_griegas is None or None in (S, K, T, r, q, sigma):
        return None
    argumentos = {
        "S": float(S),  # type: ignore[arg-type]
        "K": float(K),  # type: ignore[arg-type]
        "T": float(T),  # type: ignore[arg-type]
        "r": float(r),  # type: ignore[arg-type]
        "q": float(q),  # type: ignore[arg-type]
        "sigma": float(sigma),  # type: ignore[arg-type]
    }
    coste = _numero(b)
    if coste is None:
        coste = argumentos["r"] - argumentos["q"]
    resultado: List[Dict[str, float]] = []
    for tipo in ("call", "put"):
        valores = _llamar_bsm(funcion_griegas, argumentos, coste, tipo)
        limpio: Dict[str, float] = {}
        if isinstance(valores, dict):
            for clave, valor in valores.items():
                numero = _numero(valor)
                if numero is not None:
                    limpio[str(clave).lower()] = numero
        elif isinstance(valores, (tuple, list)):
            for nombre, valor in zip(("delta", "gamma", "vega", "theta", "rho"), valores):
                numero = _numero(valor)
                if numero is not None:
                    limpio[nombre] = numero
        if not limpio:
            prima = _numero(_llamar_bsm(precio_bsm, argumentos, coste, tipo))
            if prima is None:
                return None
            limpio = {"prima": prima}
        resultado.append(limpio)
    return resultado[0], resultado[1]


# ==========================================================================
# Hoja CAPM
# ==========================================================================


def _escribir_capm(hoja: _Hoja, r: ResultadoAnalisis, fila: int) -> Tuple[Dict[str, Any], int]:
    """Escribe el bloque CAPM de un ticker (tabla mensual + Beta + precio objetivo).

    Args:
        hoja: hoja ``CAPM``.
        r: resultado del ticker.
        fila: primera fila libre del bloque.

    Returns:
        ``(referencias, siguiente_fila)``. Las referencias apuntan a las celdas
        de TLR, Beta, PRH, Rend_CAPM, spot y precio objetivo del ticker.
    """
    df = _tabla_mensual(r)
    n = int(len(df))
    refs: Dict[str, Any] = {}

    hoja.titulo(fila, f"{r.ticker} - Modelo CAPM ({n} meses, indice {r.indice_nombre}, modo {r.modo})", 1, 9)
    fila += 1
    hoja.nota(
        fila,
        "Las celdas azules son datos de entrada (precio, indice, TLR); las celdas con comentario contienen "
        "formulas de Excel. Rend_CAPM = TLR + Beta x PRH y el precio objetivo = Spot x (1 + Rend_CAPM).",
        1,
        9,
    )
    fila += 1
    hoja.cabecera(
        fila,
        ["Fecha", "Precio cierre", "Indice", "Rend. accion", "Rend. mercado",
         "TLR anual", "TLR mensual", "PRH mensual (Ra - Rf)"],
    )
    fila_cab = fila
    fila += 1
    fila_datos = fila
    for i in range(n):
        f = fila + i
        fecha = df.at[i, "Fecha"]
        entrada = df.iloc[i]
        valor_fecha = fecha.date() if hasattr(fecha, "date") else fecha
        hoja.entrada(f, 1, valor_fecha, fmt=FMT_FECHA, comentario="Mes de la serie mensual (entrada)")
        hoja.entrada(f, 2, _numero(entrada["Precio"]), fmt=FMT_PRECIO, comentario="Precio de cierre del mes (entrada)")
        hoja.entrada(f, 3, _numero(entrada["Indice"]), fmt=FMT_PRECIO, comentario=f"Nivel del indice {r.indice_nombre} (entrada)")
        if i == 0:
            hoja.texto(f, 4, ND, comentario="El primer mes de la serie no tiene rendimiento")
            hoja.texto(f, 5, ND, comentario="El primer mes de la serie no tiene rendimiento")
        else:
            hoja.formula(
                f, 4, f'=IFERROR(B{f}/B{f-1}-1,"{ND}")', alternativo=_numero(entrada["R_Accion"]),
                fmt=FMT_PCT, comentario="Rend. accion = Precio(t) / Precio(t-1) - 1",
            )
            hoja.formula(
                f, 5, f'=IFERROR(C{f}/C{f-1}-1,"{ND}")', alternativo=_numero(entrada["R_Mercado"]),
                fmt=FMT_PCT, comentario="Rend. mercado = Indice(t) / Indice(t-1) - 1",
            )
        hoja.entrada(f, 6, _numero(entrada["TLR_anual"]), fmt=FMT_PCT4, comentario="TLR anual (T-Bill 4 semanas) del mes (entrada)")
        hoja.formula(
            f, 7, f'=IFERROR(F{f}/12,"{ND}")', alternativo=_numero(entrada["TLR_mensual"]),
            fmt=FMT_PCT4, comentario="TLR mensual = TLR anual / 12",
        )
        hoja.formula(
            f, 8, f'=IFERROR(D{f}-G{f},"{ND}")', alternativo=_numero(entrada["PRH_mensual"]),
            fmt=FMT_PCT4, comentario="PRH mensual = Rend. accion - TLR mensual (igual que la tabla del analisis)",
        )
    fila_ult = fila + n - 1
    if n > 0:
        hoja.autofiltro(fila_cab, 1, 8, fila_ult)
        hoja.congelar(f"A{fila_datos}")
    fila = fila_ult + 2

    rango_d = f"D{fila_datos}:D{fila_ult}"
    rango_e = f"E{fila_datos}:E{fila_ult}"
    rango_h = f"H{fila_datos}:H{fila_ult}"
    hay_serie = n > 2

    hoja.titulo(fila, f"{r.ticker} - Resumen CAPM", 1, 9)
    fila += 1
    hoja.cabecera(fila, ["Concepto", "Valor", "Formula / nota", "Valor Python (contraste)"])
    fila += 1

    # Beta (covarianza / varianza)
    fila_beta_cov = fila
    hoja.texto(fila, 1, "Beta (covarianza / varianza)", negrita=True)
    hoja.formula(
        fila, 2,
        f'=IFERROR(COVAR({rango_d},{rango_e})/VAR({rango_e}),"{ND}")' if hay_serie else None,
        alternativo=_numero(r.beta_cov), fmt=FMT_NUM,
        comentario="Beta = COVAR(rend. accion; rend. mercado) / VAR(rend. mercado). COVAR de Excel usa la "
                   "covarianza poblacional (divide por n) y VAR la varianza muestral (divide por n-1).",
    )
    hoja.texto(fila, 3, "COVAR(rend. accion, rend. mercado) / VAR(rend. mercado)", wrap=True)
    hoja.valor(fila, 4, _numero(r.beta_cov), fmt=FMT_NUM)
    fila += 1

    # Beta OLS
    fila_beta_ols = fila
    hoja.texto(fila, 1, "Beta (regresion OLS)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(SLOPE({rango_d},{rango_e}),"{ND}")' if hay_serie else None,
        alternativo=_numero(r.beta_ols), fmt=FMT_NUM,
        comentario="Beta OLS = SLOPE(rend. accion; rend. mercado), la pendiente de Ra ~ Rm.",
    )
    hoja.texto(fila, 3, "SLOPE(rend. accion, rend. mercado)", wrap=True)
    hoja.valor(fila, 4, _numero(r.beta_ols), fmt=FMT_NUM)
    fila += 1

    # Beta publicada
    fila_beta_pub = fila
    hoja.texto(fila, 1, "Beta publicada (fuente externa)", negrita=True)
    hoja.entrada(fila, 2, _numero(r.beta_publicada), fmt=FMT_NUM, comentario="Beta publicada, dato de entrada (no calculado)")
    hoja.texto(fila, 3, "Dato publicado por la fuente; no se calcula", wrap=True)
    hoja.valor(fila, 4, _numero(r.fundamentales.beta_publicada), fmt=FMT_NUM)
    fila += 1

    # Diferencia
    hoja.texto(fila, 1, "Diferencia (calculada - publicada)")
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_beta_cov}-B{fila_beta_pub},"{ND}")',
        alternativo=(
            _numero(r.beta_cov) - _numero(r.beta_publicada)
            if _numero(r.beta_cov) is not None and _numero(r.beta_publicada) is not None
            else None
        ),
        fmt=FMT_NUM, comentario="Diferencia entre la beta calculada (COVAR/VAR) y la beta publicada.",
    )
    fila += 1

    # TLR
    fila_tlr = fila
    hoja.texto(fila, 1, "TLR anual (r)", negrita=True)
    hoja.entrada(fila, 2, _numero(r.tlr), fmt=FMT_PCT, comentario="Tasa libre de riesgo anual (T-Bill 4 semanas), dato de entrada")
    hoja.texto(fila, 3, f"Metodo: {r.tasas.metodo_de('tbill_4w')}", wrap=True)
    fila += 1

    hoja.texto(fila, 1, "TLR mensual (r_m)")
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_tlr}/12,"{ND}")', alternativo=_numero(r.tlr_mensual_valor) or (
            _numero(r.tlr) / 12.0 if _numero(r.tlr) is not None else None
        ),
        fmt=FMT_PCT4, comentario="TLR mensual = TLR anual / 12",
    )
    fila += 1

    # PRH
    fila_prh = fila
    hoja.texto(fila, 1, "PRH mensual promedio (Ra - Rf)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(AVERAGE({rango_h}),"{ND}")' if n > 0 else None,
        alternativo=_numero(r.prh_mensual_promedio), fmt=FMT_PCT4,
        comentario="PRH mensual = AVERAGE de la columna 'PRH mensual (Ra - Rf)'.",
    )
    fila += 1

    fila_prh_anual = fila
    hoja.texto(fila, 1, "PRH anualizado (x 12)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_prh}*12,"{ND}")', alternativo=_numero(r.prh), fmt=FMT_PCT,
        comentario="PRH anual = PRH mensual promedio x 12.",
    )
    fila += 1

    # Rend_CAPM
    fila_capm = fila
    hoja.texto(fila, 1, "Rend_CAPM = TLR + Beta x PRH", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_tlr}+B{fila_beta_cov}*B{fila_prh_anual},"{ND}")',
        alternativo=_numero(r.rend_capm), fmt=FMT_PCT,
        comentario="Rend_CAPM = TLR + Beta x PRH (modelo CAPM con la beta de covarianza/varianza).",
    )
    hoja.texto(fila, 3, f"Python: {_numero(r.rend_capm) if _numero(r.rend_capm) is not None else ND}", wrap=True)
    fila += 1

    # Volatilidad de contraste (STDEV.S)
    hoja.texto(fila, 1, "Volatilidad anual (STDEV.S mensual x raiz de 12)")
    hoja.formula(
        fila, 2, f'=IFERROR(STDEV.S({rango_d})*SQRT(12),"{ND}")' if hay_serie else None,
        alternativo=_numero(r.riesgo.sigma_anual), fmt=FMT_PCT,
        comentario="Desviacion estandar muestral de los rendimientos mensuales x SQRT(12). Contraste de la "
                   "volatilidad usada en Black-Scholes (NORM.S.DIST/STDEV.S son funciones de Excel 2010+).",
    )
    hoja.valor(fila, 4, _numero(r.riesgo.sigma_anual), fmt=FMT_PCT)
    fila += 1

    # Spot y precio objetivo
    fila_spot = fila
    hoja.texto(fila, 1, "Spot (S)", negrita=True)
    hoja.entrada(fila, 2, _numero(r.spot), fmt=FMT_PRECIO, comentario="Ultimo cierre disponible (dato de entrada)")
    fila += 1

    fila_objetivo = fila
    hoja.texto(fila, 1, "Precio objetivo = Spot x (1 + Rend_CAPM)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_spot}*(1+B{fila_capm}),"{ND}")',
        alternativo=_numero(r.precio_objetivo), fmt=FMT_PRECIO,
        comentario="Precio objetivo = Spot x (1 + Rend_CAPM).",
    )
    hoja.texto(fila, 3, f"Python: {_numero(r.precio_objetivo) if _numero(r.precio_objetivo) is not None else ND}", wrap=True)
    fila += 2

    refs.update(
        {
            "titulo": f"'{hoja.nombre}'!A{fila_cab - 2}",
            "beta_cov": _ref(hoja.nombre, 2, fila_beta_cov),
            "beta_ols": _ref(hoja.nombre, 2, fila_beta_ols),
            "beta_pub": _ref(hoja.nombre, 2, fila_beta_pub),
            "tlr": _ref(hoja.nombre, 2, fila_tlr),
            "prh_mensual": _ref(hoja.nombre, 2, fila_prh),
            "prh": _ref(hoja.nombre, 2, fila_prh_anual),
            "rend_capm": _ref(hoja.nombre, 2, fila_capm),
            "spot": _ref(hoja.nombre, 2, fila_spot),
            "precio_objetivo": _ref(hoja.nombre, 2, fila_objetivo),
            "col_rend_accion": _ref(hoja.nombre, 4, fila_datos),
            "col_rend_mercado": _ref(hoja.nombre, 5, fila_datos),
            "filas_datos": (fila_datos, fila_ult),
            "n": n,
            "hoja": hoja.nombre,
        }
    )
    return refs, fila


# ==========================================================================
# Hoja Econometrico
# ==========================================================================


def _serie_ols(ols: ResultadoOLS, df: pd.DataFrame) -> Tuple[List[int], List[float]]:
    """Periodos y precios observados del modelo MCO, tolerante a listas cortas."""
    periodos = [int(p) for p in list(ols.periodos)] if ols.periodos else []
    precios = [_numero(p) for p in list(ols.precios)]
    if not periodos:
        periodos = list(range(1, len(precios) + 1))
    if len(precios) < len(periodos) and not df.empty:
        faltan = len(periodos) - len(precios)
        precios = precios + [_numero(v) for v in list(df["Precio"].tail(faltan))]
    return periodos, [p if p is not None else None for p in precios]  # type: ignore[list-item]


def _escribir_econometrico(
    hoja: _Hoja, r: ResultadoAnalisis, df: pd.DataFrame, capm: Dict[str, Any], fila: int
) -> Tuple[Dict[str, Any], int]:
    """Escribe el bloque del modelo econometrico MCO de un ticker.

    Incluye la tabla (precio observado, ajustado y residuos), el resumen de la
    regresion con formulas de Excel auditables, el diagnostico y el pronostico.

    Args:
        hoja: hoja ``Econometrico``.
        r: resultado del ticker.
        df: rejilla mensual del ticker (para las fechas).
        capm: referencias a las celdas de la hoja ``CAPM`` de este ticker.
        fila: primera fila libre del bloque.

    Returns:
        ``(referencias, siguiente_fila)`` con las celdas de R2, pronostico,
        proyeccion TRG y umbral.
    """
    refs: Dict[str, Any] = {}
    ols = r.ols
    if ols is None:
        hoja.titulo(fila, f"{r.ticker} - Modelo econometrico: no disponible", 1, 9)
        fila += 1
        hoja.texto(fila, 1, ND, comentario="No se pudo estimar la regresion MCO (serie insuficiente)")
        hoja.texto(fila, 2, ND)
        refs.update({"r2": _ref(hoja.nombre, 2, fila), "veredicto": _ref(hoja.nombre, 2, fila), "hoja": hoja.nombre})
        return refs, fila + 2

    periodos, precios = _serie_ols(ols, df)
    n = int(ols.n or len(periodos))
    n = max(n, len(periodos))
    hay = n >= 2

    hoja.titulo(
        fila,
        f"{r.ticker} - Modelo econometrico MCO: Precio = b0 + b1 x Periodo (n = {n}, metodo {ols.metodo or ND})",
        1, 9,
    )
    fila += 1
    hoja.nota(
        fila,
        "Equivale a RSQ(precio, periodo) del libro de referencia, con diagnostico completo. "
        "La columna 'Precio (Y)' es una entrada; 'Ajustado' y 'Residuo' son formulas.",
        1, 9,
    )
    fila += 1
    hoja.cabecera(fila, ["Fecha", "Periodo (t)", "Precio (Y)", "Ajustado (Y^)", "Residuo", "Residuo^2"])
    fila_cab = fila
    fila += 1
    fila_datos = fila
    fila_ult = fila + max(n, 1) - 1
    fila_coef_int = fila_ult + 2
    fila_coef_pen = fila_coef_int + 1
    fechas = list(df["Fecha"]) if not df.empty else []
    for i in range(max(n, 1)):
        f = fila + i
        fecha = fechas[i + 1] if i + 1 < len(fechas) else (fechas[i] if i < len(fechas) else None)
        hoja.entrada(f, 1, fecha.date() if hasattr(fecha, "date") else fecha, fmt=FMT_FECHA)
        hoja.entrada(f, 2, periodos[i] if i < len(periodos) else i + 1, fmt=FMT_INT, comentario="Periodo t (entrada)")
        hoja.entrada(f, 3, precios[i] if i < len(precios) else None, fmt=FMT_PRECIO, comentario="Precio observado Y (entrada)")
        hoja.formula(
            f, 4, f'=IFERROR($B${fila_coef_int}+$B${fila_coef_pen}*B{f},"{ND}")',
            alternativo=_numero(ols.ajustados[i]) if i < len(ols.ajustados) else None,
            fmt=FMT_PRECIO, comentario="Ajustado = intercepto + pendiente x periodo (coeficientes del resumen inferior).",
        )
        hoja.formula(
            f, 5, f'=IFERROR(C{f}-D{f},"{ND}")',
            alternativo=_numero(ols.residuos[i]) if i < len(ols.residuos) else None,
            fmt=FMT_PRECIO, comentario="Residuo = Precio observado - Precio ajustado.",
        )
        hoja.formula(f, 6, f'=IFERROR(E{f}^2,"{ND}")', alternativo=None, fmt=FMT_PRECIO,
                     comentario="Residuo al cuadrado (para el diagnostico de heterocedasticidad).")
    hoja.autofiltro(fila_cab, 1, 6, fila_ult)
    hoja.congelar(f"A{fila_datos}")
    fila = fila_ult + 1

    hoja.cabecera(fila, ["Resumen de la regresion", "Valor", "Formula / nota", "Valor Python (contraste)"])
    fila += 1

    fila_r_int = fila
    hoja.texto(fila, 1, "Intercepto (b0)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(INTERCEPT(C{fila_datos}:C{fila_ult},B{fila_datos}:B{fila_ult}),"{ND}")',
        alternativo=_numero(ols.intercepto), fmt=FMT_NUM,
        comentario="INTERCEPT(precio; periodo): termino independiente de la regresion MCO.",
    )
    hoja.texto(fila, 3, f"Python: {_numero(ols.intercepto)}", wrap=True)
    fila += 1

    fila_r_pen = fila
    hoja.texto(fila, 1, "Pendiente (b1)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(SLOPE(C{fila_datos}:C{fila_ult},B{fila_datos}:B{fila_ult}),"{ND}")',
        alternativo=_numero(ols.pendiente), fmt=FMT_NUM,
        comentario="SLOPE(precio; periodo): pendiente de la tendencia lineal.",
    )
    hoja.texto(fila, 3, f"Python: {_numero(ols.pendiente)}", wrap=True)
    fila += 1

    fila_r2 = fila
    hoja.texto(fila, 1, "R cuadrado (R2)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(RSQ(C{fila_datos}:C{fila_ult},B{fila_datos}:B{fila_ult}),"{ND}")',
        alternativo=_numero(ols.r2), fmt=FMT_NUM,
        comentario="RSQ(precio; periodo): coeficiente de determinacion de la regresion.",
    )
    hoja.texto(fila, 3, f"Python: {_numero(ols.r2)}", wrap=True)
    fila += 1

    fila_se_reg = fila
    hoja.texto(fila, 1, "Error estandar de la regresion")
    hoja.formula(
        fila, 2, f'=IFERROR(STEYX(C{fila_datos}:C{fila_ult},B{fila_datos}:B{fila_ult}),"{ND}")',
        alternativo=_numero(ols.se_regresion), fmt=FMT_NUM,
        comentario="STEYX(precio; periodo): error estandar de la estimacion.",
    )
    fila += 1

    hoja.texto(fila, 1, "R2 ajustado")
    hoja.formula(
        fila, 2, f'=IFERROR(1-(1-B{fila_r2})*({n}-1)/({n}-2),"{ND}")',
        alternativo=_numero(ols.r2_ajustado), fmt=FMT_NUM,
        comentario="R2 ajustado = 1 - (1 - R2) x (n - 1) / (n - 2).",
    )
    fila += 1

    hoja.texto(fila, 1, "Error estandar del intercepto")
    hoja.formula(
        fila, 2,
        f'=IFERROR(B{fila_se_reg}*SQRT(1/{n}+AVERAGE(B{fila_datos}:B{fila_ult})^2/DEVSQ(B{fila_datos}:B{fila_ult})),"{ND}")',
        alternativo=_numero(ols.se_intercepto), fmt=FMT_NUM,
        comentario="SE(b0) = SEE x SQRT(1/n + media(t)^2 / DEVSQ(t)).",
    )
    fila += 1

    hoja.texto(fila, 1, "Error estandar de la pendiente")
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_se_reg}/SQRT(DEVSQ(B{fila_datos}:B{fila_ult})),"{ND}")',
        alternativo=_numero(ols.se_pendiente), fmt=FMT_NUM,
        comentario="SE(b1) = SEE / SQRT(DEVSQ(t)).",
    )
    fila += 1

    fila_t_int = fila
    hoja.texto(fila, 1, "Estadistico t del intercepto")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_r_int}/B{fila-2},"{ND}")', alternativo=_numero(ols.t_intercepto),
                 fmt=FMT_NUM, comentario="t(b0) = b0 / SE(b0)." if hay else "")
    fila += 1

    fila_t_pen = fila
    hoja.texto(fila, 1, "Estadistico t de la pendiente")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_r_pen}/B{fila-2},"{ND}")', alternativo=_numero(ols.t_pendiente),
                 fmt=FMT_NUM, comentario="t(b1) = b1 / SE(b1).")
    fila += 1

    hoja.texto(fila, 1, "p-value del intercepto")
    hoja.formula(fila, 2, f'=IFERROR(TDIST(ABS(B{fila_t_int}),{max(n-2,1)},2),"{ND}")',
                 alternativo=_numero(ols.p_intercepto), fmt=FMT_NUM,
                 comentario="p-value bilateral = TDIST(|t|; n-2; 2) (funcion compatible de Excel).")
    fila += 1

    hoja.texto(fila, 1, "p-value de la pendiente")
    hoja.formula(fila, 2, f'=IFERROR(TDIST(ABS(B{fila_t_pen}),{max(n-2,1)},2),"{ND}")',
                 alternativo=_numero(ols.p_pendiente), fmt=FMT_NUM,
                 comentario="p-value bilateral = TDIST(|t|; n-2; 2).")
    fila += 1

    fila_f = fila
    hoja.texto(fila, 1, "Estadistico F")
    hoja.formula(
        fila, 2, f'=IFERROR((B{fila_r2}/1)/((1-B{fila_r2})/({max(n-2,1)})),"{ND}")',
        alternativo=_numero(ols.f_stat), fmt=FMT_NUM,
        comentario="F = (R2/1) / ((1-R2)/(n-2)).",
    )
    fila += 1

    hoja.texto(fila, 1, "p-value de F")
    hoja.formula(fila, 2, f'=IFERROR(FDIST(B{fila_f},1,{max(n-2,1)}),"{ND}")',
                 alternativo=_numero(ols.f_pvalue), fmt=FMT_NUM,
                 comentario="p-value de F = FDIST(F; 1; n-2) (funcion compatible de Excel).")
    fila += 1

    hoja.texto(fila, 1, "Durbin-Watson")
    hoja.formula(
        fila, 2,
        f'=IFERROR(SUMPRODUCT((E{fila_datos+1}:E{fila_ult}-E{fila_datos}:E{fila_ult-1})^2)/SUMSQ(E{fila_datos}:E{fila_ult}),"{ND}")',
        alternativo=_numero(ols.durbin_watson), fmt=FMT_NUM,
        comentario="DW = suma de diferencias al cuadrado de los residuos / SUMSQ(residuos).",
    )
    fila += 1

    fila_jb = fila
    hoja.texto(fila, 1, "Jarque-Bera (normalidad)")
    hoja.formula(
        fila, 2,
        f'=IFERROR({n}/6*((SKEW(E{fila_datos}:E{fila_ult})*({n}-2)/SQRT({n}*({n}-1)))^2'
        f'+((KURT(E{fila_datos}:E{fila_ult})*({n}-2)*({n}-3)/({n}-1)-6)/({n}+1))^2/4),"{ND}")',
        alternativo=_numero(ols.jarque_bera), fmt=FMT_NUM,
        comentario="Jarque-Bera = n/6 x (sesgo^2 + curtosis^2/4), con SKEW y KURT convertidos a momentos poblacionales.",
    )
    hoja.texto(fila, 3, "SKEW y KURT de Excel convertidos a momentos poblacionales", wrap=True)
    fila += 1

    hoja.texto(fila, 1, "p-value Jarque-Bera")
    hoja.formula(fila, 2, f'=IFERROR(CHIDIST(B{fila_jb},2),"{ND}")', alternativo=_numero(ols.jarque_bera_p),
                 fmt=FMT_NUM, comentario="p-value = CHIDIST(JB; 2) (funcion compatible de Excel).")
    fila += 1

    fila_bp = fila
    hoja.texto(fila, 1, "Breusch-Pagan (LM)")
    hoja.formula(
        fila, 2, f'=IFERROR({n}*RSQ(F{fila_datos}:F{fila_ult},B{fila_datos}:B{fila_ult}),"{ND}")',
        alternativo=_numero(ols.breusch_pagan), fmt=FMT_NUM,
        comentario="LM = n x RSQ(residuo^2; periodo): regresion auxiliar de heterocedasticidad.",
    )
    fila += 1

    hoja.texto(fila, 1, "p-value Breusch-Pagan")
    hoja.formula(fila, 2, f'=IFERROR(CHIDIST(B{fila_bp},1),"{ND}")', alternativo=_numero(ols.breusch_pagan_p),
                 fmt=FMT_NUM, comentario="p-value = CHIDIST(LM; 1).")
    fila += 1

    meses = int(ols.meses_pronostico or 12)
    fila_pron = fila
    hoja.texto(fila, 1, f"Pronostico de precio a {meses} meses", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_r_int}+B{fila_r_pen}*({n}+{meses}),"{ND}")',
        alternativo=_numero(ols.pronostico_precio), fmt=FMT_PRECIO,
        comentario="Pronostico = intercepto + pendiente x (n + meses de horizonte).",
    )
    hoja.texto(fila, 3, f"Python: {_numero(ols.pronostico_precio) if _numero(ols.pronostico_precio) is not None else ND}", wrap=True)
    fila += 1

    fila_ic_inf = fila
    hoja.texto(fila, 1, "IC 95% inferior (prediccion individual)")
    hoja.formula(
        fila, 2,
        f'=IFERROR(B{fila_pron}-TINV(0.05,{max(n-2,1)})*B{fila_se_reg}*SQRT(1+1/{n}+'
        f'(({n}+{meses})-AVERAGE(B{fila_datos}:B{fila_ult}))^2/DEVSQ(B{fila_datos}:B{fila_ult})),"{ND}")',
        alternativo=_numero(ols.pronostico_li), fmt=FMT_PRECIO,
        comentario="Limite inferior del intervalo de prediccion individual al 95%.",
    )
    fila += 1

    hoja.texto(fila, 1, "IC 95% superior (prediccion individual)")
    hoja.formula(
        fila, 2,
        f'=IFERROR(B{fila_pron}+TINV(0.05,{max(n-2,1)})*B{fila_se_reg}*SQRT(1+1/{n}+'
        f'(({n}+{meses})-AVERAGE(B{fila_datos}:B{fila_ult}))^2/DEVSQ(B{fila_datos}:B{fila_ult})),"{ND}")',
        alternativo=_numero(ols.pronostico_ls), fmt=FMT_PRECIO,
        comentario="Limite superior del intervalo de prediccion individual al 95%.",
    )
    fila += 1

    trg = _numero(r.trg_valor)
    fila_trg = fila
    hoja.texto(fila, 1, "TRG (tasa de crecimiento, dato de entrada)")
    hoja.entrada(fila, 2, trg, fmt=FMT_PCT, comentario="Tasa de crecimiento usada en la proyeccion (entrada)")
    fila += 1

    ref_spot = capm.get("spot") or ""
    ref_tlr = capm.get("tlr") or ""
    fila_trg_proy = fila
    hoja.texto(fila, 1, "Proyeccion TRG a 12 meses = Spot x (1 + TRG)^12")
    hoja.formula(
        fila, 2,
        f'=IFERROR({ref_spot}*(1+B{fila_trg})^12,"{ND}")' if ref_spot else None,
        alternativo=_numero(r.precio_proyectado_trg), fmt=FMT_PRECIO,
        comentario="Proyeccion TRG = Spot (hoja CAPM) x (1 + TRG)^12.",
    )
    fila += 1

    fila_trg_umbral = fila
    hoja.texto(fila, 1, "Umbral = Spot x (1 + TLR + 1%)")
    hoja.formula(
        fila, 2,
        f'=IFERROR({ref_spot}*(1+{ref_tlr}+0.01),"{ND}")' if (ref_spot and ref_tlr) else None,
        alternativo=(
            _numero(r.spot) * (1 + _numero(r.tlr) + 0.01)
            if (_numero(r.spot) is not None and _numero(r.tlr) is not None)
            else None
        ),
        fmt=FMT_PRECIO, comentario="Umbral = Spot x (1 + TLR + 1 punto porcentual); sirve de referencia al criterio 10.",
    )
    fila += 1

    fila_veredicto = fila
    hoja.texto(fila, 1, "Veredicto de fiabilidad", negrita=True)
    relleno = FILL_OK if ols.veredicto == "Alta" else (FILL_AVISO if ols.veredicto == "Media" else FILL_NO)
    hoja.entrada(fila, 2, ols.veredicto or ND, fill=relleno, comentario="Veredicto calculado en Python a partir del diagnostico")
    fila += 1

    hoja.texto(fila, 1, "Justificacion")
    hoja.nota(fila, ols.justificacion or ND, 2, 9)
    fila += 2

    refs.update(
        {
            "r2": _ref(hoja.nombre, 2, fila_r2),
            "veredicto": _ref(hoja.nombre, 2, fila_veredicto),
            "pronostico": _ref(hoja.nombre, 2, fila_pron),
            "ic_inferior": _ref(hoja.nombre, 2, fila_ic_inf),
            "proyeccion_trg": _ref(hoja.nombre, 2, fila_trg_proy),
            "umbral_trg": _ref(hoja.nombre, 2, fila_trg_umbral),
            "hoja": hoja.nombre,
        }
    )
    return refs, fila


# ==========================================================================
# Hoja Griegas
# ==========================================================================


def _escribir_griegas(hoja: _Hoja, r: ResultadoAnalisis, fila: int) -> Tuple[Dict[str, Any], int]:
    """Escribe el bloque de Black-Scholes-Merton y sus griegas con formulas.

    Returns:
        ``(referencias, siguiente_fila)`` con las celdas de S, K, T, r, q, b,
        sigma, forward, primas y delta.
    """
    refs: Dict[str, Any] = {}
    spot = _numero(r.spot)
    strike = _numero(r.strike)
    vencimiento = r.vencimiento
    T = _numero(r.T)
    if T is None and vencimiento is not None:
        T = max((vencimiento - date.today()).days, 0) / 365.0
    tasa = _numero(r.tlr)
    q = _numero(r.q)
    sigma = _numero(r.riesgo.sigma_anual) or _numero(r.params.sigma)
    b_py = _numero(r.b)
    if b_py is None and tasa is not None and q is not None:
        b_py = tasa - q

    hoja.titulo(fila, f"{r.ticker} - Griegas Black-Scholes-Merton generalizado (b = r - q)", 1, 9)
    fila += 1
    hoja.nota(
        fila,
        "Formulas con el factor e^((b-r)T). Las celdas azules son entradas; las celdas con comentario son formulas "
        "auditables. N(d) se calcula con NORM.S.DIST(x; VERDADERO) (Excel 2010+); openpyxl escribe el prefijo "
        "interno _xlfn. que Excel/LibreOffice ocultan.",
        1, 9,
    )
    fila += 1
    hoja.cabecera(fila, ["Parametro", "Valor", "Formula / nota", "Valor Python (contraste)"])
    fila += 1

    fila_s = fila
    hoja.texto(fila, 1, "Spot (S)", negrita=True)
    hoja.entrada(fila, 2, spot, fmt=FMT_PRECIO, comentario="Precio del subyacente (entrada)")
    fila += 1

    fila_venc = fila
    hoja.texto(fila, 1, "Fecha de vencimiento")
    hoja.entrada(fila, 2, vencimiento if vencimiento is not None else ND, fmt=FMT_FECHA)
    fila += 1

    fila_fecha_spot = fila
    hoja.texto(fila, 1, "Fecha de valoracion")
    hoja.entrada(fila, 2, date.today(), fmt=FMT_FECHA)
    fila += 1

    fila_t = fila
    hoja.texto(fila, 1, "Time to maturity T (años)", negrita=True)
    if vencimiento is not None:
        hoja.formula(
            fila, 2, f'=IFERROR((B{fila_venc}-B{fila_fecha_spot})/365,"{ND}")', alternativo=T,
            fmt=FMT_NUM, comentario="T = (fecha de vencimiento - fecha de valoracion) / 365 dias.",
        )
    else:
        hoja.formula(fila, 2, None, alternativo=T, fmt=FMT_NUM,
                     comentario="T en años tomado del resultado (no hay fecha de vencimiento).")
    fila += 1

    fila_r = fila
    hoja.texto(fila, 1, "Tasa libre de riesgo r (anual, continua)", negrita=True)
    hoja.entrada(fila, 2, tasa, fmt=FMT_PCT, comentario="TLR anual usada como tipo continuo (entrada)")
    fila += 1

    fila_q = fila
    hoja.texto(fila, 1, "Dividend yield q", negrita=True)
    hoja.entrada(fila, 2, q, fmt=FMT_PCT, comentario="Rentabilidad por dividendo anual (entrada)")
    fila += 1

    fila_b = fila
    hoja.texto(fila, 1, "Costo de mantener b = r - q", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_r}-B{fila_q},"{ND}")', alternativo=b_py, fmt=FMT_PCT,
        comentario="b = r - q (coste de mantenimiento del modelo generalizado).",
    )
    fila += 1

    fila_sigma = fila
    hoja.texto(fila, 1, "Volatilidad sigma (anual)", negrita=True)
    hoja.entrada(fila, 2, sigma, fmt=FMT_PCT,
                 comentario=r.riesgo.nota_sigma or "Desviacion estandar anualizada de los rendimientos (entrada)")
    fila += 1

    fila_forward = fila
    hoja.texto(fila, 1, "Forward = S x e^(bT)", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(B{fila_s}*EXP(B{fila_b}*B{fila_t}),"{ND}")',
        alternativo=(spot * math.exp(b_py * T) if None not in (spot, b_py, T) else None),
        fmt=FMT_PRECIO, comentario="Forward = Spot x EXP(b x T).",
    )
    fila += 1

    fila_k = fila
    hoja.texto(fila, 1, "Strike (K)", negrita=True)
    if strike is not None:
        hoja.entrada(fila, 2, strike, fmt=FMT_PRECIO, comentario="Strike (entrada)")
    else:
        hoja.formula(fila, 2, f'=IFERROR(B{fila_forward},"{ND}")', alternativo=None, fmt=FMT_PRECIO,
                     comentario="Sin strike explicito: K = Forward (valor por defecto).")
    fila += 2

    hoja.cabecera(
        fila,
        ["Griega", "Call (formula)", "Put (formula)", "Formula usada", "Call (Python)", "Put (Python)", "Dif. call"],
    )
    fila += 1

    g_call = r.griegas_call or {}
    g_put = r.griegas_put or {}
    if not g_call and not g_put:
        strike_efectivo = strike if strike is not None else (
            spot * math.exp(b_py * T) if None not in (spot, b_py, T) else None
        )
        calculadas = _python_bsm(spot, strike_efectivo, T, tasa, q, sigma, b_py)
        if calculadas is not None:
            g_call, g_put = dict(calculadas[0]), dict(calculadas[1])
            LOG.debug("%s: griegas calculadas con dml.models.blackscholes (call y put)", r.ticker)
    aliases_precio = ("precio", "prima", "valor", "call", "precio_call", "precio_bsm", "bsm")
    aliases: Dict[str, Tuple[str, ...]] = {
        "d1": ("d1",),
        "d2": ("d2",),
        "nd1": ("n_d1", "nd1", "n(d1)"),
        "nd2": ("n_d2", "nd2", "n(d2)"),
        "prima": aliases_precio,
        "delta": ("delta", "delta_call"),
        "gamma": ("gamma",),
        "vega": ("vega",),
        "theta": ("theta",),
        "rho": ("rho",),
        "elasticidad": ("elasticidad", "lambda"),
        "vanna": ("vanna",),
        "vomma": ("vomma", "volga"),
    }
    py_call = {clave: _primero(g_call, nombres) for clave, nombres in aliases.items()}
    py_put = {clave: _primero(g_put, nombres) for clave, nombres in aliases.items()}
    py_call["prima"] = _primero(g_call, aliases_precio)
    py_put["prima"] = _primero(g_put, aliases_precio)

    #: Orden de las filas de griegas y factor aplicado al valor Python de
    #: contraste (la vega por 1 p.p. es vega/100 y la theta diaria theta/365).
    contraste: List[Tuple[str, float]] = [
        ("d1", 1.0), ("d2", 1.0), ("nd1", 1.0), ("prima", 1.0), ("delta", 1.0), ("gamma", 1.0),
        ("vega", 1.0), ("vega", 0.01), ("theta", 1.0), ("theta", 1.0 / 365.0), ("rho", 1.0),
        ("rho", 0.01), ("elasticidad", 1.0), ("vanna", 1.0), ("vomma", 1.0),
    ]

    exponente = f"EXP((B{fila_b}-B{fila_r})*B{fila_t})"

    fila_d1 = fila
    hoja.texto(fila, 1, "d1", negrita=True)
    hoja.formula(
        fila, 2,
        f'=IFERROR((LN(B{fila_s}/B{fila_k})+(B{fila_b}+B{fila_sigma}^2/2)*B{fila_t})/'
        f'(B{fila_sigma}*SQRT(B{fila_t})),"{ND}")',
        alternativo=py_call["d1"], fmt=FMT_NUM,
        comentario="d1 = [LN(S/K) + (b + sigma^2/2) x T] / (sigma x SQRT(T)).",
    )
    hoja.formula(fila, 3, f'=IFERROR(B{fila_d1},"{ND}")', alternativo=py_put["d1"], fmt=FMT_NUM,
                 comentario="d1 es identico para la call y la put.")
    fila += 1

    fila_d2 = fila
    hoja.texto(fila, 1, "d2", negrita=True)
    hoja.formula(fila, 2, f'=IFERROR(B{fila_d1}-B{fila_sigma}*SQRT(B{fila_t}),"{ND}")',
                 alternativo=py_call["d2"], fmt=FMT_NUM, comentario="d2 = d1 - sigma x SQRT(T).")
    hoja.formula(fila, 3, f'=IFERROR(B{fila_d2},"{ND}")', alternativo=py_put["d2"], fmt=FMT_NUM,
                 comentario="d2 es identico para la call y la put.")
    fila += 1

    fila_nd1 = fila
    hoja.texto(fila, 1, "N(d1) / N(d2)", negrita=True)
    hoja.formula(fila, 2, f'=IFERROR(NORM.S.DIST(B{fila_d1},TRUE),"{ND}")', alternativo=py_call["nd1"],
                 fmt=FMT_NUM, comentario="N(d1) = NORM.S.DIST(d1; VERDADERO): funcion normal estandar acumulada.")
    hoja.formula(fila, 3, f'=IFERROR(NORM.S.DIST(B{fila_d2},TRUE),"{ND}")', alternativo=py_put["nd2"],
                 fmt=FMT_NUM, comentario="N(d2) = NORM.S.DIST(d2; VERDADERO).")
    fila += 1

    fila_prima = fila
    hoja.texto(fila, 1, "Prima (V)", negrita=True)
    hoja.formula(
        fila, 2,
        f'=IFERROR(B{fila_s}*{exponente}*NORM.S.DIST(B{fila_d1},TRUE)'
        f'-B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(B{fila_d2},TRUE),"{ND}")',
        alternativo=py_call["prima"], fmt=FMT_PRECIO,
        comentario="Call = S x e^((b-r)T) x N(d1) - K x e^(-rT) x N(d2).",
    )
    hoja.formula(
        fila, 3,
        f'=IFERROR(B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(-B{fila_d2},TRUE)'
        f'-B{fila_s}*{exponente}*NORM.S.DIST(-B{fila_d1},TRUE),"{ND}")',
        alternativo=py_put["prima"], fmt=FMT_PRECIO,
        comentario="Put = K x e^(-rT) x N(-d2) - S x e^((b-r)T) x N(-d1).",
    )
    fila += 1

    fila_delta = fila
    hoja.texto(fila, 1, "Delta", negrita=True)
    hoja.formula(fila, 2, f'=IFERROR({exponente}*NORM.S.DIST(B{fila_d1},TRUE),"{ND}")', alternativo=py_call["delta"],
                 fmt=FMT_NUM, comentario="Delta call = e^((b-r)T) x N(d1).")
    hoja.formula(fila, 3, f'=IFERROR(-{exponente}*NORM.S.DIST(-B{fila_d1},TRUE),"{ND}")', alternativo=py_put["delta"],
                 fmt=FMT_NUM, comentario="Delta put = -e^((b-r)T) x N(-d1).")
    fila += 1

    hoja.texto(fila, 1, "Gamma", negrita=True)
    gamma = (f'=IFERROR({exponente}*EXP(-0.5*B{fila_d1}^2)/SQRT(2*PI())'
             f'/(B{fila_s}*B{fila_sigma}*SQRT(B{fila_t})),"{ND}")')
    hoja.formula(fila, 2, gamma, alternativo=py_call["gamma"], fmt=FMT_NUM,
                 comentario="Gamma = e^((b-r)T) x phi(d1) / (S x sigma x SQRT(T)); phi es la densidad normal estandar.")
    hoja.formula(fila, 3, gamma, alternativo=py_put["gamma"], fmt=FMT_NUM,
                 comentario="Gamma es identica para la call y la put.")
    fila += 1

    fila_vega = fila
    hoja.texto(fila, 1, "Vega (por 1.00 de sigma)", negrita=True)
    vega = (f'=IFERROR(B{fila_s}*{exponente}*EXP(-0.5*B{fila_d1}^2)/SQRT(2*PI())'
            f'*SQRT(B{fila_t}),"{ND}")')
    hoja.formula(fila, 2, vega, alternativo=py_call["vega"], fmt=FMT_NUM,
                 comentario="Vega = S x e^((b-r)T) x phi(d1) x SQRT(T).")
    hoja.formula(fila, 3, vega, alternativo=py_put["vega"], fmt=FMT_NUM, comentario="Vega es identica en call y put.")
    fila += 1

    hoja.texto(fila, 1, "Vega (por 1 p.p.)")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_vega}/100,"{ND}")',
                 alternativo=(py_call["vega"] / 100.0 if _numero(py_call["vega"]) is not None else None),
                 fmt=FMT_NUM, comentario="Vega por 1 punto porcentual = Vega / 100.")
    hoja.formula(fila, 3, f'=IFERROR(C{fila_vega}/100,"{ND}")',
                 alternativo=(py_put["vega"] / 100.0 if _numero(py_put["vega"]) is not None else None),
                 fmt=FMT_NUM, comentario="Vega por 1 punto porcentual = Vega / 100.")
    fila += 1

    fila_theta = fila
    hoja.texto(fila, 1, "Theta (anual)", negrita=True)
    comun = f'B{fila_s}*{exponente}*EXP(-0.5*B{fila_d1}^2)/SQRT(2*PI())'
    hoja.formula(
        fila, 2,
        f'=IFERROR(-{comun}*B{fila_sigma}/(2*SQRT(B{fila_t}))'
        f'-(B{fila_b}-B{fila_r})*B{fila_s}*{exponente}*NORM.S.DIST(B{fila_d1},TRUE)'
        f'-B{fila_r}*B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(B{fila_d2},TRUE),"{ND}")',
        alternativo=py_call["theta"], fmt=FMT_NUM,
        comentario="Theta call (anual) = -S x e^((b-r)T) x phi(d1) x sigma/(2 x SQRT(T)) - (b-r) x S x e^((b-r)T) "
                   "x N(d1) - r x K x e^(-rT) x N(d2).",
    )
    hoja.formula(
        fila, 3,
        f'=IFERROR(-{comun}*B{fila_sigma}/(2*SQRT(B{fila_t}))'
        f'+(B{fila_b}-B{fila_r})*B{fila_s}*{exponente}*NORM.S.DIST(-B{fila_d1},TRUE)'
        f'+B{fila_r}*B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(-B{fila_d2},TRUE),"{ND}")',
        alternativo=py_put["theta"], fmt=FMT_NUM,
        comentario="Theta put (anual) = -S x e^((b-r)T) x phi(d1) x sigma/(2 x SQRT(T)) + (b-r) x S x e^((b-r)T) "
                   "x N(-d1) + r x K x e^(-rT) x N(-d2).",
    )
    fila += 1

    hoja.texto(fila, 1, "Theta (diaria)")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_theta}/365,"{ND}")',
                 alternativo=(_numero(py_call["theta"]) / 365.0 if _numero(py_call["theta"]) is not None else None),
                 fmt=FMT_NUM, comentario="Theta diaria = Theta anual / 365.")
    hoja.formula(fila, 3, f'=IFERROR(C{fila_theta}/365,"{ND}")',
                 alternativo=(_numero(py_put["theta"]) / 365.0 if _numero(py_put["theta"]) is not None else None),
                 fmt=FMT_NUM, comentario="Theta diaria = Theta anual / 365.")
    fila += 1

    fila_rho = fila
    hoja.texto(fila, 1, "Rho (por 1.00 de r)", negrita=True)
    hoja.formula(fila, 2, f'=IFERROR(B{fila_t}*B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(B{fila_d2},TRUE),"{ND}")',
                 alternativo=py_call["rho"], fmt=FMT_NUM, comentario="Rho call = T x K x e^(-rT) x N(d2).")
    hoja.formula(fila, 3, f'=IFERROR(-B{fila_t}*B{fila_k}*EXP(-B{fila_r}*B{fila_t})*NORM.S.DIST(-B{fila_d2},TRUE),"{ND}")',
                 alternativo=py_put["rho"], fmt=FMT_NUM, comentario="Rho put = -T x K x e^(-rT) x N(-d2).")
    fila += 1

    hoja.texto(fila, 1, "Rho (por 1 p.p.)")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_rho}/100,"{ND}")',
                 alternativo=(_numero(py_call["rho"]) / 100.0 if _numero(py_call["rho"]) is not None else None),
                 fmt=FMT_NUM, comentario="Rho por 1 punto porcentual = Rho / 100.")
    hoja.formula(fila, 3, f'=IFERROR(C{fila_rho}/100,"{ND}")',
                 alternativo=(_numero(py_put["rho"]) / 100.0 if _numero(py_put["rho"]) is not None else None),
                 fmt=FMT_NUM, comentario="Rho por 1 punto porcentual = Rho / 100.")
    fila += 1

    hoja.texto(fila, 1, "Elasticidad (lambda)")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_delta}*B{fila_s}/B{fila_prima},"{ND}")',
                 alternativo=py_call["elasticidad"], fmt=FMT_NUM,
                 comentario="Elasticidad = Delta x S / Prima (apalancamiento de la opcion).")
    hoja.formula(fila, 3, f'=IFERROR(C{fila_delta}*B{fila_s}/C{fila_prima},"{ND}")',
                 alternativo=py_put["elasticidad"], fmt=FMT_NUM,
                 comentario="Elasticidad = Delta x S / Prima (apalancamiento de la opcion).")
    fila += 1

    hoja.texto(fila, 1, "Vanna")
    vanna = f'=IFERROR(B{fila_vega}/B{fila_s}*(1-B{fila_d1}/(B{fila_sigma}*SQRT(B{fila_t}))),"{ND}")'
    hoja.formula(fila, 2, vanna, alternativo=py_call["vanna"], fmt=FMT_NUM,
                 comentario="Vanna = Vega/S x (1 - d1/(sigma x SQRT(T))).")
    hoja.formula(fila, 3, vanna, alternativo=py_put["vanna"], fmt=FMT_NUM, comentario="Vanna es identica en call y put.")
    fila += 1

    hoja.texto(fila, 1, "Vomma (volga)")
    vomma = f'=IFERROR(B{fila_vega}*B{fila_d1}*B{fila_d2}/B{fila_sigma},"{ND}")'
    hoja.formula(fila, 2, vomma, alternativo=py_call["vomma"], fmt=FMT_NUM,
                 comentario="Vomma = Vega x d1 x d2 / sigma.")
    hoja.formula(fila, 3, vomma, alternativo=py_put["vomma"], fmt=FMT_NUM, comentario="Vomma es identica en call y put.")
    fila += 1

    for i in range(0, len(contraste)):
        f = fila_d1 + i
        if f >= fila:
            break
        clave, factor = contraste[i]
        formato = hoja.ws.cell(row=f, column=2).number_format
        hoja.valor(f, 5, (lambda v: v * factor if v is not None else None)(_numero(py_call.get(clave))), fmt=formato)
        hoja.valor(f, 6, (lambda v: v * factor if v is not None else None)(_numero(py_put.get(clave))), fmt=formato)
        hoja.formula(
            f, 7, f'=IFERROR(B{f}-E{f},"{ND}")', alternativo=None, fmt=FMT_CIENTIFICO,
            comentario="Diferencia entre la formula de Excel y el valor calculado en Python (control de calidad).",
        )
    fila += 1

    fila_paridad = fila
    hoja.texto(fila, 1, "Paridad put-call: C - P debe igualar S x e^((b-r)T) - K x e^(-rT)", negrita=True)
    fila += 1
    fila_cp = fila
    hoja.texto(fila, 1, "C - P")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_prima}-C{fila_prima},"{ND}")', alternativo=(
        _numero(py_call["prima"]) - _numero(py_put["prima"])
        if _numero(py_call["prima"]) is not None and _numero(py_put["prima"]) is not None else None
    ), fmt=FMT_PRECIO, comentario="Diferencia entre la prima de la call y la de la put.")
    fila += 1
    hoja.texto(fila, 1, "S x e^((b-r)T) - K x e^(-rT)")
    hoja.formula(
        fila, 2,
        f'=IFERROR(B{fila_s}*{exponente}-B{fila_k}*EXP(-B{fila_r}*B{fila_t}),"{ND}")',
        alternativo=(_numero(r.paridad.get("diferencia")) if isinstance(r.paridad, dict) else None),
        fmt=FMT_PRECIO, comentario="Valor teorico de la paridad put-call en el modelo generalizado.",
    )
    fila += 1
    fila_dif_paridad = fila
    hoja.texto(fila, 1, "Diferencia (C-P) - (S e^((b-r)T) - K e^(-rT))")
    hoja.formula(fila, 2, f'=IFERROR(B{fila_cp}-B{fila-1},"{ND}")', alternativo=None, fmt=FMT_CIENTIFICO,
                 comentario="Debe ser cero si la paridad se cumple.")
    fila += 1
    hoja.texto(fila, 1, "¿Paridad OK?", negrita=True)
    hoja.formula(
        fila, 2, f'=IFERROR(IF(ABS(B{fila_dif_paridad})<=0.000001,"OK","REVISAR"),"{ND}")', alternativo=None,
        comentario="Comprueba que la diferencia de paridad es practicamente cero (N/D si falta algun dato).",
    )
    fila += 2

    refs.update(
        {
            "S": _ref(hoja.nombre, 2, fila_s),
            "K": _ref(hoja.nombre, 2, fila_k),
            "T": _ref(hoja.nombre, 2, fila_t),
            "r": _ref(hoja.nombre, 2, fila_r),
            "q": _ref(hoja.nombre, 2, fila_q),
            "b": _ref(hoja.nombre, 2, fila_b),
            "sigma": _ref(hoja.nombre, 2, fila_sigma),
            "forward": _ref(hoja.nombre, 2, fila_forward),
            "prima_call": _ref(hoja.nombre, 2, fila_prima),
            "prima_put": _ref(hoja.nombre, 3, fila_prima),
            "delta_call": _ref(hoja.nombre, 2, fila_delta),
            "delta_put": _ref(hoja.nombre, 3, fila_delta),
            "gamma_call": _ref(hoja.nombre, 2, fila_delta + 1),
            "paridad_dif": _ref(hoja.nombre, 2, fila_dif_paridad),
            "hoja": hoja.nombre,
        }
    )
    return refs, fila


# ==========================================================================
# Hojas de fundamentales (una fila por ticker)
# ==========================================================================


def _escribir_per(hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], fila: int) -> Dict[str, Dict[str, str]]:
    """Hoja ``PER``: una fila por ticker con ``PER = Precio / EPS`` como formula."""
    hoja.titulo(fila, "PER - precio / beneficio por accion (una fila por ticker)", 1, 7)
    fila += 1
    cabecera = fila
    hoja.cabecera(
        fila,
        ["Ticker", "Precio (spot)", "EPS", "PER = Precio / EPS", "PER del sector", "¿PER < sector?", "Nota"],
    )
    fila += 1
    primera = fila
    refs: Dict[str, Dict[str, str]] = {}
    for r in resultados:
        f = fila
        fund = r.fundamentales
        precio = _numero(r.spot)
        eps = _numero(fund.eps)
        per_py = _numero(fund.per)
        if per_py is None and precio is not None and eps not in (None, 0):
            per_py = precio / eps
        hoja.entrada(f, 1, r.ticker)
        hoja.entrada(f, 2, precio, fmt=FMT_PRECIO, comentario="Spot usado en el calculo del PER (entrada)")
        hoja.entrada(f, 3, eps, fmt=FMT_PRECIO, comentario="Beneficio por accion (BPA/EPS) (entrada)")
        hoja.formula(f, 4, f'=IFERROR(B{f}/C{f},"{ND}")', alternativo=per_py, fmt=FMT_NUM2,
                     comentario="PER = Precio / EPS.")
        hoja.entrada(f, 5, _numero(fund.per_sector), fmt=FMT_NUM2, comentario="PER medio del sector (entrada)")
        hoja.formula(f, 6, _formula_cumple("menor", f), alternativo=("SI" if (per_py is not None and _numero(fund.per_sector) is not None and per_py < _numero(fund.per_sector)) else "NO"),
                     comentario="¿Cumple? = IF(PER < PER del sector; \"SI\"; \"NO\").")
        hoja.texto(f, 7, f"Sector: {fund.sector or ND}", wrap=True)
        refs[r.ticker] = {
            "per_valor": _ref(hoja.nombre, 4, f),
            "per_sector": _ref(hoja.nombre, 5, f),
            "eps": _ref(hoja.nombre, 3, f),
            "precio": _ref(hoja.nombre, 2, f),
        }
        fila += 1
    hoja.autofiltro(cabecera, 1, 7, fila - 1)
    hoja.congelar(f"A{primera}")
    hoja.colorear_semaforo(f"F{primera}:F{fila-1}")
    hoja.nota(fila + 1, "PER = Precio / EPS. Se compara con el PER medio del sector para el criterio 1 de la parrilla.", 1, 7)
    return refs


def _escribir_eps(hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], fila: int) -> Dict[str, Dict[str, str]]:
    """Hoja ``EPS``: beneficio por accion actual y previsto, con su crecimiento."""
    hoja.titulo(fila, "EPS - beneficio por accion (una fila por ticker)", 1, 7)
    fila += 1
    cabecera = fila
    hoja.cabecera(fila, ["Ticker", "EPS", "EPS previsto", "Crecimiento implicito", "¿EPS >= previsto?", "Nota"])
    fila += 1
    primera = fila
    refs: Dict[str, Dict[str, str]] = {}
    for r in resultados:
        f = fila
        fund = r.fundamentales
        eps = _numero(fund.eps)
        prev = _numero(fund.eps_forecast)
        crecimiento = (prev / eps - 1.0) if (eps not in (None, 0) and prev is not None) else None
        hoja.entrada(f, 1, r.ticker)
        hoja.entrada(f, 2, eps, fmt=FMT_PRECIO, comentario="EPS actual (entrada)")
        hoja.entrada(f, 3, prev, fmt=FMT_PRECIO, comentario="EPS previsto por el consenso (entrada)")
        hoja.formula(f, 4, f'=IFERROR(C{f}/B{f}-1,"{ND}")', alternativo=crecimiento, fmt=FMT_PCT,
                     comentario="Crecimiento implicito = EPS previsto / EPS - 1.")
        hoja.formula(f, 5, _formula_cumple("mayor_igual", f, 2, 3),
                     alternativo=("SI" if (eps is not None and prev is not None and eps >= prev) else "NO"),
                     comentario="¿Cumple? = IF(EPS >= EPS previsto; \"SI\"; \"NO\"): criterio 2 de la parrilla.")
        hoja.texto(f, 6, f"EPS publicado el {r.fecha_analisis or ND}", wrap=True)
        refs[r.ticker] = {
            "eps": _ref(hoja.nombre, 2, f),
            "eps_forecast": _ref(hoja.nombre, 3, f),
            "eps_crecimiento": _ref(hoja.nombre, 4, f),
        }
        fila += 1
    hoja.autofiltro(cabecera, 1, 6, fila - 1)
    hoja.congelar(f"A{primera}")
    hoja.colorear_semaforo(f"E{primera}:E{fila-1}")
    return refs


def _escribir_price_to_fcf(hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], fila: int) -> Dict[str, Dict[str, str]]:
    """Hoja ``Price to FCF``: capitalizacion / flujo de caja libre, con respaldo publicado."""
    hoja.titulo(fila, "Price to FCF - capitalizacion / flujo de caja libre (una fila por ticker)", 1, 8)
    fila += 1
    cabecera = fila
    hoja.cabecera(
        fila,
        ["Ticker", "Capitalizacion", "Free cash flow", "Price to FCF", "P/FCF del sector",
         "P/FCF publicado", "¿P/FCF < sector?", "Nota"],
    )
    fila += 1
    primera = fila
    refs: Dict[str, Dict[str, str]] = {}
    for r in resultados:
        f = fila
        fund = r.fundamentales
        cap = _numero(fund.market_cap)
        fcf = _numero(fund.free_cash_flow)
        sector = _numero(fund.p_fcf_sector)
        publicado = _numero(fund.p_fcf)
        calculado = (cap / fcf) if (cap is not None and fcf not in (None, 0)) else publicado
        hoja.entrada(f, 1, r.ticker)
        hoja.entrada(f, 2, cap, fmt=FMT_PRECIO, comentario="Capitalizacion bursatil (entrada)")
        hoja.entrada(f, 3, fcf, fmt=FMT_PRECIO, comentario="Free cash flow (entrada)")
        hoja.formula(f, 4, f'=IFERROR(B{f}/C{f},IF(ISNUMBER(F{f}),F{f},"{ND}"))', alternativo=calculado,
                     fmt=FMT_NUM2,
                     comentario="Price to FCF = Capitalizacion / Free cash flow. Si falta algun dato se usa el "
                                "multiplo publicado de la columna F.")
        hoja.entrada(f, 5, sector, fmt=FMT_NUM2, comentario="Price to FCF medio del sector (entrada)")
        hoja.entrada(f, 6, publicado, fmt=FMT_NUM2, comentario="Price to FCF publicado por la fuente (entrada)")
        hoja.formula(f, 7, _formula_cumple("menor", f, 4, 5),
                     alternativo=("SI" if (calculado is not None and sector is not None and calculado < sector) else "NO"),
                     comentario="¿Cumple? = IF(Price to FCF < sector; \"SI\"; \"NO\"): criterio 4 de la parrilla.")
        hoja.texto(f, 8, f"Sector: {fund.sector or ND}", wrap=True)
        refs[r.ticker] = {
            "pfcf": _ref(hoja.nombre, 4, f),
            "pfcf_sector": _ref(hoja.nombre, 5, f),
            "pfcf_publicado": _ref(hoja.nombre, 6, f),
        }
        fila += 1
    hoja.autofiltro(cabecera, 1, 8, fila - 1)
    hoja.congelar(f"A{primera}")
    hoja.colorear_semaforo(f"G{primera}:G{fila-1}")
    return refs


def _escribir_renta_per(
    hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], refs: Dict[str, Dict[str, Any]], fila: int
) -> Dict[str, Dict[str, str]]:
    """Hoja ``Renta PER``: ``1 / PER`` tomando el PER de la hoja ``PER``."""
    hoja.titulo(fila, "Renta PER - rentabilidad por beneficio, 1 / PER (una fila por ticker)", 1, 7)
    fila += 1
    cabecera = fila
    hoja.cabecera(fila, ["Ticker", "PER", "Renta PER = 1 / PER", "Renta PER del sector", "¿Renta PER > sector?", "Nota"])
    fila += 1
    primera = fila
    salida: Dict[str, Dict[str, str]] = {}
    for r in resultados:
        f = fila
        fund = r.fundamentales
        per_py = _numero(fund.per)
        precio = _numero(r.spot)
        eps = _numero(fund.eps)
        if per_py is None and precio is not None and eps not in (None, 0):
            per_py = precio / eps
        per_sector = _numero(fund.per_sector)
        renta = (1.0 / per_py) if per_py not in (None, 0) else None
        renta_sector = (1.0 / per_sector) if per_sector not in (None, 0) else None
        referencia_per = refs.get(r.ticker, {}).get("per_valor")
        hoja.entrada(f, 1, r.ticker)
        hoja.formula(f, 2, f'=IFERROR({referencia_per},"{ND}")' if referencia_per else None,
                     alternativo=per_py, fmt=FMT_NUM2,
                     comentario="PER tomado de la hoja PER (misma magnitud, sin recalcular).")
        hoja.formula(f, 3, f'=IFERROR(1/B{f},"{ND}")', alternativo=renta, fmt=FMT_PCT,
                     comentario="Renta PER = 1 / PER (rentabilidad por beneficio).")
        referencia_sector = refs.get(r.ticker, {}).get("per_sector")
        hoja.formula(f, 4, f'=IFERROR(1/{referencia_sector},"{ND}")' if referencia_sector else None,
                     alternativo=renta_sector, fmt=FMT_PCT,
                     comentario="Renta PER del sector = 1 / PER del sector (hoja PER).")
        hoja.formula(f, 5, _formula_cumple("mayor", f, 3, 4),
                     alternativo=("SI" if (renta is not None and renta_sector is not None and renta > renta_sector) else "NO"),
                     comentario="¿Cumple? = IF(Renta PER > Renta PER del sector; \"SI\"; \"NO\"): criterio 7.")
        hoja.texto(f, 6, "Renta PER = beneficio por accion / precio.", wrap=True)
        salida[r.ticker] = {
            "renta_per": _ref(hoja.nombre, 3, f),
            "renta_per_sector": _ref(hoja.nombre, 4, f),
            "per_valor": _ref(hoja.nombre, 2, f),
        }
        fila += 1
    hoja.autofiltro(cabecera, 1, 6, fila - 1)
    hoja.congelar(f"A{primera}")
    hoja.colorear_semaforo(f"E{primera}:E{fila-1}")
    return salida


def _escribir_rdr(
    hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], refs: Dict[str, Dict[str, Any]], fila: int
) -> Dict[str, Dict[str, str]]:
    """Hoja ``RDR``: relacion rendimiento-riesgo, ``RDR = Rend_CAPM / Riesgo``."""
    hoja.titulo(fila, "RDR - relacion rendimiento / riesgo (una fila por ticker)", 1, 12)
    fila += 1
    cabecera = fila
    hoja.cabecera(
        fila,
        ["Ticker", "Rend_CAPM", "TLR", "Riesgo (sigma anual)", "RDR = Rend / Riesgo", "¿Rend > Riesgo?",
         "Sharpe", "Treynor", "VaR 95% mensual", "VaR 99% mensual", "Max drawdown", "Señal MACD"],
    )
    fila += 1
    primera = fila
    salida: Dict[str, Dict[str, str]] = {}
    for r in resultados:
        f = fila
        riesgo = r.riesgo
        # El RDR se calcula contra la DESVIACION TIPICA ANUAL, que es la misma
        # magnitud que evalua el criterio 8 de la parrilla. Antes se usaba
        # ``riesgo_total``, que es una VARIANZA mensual: como es un numero pequeno
        # pero siempre positivo, el ``or`` nunca caia al valor correcto y la hoja
        # comparaba el rendimiento con la varianza (el libro y la interfaz no
        # coincidian).
        sigma = _numero(riesgo.sigma_anual)
        rend_py = _numero(r.rend_capm)
        tlr_py = _numero(r.tlr)
        rdr_py = (rend_py / sigma) if (rend_py is not None and sigma not in (None, 0)) else None
        ref_rend = refs.get(r.ticker, {}).get("rend_capm")
        ref_tlr = refs.get(r.ticker, {}).get("tlr")
        ref_beta = refs.get(r.ticker, {}).get("beta_cov")
        hoja.entrada(f, 1, r.ticker)
        hoja.formula(f, 2, f'=IFERROR({ref_rend},"{ND}")' if ref_rend else None, alternativo=rend_py,
                     fmt=FMT_PCT, comentario="Rendimiento esperado del CAPM (hoja CAPM).")
        hoja.formula(f, 3, f'=IFERROR({ref_tlr},"{ND}")' if ref_tlr else None, alternativo=tlr_py,
                     fmt=FMT_PCT, comentario="Tasa libre de riesgo usada en el CAPM (hoja CAPM).")
        hoja.entrada(f, 4, sigma, fmt=FMT_PCT, comentario="Riesgo total: desviacion estandar anualizada (entrada)")
        hoja.formula(f, 5, f'=IFERROR(B{f}/D{f},"{ND}")', alternativo=rdr_py, fmt=FMT_NUM,
                     comentario="RDR = Rend_CAPM / Riesgo.")
        hoja.formula(f, 6, f'=IF(AND(ISNUMBER(B{f}),ISNUMBER(D{f})),IF(B{f}>D{f},"SI","NO"),"NO")',
                     alternativo=("SI" if (rend_py is not None and sigma is not None and rend_py > sigma) else "NO"),
                     comentario="¿Rendimiento > Riesgo? Compara el rendimiento esperado con la volatilidad.")
        hoja.entrada(f, 7, _numero(riesgo.sharpe), fmt=FMT_NUM, comentario="Ratio de Sharpe calculado en Python (entrada)")
        hoja.formula(f, 8, f'=IFERROR((B{f}-C{f})/{ref_beta},"{ND}")' if ref_beta else None,
                     alternativo=_numero(riesgo.treynor), fmt=FMT_NUM,
                     comentario="Treynor = (Rend_CAPM - TLR) / Beta.")
        hoja.entrada(f, 9, _numero(riesgo.var_95), fmt=FMT_PCT, comentario="VaR 95% mensual parametrico (entrada)")
        hoja.entrada(f, 10, _numero(riesgo.var_99), fmt=FMT_PCT, comentario="VaR 99% mensual parametrico (entrada)")
        hoja.entrada(f, 11, _numero(riesgo.max_drawdown), fmt=FMT_PCT, comentario="Maxima caida desde maximos (entrada)")
        hoja.entrada(f, 12, r.macd_senal or ND, comentario="Señal MACD de 1 mes (entrada)")
        salida[r.ticker] = {
            "riesgo": _ref(hoja.nombre, 4, f),
            "rend_capm": _ref(hoja.nombre, 2, f),
            "rdr": _ref(hoja.nombre, 5, f),
            "beta": _ref(hoja.nombre, 8, f),
        }
        fila += 1
    hoja.autofiltro(cabecera, 1, 12, fila - 1)
    hoja.congelar(f"A{primera}")
    hoja.colorear_semaforo(f"F{primera}:F{fila-1}")
    hoja.nota(fila + 1, "RDR = Rend_CAPM / Riesgo. Sharpe y Treynor se toman de las metricas calculadas en Python.", 1, 12)
    return salida


def _escribir_bonos(hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], fila: int) -> int:
    """Hoja ``Bonos y tasas``: tasas de referencia, metodos y series mensuales."""
    hoja.titulo(fila, "Bonos y tasas - tasas de referencia de EE.UU. y su procedencia", 1, 9)
    fila += 1
    cabecera = fila
    hoja.cabecera(
        fila,
        ["Ticker", "T-Bill 4 semanas", "UST 10 años", "UST 30 años", "TLR usada (r)",
         "Diferencia 10a - 4s (pb)", "Metodo T-Bill", "Metodo 10 años", "Metodo 30 años"],
    )
    fila += 1
    primera = fila
    for r in resultados:
        f = fila
        tasas: Tasas = r.tasas
        b4 = _numero(tasas.tbill_4w)
        u10 = _numero(tasas.ust_10y)
        u30 = _numero(tasas.ust_30y)
        hoja.entrada(f, 1, r.ticker)
        hoja.entrada(f, 2, b4, fmt=FMT_PCT, comentario="T-Bill a 4 semanas (entrada)")
        hoja.entrada(f, 3, u10, fmt=FMT_PCT, comentario="UST a 10 años (entrada)")
        hoja.entrada(f, 4, u30, fmt=FMT_PCT, comentario="UST a 30 años (entrada)")
        hoja.formula(f, 5, f'=IFERROR(B{f},"{ND}")', alternativo=_numero(r.tlr), fmt=FMT_PCT,
                     comentario="TLR usada en el CAPM: la T-Bill a 4 semanas.")
        hoja.formula(
            f, 6, f'=IFERROR((C{f}-B{f})*10000,"{ND}")',
            alternativo=(
                (_numero((tasas.diferencias_pb or {}).get("10y_4w")))
                if _numero((tasas.diferencias_pb or {}).get("10y_4w")) is not None
                else ((u10 - b4) * 10000 if (u10 is not None and b4 is not None) else None)
            ),
            fmt=FMT_PB, comentario="Diferencia de pendiente 10 años - 4 semanas, en puntos basicos.",
        )
        hoja.texto(f, 7, tasas.metodo_de("tbill_4w"))
        hoja.texto(f, 8, tasas.metodo_de("ust_10y"))
        hoja.texto(f, 9, tasas.metodo_de("ust_30y"))
        fila += 1
    hoja.autofiltro(cabecera, 1, 9, fila - 1)
    hoja.congelar(f"A{primera}")

    fila += 1
    series: List[Tuple[str, Optional[pd.Series], Optional[pd.Series], Optional[pd.Series]]] = []
    for r in resultados:
        series.append(
            (
                r.ticker,
                normalizar_mensual(r.tasas.serie_tbill_mensual),
                normalizar_mensual(r.tasas.serie_10y_mensual),
                normalizar_mensual(r.tasas.serie_30y_mensual),
            )
        )
    con_series = [s for s in series if any(x is not None and len(x) > 0 for x in s[1:])]
    if con_series:
        hoja.titulo(fila, "Series mensuales de tasas", 1, 5)
        fila += 1
        cab2 = fila
        hoja.cabecera(fila, ["Fecha", "T-Bill 4 semanas", "UST 10 años", "UST 30 años", "Ticker"])
        fila += 1
        primera2 = fila
        for ticker, s4, s10, s30 in con_series:
            fechas = sorted({*(list(s4.index) if s4 is not None else []),
                             *(list(s10.index) if s10 is not None else []),
                             *(list(s30.index) if s30 is not None else [])})
            for fecha in fechas:
                hoja.entrada(fila, 1, fecha.date() if hasattr(fecha, "date") else fecha, fmt=FMT_FECHA)
                for col, serie in ((2, s4), (3, s10), (4, s30)):
                    valor = _numero(serie.get(fecha)) if serie is not None and fecha in serie.index else None
                    hoja.entrada(fila, col, valor, fmt=FMT_PCT, comentario="Serie mensual de tasas (entrada)")
                hoja.texto(fila, 5, ticker)
            fila += 1
        hoja.autofiltro(cab2, 1, 5, fila - 1)
        hoja.congelar(f"A{primera2}")

    advertencias = [a for r in resultados for a in (r.tasas.advertencias or [])]
    if advertencias:
        hoja.nota(fila + 1, "Advertencias de tasas: " + " | ".join(dict.fromkeys(advertencias)), 1, 9)
        fila += 2
    return fila


def _escribir_fuentes(
    hoja: _Hoja, resultados: Sequence[ResultadoAnalisis], fuentes: Optional[Fuentes]
) -> int:
    """Hoja ``Fuentes y avisos``: procedencia de cada dato, faltantes y avisos.

    Combina ``Fuentes.como_dataframe()`` (o sus registros si el ``DataFrame`` no
    esta disponible), los datos clave calculados de cada ticker y las
    advertencias de cada :class:`ResultadoAnalisis`.

    Returns:
        La primera fila libre por debajo de la tabla.
    """
    hoja.titulo(1, "Fuentes y avisos - dato, valor, fuente, metodo, URL, consulta y advertencias", 1, 9)
    cabecera = 2
    hoja.cabecera(
        cabecera,
        ["Dato", "Valor", "Fuente", "Metodo", "URL", "Consultado", "Advertencia", "Categoria", "Ticker"],
    )
    fila = 3
    registros: List[Dict[str, Any]] = []
    if fuentes is not None:
        try:
            marco = fuentes.como_dataframe()
            if marco is not None and len(marco) > 0:
                registros = marco.to_dict("records")
        except Exception as exc:  # pragma: no cover - proteccion defensiva
            LOG.warning("Fuentes.como_dataframe() fallo (%s): se usan los registros directos", exc)
        if not registros:
            for item in getattr(fuentes, "items", []) or []:
                registros.append(
                    {
                        "Dato": getattr(item, "dato", ND),
                        "Valor": getattr(item, "valor", ND),
                        "Fuente": getattr(item, "fuente", "") or ND,
                        "Metodo": getattr(item, "metodo", "") or ND,
                        "URL": getattr(item, "url", ""),
                        "Consultado": getattr(item, "consultado", ""),
                        "Advertencia": getattr(item, "advertencia", ""),
                        "Categoria": getattr(item, "categoria", "general"),
                    }
                )
    for registro in registros:
        valores = [
            registro.get("Dato", ND),
            registro.get("Valor", ND),
            registro.get("Fuente", ND),
            registro.get("Metodo", ND),
            registro.get("URL", ""),
            registro.get("Consultado", ""),
            registro.get("Advertencia", ""),
            registro.get("Categoria", "general"),
            registro.get("Ticker", ""),
        ]
        for j, valor in enumerate(valores):
            hoja.entrada(fila, j + 1, _texto_nd(valor), wrap=j in (4, 6))
        fila += 1

    # Datos clave calculados de cada ticker (documentan el analisis aunque no
    # se haya pasado un registro de Fuentes).
    for r in resultados:
        fundamentales = r.fundamentales
        claves: List[Tuple[str, Any, str]] = [
            ("Spot", r.spot, "Entrada: ultimo cierre disponible"),
            ("TLR anual (T-Bill 4 semanas)", r.tlr, r.tasas.metodo_de("tbill_4w")),
            ("Beta (COVAR/VAR)", r.beta_cov, "Calculado a partir de los rendimientos mensuales"),
            ("PRH anualizado", r.prh, "Prima de riesgo del mercado anualizada"),
            ("Rend_CAPM", r.rend_capm, "CAPM = TLR + Beta x PRH"),
            ("Precio objetivo", r.precio_objetivo, "Spot x (1 + Rend_CAPM)"),
            ("PER", fundamentales.per, "Publicado por la fuente de fundamentales"),
            ("EPS", fundamentales.eps, "Publicado por la fuente de fundamentales"),
            ("Price to FCF", fundamentales.p_fcf, "Publicado por la fuente de fundamentales"),
            ("Riesgo total (desviacion tipica anual)", r.riesgo.sigma_anual, "sigma_mensual x sqrt(12)"),
            ("R2 del modelo MCO", (r.ols.r2 if r.ols is not None else None), "Regresion Precio ~ periodo"),
            ("Calificacion", r.calificacion, "Promedio de los criterios de la parrilla"),
        ]
        for dato, valor, metodo in claves:
            numero = _numero(valor)
            hoja.entrada(fila, 1, f"{r.ticker}: {dato}")
            hoja.entrada(fila, 2, numero if numero is not None else _texto_nd(valor), fmt=FMT_NUM if numero is not None else None)
            hoja.texto(fila, 3, "Analisis DML-FINANCE")
            hoja.texto(fila, 4, "calculo" if numero is not None else ND)
            hoja.texto(fila, 5, "")
            hoja.texto(fila, 6, r.fecha_analisis or ahora_iso())
            hoja.texto(fila, 7, "" if numero is not None else f"{dato} no disponible")
            hoja.texto(fila, 8, "derivado")
            hoja.texto(fila, 9, r.ticker)
            fila += 1
        for aviso in r.advertencias or []:
            hoja.entrada(fila, 1, f"{r.ticker}: advertencia")
            hoja.texto(fila, 2, ND)
            hoja.texto(fila, 3, "Analisis DML-FINANCE")
            hoja.texto(fila, 4, "calculo")
            hoja.texto(fila, 5, "")
            hoja.texto(fila, 6, r.fecha_analisis or ahora_iso())
            hoja.entrada(fila, 7, aviso, wrap=True)
            hoja.texto(fila, 8, "advertencia")
            hoja.texto(fila, 9, r.ticker)
            fila += 1
        if r.riesgo.nota_sigma:
            hoja.entrada(fila, 1, f"{r.ticker}: nota de volatilidad")
            hoja.texto(fila, 2, ND)
            hoja.texto(fila, 3, "Analisis DML-FINANCE")
            hoja.texto(fila, 4, "calculo")
            hoja.texto(fila, 6, r.fecha_analisis or ahora_iso())
            hoja.entrada(fila, 7, r.riesgo.nota_sigma, wrap=True)
            hoja.texto(fila, 8, "advertencia")
            hoja.texto(fila, 9, r.ticker)
            fila += 1

    hoja.autofiltro(cabecera, 1, 9, fila - 1)
    hoja.congelar("A3")
    return fila


# ==========================================================================
# Hoja Principal
# ==========================================================================


def _escribir_principal(
    hoja: _Hoja,
    resultados: Sequence[ResultadoAnalisis],
    referencias: Dict[str, Dict[str, Any]],
) -> int:
    """Hoja ``Principal``: tabla comparativa, resumen por accion y parrilla de decision.

    Args:
        hoja: hoja ``Principal``.
        resultados: resultados a exportar (uno o varios tickers).
        referencias: referencias a celdas del resto de hojas, por ticker.

    Returns:
        La primera fila libre por debajo del ultimo bloque escrito.
    """
    hoja.titulo(1, "DML FINANCE - PARRILLA DE DECISION DE INVERSION", 1, 12)
    hoja.nota(
        2,
        f"Generado el {ahora_iso()} | {len(resultados)} valor(es) | Las celdas azules son entradas y las celdas "
        "con comentario son formulas auditables.",
        1, 12,
    )
    hoja.cabecera(
        4,
        ["Ticker", "Nombre", "Calificacion", "Decision", "Spot", "Rend_CAPM", "Beta (COVAR/VAR)",
         "Precio objetivo", "Criterios que cumplen", "Modo"],
    )
    fila_comp_ini = 5
    fila = fila_comp_ini
    bloques: Dict[str, Dict[str, int]] = {}
    for r in resultados:
        f = fila
        ref = referencias.get(r.ticker, {})
        bloques[r.ticker] = {"fila_comp": f}
        comprar = float(getattr(r.params, "comprar_min", 0.70) or 0.70)
        mantener = float(getattr(r.params, "mantener_min", 0.40) or 0.40)
        hoja.entrada(f, 1, r.ticker)
        hoja.texto(f, 2, r.nombre or ND)
        # La calificacion y el recuento de criterios se reescriben como formula
        # cuando se conoce el bloque de la parrilla de este ticker (mas abajo).
        hoja.valor(f, 3, _numero(r.calificacion), fmt=FMT_NUM,
                   comentario="Calificacion = AVERAGE de la columna Calif. de la parrilla de este ticker.")
        hoja.formula(
            f, 4,
            f'=IF(ISNUMBER(C{f}),IF(C{f}>{comprar},"COMPRAR",IF(C{f}>={mantener},"MANTENER","NO INVERTIR")),"{ND}")',
            alternativo=r.decision or ND,
            comentario=f"Decision = IF(Calificacion > {comprar:.2f}; COMPRAR; IF(Calificacion >= {mantener:.2f}; "
                       "MANTENER; NO INVERTIR)).",
            fill=FILL_DECISION.get(r.decision, FILL_AVISO),
            negrita=True,
        )
        hoja.formula(f, 5, f'=IFERROR({ref.get("spot", "")},"{ND}")' if ref.get("spot") else None,
                     alternativo=_numero(r.spot), fmt=FMT_PRECIO, comentario="Spot de la hoja CAPM.")
        hoja.formula(f, 6, f'=IFERROR({ref.get("rend_capm", "")},"{ND}")' if ref.get("rend_capm") else None,
                     alternativo=_numero(r.rend_capm), fmt=FMT_PCT, comentario="Rend_CAPM = TLR + Beta x PRH (hoja CAPM).")
        hoja.formula(f, 7, f'=IFERROR({ref.get("beta_cov", "")},"{ND}")' if ref.get("beta_cov") else None,
                     alternativo=_numero(r.beta_cov), fmt=FMT_NUM, comentario="Beta = COVAR/VAR (hoja CAPM).")
        hoja.formula(f, 8, f'=IFERROR({ref.get("precio_objetivo", "")},"{ND}")' if ref.get("precio_objetivo") else None,
                     alternativo=_numero(r.precio_objetivo), fmt=FMT_PRECIO,
                     comentario="Precio objetivo = Spot x (1 + Rend_CAPM) (hoja CAPM).")
        hoja.valor(f, 9, sum(1 for c in r.criterios if c.activo and c.cumple), fmt=FMT_INT,
                   comentario=f"Criterios que cumplen segun Python: "
                              f"{sum(1 for c in r.criterios if c.activo and c.cumple)} de {len(r.criterios)}.")
        hoja.texto(f, 10, r.modo or ND)
        fila += 1
    hoja.autofiltro(4, 1, 10, fila - 1)
    hoja.congelar(f"A{fila_comp_ini}")
    fila += 2

    for r in resultados:
        ref = referencias.get(r.ticker, {})
        hoja.titulo(fila, f"ACCION: {r.ticker} - {r.nombre or ND} ({r.bolsa or ND}) | Sector: {r.sector or ND}", 1, 12)
        fila += 1
        resumen: List[Tuple[str, Any, str]] = [
            ("Spot (valor actual)", _numero(r.spot), FMT_PRECIO),
            ("Rend_CAPM", _numero(r.rend_capm), FMT_PCT),
            ("Beta (COVAR/VAR)", _numero(r.beta_cov), FMT_NUM),
            ("Precio objetivo CAPM", _numero(r.precio_objetivo), FMT_PRECIO),
            ("TLR anual", _numero(r.tlr), FMT_PCT),
            ("Riesgo (desviacion tipica anual)", _numero(r.riesgo.sigma_anual), FMT_PCT),
            ("PER", _numero(r.fundamentales.per), FMT_NUM2),
            ("EPS", _numero(r.fundamentales.eps), FMT_PRECIO),
            ("Calificacion (Python)", _numero(r.calificacion), FMT_NUM),
            ("Decision (Python)", r.decision or ND, None),
        ]
        for etiqueta, valor, fmt in resumen:
            hoja.texto(fila, 2, etiqueta)
            hoja.valor(fila, 3, valor, fmt=fmt)
            fila += 1
        fila += 1

        hoja.cabecera(
            fila,
            ["#", "Criterio", "Optimo", "Valor obtenido", "Comparacion", "¿Cumple?", "Calif.",
             "Fuente del dato", "Ruta / enlace", "Formula del criterio"],
        )
        fila += 1
        fila_pri = fila
        for criterio in r.criterios:
            fila = _escribir_criterio(hoja, criterio, r, ref, fila)
        fila_ult = fila - 1
        if fila_ult >= fila_pri:
            hoja.colorear_semaforo(f"F{fila_pri}:F{fila_ult}")

        comprar = float(getattr(r.params, "comprar_min", 0.70) or 0.70)
        mantener = float(getattr(r.params, "mantener_min", 0.40) or 0.40)
        hoja.texto(fila, 2, f"CALIFICACION PROMEDIO ({len(r.criterios)} criterios)", negrita=True)
        fila_calif = fila
        hoja.formula(
            fila, 4, f'=IFERROR(AVERAGE(G{fila_pri}:G{fila_ult}),"{ND}")',
            alternativo=_numero(r.calificacion), fmt=FMT_NUM, negrita=True,
            comentario="Calificacion = AVERAGE de la columna Calif. (1 si el criterio cumple, 0 si no).",
        )
        hoja.texto(fila, 5, f"> {comprar:.2f} COMPRAR | >= {mantener:.2f} MANTENER")
        hoja.formula(
            fila, 6,
            f'=IF(ISNUMBER(D{fila}),IF(D{fila}>{comprar},"COMPRAR",IF(D{fila}>={mantener},"MANTENER","NO INVERTIR")),"{ND}")',
            alternativo=r.decision or ND,
            comentario=f"Decision = IF(Calificacion > {comprar:.2f}; COMPRAR; IF(Calificacion >= {mantener:.2f}; "
                       "MANTENER; NO INVERTIR)).",
            fill=FILL_DECISION.get(r.decision, FILL_AVISO), negrita=True,
        )
        hoja.texto(fila, 8, f"Decision en Python: {r.decision or ND} (calificacion "
                            f"{_numero(r.calificacion) if _numero(r.calificacion) is not None else ND})", wrap=True)
        fila += 1
        if r.advertencias:
            hoja.texto(fila, 2, "Advertencias", negrita=True)
            hoja.nota(fila, " | ".join(r.advertencias), 3, 12)
            fila += 1
        # La calificacion comparativa apunta al bloque de la parrilla recien escrito.
        fila_comp = bloques[r.ticker]["fila_comp"]
        hoja.formula(
            fila_comp, 3, f'=IFERROR(AVERAGE(G{fila_pri}:G{fila_ult}),"{ND}")',
            alternativo=_numero(r.calificacion), fmt=FMT_NUM,
            comentario="Calificacion = AVERAGE de la columna Calif. de este ticker.",
        )
        hoja.formula(
            fila_comp, 9, f'=IFERROR(COUNTIF(F{fila_pri}:F{fila_ult},"SI"),"{ND}")',
            alternativo=sum(1 for c in r.criterios if c.activo and c.cumple), fmt=FMT_INT,
            comentario='Criterios que cumplen = COUNTIF de la columna ¿Cumple? con el valor "SI".',
        )
        fila += 2
    return fila


def _escribir_criterio(
    hoja: _Hoja, criterio: Criterio, r: ResultadoAnalisis, ref: Dict[str, Any], fila: int
) -> int:
    """Escribe una fila de la parrilla de decision (criterio individual).

    Args:
        hoja: hoja ``Principal``.
        criterio: criterio a escribir.
        r: resultado del ticker (para los umbrales de ``Params``).
        ref: referencias a celdas de otras hojas para este ticker.
        fila: fila donde se escribe el criterio.

    Returns:
        La fila siguiente.
    """
    tipo, clave_valor, clave_comparacion = ESPECIFICACIONES_CRITERIOS.get(criterio.numero, ("mayor", "", ""))
    fmt = FMT_POR_UNIDAD.get(criterio.unidad, FMT_NUM)
    if criterio.unidad == "texto":
        fmt = None

    hoja.texto(fila, 1, criterio.numero, centrado=True)
    hoja.texto(fila, 2, criterio.nombre, wrap=True)
    hoja.texto(fila, 3, criterio.optimo, wrap=True)

    if tipo == "texto_distinto":
        hoja.entrada(fila, 4, r.macd_senal or ND, comentario="Señal MACD de 1 mes (entrada)")
        hoja.texto(fila, 5, "Sell")
        hoja.formula(
            fila, 6, _formula_cumple("texto_distinto", fila),
            alternativo="SI" if criterio.cumple else "NO",
            comentario='¿Cumple? = IF(señal MACD = "Sell" o N/D; "NO"; "SI").',
        )
    else:
        referencia = ref.get(clave_valor)
        if referencia:
            hoja.formula(
                fila, 4, f'=IFERROR({referencia},"{ND}")', alternativo=criterio.valor, fmt=fmt,
                comentario=f"Valor obtenido: {referencia} ({criterio.nombre}).",
            )
        else:
            hoja.entrada(fila, 4, _texto_nd(criterio.valor), fmt=fmt,
                         comentario=f"Valor calculado en Python para el criterio {criterio.numero}.")
        if clave_comparacion in CLAVES_PARAMS:
            umbral = _numero(getattr(r.params, CLAVES_PARAMS[clave_comparacion], None))
            hoja.entrada(
                fila, 5, umbral if umbral is not None else _texto_nd(criterio.comparacion), fmt=fmt,
                comentario=f"Umbral de configuracion ({clave_comparacion}) usado como comparacion.",
            )
        else:
            referencia_comparacion = ref.get(clave_comparacion)
            if referencia_comparacion:
                hoja.formula(
                    fila, 5, f'=IFERROR({referencia_comparacion},"{ND}")', alternativo=criterio.comparacion, fmt=fmt,
                    comentario=f"Comparacion: {referencia_comparacion}.",
                )
            else:
                hoja.entrada(fila, 5, _texto_nd(criterio.comparacion), fmt=fmt,
                             comentario="Comparacion calculada en Python.")
        hoja.formula(
            fila, 6, _formula_cumple(tipo, fila),
            alternativo="SI" if criterio.cumple else "NO",
            comentario=f'¿Cumple? = IF(comparacion "{tipo}" entre el valor obtenido y la referencia; "SI"; "NO"). '
                       f"Optimo: {criterio.optimo or ND}",
            fill=FILL_OK if criterio.cumple else FILL_NO,
        )
    hoja.formula(
        fila, 7, f'=IF(F{fila}="SI",1,0)', alternativo=1 if criterio.cumple else 0, fmt=FMT_INT,
        comentario="Calificacion del criterio: 1 si cumple, 0 si no.",
    )
    hoja.texto(fila, 8, criterio.fuente or ND, wrap=True)
    hoja.texto(fila, 9, criterio.ruta or ND, wrap=True)
    detalle = criterio.formula or criterio.nota or ND
    if not criterio.activo:
        detalle = f"{detalle} (criterio inactivo)".strip()
    hoja.texto(fila, 10, detalle, wrap=True)
    return fila + 1


# ==========================================================================
# Imagenes
# ==========================================================================


def _siguiente_fila_libre(hoja: _Hoja) -> int:
    """Primera fila libre por debajo del contenido de una hoja (para las imagenes)."""
    return int(hoja.ws.max_row or 1) + 2


def _insertar_imagen(hoja: _Hoja, ruta: Path, fila: int, col: int = 2, alto: int = 320) -> bool:
    """Inserta un PNG en la hoja si el fichero existe.

    Args:
        hoja: hoja de destino.
        ruta: ruta del PNG.
        fila: fila del ancla.
        col: columna del ancla.
        alto: altura en pixeles usada para reservar espacio.

    Returns:
        ``True`` si se inserto la imagen.
    """
    if _XLImage is None or get_column_letter is None:  # pragma: no cover - sin openpyxl
        return False
    try:
        if not ruta.is_file():
            LOG.warning("Imagen no encontrada para la hoja %s: %s", hoja.nombre, ruta)
            return False
        imagen = _XLImage(str(ruta))
        if imagen.height and imagen.height > alto:
            factor = alto / float(imagen.height)
            imagen.height = int(imagen.height * factor)
            imagen.width = int(imagen.width * factor)
        hoja.ws.add_image(imagen, f"{get_column_letter(col)}{fila}")
        return True
    except Exception as exc:  # pragma: no cover - proteccion defensiva
        LOG.warning("No se pudo insertar la imagen %s en %s: %s", ruta, hoja.nombre, exc)
        return False


def _normalizar_clave_imagen(clave: str) -> str:
    """Normaliza la clave de una imagen (minusculas, sin acentos ni espacios)."""
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    texto = str(clave).strip().lower()
    for original, limpio in reemplazos.items():
        texto = texto.replace(original, limpio)
    return re.sub(r"[\s\-]+", "_", texto)


def _insertar_imagenes(hojas: Dict[str, _Hoja], libres: Dict[str, int], imagenes: Optional[Dict[str, Path]]) -> None:
    """Inserta todas las imagenes solicitadas en su hoja correspondiente.

    Una clave desconocida o una ruta inexistente solo generan un aviso: la
    exportacion nunca falla por una imagen.
    """
    if not imagenes:
        return
    for clave, ruta in imagenes.items():
        if ruta is None:
            continue
        nombre_hoja = CLAVES_IMAGENES.get(_normalizar_clave_imagen(clave))
        if nombre_hoja is None:
            LOG.warning("Clave de imagen desconocida '%s': se ignora", clave)
            continue
        hoja = hojas.get(nombre_hoja)
        if hoja is None:
            continue
        fila = libres.get(nombre_hoja, 1) + 1
        if _insertar_imagen(hoja, Path(ruta), fila):
            libres[nombre_hoja] = fila + 18


# ==========================================================================
# API publica
# ==========================================================================


def nombre_sugerido(resultados: Sequence[ResultadoAnalisis], fecha: Optional[date] = None) -> str:
    """Nombre de fichero sugerido para la exportacion.

    Args:
        resultados: resultados analizados (se usan sus tickers).
        fecha: fecha a incluir; por defecto, la de hoy.

    Returns:
        Por ejemplo ``"DML_FINANCE_NVDA_AAPL_2026-10-09.xlsx"``.
    """
    dia = fecha or date.today()
    tickers: List[str] = []
    for r in resultados or []:
        bruto = str(getattr(r, "ticker", "") or "")
        limpio = re.sub(r"[^A-Za-z0-9]+", "_", bruto).strip("_").upper()
        if limpio and limpio not in tickers:
            tickers.append(limpio)
    base = "DML_FINANCE_" + "_".join(tickers) if tickers else "DML_FINANCE"
    return f"{base}_{dia.isoformat()}.xlsx"


def exportar_excel(
    resultados: Sequence[ResultadoAnalisis],
    ruta: Path,
    *,
    con_formulas: bool = True,
    fuentes: Optional[Fuentes] = None,
    imagenes: Optional[Dict[str, Path]] = None,
) -> Path:
    """Escribe el libro Excel completo con el analisis de uno o varios tickers.

    Hojas escritas, en este orden: ``Principal``, ``Econometrico``, ``Griegas``,
    ``CAPM``, ``PER``, ``EPS``, ``Price to FCF``, ``Renta PER``, ``RDR``,
    ``Bonos y tasas`` y ``Fuentes y avisos``.

    Args:
        resultados: uno o varios resultados de analisis.
        ruta: ruta de destino del ``.xlsx`` (se crean las carpetas necesarias).
        con_formulas: si es ``True`` las magnitudes derivadas se escriben como
            formulas de Excel que referencian las celdas de entrada; si es
            ``False`` se escriben los valores calculados en Python.
        fuentes: registro de procedencia de los datos (opcional).
        imagenes: mapa ``clave -> PNG`` (``principal``, ``econometrico``,
            ``griegas``...); las rutas inexistentes se ignoran con un aviso.

    Returns:
        La ruta del fichero escrito.

    Raises:
        RuntimeError: si openpyxl no esta instalado o el fichero no se puede
            escribir (por ejemplo, porque esta abierto en Excel).
    """
    if not _OPENPYXL_DISPONIBLE or Workbook is None:
        raise RuntimeError(
            "openpyxl no esta instalado: no se puede exportar a Excel. "
            "Instalelo con 'pip install openpyxl' y vuelva a intentarlo."
            + (f" (detalle: {_ERROR_OPENPYXL})" if _ERROR_OPENPYXL else "")
        )

    destino = Path(ruta).expanduser()
    if not destino.suffix:
        destino = destino.with_suffix(".xlsx")
    try:
        if str(destino.parent) not in ("", "."):
            destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"No se pudo crear la carpeta de destino '{destino.parent}': {exc}") from exc

    lista: List[ResultadoAnalisis] = [r for r in (resultados or [])]
    if not lista:
        LOG.warning("exportar_excel recibido sin resultados: se escribira el libro vacio con N/D")

    libro = Workbook()
    hojas: Dict[str, _Hoja] = {}
    for indice, nombre in enumerate(ORDEN_HOJAS):
        ws = libro.active if indice == 0 else libro.create_sheet(nombre)
        if indice == 0:
            ws.title = nombre
        hojas[nombre] = _Hoja(ws, con_formulas)
    libro.active = 0

    libres: Dict[str, int] = {nombre: 1 for nombre in ORDEN_HOJAS}
    referencias: Dict[str, Dict[str, Any]] = {}
    for r in lista:
        referencias.setdefault(r.ticker, {})

    # 1) CAPM (el resto de hojas referencia sus celdas)
    fila = 1
    for r in lista:
        refs, fila = _escribir_capm(hojas["CAPM"], r, fila)
        referencias[r.ticker].update(refs)
        fila += 1

    # 2) Griegas
    fila = 1
    for r in lista:
        refs, fila = _escribir_griegas(hojas["Griegas"], r, fila)
        referencias[r.ticker].update(refs)
        fila += 1

    # 3) Econometrico
    fila = 1
    for r in lista:
        refs, fila = _escribir_econometrico(
            hojas["Econometrico"], r, _tabla_mensual(r), referencias[r.ticker], fila
        )
        referencias[r.ticker].update(refs)
        fila += 1

    # 4) Fundamentales y RDR (una fila por ticker)
    refs_per = _escribir_per(hojas["PER"], lista, 1)
    for ticker, valores in refs_per.items():
        referencias[ticker].update(valores)

    refs_eps = _escribir_eps(hojas["EPS"], lista, 1)
    for ticker, valores in refs_eps.items():
        referencias[ticker].update(valores)

    refs_fcf = _escribir_price_to_fcf(hojas["Price to FCF"], lista, 1)
    for ticker, valores in refs_fcf.items():
        referencias[ticker].update(valores)

    refs_renta = _escribir_renta_per(hojas["Renta PER"], lista, referencias, 1)
    for ticker, valores in refs_renta.items():
        referencias[ticker].update(valores)

    refs_rdr = _escribir_rdr(hojas["RDR"], lista, referencias, 1)
    for ticker, valores in refs_rdr.items():
        referencias[ticker].update(valores)

    # 5) Bonos y tasas
    _escribir_bonos(hojas["Bonos y tasas"], lista, 1)

    # 6) Fuentes y avisos
    for r in lista:
        for aviso in r.advertencias or []:
            LOG.debug("%s: %s", r.ticker, aviso)
    _escribir_fuentes(hojas["Fuentes y avisos"], lista, fuentes)

    # 7) Principal (al final: referencia todas las hojas anteriores)
    _escribir_principal(hojas["Principal"], lista, referencias)

    # Las imagenes se insertan debajo del contenido ya escrito de cada hoja.
    for nombre, hoja in hojas.items():
        libres[nombre] = _siguiente_fila_libre(hoja)
    _insertar_imagenes(hojas, libres, imagenes)

    for hoja in hojas.values():
        hoja.cerrar()

    total_formulas = sum(hoja.n_formulas for hoja in hojas.values())
    total_nd = sum(hoja.n_nd for hoja in hojas.values())
    try:
        libro.save(destino)
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo escribir el fichero Excel '{destino}': {exc}. "
            "Compruebe que el archivo no esta abierto en Excel y que tiene permisos de escritura."
        ) from exc

    LOG.info(
        "Excel exportado en %s (%d tickers, %d celdas de formula, %d celdas N/D, con_formulas=%s)",
        destino, len(lista), total_formulas, total_nd, con_formulas,
    )
    return destino
