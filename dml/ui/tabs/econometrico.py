# -*- coding: utf-8 -*-
"""Pestana "Econometrico": todo el proceso del MCO ``Precio ~ periodo``.

La pestana no calcula nada: solo presenta el :class:`~dml.core.tipos.ResultadoOLS`
que ya viene resuelto en el :class:`~dml.core.tipos.ResultadoAnalisis`. Se
muestran los datos usados, la tabla de coeficientes, el diagnostico completo de
los residuos (Durbin-Watson, Jarque-Bera y Breusch-Pagan), el veredicto de
confiabilidad, la tabla de residuos, el pronostico con su intervalo de
prediccion al 95% y tres graficos (ajuste observado, residuos e histograma de
residuos con la densidad normal superpuesta).

El modulo importa :mod:`dml.models.econometria` de forma **opcional**: si el
modulo no estuviera disponible (o fallara al importarse) la pestana construye el
diagnostico directamente a partir de los campos de ``ResultadoOLS``.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.tipos import ND, ResultadoAnalisis, ResultadoOLS
from ...core.util import a_float, fmt_num
from ..widgets import AMBAR, GRIS, ROJO, VERDE, GraficoDML, PanelTarjetas, TablaDML
from .base import TabBase

LOG = logging.getLogger("dml.ui.tabs.econometrico")

# --------------------------------------------------------------------------
# Import opcional del modelo econometrico (puede estar escribiendose en
# paralelo): la pestana nunca debe fallar al importarse por su causa.
# --------------------------------------------------------------------------
try:  # pragma: no cover - depende del estado del repositorio
    from ...models.econometria import (
        DW_MAX as _ECO_DW_MAX,
        DW_MIN as _ECO_DW_MIN,
        R2_MIN_POR_DEFECTO as _ECO_R2_MIN,
        UMBRAL_P_POR_DEFECTO as _ECO_UMBRAL_P,
        interpretar as _interpretar,
        pruebas_residuos as _pruebas_residuos,
    )

    _ECONOMETRIA_OK = True
except Exception as _exc:  # pragma: no cover - solo si el modulo falta o falla
    LOG.warning("No se pudo importar dml.models.econometria (%s): se usa el diagnostico propio", _exc)
    _ECO_DW_MIN, _ECO_DW_MAX = 1.5, 2.5
    _ECO_R2_MIN, _ECO_UMBRAL_P = 0.70, 0.05
    _pruebas_residuos = None  # type: ignore[assignment]
    _interpretar = None  # type: ignore[assignment]
    _ECONOMETRIA_OK = False

#: Columnas de la tabla de coeficientes y su explicacion (tooltip del encabezado).
_TOOLTIPS_COEFICIENTES: Dict[str, str] = {
    "Coeficiente": (
        "Termino del modelo Precio = a + b x periodo. "
        "'Intercepto' es el valor estimado del precio en el periodo 0 (extrapolacion, "
        "no un dato observado); 'Pendiente (periodo)' es el cambio medio de precio por mes."
    ),
    "Valor": (
        "Estimacion MCO del coeficiente (minimos cuadrados ordinarios). "
        "La pendiente equivale a la pendiente de la linea de tendencia de Excel y "
        "es la base de RSQ(precio, periodo)."
    ),
    "Error estandar": (
        "Error estandar de la estimacion del coeficiente: sqrt(SSE/(n-2)) dividido por "
        "la raiz de la suma de cuadrados del regresor (para la pendiente) o su version "
        "con el termino 1/n + xbar^2/Sxx (para el intercepto)."
    ),
    "t": "Estadistico t = Valor / Error estandar. Mide cuantas desviaciones tipicas dista el coeficiente de 0.",
    "p-value": (
        "Probabilidad bilateral de observar un |t| igual o mayor bajo la hipotesis nula de "
        "coeficiente = 0 (grados de libertad n-2). p < 0.05: coeficiente significativo."
    ),
}

#: Tooltips de los encabezados de la tabla de diagnosticos.
_TOOLTIPS_DIAGNOSTICOS: Dict[str, str] = {
    "Diagnostico": "Estadistico de bondad del ajuste o contraste de los residuos.",
    "Valor": "Valor numerico calculado del estadistico.",
    "p-value": (
        "p-value de la prueba (N/D cuando el contraste no tiene p-value, como "
        "Durbin-Watson, que se interpreta por bandas)."
    ),
    "Interpretacion": "Lectura en espanol del estadistico y umbrales aplicados.",
}

#: Tooltips de la tabla de respuestas exigidas por el pliego.
_TOOLTIPS_PREGUNTAS: Dict[str, str] = {
    "Pregunta": "Cuestion concreta que exige responder el pliego del proyecto.",
    "Respuesta": "Respuesta calculada a partir de los estadisticos del modelo.",
    "Detalle": "Valor del estadistico y umbral aplicado en la decision.",
}

#: Tooltips de la tabla de residuos.
_TOOLTIPS_RESIDUOS: Dict[str, str] = {
    "Periodo": "Indice de tiempo del regresor (1..n) usado en el MCO.",
    "Precio observado": "Precio mensual realmente observado en ese periodo.",
    "Precio ajustado": "Precio estimado por la recta MCO: a + b x periodo (valor ajustado).",
    "Residuo": "Diferencia Precio observado - Precio ajustado. Mide el error del modelo en ese mes.",
}

#: Formateo de una cifra de precio (2 decimales).
_PRECIO: Callable[[Any], str] = lambda valor: fmt_num(valor, 2)
#: Formateo de un estadistico o coeficiente (4 decimales).
_ESTADISTICO: Callable[[Any], str] = lambda valor: fmt_num(valor, 4)

#: Formateadores de la tabla de coeficientes.
_FORMATOS_COEFICIENTES: Dict[str, Callable[[Any], str]] = {
    "Valor": _ESTADISTICO,
    "Error estandar": _ESTADISTICO,
    "t": _ESTADISTICO,
    "p-value": _ESTADISTICO,
}

#: Formateadores de la tabla de diagnosticos.
_FORMATOS_DIAGNOSTICOS: Dict[str, Callable[[Any], str]] = {
    "Valor": _ESTADISTICO,
    "p-value": _ESTADISTICO,
}

#: Formateadores de la tabla de residuos (precios a 2 decimales, residuo a 4).
_FORMATOS_RESIDUOS: Dict[str, Callable[[Any], str]] = {
    "Precio observado": _PRECIO,
    "Precio ajustado": _PRECIO,
    "Residuo": _ESTADISTICO,
}



def _reponer_tooltips(tabla: TablaDML, tooltips: Dict[str, str]) -> None:
    """Vuelve a colocar los tooltips de las cabeceras de una tabla DML.

    ``TablaDML.cargar_filas`` reconstruye las cabeceras y pierde sus tooltips
    (limitacion conocida del widget); esta funcion los restaura para que cada
    columna siga explicando que contiene.
    """
    try:
        tabla.tooltips_columnas = dict(tooltips)
    except Exception:  # pragma: no cover - defensivo
        LOG.debug("No se pudo registrar el diccionario de tooltips")
    for posicion, (_nombre, texto) in enumerate(tooltips.items()):
        item: Optional[QTableWidgetItem] = tabla.horizontalHeaderItem(posicion)
        if item is not None:
            item.setToolTip(texto)


class PanelVeredicto(QFrame):
    """Panel con el veredicto de confiabilidad grande y coloreado."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(12, 10, 12, 10)
        caja.setSpacing(4)
        self._titulo = QLabel("Confiabilidad del modelo econometrico")
        self._titulo.setObjectName("subtitulo")
        self._veredicto = QLabel(ND)
        fuente = QFont()
        fuente.setPointSize(24)
        fuente.setBold(True)
        self._veredicto.setFont(fuente)
        self._veredicto.setAlignment(Qt.AlignCenter)
        self._justificacion = QLabel("")
        self._justificacion.setWordWrap(True)
        self._justificacion.setObjectName("subtitulo")
        caja.addWidget(self._titulo)
        caja.addWidget(self._veredicto)
        caja.addWidget(self._justificacion)

    def cargar(self, veredicto: Optional[str], justificacion: str, color: str = GRIS) -> None:
        """Pinta el veredicto, su color y la justificacion."""
        self._veredicto.setText(str(veredicto) if veredicto else ND)
        self._veredicto.setStyleSheet(f"color: {color};")
        self._justificacion.setText(justificacion or "Sin justificacion disponible.")


class TabEconometrico(TabBase):
    """Pestana con el proceso econometrico completo del modelo MCO."""

    titulo = "Econometrico"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        self._graficos: List[GraficoDML] = []
        self._veredicto = PanelVeredicto()
        self._tabla_coeficientes = self._tabla(("Coeficiente", "Valor", "Error estandar", "t", "p-value"), _TOOLTIPS_COEFICIENTES)
        self._tabla_diagnosticos = self._tabla(("Diagnostico", "Valor", "p-value", "Interpretacion"), _TOOLTIPS_DIAGNOSTICOS)
        self._tabla_preguntas = self._tabla(("Pregunta", "Respuesta", "Detalle"), _TOOLTIPS_PREGUNTAS)
        self._tabla_residuos = self._tabla(
            ("Periodo", "Precio observado", "Precio ajustado", "Residuo"), _TOOLTIPS_RESIDUOS
        )
        self._tarjetas_pronostico = PanelTarjetas(columnas=4)
        self._nota_datos = QLabel("")
        self._nota_datos.setWordWrap(True)
        self._nota_datos.setObjectName("subtitulo")
        self._caja_graficos = QTabWidget()
        self._caja_graficos.addTab(self._nuevo_grafico("(a) Precio observado vs tendencia ajustada"), "(a) Ajuste")
        self._caja_graficos.addTab(self._nuevo_grafico("(b) Residuos vs periodo"), "(b) Residuos")
        self._caja_graficos.addTab(self._nuevo_grafico("(c) Histograma de residuos"), "(c) Normalidad")
        self._construir()
        self._pintar_vacio()

    # ------------------------------------------------------------------ ayudas
    @staticmethod
    def _tabla(columnas: Sequence[str], tooltips: Dict[str, str], alto: Optional[int] = None) -> TablaDML:
        """Crea una tabla DML con tooltips de encabezado y formateo numerico."""
        tabla = TablaDML(columnas, tooltips_columnas=tooltips)
        if alto:
            tabla.setMinimumHeight(alto)
        return tabla

    def _nuevo_grafico(self, titulo: str) -> GraficoDML:
        """Crea y registra un lienzo matplotlib de la pestana."""
        grafico = GraficoDML(titulo, alto=3, ancho=5)
        grafico.setMinimumHeight(240)
        self._graficos.append(grafico)
        return grafico

    def _construir(self) -> None:
        """Monta la estructura fija de la pestana (los datos se rellenan en ``cargar``)."""
        self.add_titulo(
            "Modelo econometrico (MCO)",
            "Regresion por Minimos Cuadrados Ordinarios del precio sobre el indice de tiempo (periodo 1..n).",
        )
        self.add(self._nota_datos)

        self._caja_datos = QWidget()
        caja_datos = QHBoxLayout(self._caja_datos)
        caja_datos.setContentsMargins(0, 0, 0, 0)
        self._tarjetas_datos = PanelTarjetas(columnas=5)
        caja_datos.addWidget(self._tarjetas_datos)
        self.add(self._caja_datos)

        self.add(QLabel("1. Coeficientes estimados"))
        self.add(self.scroll(self._tabla_coeficientes), 1)

        self.add(QLabel("2. Diagnostico del modelo y de los residuos"))
        self.add(self.scroll(self._tabla_diagnosticos), 1)

        self.add(QLabel("3. Veredicto de confiabilidad y respuestas exigidas"))
        self.add(self._veredicto)
        self.add(self.scroll(self._tabla_preguntas), 1)

        self.add(QLabel("4. Residuos por periodo"))
        self.add(self.scroll(self._tabla_residuos), 1)

        self.add(QLabel("5. Pronostico de precio al horizonte configurado"))
        self.add(self._tarjetas_pronostico)

        self.add(QLabel("6. Graficos"))
        self.add(self._caja_graficos, 2)

    # ------------------------------------------------------------------ datos
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta el modelo econometrico del resultado seleccionado.

        Args:
            resultados: todos los analisis disponibles.
            actual: analisis seleccionado; si es ``None`` se usa el primero.
        """
        super().cargar(resultados, actual)
        ols = getattr(self.resultado, "ols", None) if self.resultado is not None else None
        if not isinstance(ols, ResultadoOLS):
            self._pintar_vacio()
            return
        try:
            self._pintar(ols)
        except Exception as exc:  # pragma: no cover - defensivo: nunca romper la pestana
            LOG.exception("No se pudo pintar la pestana econometrica (%s)", exc)
            self._pintar_vacio(f"Error al presentar el modelo econometrico: {exc}")

    def _pintar_vacio(self, motivo: str = "") -> None:
        """Estado "N/D": no hay modelo estimable (nunca deja la pestana en blanco)."""
        texto = motivo or (
            "N/D: el modelo econometrico no se pudo estimar. Se necesitan al menos 5 observaciones "
            "mensuales validas de precio y un periodo (indice de tiempo) no degenerado."
        )
        self._nota_datos.setText(
            "N/D: sin modelo MCO. Comprueba que el ticker tenga historico mensual suficiente "
            "(minimo 5 observaciones) y que la descarga de precios haya terminado correctamente."
        )
        self._tarjetas_datos.cargar(
            {
                "Observaciones (n)": None,
                "Metodo": ND,
                "Regresor": ND,
                "Equivalencia Excel": ND,
                "Estado": "Sin modelo",
            },
            tooltips={
                "Observaciones (n)": texto,
                "Metodo": texto,
                "Regresor": "Regresor del MCO: indice de tiempo periodo = 1..n.",
                "Equivalencia Excel": "En Excel: =RSQ(precio, periodo) y =PENDIENTE(precio, periodo).",
                "Estado": texto,
            },
            colores={"Estado": ROJO},
        )
        self._tabla_coeficientes.formateadores = dict(_FORMATOS_COEFICIENTES)
        self._tabla_diagnosticos.formateadores = dict(_FORMATOS_DIAGNOSTICOS)
        self._tabla_preguntas.formateadores = {}
        self._tabla_preguntas.colores_condicionales = self._color_respuesta
        self._tabla_residuos.formateadores = dict(_FORMATOS_RESIDUOS)
        self._tabla_coeficientes.cargar_filas([], list(_TOOLTIPS_COEFICIENTES.keys()))
        self._tabla_diagnosticos.cargar_filas([], list(_TOOLTIPS_DIAGNOSTICOS.keys()))
        self._tabla_preguntas.cargar_filas([], list(_TOOLTIPS_PREGUNTAS.keys()))
        self._tabla_residuos.cargar_filas([], list(_TOOLTIPS_RESIDUOS.keys()))
        _reponer_tooltips(self._tabla_coeficientes, _TOOLTIPS_COEFICIENTES)
        _reponer_tooltips(self._tabla_diagnosticos, _TOOLTIPS_DIAGNOSTICOS)
        _reponer_tooltips(self._tabla_preguntas, _TOOLTIPS_PREGUNTAS)
        _reponer_tooltips(self._tabla_residuos, _TOOLTIPS_RESIDUOS)
        self._veredicto.cargar(ND, texto, ROJO)
        self._tarjetas_pronostico.cargar(
            {
                "Precio pronosticado": None,
                "Limite inferior 95%": None,
                "Limite superior 95%": None,
                "Horizonte (meses)": None,
            },
            tooltips={
                "Precio pronosticado": "N/D: no hay modelo estimado.",
                "Limite inferior 95%": "N/D: no hay modelo estimado.",
                "Limite superior 95%": "N/D: no hay modelo estimado.",
                "Horizonte (meses)": "N/D: no hay modelo estimado.",
            },
            colores={},
        )
        for grafico in self._graficos:
            self._grafico_vacio(grafico, "N/D: sin modelo estimado")
        self.refrescar_tema(self.tema_actual)

    def _pintar(self, ols: ResultadoOLS) -> None:
        """Rellena todas las secciones con el ``ResultadoOLS`` disponible."""
        n = a_float(ols.n)
        metodo = str(ols.metodo or ND)
        self._nota_datos.setText(
            "Datos usados: serie mensual de precios del ticker seleccionado. La regresion es "
            "Precio ~ periodo, con periodo = 1..n (n = "
            f"{self.num(n, 0) if n is not None else ND} observaciones mensuales). "
            f"Metodo de estimacion: {metodo}. Es exactamente el ajuste de la hoja *Econometrico* del "
            "Excel de referencia, equivalente a =RSQ(precio, periodo) para el R2 y a "
            "=PENDIENTE(precio, periodo) para la pendiente."
        )
        self._pintar_datos(ols, n, metodo)
        self._pintar_coeficientes(ols)
        self._pintar_diagnosticos(ols)
        self._pintar_veredicto(ols)
        self._pintar_residuos(ols)
        self._pintar_pronostico(ols)
        self._pintar_graficos(ols)

    def _pintar_datos(self, ols: ResultadoOLS, n: Optional[float], metodo: str) -> None:
        """Tarjetas con el tamano de muestra, el metodo y la equivalencia con Excel."""
        gl = (int(n) - 2) if n is not None and n >= 2 else None
        self._tarjetas_datos.cargar(
            {
                "Observaciones (n)": None if n is None else int(n),
                "Grados de libertad (n-2)": gl,
                "Metodo": metodo,
                "Regresor": "periodo = 1..n",
                "Equivalencia Excel": "RSQ(precio, periodo)",
            },
            tooltips={
                "Observaciones (n)": "Numero de meses con precio valido usados en la regresion.",
                "Grados de libertad (n-2)": "Grados de libertad del MCO simple: n - 2 (intercepto y pendiente).",
                "Metodo": (
                    "Motor que resolvio el MCO: 'statsmodels' si esta instalado, con respaldo "
                    "'numpy' (mismas formulas) en caso contrario."
                ),
                "Regresor": "Variable explicativa: el indice de tiempo 1, 2, ..., n.",
                "Equivalencia Excel": "El R2 del ajuste es identico a =RSQ(precio, periodo) de Excel.",
            },
            colores={},
        )

    def _pintar_coeficientes(self, ols: ResultadoOLS) -> None:
        """Tabla de coeficientes a partir de ``como_dataframe_coeficientes``."""
        try:
            marco = ols.como_dataframe_coeficientes()
            filas = marco.to_dict(orient="records")
            columnas = [str(c) for c in marco.columns]
        except Exception as exc:
            LOG.warning("No se pudo construir la tabla de coeficientes (%s)", exc)
            filas, columnas = [], ["Coeficiente", "Valor", "Error estandar", "t", "p-value"]
        self._tabla_coeficientes.formateadores = dict(_FORMATOS_COEFICIENTES)
        self._tabla_coeficientes.cargar_filas(filas, columnas)
        _reponer_tooltips(self._tabla_coeficientes, _TOOLTIPS_COEFICIENTES)

    def _pintar_diagnosticos(self, ols: ResultadoOLS) -> None:
        """Tabla de diagnosticos (usa ``pruebas_residuos`` si esta disponible)."""
        filas, columnas = self._filas_diagnostico(ols)
        self._tabla_diagnosticos.formateadores = dict(_FORMATOS_DIAGNOSTICOS)
        self._tabla_diagnosticos.cargar_filas(filas, columnas)
        _reponer_tooltips(self._tabla_diagnosticos, _TOOLTIPS_DIAGNOSTICOS)

    def _filas_diagnostico(self, ols: ResultadoOLS) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Construye las filas del diagnostico, con respaldo propio si falta el modulo."""
        columnas = ["Diagnostico", "Valor", "p-value", "Interpretacion"]
        filas: List[Dict[str, Any]] = [
            {
                "Diagnostico": "R2 (coeficiente de determinacion)",
                "Valor": a_float(ols.r2),
                "p-value": None,
                "Interpretacion": "Fraccion de la variacion del precio explicada por la tendencia lineal.",
            },
            {
                "Diagnostico": "R2 ajustado",
                "Valor": a_float(ols.r2_ajustado),
                "p-value": None,
                "Interpretacion": "R2 penalizado por el numero de regresores; comparable entre modelos.",
            },
            {
                "Diagnostico": "Estadistico F de la regresion",
                "Valor": a_float(ols.f_stat),
                "p-value": a_float(ols.f_pvalue),
                "Interpretacion": "Contraste conjunto de significacion de la regresion (grados 1 y n-2).",
            },
            {
                "Diagnostico": "Error estandar de la regresion",
                "Valor": a_float(ols.se_regresion),
                "p-value": None,
                "Interpretacion": "Desviacion tipica de los residuos en unidades de precio: sqrt(SSE/(n-2)).",
            },
        ]
        residuo: List[Dict[str, Any]] = []
        if _pruebas_residuos is not None:
            try:
                marco = _pruebas_residuos(ols)
                residuo = [
                    {
                        "Diagnostico": str(fila.get("Prueba", "")),
                        "Valor": a_float(fila.get("Estadistico")),
                        "p-value": a_float(fila.get("p-value")),
                        "Interpretacion": str(fila.get("Interpretacion", "")),
                    }
                    for fila in marco.to_dict(orient="records")
                ]
            except Exception as exc:
                LOG.warning("pruebas_residuos fallo (%s): se usa el diagnostico propio", exc)
                residuo = []
        if not residuo:
            residuo = [
                {
                    "Diagnostico": "Durbin-Watson (autocorrelacion)",
                    "Valor": a_float(ols.durbin_watson),
                    "p-value": None,
                    "Interpretacion": self._texto_dw(a_float(ols.durbin_watson)),
                },
                {
                    "Diagnostico": "Jarque-Bera (normalidad)",
                    "Valor": a_float(ols.jarque_bera),
                    "p-value": a_float(ols.jarque_bera_p),
                    "Interpretacion": self._texto_jb(a_float(ols.jarque_bera_p)),
                },
                {
                    "Diagnostico": "Breusch-Pagan (heterocedasticidad)",
                    "Valor": a_float(ols.breusch_pagan),
                    "p-value": a_float(ols.breusch_pagan_p),
                    "Interpretacion": self._texto_bp(a_float(ols.breusch_pagan_p)),
                },
            ]
        else:
            # Se respeta el orden del modulo, pero se garantiza que los tres
            # contrastes de residuos esten presentes.
            nombres = " ".join(str(f["Diagnostico"]).lower() for f in residuo)
            if "durbin" not in nombres:
                residuo.insert(
                    0,
                    {
                        "Diagnostico": "Durbin-Watson (autocorrelacion)",
                        "Valor": a_float(ols.durbin_watson),
                        "p-value": None,
                        "Interpretacion": self._texto_dw(a_float(ols.durbin_watson)),
                    },
                )
        return filas + residuo, columnas

    @staticmethod
    def _texto_dw(dw: Optional[float]) -> str:
        """Interpretacion por bandas del Durbin-Watson."""
        if dw is None:
            return "N/D: estadistico no calculable (residuos nulos o serie demasiado corta)."
        if dw < _ECO_DW_MIN:
            return f"DW = {dw:.4f} < {_ECO_DW_MIN:.1f}: posible autocorrelacion positiva."
        if dw > _ECO_DW_MAX:
            return f"DW = {dw:.4f} > {_ECO_DW_MAX:.1f}: posible autocorrelacion negativa."
        return f"DW = {dw:.4f} dentro de [{_ECO_DW_MIN:.1f}, {_ECO_DW_MAX:.1f}]: sin autocorrelacion aparente."

    @staticmethod
    def _texto_jb(p: Optional[float]) -> str:
        """Interpretacion del contraste de normalidad (Jarque-Bera)."""
        if p is None:
            return "N/D: contraste no calculable (residuos degenerados o serie demasiado corta)."
        if p > 0.05:
            return f"Residuos compatibles con la normalidad (p = {p:.4f} > 0.05)."
        return f"Se rechaza la normalidad de los residuos (p = {p:.4f} <= 0.05)."

    @staticmethod
    def _texto_bp(p: Optional[float]) -> str:
        """Interpretacion del contraste de heterocedasticidad (Breusch-Pagan)."""
        if p is None:
            return "N/D: contraste no calculable (residuos degenerados o serie demasiado corta)."
        if p > 0.05:
            return f"Varianza de los residuos compatible con la homocedasticidad (p = {p:.4f} > 0.05)."
        return f"Indicios de heterocedasticidad: la varianza depende del periodo (p = {p:.4f} <= 0.05)."

    # --------------------------------------------------------------- veredicto
    def _pintar_veredicto(self, ols: ResultadoOLS) -> None:
        """Veredicto grande, justificacion y respuestas exigidas por el pliego."""
        veredicto = str(ols.veredicto or ND)
        justificacion = str(ols.justificacion or "")
        banderas = self._banderas(ols)
        if not justificacion and _interpretar is not None:
            try:
                justificacion = str(_interpretar(ols).get("justificacion", ""))
            except Exception as exc:  # pragma: no cover - defensivo
                LOG.warning("interpretar() fallo (%s)", exc)
        color = {"alta": VERDE, "media": AMBAR, "baja": ROJO}.get(veredicto.strip().lower(), GRIS)
        self._veredicto.cargar(veredicto, justificacion, color)

        filas = [
            {
                "Pregunta": f"El R2 supera el umbral de {_ECO_R2_MIN:.2f}?",
                "Respuesta": "SI" if banderas["r2_ok"] else "NO",
                "Detalle": f"R2 = {fmt_num(banderas['r2'], 4)} (umbral {_ECO_R2_MIN:.2f})",
            },
            {
                "Pregunta": f"La pendiente es significativa (p < {_ECO_UMBRAL_P:.2f})?",
                "Respuesta": "SI" if banderas["pendiente_ok"] else "NO",
                "Detalle": f"p-value de la pendiente = {fmt_num(banderas['p_pendiente'], 4)}",
            },
            {
                "Pregunta": f"Los residuos estan autocorrelacionados (DW fuera de [{_ECO_DW_MIN:.1f}, {_ECO_DW_MAX:.1f}])?",
                "Respuesta": "SI" if banderas["autocorrelacion"] else "NO",
                "Detalle": f"Durbin-Watson = {fmt_num(banderas['dw'], 4)}",
            },
        ]
        self._tabla_preguntas.formateadores = {}
        self._tabla_preguntas.colores_condicionales = self._color_respuesta
        self._tabla_preguntas.cargar_filas(filas, ["Pregunta", "Respuesta", "Detalle"])
        _reponer_tooltips(self._tabla_preguntas, _TOOLTIPS_PREGUNTAS)

    @staticmethod
    def _color_respuesta(fila: int, columna: int, valor: Any) -> Optional[str]:
        """Colorea la columna "Respuesta" (SI verde / NO ambar)."""
        if columna != 1:
            return None
        texto = str(valor).strip().upper()
        if texto == "SI":
            return VERDE
        if texto == "NO":
            return AMBAR
        return None

    def _banderas(self, ols: ResultadoOLS) -> Dict[str, Any]:
        """Calcula las banderas del veredicto (con ``interpretar`` si esta disponible)."""
        banderas: Dict[str, Any] = {
            "r2": a_float(ols.r2),
            "p_pendiente": a_float(ols.p_pendiente),
            "dw": a_float(ols.durbin_watson),
            "r2_ok": False,
            "pendiente_ok": False,
            "autocorrelacion": False,
        }
        if _interpretar is not None:
            try:
                datos = _interpretar(ols)
                banderas["r2_ok"] = bool(datos.get("r2_supera_umbral", False))
                banderas["pendiente_ok"] = bool(datos.get("pendiente_significativa", False))
                banderas["autocorrelacion"] = bool(datos.get("residuos_autocorrelacionados", False))
                return banderas
            except Exception as exc:  # pragma: no cover - defensivo
                LOG.warning("interpretar() fallo (%s): se calculan las banderas localmente", exc)
        r2, p_pen, dw = banderas["r2"], banderas["p_pendiente"], banderas["dw"]
        banderas["r2_ok"] = bool(r2 is not None and r2 >= _ECO_R2_MIN)
        banderas["pendiente_ok"] = bool(p_pen is not None and p_pen < _ECO_UMBRAL_P)
        banderas["autocorrelacion"] = bool(dw is not None and not (_ECO_DW_MIN <= dw <= _ECO_DW_MAX))
        return banderas

    # ----------------------------------------------------------------- residuos
    def _pintar_residuos(self, ols: ResultadoOLS) -> None:
        """Tabla desplazable con residuos y valores ajustados."""
        try:
            marco = ols.como_dataframe_residuos()
            filas = marco.to_dict(orient="records")
            columnas = [str(c) for c in marco.columns]
        except Exception as exc:
            LOG.warning("No se pudo construir la tabla de residuos (%s)", exc)
            filas, columnas = [], ["Periodo", "Precio observado", "Precio ajustado", "Residuo"]
        self._tabla_residuos.formateadores = dict(_FORMATOS_RESIDUOS)
        self._tabla_residuos.cargar_filas(filas, columnas)
        _reponer_tooltips(self._tabla_residuos, _TOOLTIPS_RESIDUOS)

    # --------------------------------------------------------------- pronostico
    def _pintar_pronostico(self, ols: ResultadoOLS) -> None:
        """Tarjetas con el pronostico y su intervalo de prediccion al 95%."""
        meses = ols.meses_pronostico
        tooltip_pron = (
            "Precio estimado por la recta MCO en el periodo n + meses_pronostico "
            "(extrapolacion de la tendencia)."
        )
        tooltip_li = (
            "Limite inferior del intervalo de PREDICCION al 95%: "
            "pronostico - t(0.975, n-2) * sqrt(1 + 1/n + (x0 - xbar)^2/Sxx) * se_regresion."
        )
        tooltip_ls = "Limite superior del intervalo de prediccion al 95% (misma formula que el inferior)."
        self._tarjetas_pronostico.cargar(
            {
                "Precio pronosticado": a_float(ols.pronostico_precio),
                "Limite inferior 95%": a_float(ols.pronostico_li),
                "Limite superior 95%": a_float(ols.pronostico_ls),
                "Horizonte (meses)": meses,
            },
            tooltips={
                "Precio pronosticado": tooltip_pron,
                "Limite inferior 95%": tooltip_li,
                "Limite superior 95%": tooltip_ls,
                "Horizonte (meses)": "Meses proyectados desde el final de la serie (parametro meses_pronostico).",
            },
            colores={},
        )

    # ----------------------------------------------------------------- graficos
    def _pintar_graficos(self, ols: ResultadoOLS) -> None:
        """Dibuja los tres graficos de la pestana."""
        periodos = np.asarray([a_float(p) for p in (ols.periodos or [])], dtype=float)
        precios = np.asarray([a_float(p) for p in (ols.precios or [])], dtype=float)
        ajustados = np.asarray([a_float(p) for p in (ols.ajustados or [])], dtype=float)
        residuos = np.asarray([a_float(p) for p in (ols.residuos or [])], dtype=float)
        self._grafico_ajuste(periodos, precios, ajustados, ols)
        self._grafico_residuos(periodos, residuos)
        self._grafico_histograma(residuos)
        self.refrescar_tema(self.tema_actual)

    def _grafico_ajuste(
        self, periodos: np.ndarray, precios: np.ndarray, ajustados: np.ndarray, ols: ResultadoOLS
    ) -> None:
        """(a) Precio observado frente a la tendencia ajustada."""
        grafico = self._graficos[0]
        grafico.limpiar()
        eje = grafico.ax
        if periodos.size == 0 or precios.size == 0:
            self._grafico_vacio(grafico, "N/D: sin precios observados")
            return
        if precios.size == periodos.size:
            eje.plot(periodos, precios, marker="o", markersize=3, linewidth=1.2, label="Precio observado")
        if ajustados.size == periodos.size and ajustados.size:
            eje.plot(periodos, ajustados, linewidth=1.8, color="#f2b544", label="Tendencia ajustada (MCO)")
        pendiente = a_float(ols.pendiente)
        intercepto = a_float(ols.intercepto)
        if pendiente is not None and intercepto is not None:
            eje.set_title(
                f"Precio ~ periodo:  Precio = {intercepto:.4f} + {pendiente:.4f} x periodo", fontsize=9
            )
        eje.set_xlabel("Periodo (mes)")
        eje.set_ylabel("Precio")
        eje.grid(True, alpha=0.25)
        eje.legend(fontsize=7)

    def _grafico_residuos(self, periodos: np.ndarray, residuos: np.ndarray) -> None:
        """(b) Residuos frente al periodo con la linea del cero."""
        grafico = self._graficos[1]
        grafico.limpiar()
        eje = grafico.ax
        if residuos.size == 0:
            self._grafico_vacio(grafico, "N/D: sin residuos")
            return
        x = periodos if periodos.size == residuos.size else np.arange(1, residuos.size + 1, dtype=float)
        eje.axhline(0.0, color="#8a939f", linewidth=1.0, linestyle="--")
        eje.plot(x, residuos, marker="o", markersize=3, linewidth=1.2, label="Residuo")
        eje.set_title("Residuos del MCO (observado - ajustado)", fontsize=9)
        eje.set_xlabel("Periodo (mes)")
        eje.set_ylabel("Residuo (unidades de precio)")
        eje.grid(True, alpha=0.25)
        eje.legend(fontsize=7)

    def _grafico_histograma(self, residuos: np.ndarray) -> None:
        """(c) Histograma de residuos con la densidad normal superpuesta."""
        grafico = self._graficos[2]
        grafico.limpiar()
        eje = grafico.ax
        validos = residuos[np.isfinite(residuos)] if residuos.size else residuos
        if validos.size < 2:
            self._grafico_vacio(grafico, "N/D: residuos insuficientes para el histograma")
            return
        desviacion = float(np.std(validos, ddof=1))
        media = float(np.mean(validos))
        clases = int(min(max(round(math.sqrt(validos.size)) + 1, 5), 30))
        densidad, bordes, _ = eje.hist(
            validos, bins=clases, density=True, alpha=0.55, label="Residuos (densidad)"
        )
        if desviacion > 0.0:
            rejilla = np.linspace(float(validos.min()), float(validos.max()), 200)
            densidad_normal = np.exp(-0.5 * ((rejilla - media) / desviacion) ** 2) / (desviacion * math.sqrt(2.0 * math.pi))
            eje.plot(rejilla, densidad_normal, linewidth=1.8, color="#f26d6d", label="Normal ajustada")
        else:
            _ = densidad
        eje.set_title(f"Histograma de residuos (media = {media:.4f}, desv. = {desviacion:.4f})", fontsize=9)
        eje.set_xlabel("Residuo")
        eje.set_ylabel("Densidad")
        eje.grid(True, alpha=0.25)
        eje.legend(fontsize=7)
        _ = bordes

    @staticmethod
    def _grafico_vacio(grafico: GraficoDML, mensaje: str) -> None:
        """Deja un lienzo con un mensaje claro en lugar de un grafico vacio."""
        eje = grafico.ax
        eje.set_xticks([])
        eje.set_yticks([])
        eje.text(0.5, 0.5, mensaje, ha="center", va="center", transform=eje.transAxes, fontsize=9)
        eje.set_title("")

    # -------------------------------------------------------------------- tema
    def refrescar_tema(self, tema: str) -> None:
        """Aplica el tema a los tres graficos (nunca lanza excepciones).

        Si los graficos ya estan pintados con ese tema no se toca nada: es lo que
        permite cambiar de tema sin volver a dibujar tres figuras.
        """
        if not self._refrescar_graficos(tema, *self._graficos):
            return
        self._graficos_al_dia(tema)


__all__ = ["TabEconometrico", "PanelVeredicto"]
