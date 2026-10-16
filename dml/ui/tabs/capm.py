# -*- coding: utf-8 -*-
"""Pestana "CAPM": tabla mensual, Beta, PRH, Rend_CAPM y precio objetivo.

Bloques de la pestana:

1. Tarjetas con el resultado del modelo (TLR, Beta usada, PRH, ``Rend_CAPM``,
   precio objetivo, margen frente al spot y veredicto).
2. Tabla mensual (``ResultadoAnalisis.tabla``) con precio, rendimientos de la
   accion y del mercado, TLR y PRH mensual: ordenable, copiable (Ctrl+C) y con
   las columnas de rendimiento en porcentaje.
3. Bloque de Beta: covarianza, regresion MCO, Beta publicada y las diferencias
   entre las tres, con la formula en el tooltip y el **convenio de estimacion**
   explicito (muestral ``ddof=1`` [ESTANDAR] o la replica del libro:
   ``COVAR`` poblacional / ``VAR`` muestral cuando ``modo == "excel"``).
4. Bloque de PRH: prima de mercado anualizada [ESTANDAR] frente al promedio
   mensual, con el aviso visible de que en modo ``excel`` la PRH se calcula con
   los rendimientos de la **accion** y no con los del mercado.
5. Resultado CAPM: ``Rend_CAPM = TLR + Beta x PRH`` y
   ``Precio objetivo = Spot x (1 + Rend_CAPM)``, con el margen de seguridad
   frente al spot (:func:`dml.models.fundamentales.margen_seguridad`).
6. Dispersion mensual accion vs mercado con la recta de regresion por minimos
   cuadrados (numpy) y la Beta anotada sobre el grafico.

Toda la logica de calculo vive en :mod:`dml.analisis` y :mod:`dml.models`; esta
pestana solo pinta. Ningun dato se inventa: lo que falta se muestra como ``N/D``
con el motivo en el tooltip y la nota de que el criterio afectado se califica 0.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.fundamentales import decision_por_margen, margen_seguridad
from ..estilos import colores
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabConGrafico

LOG = logging.getLogger("dml.ui.tabs.capm")

# ---------------------------------------------------------------- formulas
FORMULA_BETA = "Beta = COVAR(Ra, Rm) / VAR(Rm)"
FORMULA_BETA_OLS = "Beta_OLS = pendiente de la regresion MCO  Ra = a + b x Rm"
FORMULA_BETA_PUBLICADA = "Beta publicada: valor de consenso que publica el proveedor de datos"
FORMULA_PRHR_MERCADO = "PRH = PROMEDIO(Rm - Rf) x 12   [ESTANDAR]"
FORMULA_PRHR_EXCEL = "PRH = PROMEDIO(Ra - Rf)   [MODO EXCEL: rendimientos de la ACCION]"
FORMULA_PRHR_MENSUAL = "PRH mensual = PROMEDIO(Rm - Rf) sin anualizar"
FORMULA_CAPM = "Rend_CAPM = TLR + Beta x PRH"
FORMULA_OBJETIVO = "Precio objetivo = Spot x (1 + Rend_CAPM)"
FORMULA_MARGEN = "Margen de seguridad = (Precio objetivo - Spot) / Spot"

# ---------------------------------------------------------------- columnas
COLUMNAS_MENSUAL: List[str] = [
    "Fecha",
    "Precio",
    "R_Accion",
    "Indice",
    "R_Mercado",
    "TLR_anual",
    "TLR_mensual",
    "PRH_mensual",
]
COLUMNAS_RETORNO: List[str] = ["R_Accion", "R_Mercado", "TLR_anual", "TLR_mensual", "PRH_mensual"]
COLUMNAS_BLOQUE: List[str] = ["Concepto", "Valor", "Formula", "Fuente"]
COLUMNAS_ORIGEN: List[str] = ["Dato", "Valor", "Fuente", "Metodo", "URL", "Ruta Investing", "Nota"]

#: Tooltip de cada columna de la tabla mensual (formula del dato).
TOOLTIPS_MENSUAL: Dict[str, str] = {
    "Fecha": "Mes de cierre de la serie mensual (el indice se normaliza a fin de mes).",
    "Precio": "Precio de cierre mensual del activo (Yahoo Finance / Investing.com).",
    "R_Accion": "Rendimiento simple mensual de la accion: R = Precio(t) / Precio(t-1) - 1.",
    "Indice": "Nivel de cierre mensual del indice de mercado usado como referencia.",
    "R_Mercado": "Rendimiento simple mensual del indice: Rm = Indice(t) / Indice(t-1) - 1.",
    "TLR_anual": "Tasa libre de riesgo anual de la serie mensual (T-Bill de EE.UU. a 4 semanas).",
    "TLR_mensual": "TLR mensual: TLR_anual / 12 [ESTANDAR]; TLR_anual / 365 x 28 en modo excel.",
    "PRH_mensual": "PRH mensual = R_Accion - TLR_mensual (prima historica del mes).",
}
TOOLTIPS_BLOQUE: Dict[str, str] = {
    "Concepto": "Concepto del bloque CAPM.",
    "Valor": "Valor calculado (porcentaje, importe o numero segun la fila).",
    "Formula": "Formula exacta del calculo.",
    "Fuente": "Origen del dato: calculo del programa o proveedor externo.",
}
TOOLTIPS_ORIGEN: Dict[str, str] = {
    "Dato": "Dato mostrado.",
    "Valor": "Valor del dato (formato segun su naturaleza).",
    "Fuente": "Fuente declarada del dato.",
    "Metodo": "API, scraping, respaldo, manual, demo o calculo.",
    "URL": "URL consultada o ruta equivalente de Investing.com.",
    "Ruta Investing": "Pagina de Investing.com donde localizar el dato a mano.",
    "Nota": "Observaciones, convenios y motivo cuando el dato es N/D.",
}

#: Simbolo monetario por divisa.
SIMBOLOS: Dict[str, str] = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "MXN": "MX$",
    "ARS": "$",
}


# --------------------------------------------------------------------------
# Utilidades locales de la pestana (se repiten en cada modulo de pestana para
# no crear dependencias cruzadas entre ficheros de la interfaz).
# --------------------------------------------------------------------------


def _simbolo(moneda: str = "USD") -> str:
    """Simbolo de la divisa (``$`` si se desconoce)."""
    return SIMBOLOS.get(str(moneda or "USD").upper(), "$")


def _moneda(valor: Any, moneda: str = "USD", decimales: int = 2) -> str:
    """Formatea un importe con el simbolo de la divisa (``N/D`` si falta)."""
    return fmt_moneda(valor, decimales, _simbolo(moneda))


def _color_signo(valor: Any) -> Optional[str]:
    """Verde si el valor es positivo, rojo si es negativo, ambar si falta."""
    numero = a_float(valor)
    if numero is None:
        return AMBAR
    if numero > 0:
        return VERDE
    if numero < 0:
        return ROJO
    return GRIS


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


def _texto_fuente(ev: Optional[Evidence], ruta: str = "") -> str:
    """Resume la procedencia de un dato (fuente, metodo, URL y nota)."""
    if ev is None:
        return "N/D: sin registro de procedencia para este dato"
    partes: List[str] = []
    if ev.fuente:
        partes.append(f"Fuente: {ev.fuente}")
    if ev.metodo:
        partes.append(f"Metodo: {ev.metodo}")
    url = ev.url or ruta
    if url:
        partes.append(f"URL: {url}")
    if not ev.ok:
        partes.append("Dato no disponible en el origen")
    if ev.nota:
        partes.append(f"Nota: {ev.nota}")
    if not partes:
        return "N/D: sin registro de procedencia para este dato"
    return " | ".join(partes)


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


def _formato_unidad(valor: Any, unidad: str, moneda: str = "USD") -> Optional[str]:
    """Formatea el valor de un criterio segun su unidad declarada.

    Devuelve ``None`` cuando el dato no es utilizable, para que la celda
    conserve el ``N/D`` con su tooltip explicativo.
    """
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
    """Reescribe una columna con un texto por fila (``None`` deja la celda ``N/D``).

    Permite que una misma columna muestre porcentajes, importes y numeros segun
    la fila, conservando en ``Qt.UserRole`` el valor original para ordenar.
    """
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


class TabCAPM(TabConGrafico):
    """Pestana del modelo CAPM: Beta, PRH, rendimiento esperado y precio objetivo."""

    titulo = "CAPM"

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
        _titulo(caja, "CAPM - N/D", "Sin analisis cargado")
        _aviso(
            caja,
            "N/D: no hay ningun analisis seleccionado. Analiza un ticker (o usa el modo DEMO) para ver la Beta, "
            "la prima de riesgo historica (PRH), el Rend_CAPM y el precio objetivo.",
        )

    def _subtitulo(self, r: ResultadoAnalisis) -> str:
        """Linea de contexto del analisis mostrado."""
        partes = [f"Ticker {r.ticker}"]
        if r.nombre:
            partes.append(r.nombre)
        if r.bolsa:
            partes.append(f"Bolsa {r.bolsa}")
        partes.append(f"Modo {r.modo}")
        if r.indice_nombre:
            partes.append(f"Indice de mercado: {r.indice_nombre}")
        partes.append(f"Meses en la tabla: {len(r.tabla.index)}")
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

        _titulo(caja, f"CAPM - {r.ticker}", self._subtitulo(r))
        self._bloque_tarjetas(caja, r)
        self._bloque_mensual(caja, r)
        self._bloque_beta(caja, r)
        self._bloque_prh(caja, r)
        self._bloque_capm(caja, r)
        self._bloque_origen(caja, r)
        self._bloque_grafico(caja, r)

    # ------------------------------------------------------------- tarjetas
    def _bloque_tarjetas(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tarjetas con el resultado del modelo CAPM."""
        margen = margen_seguridad(r.spot, r.precio_objetivo)
        beta_usada = r.beta_cov if a_float(r.beta_cov) is not None else r.beta_ols
        prh_usada = r.prh_mensual_promedio if r.modo == "excel" else r.prh
        tarjetas = PanelTarjetas(3)
        tarjetas.cargar(
            {
                "Ticker": r.ticker,
                "Spot (valor actual)": _moneda(r.spot, r.moneda, 2),
                "TLR anual": fmt_pct(r.tlr, 2),
                "Beta usada en el CAPM": fmt_num(beta_usada, 4),
                "PRH usada": fmt_pct(prh_usada, 2),
                "Rend_CAPM": fmt_pct(r.rend_capm, 2),
                "Precio objetivo CAPM": _moneda(r.precio_objetivo, r.moneda, 2),
                "Margen de seguridad": fmt_pct(margen, 2),
                "Veredicto": decision_por_margen(margen),
            },
            tooltips={
                "Ticker": "Simbolo analizado.",
                "Spot (valor actual)": "Ultimo precio de cierre disponible del activo (Yahoo Finance / Investing.com).",
                "TLR anual": "TLR = T-Bill de EE.UU. a 4 semanas (Investing.com; respaldo FRED DTB4WK).",
                "Beta usada en el CAPM": f"{FORMULA_BETA}. Se usa la Beta por covarianza y, si falta, la de la regresion MCO.",
                "PRH usada": (
                    f"{FORMULA_PRHR_EXCEL}" if r.modo == "excel" else f"{FORMULA_PRHR_MERCADO}"
                ),
                "Rend_CAPM": FORMULA_CAPM,
                "Precio objetivo CAPM": FORMULA_OBJETIVO,
                "Margen de seguridad": FORMULA_MARGEN,
                "Veredicto": f"Decision cualitativa por margen: {FORMULA_MARGEN}.",
            },
            colores={
                "Rend_CAPM": _color_signo(r.rend_capm),
                "Margen de seguridad": _color_signo(margen),
                "Veredicto": _color_signo(margen),
            },
        )
        caja.addWidget(tarjetas)

    # -------------------------------------------------------- tabla mensual
    def _bloque_mensual(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tabla mensual del analisis (precio, rendimientos, TLR y PRH)."""
        _titulo(
            caja,
            "Tabla mensual del analisis",
            "Serie mensual usada por los modelos. Las columnas de rendimiento se muestran en porcentaje.",
        )
        formateadores: Dict[str, Callable[[Any], str]] = {
            columna: (lambda valor: fmt_pct(valor, 2)) for columna in COLUMNAS_RETORNO
        }
        formateadores["Precio"] = lambda valor: fmt_num(valor, 2)
        formateadores["Indice"] = lambda valor: fmt_num(valor, 2)
        tabla = TablaDML(COLUMNAS_MENSUAL, formateadores=formateadores, tooltips_columnas=TOOLTIPS_MENSUAL)
        tabla.setMinimumHeight(300)
        registros = self._registros_mensuales(r)
        if registros:
            tabla.cargar_filas(registros, COLUMNAS_MENSUAL)
        else:
            _aviso(caja, "N/D: la tabla mensual esta vacia (no hay serie de precios); los modelos no se pueden calcular.")
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Origen de la serie mensual: precios de cierre mensuales de Yahoo Finance y del indice "
            f"{r.indice_nombre}; la TLR mensual procede de la serie del T-Bill a 4 semanas de Investing.com "
            f"({_texto_ruta(r, 'tasa', 'renta fija de EE.UU.')}). Si algun mes no tiene dato, la celda se "
            "muestra como N/D y ese mes queda fuera de la regresion.",
        )

    @staticmethod
    def _registros_mensuales(r: ResultadoAnalisis) -> List[Dict[str, Any]]:
        """Convierte ``ResultadoAnalisis.tabla`` en registros listos para la tabla."""
        try:
            datos = r.tabla.como_dataframe()
        except Exception as exc:  # pragma: no cover - proteccion defensiva
            LOG.error("No se pudo construir la tabla mensual: %s", exc)
            return []
        if datos is None or datos.empty:
            return []
        datos = datos.copy()
        fechas = pd.to_datetime(datos["Fecha"], errors="coerce")
        datos["Fecha"] = [None if pd.isna(fecha) else fecha.strftime("%Y-%m") for fecha in fechas]
        return datos.to_dict(orient="records")

    # --------------------------------------------------------------- Beta
    def _bloque_beta(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Beta por covarianza, por MCO, publicada y sus diferencias."""
        _titulo(caja, "Beta", f"{FORMULA_BETA} (rendimientos mensuales de los ultimos {len(r.tabla.index)} meses)")
        ruta_beta = _ruta(r, "beta")
        beta_usada = r.beta_cov if a_float(r.beta_cov) is not None else r.beta_ols
        filas: List[Dict[str, Any]] = [
            {
                "Concepto": "Beta por covarianza/varianza",
                "Valor": r.beta_cov,
                "Formula": FORMULA_BETA,
                "Fuente": self._texto_convenio(r, "covarianza"),
            },
            {
                "Concepto": "Beta por regresion MCO",
                "Valor": r.beta_ols,
                "Formula": FORMULA_BETA_OLS,
                "Fuente": "Calculado con los rendimientos mensuales alineados de la accion y del indice.",
            },
            {
                "Concepto": "Beta publicada",
                "Valor": r.beta_publicada,
                "Formula": FORMULA_BETA_PUBLICADA,
                "Fuente": _texto_fuente(r.fundamentales.ev_beta_publicada, ruta_beta),
            },
            {
                "Concepto": "Diferencia |covarianza - MCO|",
                "Valor": self._diferencia(r.beta_cov, r.beta_ols),
                "Formula": "|Beta_cov - Beta_OLS|",
                "Fuente": "Calculado: contraste entre las dos vias de estimacion.",
            },
            {
                "Concepto": "Diferencia |covarianza - publicada|",
                "Valor": self._diferencia(r.beta_cov, r.beta_publicada),
                "Formula": "|Beta_cov - Beta_publicada|",
                "Fuente": "Calculado: contraste con el valor de consenso del proveedor.",
            },
            {
                "Concepto": "Diferencia |MCO - publicada|",
                "Valor": self._diferencia(r.beta_ols, r.beta_publicada),
                "Formula": "|Beta_OLS - Beta_publicada|",
                "Fuente": "Calculado: contraste con el valor de consenso del proveedor.",
            },
            {
                "Concepto": "Beta usada en el CAPM",
                "Valor": beta_usada,
                "Formula": "Se usa la Beta por covarianza; si falta, la de la regresion MCO.",
                "Fuente": "Calculado.",
            },
        ]
        tabla = TablaDML(COLUMNAS_BLOQUE, tooltips_columnas=TOOLTIPS_BLOQUE)
        # ordenar=False: el formateo por fila se aplica despues, por indice.
        tabla.cargar_filas(filas, COLUMNAS_BLOQUE, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_BLOQUE.index("Valor"),
            [fmt_num(fila["Valor"], 4) if a_float(fila["Valor"]) is not None else None for fila in filas],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)

        if r.modo == "excel":
            _aviso(
                caja,
                "[MODO EXCEL] Convenio de estimacion: Beta = COVAR poblacional (ddof=0) / VAR muestral (ddof=1), "
                "replicando la hoja de referencia; por eso la Beta por covarianza puede no coincidir con la "
                "pendiente de la regresion MCO. [ESTANDAR] usa covarianza y varianza muestrales (ddof=1) en "
                "numerador y denominador, y ambas vias coinciden.",
            )
        else:
            _aviso(
                caja,
                "[ESTANDAR] Convenio de estimacion: covarianza y varianza MUESTRALES (ddof=1) en numerador y "
                "denominador; con este convenio la Beta por covarianza coincide numericamente con la pendiente "
                "de la regresion MCO. En modo excel se replicaria COVAR poblacional / VAR muestral.",
            )

    @staticmethod
    def _diferencia(primero: Any, segundo: Any) -> Optional[float]:
        """Diferencia absoluta entre dos valores (``None`` si falta alguno)."""
        a, b = a_float(primero), a_float(segundo)
        if a is None or b is None:
            return None
        return abs(a - b)

    @staticmethod
    def _texto_convenio(r: ResultadoAnalisis, via: str) -> str:
        """Texto del convenio de estimacion usado para la Beta."""
        if r.modo == "excel":
            return (
                f"[MODO EXCEL] Calculado como COVAR poblacional / VAR muestral ({via}); "
                "replica la metodologia del libro de referencia."
            )
        return f"[ESTANDAR] Calculado como covarianza y varianza muestrales, ddof=1 ({via})."

    # ---------------------------------------------------------------- PRH
    def _bloque_prh(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Prima de riesgo historica: mercado anualizada frente al promedio mensual."""
        _titulo(caja, "PRH (prima de riesgo historica)")
        ruta_tasa = _ruta(r, "tasa")
        base_tlr_capm = r.tlr_mensual_valor if r.modo == "excel" else r.tlr
        if r.modo == "excel":
            formula_mercado = FORMULA_PRHR_MENSUAL + " (sin anualizar en modo excel)"
            etiqueta_mercado = "PRH de mercado (mensual, sin anualizar)"
        else:
            formula_mercado = FORMULA_PRHR_MERCADO
            etiqueta_mercado = "PRH de mercado anualizada [ESTANDAR]"
        filas: List[Dict[str, Any]] = [
            {
                "Concepto": etiqueta_mercado,
                "Valor": r.prh,
                "Formula": formula_mercado,
                "Fuente": "Calculado con los rendimientos mensuales del mercado y la TLR mensual.",
            },
            {
                "Concepto": "PRH mensual promedio",
                "Valor": r.prh_mensual_promedio,
                "Formula": FORMULA_PRHR_EXCEL if r.modo == "excel" else FORMULA_PRHR_MENSUAL,
                "Fuente": (
                    "Calculado con los rendimientos de la ACCION (modo excel)."
                    if r.modo == "excel"
                    else "Calculado con los rendimientos del MERCADO."
                ),
            },
            {
                "Concepto": "TLR usada como base",
                "Valor": base_tlr_capm,
                "Formula": (
                    "TLR_mensual = TLR_anual / 12 (modo excel)"
                    if r.modo == "excel"
                    else "TLR anual del T-Bill a 4 semanas [ESTANDAR]"
                ),
                "Fuente": _texto_fuente(r.tasas.ev_tbill_4w, ruta_tasa),
            },
        ]
        tabla = TablaDML(COLUMNAS_BLOQUE, tooltips_columnas=TOOLTIPS_BLOQUE)
        tabla.cargar_filas(filas, COLUMNAS_BLOQUE, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_BLOQUE.index("Valor"),
            [
                fmt_pct(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                fmt_pct(filas[1]["Valor"], 2) if a_float(filas[1]["Valor"]) is not None else None,
                fmt_pct(filas[2]["Valor"], 2) if a_float(filas[2]["Valor"]) is not None else None,
            ],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        if r.modo == "excel":
            _aviso(
                caja,
                "[MODO EXCEL] Aviso visible: en este modo la PRH se calcula como promedio mensual de "
                "(rendimiento de la ACCION - TLR), no como prima de riesgo del MERCADO. No es una prima de "
                "riesgo de mercado y, ademas, se suma a una TLR mensual: no es comparable con el Rend_CAPM "
                "estandar. Cambia a modo estandar para la prima de mercado anualizada (x12).",
            )
        else:
            _aviso(
                caja,
                "[ESTANDAR] La PRH es la prima de riesgo del MERCADO anualizada (promedio mensual x12), coherente "
                "con la TLR anual que se suma en el CAPM. El promedio mensual se muestra solo como referencia.",
            )

    # --------------------------------------------------------------- CAPM
    def _bloque_capm(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Rend_CAPM, precio objetivo y margen frente al spot."""
        _titulo(caja, "Resultado CAPM", f"{FORMULA_CAPM} y {FORMULA_OBJETIVO}")
        beta_usada = r.beta_cov if a_float(r.beta_cov) is not None else r.beta_ols
        prh_usada = r.prh_mensual_promedio if r.modo == "excel" else r.prh
        base_tlr = r.tlr_mensual_valor if r.modo == "excel" else r.tlr
        margen = margen_seguridad(r.spot, r.precio_objetivo)
        filas: List[Dict[str, Any]] = [
            {
                "Concepto": "TLR (base)",
                "Valor": base_tlr,
                "Formula": "TLR mensual (excel) | TLR anual (estandar)",
                "Fuente": _texto_fuente(r.tasas.ev_tbill_4w, _ruta(r, "tasa")) if r.modo != "excel" else "TLR/12 a partir de la TLR anual.",
            },
            {
                "Concepto": "Beta usada",
                "Valor": beta_usada,
                "Formula": FORMULA_BETA,
                "Fuente": self._texto_convenio(r, "CAPM"),
            },
            {
                "Concepto": "PRH usada",
                "Valor": prh_usada,
                "Formula": FORMULA_PRHR_EXCEL if r.modo == "excel" else FORMULA_PRHR_MERCADO,
                "Fuente": "Calculado con los rendimientos mensuales alineados.",
            },
            {
                "Concepto": "Rend_CAPM (rendimiento esperado)",
                "Valor": r.rend_capm,
                "Formula": FORMULA_CAPM,
                "Fuente": "Calculado: el detalle de la procedencia esta en la pestana Fuentes.",
            },
            {
                "Concepto": "Spot",
                "Valor": r.spot,
                "Formula": "Ultimo cierre disponible.",
                "Fuente": "N/D: el resultado no conserva el registro de procedencia del spot; consulta la pestana Fuentes.",
            },
            {
                "Concepto": "Precio objetivo",
                "Valor": r.precio_objetivo,
                "Formula": FORMULA_OBJETIVO,
                "Fuente": "Calculado.",
            },
            {
                "Concepto": "Margen de seguridad",
                "Valor": margen,
                "Formula": FORMULA_MARGEN,
                "Fuente": "Calculado.",
            },
        ]
        tabla = TablaDML(COLUMNAS_BLOQUE, tooltips_columnas=TOOLTIPS_BLOQUE)
        tabla.cargar_filas(filas, COLUMNAS_BLOQUE, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_BLOQUE.index("Valor"),
            [
                fmt_pct(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                fmt_num(filas[1]["Valor"], 4) if a_float(filas[1]["Valor"]) is not None else None,
                fmt_pct(filas[2]["Valor"], 2) if a_float(filas[2]["Valor"]) is not None else None,
                fmt_pct(filas[3]["Valor"], 2) if a_float(filas[3]["Valor"]) is not None else None,
                _moneda(filas[4]["Valor"], r.moneda, 2) if a_float(filas[4]["Valor"]) is not None else None,
                _moneda(filas[5]["Valor"], r.moneda, 2) if a_float(filas[5]["Valor"]) is not None else None,
                fmt_pct(filas[6]["Valor"], 2) if a_float(filas[6]["Valor"]) is not None else None,
            ],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            f"Lectura del margen: {decision_por_margen(margen)}. El margen se calcula como {FORMULA_MARGEN}; "
            "si falta el spot o el precio objetivo se muestra N/D y el criterio asociado se califica 0.",
        )

    # --------------------------------------------------------- procedencia
    def _bloque_origen(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Tabla de procedencia: valor, fuente, metodo y ruta de Investing.com."""
        _titulo(caja, "Procedencia de los datos", "Fuente, metodo, URL y ruta de Investing.com de cada dato.")
        ruta_tasa = _ruta(r, "tasa")
        ruta_beta = _ruta(r, "beta")
        filas: List[Dict[str, Any]] = [
            _fila_origen("TLR (T-Bill 4 semanas)", r.tlr, r.tasas.ev_tbill_4w, ruta_tasa),
            _fila_origen(
                "Spot / precio de cierre",
                r.spot,
                None,
                ruta_beta,
                "N/D: el resultado no conserva el registro de procedencia del spot; consulta la pestana Fuentes.",
            ),
            _fila_origen("Beta publicada", r.beta_publicada, r.fundamentales.ev_beta_publicada, ruta_beta),
            _fila_origen(
                "Beta por covarianza (calculada)",
                r.beta_cov,
                Evidence(fuente="Calculado", metodo="calculo", nota=self._texto_convenio(r, "covarianza")),
                ruta_beta,
            ),
            _fila_origen(
                "Beta por MCO (calculada)",
                r.beta_ols,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_BETA_OLS),
                ruta_beta,
            ),
            _fila_origen(
                "PRH (calculada)",
                r.prh,
                Evidence(
                    fuente="Calculado",
                    metodo="calculo",
                    nota=FORMULA_PRHR_EXCEL if r.modo == "excel" else FORMULA_PRHR_MERCADO,
                ),
                ruta_tasa,
            ),
            _fila_origen(
                "PRH mensual promedio (calculada)",
                r.prh_mensual_promedio,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_PRHR_MENSUAL),
                ruta_tasa,
            ),
            _fila_origen(
                "Rend_CAPM (calculado)",
                r.rend_capm,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_CAPM),
                ruta_beta,
            ),
            _fila_origen(
                "Precio objetivo (calculado)",
                r.precio_objetivo,
                Evidence(fuente="Calculado", metodo="calculo", nota=FORMULA_OBJETIVO),
                ruta_beta,
            ),
        ]
        tabla = TablaDML(COLUMNAS_ORIGEN, tooltips_columnas=TOOLTIPS_ORIGEN)
        tabla.cargar_filas(filas, COLUMNAS_ORIGEN, ordenar=False)
        _aplicar_formatos(
            tabla,
            COLUMNAS_ORIGEN.index("Valor"),
            [
                fmt_pct(filas[0]["Valor"], 2) if a_float(filas[0]["Valor"]) is not None else None,
                _moneda(filas[1]["Valor"], r.moneda, 2) if a_float(filas[1]["Valor"]) is not None else None,
                fmt_num(filas[2]["Valor"], 4) if a_float(filas[2]["Valor"]) is not None else None,
                fmt_num(filas[3]["Valor"], 4) if a_float(filas[3]["Valor"]) is not None else None,
                fmt_num(filas[4]["Valor"], 4) if a_float(filas[4]["Valor"]) is not None else None,
                fmt_pct(filas[5]["Valor"], 2) if a_float(filas[5]["Valor"]) is not None else None,
                fmt_pct(filas[6]["Valor"], 2) if a_float(filas[6]["Valor"]) is not None else None,
                fmt_pct(filas[7]["Valor"], 2) if a_float(filas[7]["Valor"]) is not None else None,
                _moneda(filas[8]["Valor"], r.moneda, 2) if a_float(filas[8]["Valor"]) is not None else None,
            ],
        )
        tabla.reactivar_ordenacion()
        self._ajustar_alto(tabla)
        caja.addWidget(tabla)
        _aviso(
            caja,
            "Donde encontrarlo en Investing.com: la Beta publicada en la ficha del valor "
            f"({_texto_ruta(r, 'beta', 'ficha del valor')}) y la TLR en la pagina del T-Bill a 4 semanas "
            f"({_texto_ruta(r, 'tasa', 'renta fija de EE.UU.')}). La Beta y la PRH calculadas son fruto del "
            "programa y no se copian de ninguna web.",
        )

    # -------------------------------------------------------------- grafico
    def _bloque_grafico(self, caja: QVBoxLayout, r: ResultadoAnalisis) -> None:
        """Dispersion mensual accion vs mercado con la recta MCO."""
        _titulo(
            caja,
            "Dispersion mensual: rendimiento de la accion frente al del mercado",
            "Cada punto es un mes; la recta es la regresion por minimos cuadrados (numpy) y su pendiente es la Beta.",
        )
        self._grafico = GraficoDML(titulo="Ra vs Rm", alto=3.4, ancho=7)
        self._grafico.setMinimumHeight(320)
        caja.addWidget(self._grafico)
        self._dibujar_grafico(r)

    def _dibujar_grafico(self, r: Optional[ResultadoAnalisis]) -> None:
        """Dibuja la dispersion y anota la Beta (o el motivo del N/D)."""
        grafico = self._grafico
        if grafico is None:
            return
        paleta = colores(self.tema_actual)
        grafico.limpiar()
        eje = grafico.ax
        try:
            x, y = self._puntos_dispersion(r)
            if len(x) >= 3:
                pendiente, intercepto = (float(valor) for valor in np.polyfit(x, y, 1))
                eje.scatter(x, y, s=20, color=paleta["acento"], alpha=0.85, zorder=3, label="Meses observados")
                rejilla = np.linspace(min(x), max(x), 50)
                eje.plot(rejilla, intercepto + pendiente * rejilla, color=VERDE, linewidth=1.8, zorder=4, label="Recta MCO")
                lineas = [f"Beta MCO (pendiente) = {fmt_num(pendiente, 4)}"]
                beta_cov = a_float(r.beta_cov) if r is not None else None
                if beta_cov is not None:
                    lineas.append(f"Beta COVAR/VAR = {fmt_num(beta_cov, 4)}")
                if r is not None:
                    lineas.append(f"Convenio: {'excel (COVAR poblacional)' if r.modo == 'excel' else 'estandar (ddof=1)'}")
                eje.text(
                    0.02,
                    0.98,
                    "\n".join(lineas),
                    transform=eje.transAxes,
                    va="top",
                    ha="left",
                    fontsize=8,
                    color=paleta["texto"],
                    bbox={"boxstyle": "round", "facecolor": paleta["panel"], "edgecolor": paleta["borde"], "alpha": 0.9},
                )
                leyenda = eje.legend(loc="lower right", fontsize=7)
                leyenda.get_frame().set_facecolor(paleta["panel"])
                for texto in leyenda.get_texts():
                    texto.set_color(paleta["texto"])
            else:
                eje.text(
                    0.5,
                    0.5,
                    "N/D: no hay al menos 3 meses con rendimiento de la accion y del mercado alineados; "
                    "la recta de regresion no se puede estimar y el criterio se califica 0.",
                    transform=eje.transAxes,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=AMBAR,
                    wrap=True,
                )
            eje.set_xlabel("Rendimiento mensual del mercado (%)")
            eje.set_ylabel("Rendimiento mensual de la accion (%)")
            eje.set_title("Dispersion mensual Ra vs Rm")
            eje.axhline(0.0, color=paleta["borde"], linewidth=0.8)
            eje.axvline(0.0, color=paleta["borde"], linewidth=0.8)
            eje.grid(True, color=paleta["borde"], alpha=0.25, linewidth=0.6)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudo dibujar la dispersion del CAPM: %s", exc)
            eje.text(0.5, 0.5, f"N/D: no se pudo dibujar el grafico ({exc})", transform=eje.transAxes, ha="center", va="center", fontsize=8, color=ROJO)
            grafico.refrescar(self.tema_actual)
            self._grafico_al_dia()

    @staticmethod
    def _puntos_dispersion(r: Optional[ResultadoAnalisis]) -> Tuple[List[float], List[float]]:
        """Pares (Rm, Ra) en puntos porcentuales, sin valores ausentes."""
        if r is None:
            return [], []
        x: List[float] = []
        y: List[float] = []
        for accion, mercado in zip(list(r.tabla.r_accion), list(r.tabla.r_mercado)):
            valor_accion, valor_mercado = a_float(accion), a_float(mercado)
            if valor_accion is None or valor_mercado is None:
                continue
            x.append(valor_mercado * 100.0)
            y.append(valor_accion * 100.0)
        return x, y

    # ---------------------------------------------------------------- ayudas
    @staticmethod
    def _ajustar_alto(tabla: TablaDML, filas_maximas: int = 10) -> None:
        """Fija un alto razonable: la tabla se desplaza si tiene mas filas."""
        filas = max(tabla.rowCount(), 1)
        alto = min(filas, filas_maximas) * 30 + 40
        tabla.setMinimumHeight(alto)
