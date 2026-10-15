# -*- coding: utf-8 -*-
"""Pestana "Principal": resumen ejecutivo, parrilla de decision y precio.

Esta pestana es la vista de detalle del ticker seleccionado. Presenta cuatro
bloques:

1. Cabecera con ticker, empresa, bolsa, fecha de analisis, modo y aviso DEMO.
2. Rejilla de tarjetas con los parametros del modelo (spot, strike, T, q, r, b,
   sigma y rendimiento esperado), sin volcar nunca fracciones en crudo.
3. Parrilla de los 12 criterios con el semaforo de cumplimiento y el panel con
   la decision final.
4. Grafico del precio mensual con las referencias de spot, strike (forward) y
   precio objetivo CAPM, la tabla comparativa multi-ticker y las advertencias.

Toda la logica de calculo vive en :mod:`dml.analisis`; aqui solo se pinta.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

import matplotlib.dates as mdates
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...analisis import resumen_ejecutivo
from ...core.tipos import ND, Criterio, Evidence, ResultadoAnalisis
from ...core.util import a_float, fmt_moneda, fmt_num, fmt_pct
from ...models.parrilla import tabla_criterios
from ..widgets import (
    AMBAR,
    GRIS,
    ROJO,
    VERDE,
    EtiquetaAviso,
    GraficoDML,
    PanelIndicadorDecision,
    PanelTarjetas,
    TablaDML,
)
from .base import TabBase

LOG = logging.getLogger("dml.ui.tabs.principal")

#: Simbolo monetario por divisa (el valor se muestra siempre con dos decimales).
SIMBOLOS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5", "MXN": "MX$", "ARS": "$"}

#: Columnas de la parrilla de criterios.
COLUMNAS_CRITERIOS = [
    "#",
    "Criterio",
    "Optimo",
    "Valor obtenido",
    "Valor de comparacion",
    "Cumple",
    "Activo",
    "Calificacion",
    "Fuente",
    "Ruta Investing",
    "Nota",
]

#: Formula mostrada en el tooltip de cada tarjeta del resumen ejecutivo.
FORMULAS: Dict[str, str] = {
    "Spot (valor actual)": "Ultimo precio de cierre disponible del activo (Yahoo Finance / Investing.com).",
    "Strike Price (Forward)": "K = S x e^(bT), con b = r - q; si el strike es manual se usa el valor indicado.",
    "Time to Maturity (anios)": "T = dias hasta el vencimiento / 365.",
    "Dividend (q)": "q = dividendo anual / spot (rentabilidad por dividendo, en tanto por uno).",
    "Tasa Libre (r)": "TLR = T-Bill de EE.UU. a 4 semanas (Investing.com; respaldo FRED DGS1MO).",
    "Costo de mantener (b = r - q)": "b = r - q, el coste neto de mantener la posicion en el modelo de Black-Scholes-Merton.",
    "Volatilidad (sigma anual)": "sigma_anual = sigma_mensual x sqrt(12) (desviacion estandar de los rendimientos mensuales).",
    "Rendimiento esperado (CAPM)": "E[R] = r + Beta x PRH (CAPM con la prima de riesgo historica).",
}

#: Motivo mostrado cuando una tarjeta del resumen no tiene valor.
MOTIVO_ND = "N/D: el modelo no se pudo calcular (faltan datos suficientes)"

def _color_cumple(valor: Any) -> Optional[str]:
    """Color del semaforo: verde SI, rojo NO, ambar N/D."""
    texto = str(valor or "").strip().upper()
    if texto == "SI":
        return VERDE
    if texto == "NO":
        return ROJO
    return AMBAR


def _celda(texto: str, dato: Any = None, color: Optional[str] = None, tooltip: str = "", alineacion: Any = None) -> QTableWidgetItem:
    """Crea una celda con color, tooltip y valor de ordenacion explicito."""
    item = QTableWidgetItem(str(texto))
    item.setData(Qt.UserRole, dato if dato is not None else texto)
    if color:
        item.setForeground(QBrush(QColor(color)))
    if tooltip:
        item.setToolTip(tooltip)
    if alineacion is not None:
        item.setTextAlignment(alineacion)
    return item


class TabPrincipal(TabBase):
    """Vista de detalle del ticker analizado."""

    titulo = "Principal"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)

        # ---- cabecera ----------------------------------------------------
        self._cabecera = QFrame()
        self._cabecera.setFrameShape(QFrame.StyledPanel)
        caja_cabecera = QVBoxLayout(self._cabecera)
        caja_cabecera.setContentsMargins(10, 8, 10, 8)
        caja_cabecera.setSpacing(2)
        fila = QHBoxLayout()
        self._lbl_ticker = QLabel("N/D")
        fuente_ticker = QFont()
        fuente_ticker.setPointSize(17)
        fuente_ticker.setBold(True)
        self._lbl_ticker.setFont(fuente_ticker)
        self._lbl_demo = QLabel("DEMO")
        self._lbl_demo.setStyleSheet(f"color: {AMBAR}; font-weight: bold; border: 1px solid {AMBAR}; padding: 0 6px;")
        self._lbl_demo.setToolTip("MODO DEMO: los datos mostrados son ficticios")
        self._lbl_demo.setVisible(False)
        fila.addWidget(self._lbl_ticker)
        fila.addWidget(self._lbl_demo)
        fila.addStretch(1)
        self._lbl_nombre = QLabel("")
        self._lbl_nombre.setObjectName("subtitulo")
        self._lbl_detalle = QLabel("")
        self._lbl_detalle.setObjectName("subtitulo")
        self._lbl_detalle.setWordWrap(True)
        caja_cabecera.addLayout(fila)
        caja_cabecera.addWidget(self._lbl_nombre)
        caja_cabecera.addWidget(self._lbl_detalle)
        self.add(self._cabecera)

        # ---- tarjetas del resumen ejecutivo -------------------------------
        self.add_titulo("Resumen ejecutivo", "Parametros del modelo y precios de referencia del analisis.")
        self._tarjetas = PanelTarjetas(columnas=4)
        self.add(self._tarjetas)

        # ---- parrilla de decision -----------------------------------------
        self.add_titulo(
            "Parrilla de decision (12 criterios)",
            "Verde = cumple, rojo = no cumple, ambar = N/D. El tooltip de la nota explica el motivo.",
        )
        self._aviso_parrilla = EtiquetaAviso()
        self.add(self._aviso_parrilla)
        self._panel_decision = PanelIndicadorDecision()
        self.add(self._panel_decision)
        self._tabla_criterios = TablaDML(
            COLUMNAS_CRITERIOS,
            tooltips_columnas={
                "#": "Numero de criterio segun el pliego.",
                "Criterio": "Regla binaria evaluada.",
                "Optimo": "Sentido de la comparacion.",
                "Valor obtenido": "Valor calculado para este ticker.",
                "Valor de comparacion": "Umbral o referencia contra la que se compara.",
                "Cumple": "SI cuando el criterio se cumple; NO en caso contrario.",
                "Activo": "SI cuando el criterio participa en la calificacion promedio.",
                "Calificacion": "1 punto si cumple, 0 si no cumple (N/D nunca puntua).",
                "Fuente": "Origen del dato del criterio.",
                "Ruta Investing": "URL de Investing.com donde se comprueba el dato.",
                "Nota": "Aclaracion, formula o motivo de N/D.",
            },
        )
        self._tabla_criterios.setMinimumHeight(260)
        self.add(self._tabla_criterios)

        # ---- grafico de precio --------------------------------------------
        self.add_titulo("Precio y referencias", "Cierres mensuales frente al spot, el strike (forward) y el objetivo CAPM.")
        self._aviso_grafico = EtiquetaAviso()
        self.add(self._aviso_grafico)
        self._grafico = GraficoDML(titulo="Precio", alto=4, ancho=9)
        self.add(self._grafico)

        # ---- comparativa multi-ticker -------------------------------------
        self._titulo_comparativa = QLabel("Comparativa de tickers analizados")
        self._titulo_comparativa.setObjectName("subtitulo")
        self.add(self._titulo_comparativa)
        self._tabla_comparativa = TablaDML(["Ticker", "Calificacion", "Decision"])
        self._tabla_comparativa.setMinimumHeight(140)
        self.add(self._tabla_comparativa)

        # ---- advertencias --------------------------------------------------
        self.add_titulo("Advertencias", "Avisos del analisis actual: ningun dato ausente se inventa.")
        self._avisos = EtiquetaAviso()
        self.add(self._avisos)

        # Estado interno del grafico (para poder redibujarlo al cambiar de tema).
        self._precios: Optional[pd.Series] = None
        self._referencias: Dict[str, Optional[float]] = {}
        self._moneda_codigo = "USD"
        self._simbolo = "$"

        self.cargar([], None)

    # ------------------------------------------------------------------ API
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta el resultado de ``actual`` y la comparativa de ``resultados``."""
        lista = [r for r in (resultados or []) if r is not None]
        self.resultados = lista
        self.resultado = actual if actual is not None else (lista[0] if lista else None)
        resultado = self.resultado

        self._limpiar_grafico()
        if resultado is None or self._sin_datos(resultado):
            self._pintar_sin_datos()
            self._pintar_comparativa(lista if resultado is None else [])
            return

        self._moneda_codigo = resultado.moneda or "USD"
        self._simbolo = SIMBOLOS.get(self._moneda_codigo.upper(), "$")
        self._pintar_cabecera(resultado)
        self._pintar_tarjetas(resultado)
        self._pintar_parrilla(resultado)
        self._pintar_grafico(resultado)
        self._pintar_comparativa(lista)
        self._pintar_advertencias(resultado)

    @staticmethod
    def _sin_datos(resultado: ResultadoAnalisis) -> bool:
        """True si el analisis esta vacio (sin spot, sin precios y sin criterios)."""
        sin_spot = a_float(resultado.spot) is None
        sin_precios = resultado.precios is None or len(resultado.precios) == 0
        sin_criterios = not resultado.criterios
        return sin_spot and sin_precios and sin_criterios

    def refrescar_tema(self, tema: str) -> None:
        """Redibuja el grafico de precio con la paleta del tema indicado."""
        self.tema_actual = tema
        if self._tema_graficado == tema:
            return
        try:
            # ``_dibujar_grafico`` rehace la figura (que pierde los colores del
            # tema) y ``refrescar`` los vuelve a aplicar y programa el repintado.
            self._dibujar_grafico()
            self._grafico.refrescar(tema)
            self._graficos_al_dia(tema)
        except Exception:  # pragma: no cover - defensivo
            LOG.debug("No se pudo refrescar el grafico del tema %s", tema)

    # ------------------------------------------------------------- cabecera
    def _pintar_cabecera(self, resultado: ResultadoAnalisis) -> None:
        """Rellena la cabecera con la identidad del analisis."""
        self._lbl_ticker.setText(resultado.ticker or ND)
        self._lbl_demo.setVisible(bool(resultado.demo))
        self._lbl_nombre.setText(resultado.nombre or "N/D: nombre de la empresa no disponible")
        bolsa = resultado.bolsa or ND
        moneda = resultado.moneda or ND
        fecha = resultado.fecha_analisis or ND
        modo = resultado.modo or ND
        sector = resultado.sector or ND
        self._lbl_detalle.setText(
            f"Bolsa: {bolsa} | Divisa: {moneda} | Sector: {sector} | "
            f"Fecha de analisis: {fecha} | Modo: {modo}"
        )

    # ------------------------------------------------------------- tarjetas
    def _pintar_tarjetas(self, resultado: ResultadoAnalisis) -> None:
        """Rellena la rejilla de tarjetas formateando tasas, precios y ratios."""
        resumen = resumen_ejecutivo(resultado)
        simbolo = self._simbolo
        riesgo = resultado.riesgo
        fundamentales = resultado.fundamentales

        valores: Dict[str, Any] = {
            "Spot (valor actual)": self._precio(resumen.get("Spot (valor actual)"), simbolo),
            "Strike Price (Forward)": self._precio(resumen.get("Strike Price (Forward)"), simbolo),
            "Time to Maturity (anios)": self._ratio(resumen.get("Time to Maturity (anios)"), 2),
            "Dividend (q)": self._porcentaje(resumen.get("Dividend (q)")),
            "Tasa Libre (r)": self._porcentaje(resumen.get("Tasa Libre (r)")),
            "Costo de mantener (b = r - q)": self._porcentaje(resumen.get("Costo de mantener (b = r - q)")),
            "Volatilidad (sigma anual)": self._porcentaje(resumen.get("Volatilidad (sigma anual)")),
            "Rendimiento esperado (CAPM)": self._porcentaje(resumen.get("Rendimiento esperado (CAPM)")),
        }
        tooltips = dict(FORMULAS)
        tooltips["Spot (valor actual)"] = self._tooltip_evidence(
            getattr(getattr(resultado, "_datos", None), "spot", None),
            FORMULAS["Spot (valor actual)"],
        )
        if a_float(resumen.get("Strike Price (Forward)")) is None:
            tooltips["Strike Price (Forward)"] += " N/D: faltan spot, tasa o plazo para calcular el forward."
        tooltips["Volatilidad (sigma anual)"] = (
            (riesgo.nota_sigma + " | ") if riesgo is not None and riesgo.nota_sigma else ""
        ) + FORMULAS["Volatilidad (sigma anual)"]
        if a_float(resumen.get("Volatilidad (sigma anual)")) is None:
            tooltips["Volatilidad (sigma anual)"] += " N/D: no se pudo calcular la desviacion estandar de los rendimientos."
        dividend_rate = None if fundamentales is None else a_float(fundamentales.dividend_rate)
        tooltips["Dividend (q)"] = FORMULAS["Dividend (q)"] + (
            f" Dividendo anual declarado: {fmt_moneda(dividend_rate, 2, simbolo)}."
            if dividend_rate is not None
            else " N/D: sin dato de dividendo anual; q se toma como 0 si el activo no reparte dividendo."
        )
        if a_float(resumen.get("Tasa Libre (r)")) is None:
            tooltips["Tasa Libre (r)"] += " N/D: no se pudo obtener el T-Bill de 4 semanas."
        if a_float(resumen.get("Costo de mantener (b = r - q)")) is None:
            tooltips["Costo de mantener (b = r - q)"] += " N/D: falta la tasa libre de riesgo o el dividendo."
        if a_float(resumen.get("Rendimiento esperado (CAPM)")) is None:
            tooltips["Rendimiento esperado (CAPM)"] += " N/D: falta la TLR, la Beta o la prima de riesgo."
        colores = {
            "Spot (valor actual)": GRIS if valores["Spot (valor actual)"] == ND else "",
            "Dividend (q)": GRIS if valores["Dividend (q)"] == ND else "",
            "Volatilidad (sigma anual)": GRIS if valores["Volatilidad (sigma anual)"] == ND else "",
            "Rendimiento esperado (CAPM)": GRIS if valores["Rendimiento esperado (CAPM)"] == ND else "",
        }
        self._tarjetas.cargar(valores, tooltips=tooltips, colores=colores)

    @staticmethod
    def _tooltip_evidence(evidence: Optional[Evidence], base: str) -> str:
        """Completa el tooltip de una tarjeta con la procedencia del dato."""
        if evidence is None:
            return base
        partes = [base, f"Fuente: {evidence.fuente or ND}", f"Metodo: {evidence.metodo or ND}"]
        if evidence.url:
            partes.append(f"URL: {evidence.url}")
        if evidence.consultado:
            partes.append(f"Consultado: {evidence.consultado}")
        if evidence.nota:
            partes.append(f"Nota: {evidence.nota}")
        return " | ".join(partes)

    def _precio(self, valor: Any, simbolo: Optional[str] = None) -> str:
        """Precio con dos decimales (``N/D`` si falta el dato)."""
        return fmt_moneda(valor, 2, simbolo or self._simbolo)

    def _porcentaje(self, valor: Any, decimales: int = 2) -> str:
        """Fraccion mostrada como porcentaje con dos decimales."""
        return fmt_pct(valor, decimales)

    def _ratio(self, valor: Any, decimales: int = 4) -> str:
        """Ratio o numero adimensional con cuatro decimales."""
        return fmt_num(valor, decimales)

    # -------------------------------------------------------------- parrilla
    def _pintar_parrilla(self, resultado: ResultadoAnalisis) -> None:
        """Pinta la rejilla de los 12 criterios y el panel de decision."""
        criterios: List[Criterio] = list(resultado.criterios or [])
        filas = tabla_criterios(criterios) if criterios else []
        tabla = self._tabla_criterios
        tabla.setSortingEnabled(False)
        tabla.setColumnCount(len(COLUMNAS_CRITERIOS))
        tabla.setHorizontalHeaderLabels(COLUMNAS_CRITERIOS)
        tabla.setRowCount(len(filas))
        for i, fila in enumerate(filas):
            criterio = criterios[i]
            cumple = str(fila.get("Cumple", ND))
            color = _color_cumple(cumple)
            nota = str(fila.get("Nota") or "")
            ruta = str(fila.get("Ruta Investing") or "")
            tooltip_nota = nota or "Sin nota adicional."
            if ruta:
                tooltip_nota = f"{tooltip_nota}\nRuta Investing: {ruta}"
            unidad = getattr(criterio, "unidad", "numero")
            activo = str(fila.get("Activo", ND))
            celdas = [
                _celda(str(fila.get("#", ND)), fila.get("#"), color, "Numero de criterio segun el pliego.", Qt.AlignCenter),
                _celda(str(fila.get("Criterio", ND)), fila.get("Criterio"), color, tooltip_nota, Qt.AlignLeft | Qt.AlignVCenter),
                _celda(str(fila.get("Optimo", ND)), fila.get("Optimo"), color, "Sentido de la comparacion.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(self._valor_criterio(fila.get("Valor obtenido"), unidad), fila.get("Valor obtenido"), color, tooltip_nota, Qt.AlignRight | Qt.AlignVCenter),
                _celda(self._valor_criterio(fila.get("Valor de comparacion"), unidad), fila.get("Valor de comparacion"), color, "Umbral o referencia de comparacion.", Qt.AlignRight | Qt.AlignVCenter),
                _celda(cumple, cumple, color, "SI cuando el criterio se cumple; NO en caso contrario.", Qt.AlignCenter),
                _celda(activo, activo, AMBAR if activo != "SI" else GRIS, "SI cuando el criterio participa en la calificacion promedio.", Qt.AlignCenter),
                _celda(self.num(fila.get("Calificacion"), 0), fila.get("Calificacion"), color, "1 punto si cumple, 0 si no cumple (N/D nunca puntua).", Qt.AlignRight | Qt.AlignVCenter),
                _celda(str(fila.get("Fuente") or ND), fila.get("Fuente"), color, str(fila.get("Fuente") or ND), Qt.AlignLeft | Qt.AlignVCenter),
                _celda(ruta or ND, ruta, color, ruta or "Sin ruta de Investing.com para este criterio.", Qt.AlignLeft | Qt.AlignVCenter),
                _celda(nota or ND, nota, color, tooltip_nota, Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for j, celda in enumerate(celdas):
                tabla.setItem(i, j, celda)
        # Se ordena por el numero de criterio (la tabla puede haber ordenado las
        # filas mientras se rellenaban) y solo despues se vuelve a habilitar la
        # ordenacion: activarla antes obligaria a Qt a reordenar dos veces.
        tabla.sortItems(0, Qt.AscendingOrder)
        tabla.setSortingEnabled(True)
        tabla.resizeColumnsToContents()

        if not filas:
            self._aviso_parrilla.mostrar(["N/D: no hay criterios evaluados (analisis vacio o datos insuficientes)."])
        else:
            self._aviso_parrilla.mostrar([])

        activos = [c for c in criterios if c.activo]
        cumplidos = sum(1 for c in activos if c.cumple)
        decision = resultado.decision if resultado.decision else ND
        self._panel_decision.cargar(decision, resultado.calificacion, len(activos), cumplidos)

    @staticmethod
    def _valor_criterio(valor: Any, unidad: str) -> str:
        """Formatea el valor de un criterio segun su unidad declarada."""
        if valor is None or str(valor).strip().upper() in {"", "N/D"}:
            return ND
        if unidad == "porcentaje":
            return fmt_pct(valor, 2)
        if unidad == "moneda":
            texto = fmt_moneda(valor, 2)
            return texto if texto != ND else ND
        numero = a_float(valor)
        if numero is None:
            return str(valor)
        return fmt_num(numero, 2)

    # --------------------------------------------------------------- grafico
    def _pintar_grafico(self, resultado: ResultadoAnalisis) -> None:
        """Prepara los datos del grafico de precio y lo dibuja."""
        precios = resultado.precios
        self._precios = precios if isinstance(precios, pd.Series) and len(precios) else None
        self._referencias = {
            "Spot (valor actual)": a_float(resultado.spot),
            "Strike / Forward": a_float(resultado.strike),
            "Precio objetivo CAPM": a_float(resultado.precio_objetivo),
        }
        avisos: List[str] = []
        if self._precios is None:
            avisos.append("N/D: no hay serie mensual de precios para dibujar el grafico.")
        if all(v is None for v in self._referencias.values()):
            avisos.append("N/D: no hay spot, strike ni precio objetivo para las lineas de referencia.")
        self._aviso_grafico.mostrar(avisos)
        self._dibujar_grafico()
        self._grafico.refrescar(self.tema_actual)
        self._graficos_al_dia(self.tema_actual)

    def _limpiar_grafico(self) -> None:
        """Deja el grafico en blanco con el aviso de estado vacio."""
        self._precios = None
        self._referencias = {}
        self._grafico.limpiar()
        self._grafico.ax.text(
            0.5,
            0.5,
            "Sin datos de precio para dibujar",
            ha="center",
            va="center",
            transform=self._grafico.ax.transAxes,
        )
        self._grafico.ax.set_xticks([])
        self._grafico.ax.set_yticks([])

    def _dibujar_grafico(self) -> None:
        """Dibuja los cierres mensuales y las lineas de referencia."""
        grafico = self._grafico
        grafico.limpiar()
        eje = grafico.ax
        if self._precios is None:
            eje.text(
                0.5,
                0.5,
                "N/D: serie mensual de precios no disponible",
                ha="center",
                va="center",
                transform=eje.transAxes,
            )
            eje.set_xticks([])
            eje.set_yticks([])
            return

        serie = self._precios.dropna()
        eje.plot(serie.index, serie.to_numpy(dtype="float64"), color="#4da3ff", linewidth=1.6, marker="o", markersize=2.5, label="Precio de cierre mensual")
        estilos = [
            ("Spot (valor actual)", "#31c48d", "-"),
            ("Strike / Forward", "#f2b544", "--"),
            ("Precio objetivo CAPM", "#f26d6d", ":"),
        ]
        for nombre, color, trazo in estilos:
            valor = self._referencias.get(nombre)
            if valor is None:
                continue
            eje.axhline(
                valor,
                color=color,
                linestyle=trazo,
                linewidth=1.2,
                label=f"{nombre}: {fmt_moneda(valor, 2, self._simbolo)}",
            )
        eje.set_title(f"Precio mensual de {self._titulo_grafico()}")
        eje.set_xlabel("Fecha")
        eje.set_ylabel(f"Precio ({self._simbolo})")
        eje.grid(True, alpha=0.25)
        eje.xaxis.set_major_locator(mdates.AutoDateLocator())
        eje.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        for etiqueta in eje.get_xticklabels():
            etiqueta.set_rotation(30)
            etiqueta.set_horizontalalignment("right")
        eje.legend(loc="best", fontsize=8)

    def _titulo_grafico(self) -> str:
        """Nombre del ticker para el titulo del grafico."""
        resultado = self.resultado
        return resultado.ticker if resultado is not None and resultado.ticker else ND

    # ----------------------------------------------------------- comparativa
    def _pintar_comparativa(self, resultados: Sequence[ResultadoAnalisis]) -> None:
        """Muestra la tabla comparativa solo cuando hay mas de un ticker."""
        visible = len(resultados) > 1
        self._titulo_comparativa.setVisible(visible)
        self._tabla_comparativa.setVisible(visible)
        if not visible:
            self._tabla_comparativa.setRowCount(0)
            return
        filas = [
            {
                "Ticker": r.ticker or ND,
                "Calificacion": r.calificacion,
                "Decision": r.decision or ND,
            }
            for r in resultados
        ]
        self._tabla_comparativa.formateadores = {"Calificacion": lambda v: fmt_pct(v, 2)}
        self._tabla_comparativa.colores_condicionales = lambda fila, columna, valor: self._color_decision(valor) if columna == 2 else None
        self._tabla_comparativa.cargar_filas(filas, ["Ticker", "Calificacion", "Decision"])

    @staticmethod
    def _color_decision(valor: Any) -> Optional[str]:
        """Color de la decision final."""
        texto = str(valor or "").strip().upper()
        if texto == "COMPRAR":
            return VERDE
        if texto == "MANTENER":
            return AMBAR
        if texto == "NO INVERTIR":
            return ROJO
        return GRIS

    # ------------------------------------------------------------ advertencias
    def _pintar_advertencias(self, resultado: ResultadoAnalisis) -> None:
        """Lista las advertencias del analisis o el estado sin datos."""
        avisos = list(resultado.advertencias or [])
        if resultado.spot is None:
            avisos.insert(0, "N/D: no se pudo determinar el spot.")
        if resultado.precios is None or len(resultado.precios) < 13:
            avisos.insert(0, "N/D: no hay datos suficientes (serie mensual de al menos 13 meses).")
        self._avisos.mostrar(avisos or ["Sin advertencias: el analisis no registro incidencias."])

    def _pintar_sin_datos(self) -> None:
        """Estado vacio: no hay ningun analisis cargado."""
        self._lbl_ticker.setText(ND)
        self._lbl_demo.setVisible(False)
        self._lbl_nombre.setText("")
        self._lbl_detalle.setText("Sin analisis cargado: introduce un ticker y pulsa Analizar.")
        self._tarjetas.cargar(
            {
                "Spot (valor actual)": ND,
                "Strike Price (Forward)": ND,
                "Time to Maturity (anios)": ND,
                "Dividend (q)": ND,
                "Tasa Libre (r)": ND,
                "Costo de mantener (b = r - q)": ND,
                "Volatilidad (sigma anual)": ND,
                "Rendimiento esperado (CAPM)": ND,
            },
            tooltips={clave: f"{MOTIVO_ND} | {texto}" for clave, texto in FORMULAS.items()},
            colores={clave: GRIS for clave in FORMULAS},
        )
        self._pintar_parrilla_vacia()
        self._aviso_grafico.mostrar(["N/D: no hay datos suficientes para el grafico (analisis vacio)."])
        self._avisos.mostrar(["N/D: no hay datos suficientes; todavia no se ha analizado ningun ticker."])

    def _pintar_parrilla_vacia(self) -> None:
        """Deja la parrilla sin filas y el indicador en N/D."""
        tabla = self._tabla_criterios
        tabla.setSortingEnabled(False)
        tabla.setColumnCount(len(COLUMNAS_CRITERIOS))
        tabla.setHorizontalHeaderLabels(COLUMNAS_CRITERIOS)
        tabla.setRowCount(0)
        tabla.setSortingEnabled(True)
        self._aviso_parrilla.mostrar(["N/D: no hay datos suficientes; la parrilla se mostrara tras el analisis."])
        self._panel_decision.cargar(ND, None, 0, 0)


__all__ = ["TabPrincipal"]
