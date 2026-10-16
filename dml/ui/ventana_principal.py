# -*- coding: utf-8 -*-
"""Ventana principal de DML-FINANCE.

Contiene la barra superior fija, el panel lateral de historial, el panel de
parametros, las pestanas de resultados y la barra de estado. Coordina los hilos
de descarga y calculo, la exportacion opcional a Excel y el cambio de tema.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QWidget,
)

from ..analisis import texto_estado
from ..core.config import cargar_config, guardar_tema
from ..core.tipos import Fuentes, ResultadoAnalisis
from ..core.util import a_float
from .paneles import PanelHistorial, PanelParametros
from .widgets import EtiquetaAviso, aplicar_icono, aplicar_tema_global
from .worker import TrabajadorAnalisis, TrabajadorExcel, TrabajadorRecalculo

LOG = logging.getLogger("dml.ui.ventana")

MESES_DEFECTO = 60

#: Cada cuanto avanza la barra de progreso entre dos avisos reales del hilo.
#: Sin esto, un paso lento (descargar la serie mensual) deja la barra parada y
#: parece que el analisis se ha colgado.
MS_LATIDO_PROGRESO = 120
#: Avance maximo del latido por tic (1,2 % cada 120 ms ≈ 10 %/s como tope).
AVANCE_LATIDO = 0.012
#: La barra nunca se muestra por encima de este valor mientras se trabaja: el
#: 100 % se reserva para cuando el analisis ha terminado de verdad.
TOPE_TRABAJANDO = 99

#: Traduccion de la etiqueta de una tasa a la clave usada en los overrides.
CLAVES_MANUALES: Dict[str, str] = {
    "T-Bill EE.UU. 4 semanas (TLR)": "tbill_4w",
    "Bono EE.UU. 10 anios": "ust_10y",
    "Bono EE.UU. 30 anios": "ust_30y",
}


class VentanaPrincipal(QMainWindow):
    """Ventana principal de la aplicacion.

    Args:
        config: configuracion efectiva (se carga ``config.yaml`` si es ``None``).
        cache: cache local por dia.
        demo: si es ``True``, el boton "Analizar" usa datos ficticios.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, cache: Optional[Any] = None, demo: bool = False) -> None:
        super().__init__()
        self.config: Dict[str, Any] = config or cargar_config()
        self.cache = cache
        self.demo = bool(demo)
        self.tema = str(((self.config.get("ui") or {}).get("tema", "oscuro")))
        self.fuentes: Fuentes = Fuentes()
        self.resultados: List[ResultadoAnalisis] = []
        #: Valores de tasas introducidos manualmente por el usuario.
        self.manuales: Dict[str, float] = {}
        self._trabajador: Optional[TrabajadorAnalisis] = None
        self._trabajador_recalculo: Optional[TrabajadorRecalculo] = None
        self._trabajador_excel: Optional[TrabajadorExcel] = None
        #: Ultima fraccion comunicada por el hilo de analisis (techo del latido).
        self._progreso_techo = 0.0
        #: Fraccion que se esta mostrando en la barra.
        self._progreso_mostrado = 0.0
        #: Overrides que llegaron mientras se recalculaba (se aplican al terminar).
        self._recalculo_pendiente: Optional[Dict[str, Any]] = None
        self._latido = QTimer(self)
        self._latido.setInterval(MS_LATIDO_PROGRESO)
        self._latido.timeout.connect(self._tic_progreso)

        self.setWindowTitle("DML-FINANCE - Analizador cuantitativo y parrilla de decision")
        self.resize(1500, 950)
        aplicar_icono(self)

        self._crear_barra_superior()
        self._crear_paneles()
        self._crear_pestanas()
        self._crear_barra_estado()
        self._conectar_acciones()

        # El QSS se aplica una sola vez, y antes de que la ventana se muestre:
        # asi el primer pintado ya lo lleva y no hay que repintar todo despues.
        aplicar_tema_global(QApplication.instance(), self.tema)
        self._refrescar_titulo_tema()

    # ------------------------------------------------------------------ barra
    def _crear_barra_superior(self) -> None:
        """Crea la barra superior fija con los controles del pliego."""
        barra = QToolBar("Principal")
        barra.setMovable(False)
        self.addToolBar(barra)

        barra.addWidget(QLabel(" Ticker: "))
        self.campo_ticker = QLineEdit()
        self.campo_ticker.setPlaceholderText("NVDA, AAPL, MSFT... (varios separados por comas)")
        self.campo_ticker.setFixedWidth(240)
        self.campo_ticker.setToolTip("Escribe uno o varios tickers separados por comas y pulsa Analizar (o Enter)")
        self.campo_ticker.returnPressed.connect(self.analizar)
        barra.addWidget(self.campo_ticker)

        self.boton_analizar = QPushButton("Analizar")
        self.boton_analizar.setObjectName("principal")
        self.boton_analizar.setToolTip("Descarga los datos y calcula todos los modelos (Enter)")
        barra.addWidget(self.boton_analizar)

        barra.addWidget(QLabel("  Modo: "))
        self.combo_modo = QComboBox()
        self.combo_modo.addItem("estandar", "estandar")
        self.combo_modo.addItem("excel", "excel")
        self.combo_modo.setToolTip(
            "estandar: formulas corregidas [ESTANDAR]. excel: replica la metodologia del libro de referencia, incluidas sus inconsistencias"
        )
        # El modo inicial sale de config.yaml (o de --modo en la linea de comandos).
        general = self.config.get("general") or {}
        posicion_modo = self.combo_modo.findData(str(general.get("modo", "estandar")))
        self.combo_modo.setCurrentIndex(posicion_modo if posicion_modo >= 0 else 0)
        barra.addWidget(self.combo_modo)

        barra.addWidget(QLabel("  Indice: "))
        self.combo_indice = QComboBox()
        for simbolo in ("^GSPC", "^IXIC", "^DJI"):
            self.combo_indice.addItem(simbolo, simbolo)
        self.combo_indice.setToolTip("Indice de mercado para la Beta y la prima de riesgo")
        posicion_indice = self.combo_indice.findData(str(general.get("indice", "^GSPC")))
        self.combo_indice.setCurrentIndex(posicion_indice if posicion_indice >= 0 else 0)
        barra.addWidget(self.combo_indice)

        barra.addWidget(QLabel("  Meses: "))
        self.spin_meses = QSpinBox()
        self.spin_meses.setRange(12, 240)
        self.spin_meses.setValue(int((self.config.get("general") or {}).get("meses", MESES_DEFECTO) or MESES_DEFECTO))
        self.spin_meses.setToolTip("Meses de historico mensual (por defecto 60)")
        barra.addWidget(self.spin_meses)

        self.boton_actualizar = QPushButton("Actualizar datos")
        self.boton_actualizar.setToolTip("Ignora la cache y vuelve a descargar todo")
        barra.addWidget(self.boton_actualizar)

        self.boton_exportar = QPushButton("Exportar a Excel")
        self.boton_exportar.setToolTip(
            "Genera un .xlsx replicando las pestanas. Es la UNICA accion que escribe un archivo en disco."
        )
        barra.addWidget(self.boton_exportar)

        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setEnabled(False)
        self.boton_cancelar.setToolTip("Detiene el analisis en curso")
        barra.addWidget(self.boton_cancelar)

        barra.addSeparator()
        self.boton_tema = QPushButton("Tema claro" if self.tema == "oscuro" else "Tema oscuro")
        barra.addWidget(self.boton_tema)

        self.boton_cache = QPushButton("Limpiar cache")
        self.boton_cache.setToolTip("Borra la cache local por dia de la aplicacion")
        barra.addWidget(self.boton_cache)

    # --------------------------------------------------------------- paneles
    #: Ancho minimo de los paneles laterales (por debajo, sus campos se cortan).
    ANCHO_PANEL = 310

    def _crear_paneles(self) -> None:
        """Crea el panel lateral de historial y el de parametros."""
        self.historial = PanelHistorial()
        self.historial.setMinimumWidth(self.ANCHO_PANEL)
        dock_historial = QDockWidget("Historial de analisis", self)
        dock_historial.setWidget(self.historial)
        dock_historial.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock_historial.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_historial)
        self.dock_historial = dock_historial

        self.parametros = PanelParametros(self.config)
        self.parametros.setMinimumWidth(self.ANCHO_PANEL)
        dock_parametros = QDockWidget("Parametros", self)
        dock_parametros.setWidget(self.parametros)
        dock_parametros.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock_parametros.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_parametros)
        self.dock_parametros = dock_parametros

    # -------------------------------------------------------------- pestanas
    def _crear_pestanas(self) -> None:
        """Crea todas las pestanas de resultados, tolerando modulos ausentes."""
        self.pestanas = QTabWidget()
        self.pestanas.setMovable(False)
        self.pestanas.setDocumentMode(True)
        self.avisos = EtiquetaAviso()
        self.avisos.setVisible(False)

        contenedor = QWidget()
        from PySide6.QtWidgets import QVBoxLayout

        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(4, 4, 4, 4)
        caja.addWidget(self.pestanas, 1)
        caja.addWidget(self.avisos)
        self.setCentralWidget(contenedor)

        self.tabs: Dict[str, Any] = {}
        for nombre, fabrica in self._fabricas_pestanas():
            try:
                pestana = fabrica(self.config)
                self.pestanas.addTab(pestana, pestana.titulo if hasattr(pestana, "titulo") else nombre)
                self.tabs[nombre] = pestana
            except Exception as exc:  # pragma: no cover - proteccion de la interfaz
                LOG.error("No se pudo crear la pestana %s: %s", nombre, exc)
                from .tabs.base import TabMensaje

                self.pestanas.addTab(TabMensaje(f"No se pudo crear la pestana {nombre}: {exc}", self.config), nombre)
        if self.demo:
            self.avisos.mostrar(["MODO DEMO: los datos mostrados son ficticios y sirven para probar la interfaz"])
            self.avisos.setVisible(True)

    def _fabricas_pestanas(self) -> List[Any]:
        """Devuelve la lista ``(nombre, fabrica)`` de las 11 pestanas del pliego."""
        from .tabs.base import TabMensaje
        from .tabs.bonos import TabBonos
        from .tabs.capm import TabCAPM
        from .tabs.econometrico import TabEconometrico
        from .tabs.eps import TabEPS
        from .tabs.fuentes import TabFuentes
        from .tabs.griegas import TabGriegas
        from .tabs.per import TabPER
        from .tabs.pfcf import TabPFCF
        from .tabs.principal import TabPrincipal
        from .tabs.rdr import TabRDR
        from .tabs.renta_per import TabRentaPER

        return [
            ("principal", TabPrincipal),
            ("econometrico", TabEconometrico),
            ("griegas", TabGriegas),
            ("capm", TabCAPM),
            ("per", TabPER),
            ("eps", TabEPS),
            ("pfcf", TabPFCF),
            ("renta_per", TabRentaPER),
            ("rdr", TabRDR),
            ("bonos", TabBonos),
            ("fuentes", TabFuentes),
        ]

    # ----------------------------------------------------------- barra estado
    def _crear_barra_estado(self) -> None:
        """Crea la barra de estado con el progreso, su porcentaje y el mensaje."""
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.progreso.setValue(0)
        self.progreso.setFixedWidth(220)
        self.progreso.setFormat("%p %")  # el porcentaje se muestra DENTRO de la barra
        self.progreso.setVisible(False)
        # Etiqueta de porcentaje independiente: se lee aunque la barra este oculta
        # o el estilo no dibuje el texto del chunk.
        self.etiqueta_progreso = QLabel("")
        self.etiqueta_progreso.setObjectName("subtitulo")
        self.etiqueta_progreso.setMinimumWidth(46)
        self.etiqueta_progreso.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.etiqueta_progreso.setVisible(False)
        self.etiqueta_estado = QLabel("Listo. Escribe un ticker y pulsa Analizar.")
        self.statusBar().addWidget(self.etiqueta_estado, 1)
        self.statusBar().addPermanentWidget(self.etiqueta_progreso)
        self.statusBar().addPermanentWidget(self.progreso)

    def _conectar_acciones(self) -> None:
        """Conecta las senales de los controles con sus manejadores."""
        self.boton_analizar.clicked.connect(self.analizar)
        self.boton_actualizar.clicked.connect(lambda: self.analizar(ignorar_cache=True))
        self.boton_cancelar.clicked.connect(self.cancelar)
        self.boton_exportar.clicked.connect(self.exportar_excel)
        self.boton_tema.clicked.connect(self.cambiar_tema)
        self.boton_cache.clicked.connect(self.limpiar_cache)
        self.historial.seleccionado.connect(self._seleccionar_historial)
        self.parametros.cambio.connect(self._recalcular)
        self.combo_modo.currentIndexChanged.connect(self._recalcular)
        self.combo_indice.currentIndexChanged.connect(self._recalcular)
        self.spin_meses.valueChanged.connect(self._recalcular)

        atajo = QAction("Analizar", self)
        atajo.setShortcut(QKeySequence("Ctrl+Return"))
        atajo.triggered.connect(self.analizar)
        self.addAction(atajo)

        atajo_excel = QAction("Exportar", self)
        atajo_excel.setShortcut(QKeySequence("Ctrl+E"))
        atajo_excel.triggered.connect(self.exportar_excel)
        self.addAction(atajo_excel)

    # ------------------------------------------------------------- analisis
    def _tickers(self) -> List[str]:
        """Tickers escritos en el campo de texto (separados por comas o espacios)."""
        texto = self.campo_ticker.text().replace(";", ",").replace(" ", ",")
        return [t.strip().upper() for t in texto.split(",") if t.strip()]

    def analizar(self, ignorar_cache: bool = False) -> None:
        """Lanza el analisis de los tickers indicados en un hilo aparte."""
        tickers = self._tickers()
        if not tickers and not self.demo:
            QMessageBox.information(self, "Falta el ticker", "Escribe al menos un ticker (por ejemplo NVDA).")
            return
        if self._trabajador is not None and self._trabajador.isRunning():
            QMessageBox.information(self, "Analisis en curso", "Espera a que termine el analisis actual o pulsalo a Cancelar.")
            return
        if ignorar_cache and self.cache is not None:
            self.cache.destruir()
            self.etiqueta_estado.setText("Cache borrada: se descargaran todos los datos de nuevo.")
        if ignorar_cache:
            # Al forzar la actualizacion se reintenta tambien FRED, que pudo
            # haberse marcado como no disponible en un analisis anterior.
            from ..data.proveedores import reiniciar_estado_fred

            reiniciar_estado_fred()

        overrides = self._overrides_actuales()
        self._set_ocupado(True)
        self._reiniciar_progreso(len(tickers or ["DEMO"]))
        self.etiqueta_estado.setText("Iniciando analisis...")

        self._trabajador = TrabajadorAnalisis(
            tickers or ["DEMO"], self.config, cache=self.cache, overrides=overrides, demo=self.demo, parent=self
        )
        self._trabajador.progreso.connect(self._actualizar_progreso)
        self._trabajador.estado.connect(self.etiqueta_estado.setText)
        self._trabajador.ticker_terminado.connect(self._ticker_terminado)
        self._trabajador.terminado_ok.connect(self._analisis_terminado)
        self._trabajador.fallo.connect(self._analisis_fallido)
        self._trabajador.start()

    def cancelar(self) -> None:
        """Pide la cancelacion del analisis en curso."""
        if self._trabajador is not None and self._trabajador.isRunning():
            self._trabajador.cancelar()
            self.etiqueta_estado.setText("Cancelando analisis...")

    def _overrides_actuales(self) -> Dict[str, Any]:
        """Overrides combinados del panel de parametros y de la barra superior."""
        overrides = dict(self.parametros.overrides())
        overrides["modo"] = self.combo_modo.currentData() or "estandar"
        overrides["indice"] = self.combo_indice.currentData() or "^GSPC"
        overrides["meses"] = int(self.spin_meses.value())
        manuales = getattr(self, "manuales", None)
        if manuales:
            overrides["manuales"] = dict(manuales)
        return overrides

    def _actualizar_progreso(self, mensaje: str, fraccion: float) -> None:
        """Recibe el avance real del hilo y lo refleja en la barra y el porcentaje."""
        self._progreso_techo = max(0.0, min(1.0, float(fraccion)))
        # Un aviso real nunca hace retroceder la barra (el latido puede haber
        # avanzado mas que la medida exacta del siguiente paso).
        if self._progreso_techo > self._progreso_mostrado:
            self._pintar_progreso(self._progreso_techo)
        self.etiqueta_estado.setText(mensaje)

    def _pintar_progreso(self, fraccion: float) -> None:
        """Escribe la fraccion en la barra y en la etiqueta de porcentaje."""
        self._progreso_mostrado = fraccion
        porcentaje = int(round(max(0.0, min(1.0, fraccion)) * 100))
        self.progreso.setValue(porcentaje)
        self.etiqueta_progreso.setText(f"{porcentaje} %")

    def _tic_progreso(self) -> None:
        """Avanza la barra poco a poco mientras el paso real siga en marcha.

        Sin este latido, un paso largo (la descarga de la serie mensual, la de
        Investing.com) deja la barra clavada y parece que la aplicacion se ha
        quedado parada. El avance nunca alcanza el 100 %: ese valor se reserva
        para cuando el analisis termina de verdad.
        """
        if self._trabajador is None or not self._trabajador.isRunning():
            self._latido.stop()
            return
        if self._progreso_mostrado >= self._progreso_techo:
            # Ya se muestra todo lo que el hilo ha confirmado: avanzar ahora
            # seria inventar progreso, asi que solo se espera.
            return
        objetivo = min(self._progreso_techo, self._progreso_mostrado + AVANCE_LATIDO, TOPE_TRABAJANDO / 100.0)
        self._pintar_progreso(objetivo)

    def _reiniciar_progreso(self, total: int) -> None:
        """Deja la barra a cero, visible y latiendo para un analisis nuevo."""
        self._progreso_techo = 0.0
        self._pintar_progreso(0.0)
        self.progreso.setVisible(True)
        self.etiqueta_progreso.setVisible(True)
        self._latido.start()

    def _concluir_progreso(self) -> None:
        """Muestra el 100 % un instante y oculta la barra al terminar."""
        self._latido.stop()
        self._pintar_progreso(1.0)
        QTimer.singleShot(900, self._ocultar_progreso)

    def _ocultar_progreso(self) -> None:
        """Oculta la barra de progreso cuando ya no hay trabajo en curso."""
        if self._trabajador is not None and self._trabajador.isRunning():
            return
        self.progreso.setVisible(False)
        self.etiqueta_progreso.setVisible(False)

    def _ticker_terminado(self, ticker: str, completados: int, total: int) -> None:
        """Informa del avance entre tickers sin repintar toda la interfaz.

        Los resultados se pintan de una vez al final: repintar las 11 pestanas
        por cada ticker multiplicaria el trabajo sin aportar nada.
        """
        self.etiqueta_estado.setText(f"{ticker}: analizado ({completados} de {max(total, 1)})")

    def _analisis_terminado(self, resultados: List[ResultadoAnalisis], fuentes: Fuentes) -> None:
        """Recibe los resultados del hilo y rellena todas las pestanas."""
        self._set_ocupado(False)
        self._concluir_progreso()
        self.resultados = list(resultados)
        self.fuentes = fuentes if fuentes is not None else Fuentes()
        # Se anaden todos los analisis de golpe y con las senales del historial
        # bloqueadas: cada ``setCurrentRow`` dispararia un repintado completo de
        # las 11 pestanas y con varios tickers se repintaria la interfaz entera
        # una vez por ticker.
        actual = None
        with self.historial.sin_avisar():
            for resultado in self.resultados:
                actual = self.resultados[self.historial.agregar(resultado)]
        self._pintar_todo(actual)
        if actual is not None:
            resumen = texto_estado(actual, self.fuentes)
            self.etiqueta_estado.setText(resumen)
            self._preguntar_manuales_pendientes()
            fallos = [r for r in self.resultados if not r.criterios]
            if fallos:
                QMessageBox.warning(
                    self,
                    "Analisis incompleto",
                    "Algunos tickers no se pudieron analizar por completo:\n"
                    + "\n".join(f"- {r.ticker}: {r.advertencias[0] if r.advertencias else 'sin datos'}" for r in fallos),
                )
        else:
            self.etiqueta_estado.setText("El analisis no devolvio resultados.")

    def _analisis_fallido(self, mensaje: str) -> None:
        """Muestra el error del hilo de analisis."""
        self._set_ocupado(False)
        self._concluir_progreso()
        self.etiqueta_estado.setText(f"Error: {mensaje}")
        QMessageBox.critical(self, "Error en el analisis", f"No se pudo completar el analisis:\n\n{mensaje}")

    def _preguntar_manuales_pendientes(self) -> None:
        """Pregunta por las tasas que ninguna fuente automatica pudo dar.

        Se ejecuta **aqui**, en el hilo de la interfaz, porque Qt no permite
        abrir cuadros de dialogo desde un hilo de trabajo. Los valores
        introducidos se guardan como ``manuales`` y se recalcula en el acto.
        """
        pendientes: List[str] = []
        for resultado in self.resultados:
            for etiqueta in resultado.manuales_pendientes():
                if etiqueta not in pendientes:
                    pendientes.append(etiqueta)
        if not pendientes:
            return
        respuesta = QMessageBox.question(
            self,
            "Datos no disponibles",
            "No se pudieron obtener de ninguna fuente automatica:\n\n- "
            + "\n- ".join(pendientes)
            + "\n\n¿Quieres introducirlos manualmente ahora? Si cancelas quedaran como N/D.",
            QMessageBox.Yes | QMessageBox.No,
        )
        manuales: Dict[str, float] = {}
        if respuesta == QMessageBox.Yes:
            for etiqueta in pendientes:
                texto, aceptado = QInputDialog.getText(
                    self,
                    "Valor manual",
                    f"{etiqueta}\n\nIntroduce el valor en porcentaje anual (por ejemplo 4.35).\n"
                    "Dejalo vacio para mantenerlo como N/D.",
                )
                if not aceptado or not str(texto).strip():
                    continue
                valor = a_float(str(texto).replace("%", "").strip())
                if valor is None:
                    continue
                clave = CLAVES_MANUALES.get(
                    etiqueta,
                    "tbill_4w" if "4 semanas" in etiqueta else ("ust_10y" if "10 anios" in etiqueta else "ust_30y"),
                )
                manuales[clave] = valor / 100.0 if abs(valor) > 1.0 else valor
        if manuales:
            self.manuales = {**getattr(self, "manuales", {}), **manuales}
            self.etiqueta_estado.setText("Valores manuales registrados: recalculando...")
            self.analizar()
        else:
            self.etiqueta_estado.setText("Los datos que faltan quedaran registrados como N/D.")

    def _set_ocupado(self, ocupado: bool) -> None:
        """Bloquea o desbloquea los controles durante un analisis.

        La barra de progreso **no** se toca aqui: la gestionan
        :meth:`_reiniciar_progreso` y :meth:`_concluir_progreso`, que la muestran
        desde el primer momento y la ocultan cuando termina el analisis (antes se
        ocultaba al empezar, que es lo que impedia ver el avance).
        """
        self.boton_analizar.setEnabled(not ocupado)
        self.boton_actualizar.setEnabled(not ocupado)
        self.boton_cancelar.setEnabled(ocupado)

    # ---------------------------------------------------------------- pintado
    def _pintar_todo(self, actual: Optional[ResultadoAnalisis]) -> None:
        """Entrega los resultados a cada pestana (aislando los fallos).

        Mientras se repintan las pestanas se oculta la caja de pestanas y se
        desactivan los repintados intermedios: cada pestana reconstruye sus tablas
        y sus graficos, y sin esto Qt redibujaria toda la ventana en cada paso
        (se nota especialmente con varios tickers analizados). Al terminar se
        muestra el resultado de una sola vez.
        """
        self.pestanas.setUpdatesEnabled(False)
        estaba_visible = self.pestanas.isVisible()
        self.pestanas.setVisible(False)
        try:
            for nombre, pestana in self.tabs.items():
                try:
                    if hasattr(pestana, "cargar_fuentes"):
                        pestana.cargar_fuentes(self.fuentes)
                    pestana.cargar(self.resultados, actual)
                except Exception as exc:  # pragma: no cover - proteccion de la interfaz
                    LOG.error("La pestana %s fallo al cargar los datos: %s", nombre, exc)
                    self.avisos.mostrar([f"La pestana {nombre} no pudo mostrar los resultados: {exc}"])
            if actual is not None:
                self.parametros.cargar(actual, self.config)
                self.avisos.mostrar(list(actual.advertencias))
        finally:
            self.pestanas.setVisible(estaba_visible)
            self.pestanas.setUpdatesEnabled(True)
            self.pestanas.update()

    def _seleccionar_historial(self, indice: int) -> None:
        """Recarga todas las pestanas con el analisis elegido en el historial."""
        guardados = self.historial.resultados()
        if not (0 <= indice < len(guardados)):
            return
        actual = guardados[indice]
        self.resultados = guardados
        self._pintar_todo(actual)
        self.etiqueta_estado.setText(texto_estado(actual, self.fuentes))

    # ------------------------------------------------------------ recalculo
    def _recalcular(self, *_args: Any) -> None:
        """Recalcula en vivo con los parametros actuales, sin descargar datos.

        Si ya hay un recalculo en marcha no se descarta la peticion: se guarda
        aparte y se relanza al terminar. Antes se perdia, de modo que el ultimo
        movimiento de un control podia quedar sin aplicar y la interfaz mostraba
        un resultado que no correspondia a los parametros visibles.
        """
        if not self.resultados:
            return
        if self._trabajador is not None and self._trabajador.isRunning():
            return
        overrides = self._overrides_actuales()
        if self._trabajador_recalculo is not None and self._trabajador_recalculo.isRunning():
            self._recalculo_pendiente = overrides
            return
        self._lanzar_recalculo(overrides)

    def _lanzar_recalculo(self, overrides: Dict[str, Any]) -> None:
        """Arranca el hilo de recalculo con unos overrides concretos."""
        self._recalculo_pendiente = None
        self.etiqueta_estado.setText("Recalculando con los nuevos parametros...")
        self._trabajador_recalculo = TrabajadorRecalculo(self.resultados, self.config, overrides, parent=self)
        self._trabajador_recalculo.terminado_ok.connect(self._recalculo_terminado)
        self._trabajador_recalculo.start()

    def _recalculo_terminado(self, resultados: List[ResultadoAnalisis], fuentes: Fuentes) -> None:
        """Recibe los resultados del recalculo y refresca la interfaz."""
        self.resultados = list(resultados)
        if fuentes is not None and len(getattr(fuentes, "items", [])):
            self.fuentes = fuentes
        with self.historial.sin_avisar():
            self.historial.actualizar(self.resultados)
        actual = self.resultados[0] if self.resultados else None
        if actual is not None:
            fila = self.historial.lista.currentRow()
            if 0 <= fila < len(self.resultados):
                actual = self.resultados[fila]
        self._pintar_todo(actual)
        if actual is not None:
            self.etiqueta_estado.setText(texto_estado(actual, self.fuentes))
        # Si mientras se recalculaba el usuario volvio a mover un control, se
        # aplica ahora su ultima eleccion (nunca se descarta).
        pendiente = self._recalculo_pendiente
        if pendiente is not None:
            self._lanzar_recalculo(pendiente)

    # ------------------------------------------------------------- excel
    def _preguntar_alcance_exportacion(self) -> Optional[List[ResultadoAnalisis]]:
        """Pregunta si exportar todos los tickers o solo el actual.

        Los botones llevan texto explicito en espanol ("Todos", "Solo este",
        "Cancelar"): la version de Qt que se distribuya puede estar sin traducir, y
        entonces aparecerian como "Yes" / "No" / "Cancel".

        Returns:
            La lista de analisis a exportar, o ``None`` si el usuario cancela.
        """
        total = len(self.resultados)
        if total <= 1:
            return list(self.resultados)

        caja = QMessageBox(self)
        caja.setWindowTitle("Alcance de la exportacion")
        caja.setIcon(QMessageBox.Question)
        caja.setText(f"Se han analizado {total} acciones.")
        caja.setInformativeText("¿Quieres exportar todas las acciones o solo la que tienes seleccionada?")
        boton_todos = caja.addButton("Todos", QMessageBox.AcceptRole)
        boton_uno = caja.addButton("Solo este", QMessageBox.ActionRole)
        boton_cancelar = caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.setDefaultButton(boton_todos)
        caja.setEscapeButton(boton_cancelar)
        caja.exec()

        pulsado = caja.clickedButton()
        if pulsado is boton_cancelar or pulsado is None:
            return None
        if pulsado is boton_uno:
            fila = self.historial.lista.currentRow()
            if 0 <= fila < total:
                return [self.resultados[fila]]
            return self.resultados[:1]
        return list(self.resultados)

    def _preguntar_formulas(self) -> Optional[bool]:
        """Pregunta si escribir formulas reales de Excel o solo valores.

        Returns:
            ``True``/``False`` segun la eleccion, o ``None`` si el usuario cancela.
        """
        caja = QMessageBox(self)
        caja.setWindowTitle("Formulas o valores")
        caja.setIcon(QMessageBox.Question)
        caja.setText("¿Escribir los calculos como FORMULAS reales de Excel o solo los valores?")
        caja.setInformativeText(
            "Con formulas (recomendado) el libro se puede auditar y recalcular en Excel; "
            "con valores queda un informe estatico."
        )
        boton_formulas = caja.addButton("Formulas", QMessageBox.AcceptRole)
        boton_valores = caja.addButton("Solo valores", QMessageBox.ActionRole)
        boton_cancelar = caja.addButton("Cancelar", QMessageBox.RejectRole)
        caja.setDefaultButton(boton_formulas)
        caja.setEscapeButton(boton_cancelar)
        caja.exec()

        pulsado = caja.clickedButton()
        if pulsado is boton_cancelar or pulsado is None:
            return None
        return pulsado is boton_formulas

    def exportar_excel(self) -> None:
        """Exporta a .xlsx **solo cuando el usuario lo pide**."""
        if not self.resultados:
            QMessageBox.information(self, "Sin datos", "Analiza al menos un ticker antes de exportar.")
            return
        try:
            from ..export.excel import nombre_sugerido
        except Exception as exc:
            QMessageBox.critical(self, "Exportacion no disponible", f"No se pudo cargar el modulo de exportacion:\n{exc}")
            return

        elegidos = self._preguntar_alcance_exportacion()
        if not elegidos:
            return

        con_formulas = self._preguntar_formulas()
        if con_formulas is None:
            return

        dialogo = QFileDialog(self, "Guardar analisis como...", str(Path.cwd() / nombre_sugerido(elegidos)))
        dialogo.setAcceptMode(QFileDialog.AcceptSave)
        dialogo.setNameFilter("Libro de Excel (*.xlsx)")
        dialogo.setDefaultSuffix("xlsx")
        if not dialogo.exec():
            return
        rutas = dialogo.selectedFiles()
        if not rutas:
            return
        ruta = rutas[0]
        if not ruta.lower().endswith(".xlsx"):
            ruta += ".xlsx"

        self.etiqueta_estado.setText("Generando el libro de Excel...")
        self.boton_exportar.setEnabled(False)
        self._trabajador_excel = TrabajadorExcel(
            elegidos, ruta, con_formulas=con_formulas, fuentes=self.fuentes, parent=self
        )
        self._trabajador_excel.terminado_ok.connect(self._excel_terminado)
        self._trabajador_excel.fallo.connect(self._excel_fallido)
        self._trabajador_excel.start()

    def _excel_terminado(self, ruta: str) -> None:
        """Muestra la ruta final y ofrece abrir la carpeta."""
        self.boton_exportar.setEnabled(True)
        self.etiqueta_estado.setText(f"Excel generado en {ruta}")
        caja = QMessageBox(self)
        caja.setWindowTitle("Exportacion completada")
        caja.setText(f"Libro generado:\n{ruta}")
        abrir = caja.addButton("Abrir carpeta", QMessageBox.AcceptRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is abrir:
            self._abrir_carpeta(ruta)

    def _excel_fallido(self, mensaje: str) -> None:
        """Muestra el error de la exportacion."""
        self.boton_exportar.setEnabled(True)
        self.etiqueta_estado.setText(f"Error al exportar: {mensaje}")
        QMessageBox.critical(self, "Error al exportar", f"No se pudo generar el Excel:\n\n{mensaje}")

    @staticmethod
    def _abrir_carpeta(ruta: str) -> None:
        """Abre la carpeta que contiene el archivo exportado."""
        import subprocess
        import sys

        carpeta = str(Path(ruta).parent)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", carpeta])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", carpeta])
            else:
                subprocess.Popen(["xdg-open", carpeta])
        except Exception as exc:  # pragma: no cover - depende del sistema
            LOG.warning("No se pudo abrir la carpeta %s: %s", carpeta, exc)

    # ---------------------------------------------------------------- utilidades
    def limpiar_cache(self) -> None:
        """Borra la cache local por dia."""
        if self.cache is None:
            QMessageBox.information(self, "Cache", "La cache esta desactivada en la configuracion.")
            return
        borrados = self.cache.limpiar()
        QMessageBox.information(self, "Cache limpiada", f"Se eliminaron {borrados} entradas de la cache local.")
        self.etiqueta_estado.setText(f"Cache limpiada ({borrados} entradas).")

    def cambiar_tema(self) -> None:
        """Conmuta entre tema oscuro y claro (y lo recuerda en config.yaml).

        El cambio es **inmediato**: se aplica la hoja de estilo, se da feedback en
        la barra de estado y se repintan los graficos de la pestana visible. Los
        graficos de las pestanas ocultas se actualizan al mostrarse
        (:meth:`TabBase.showEvent`), que es lo que evita los segundos de espera
        que provocaba repintar las once pestanas de golpe.
        """
        self.tema = "claro" if self.tema == "oscuro" else "oscuro"
        nombre = "claro" if self.tema == "claro" else "oscuro"
        self.etiqueta_estado.setText(f"Aplicando tema {nombre}...")
        self.boton_tema.setEnabled(False)
        QApplication.processEvents()

        try:
            aplicar_tema_global(QApplication.instance(), self.tema)
            self.boton_tema.setText("Tema claro" if self.tema == "oscuro" else "Tema oscuro")
            self._refrescar_graficos_visibles(self.tema)
        finally:
            self.boton_tema.setEnabled(True)

        # El tema se recuerda para el proximo arranque.
        self.config.setdefault("ui", {})["tema"] = self.tema
        if bool((self.config.get("ui") or {}).get("guardar_geometria", True)):
            guardar_tema(self.tema)

        self._refrescar_titulo_tema()
        self.etiqueta_estado.setText(f"Tema {nombre} aplicado.")
        # Se fuerza el repintado de una vez en lugar de esperar al siguiente ciclo
        # del bucle de eventos: el cambio se ve al instante.
        self.update()

    def _refrescar_graficos_visibles(self, tema: str) -> None:
        """Repinta solo los graficos de la pestana visible."""
        pestana = self.pestanas.currentWidget()
        if pestana is None:
            return
        try:
            if hasattr(pestana, "refrescar_tema"):
                pestana.refrescar_tema(tema)
        except Exception:  # pragma: no cover - defensivo
            LOG.debug("La pestana no pudo refrescar su tema")

    def _refrescar_titulo_tema(self) -> None:
        """Anade el tema activo al titulo de la ventana."""
        self.setWindowTitle(
            f"DML-FINANCE - Analizador cuantitativo y parrilla de decision  [tema {self.tema}]"
            + ("  [MODO DEMO]" if self.demo else "")
        )

    def closeEvent(self, evento: Any) -> None:  # noqa: N802 - API de Qt
        """Detiene los hilos antes de cerrar la ventana."""
        self._latido.stop()
        for trabajador in (self._trabajador, self._trabajador_recalculo, self._trabajador_excel):
            if trabajador is not None and trabajador.isRunning():
                try:
                    if hasattr(trabajador, "cancelar"):
                        trabajador.cancelar()
                    trabajador.wait(3000)
                except Exception:  # pragma: no cover - defensivo
                    LOG.debug("No se pudo detener un hilo de trabajo")
        super().closeEvent(evento)


def cargar_demo_en_ventana(ventana: VentanaPrincipal, tickers: Optional[Sequence[str]] = None) -> None:
    """Carga datos DEMO en una ventana ya construida (usado por las pruebas).

    Es sincrono y no usa hilos, para que la prueba de humo sea determinista.
    """
    from ..analisis import analizar_demo

    tickers = list(tickers or ["DEMO"])
    ventana.resultados = []
    for ticker in tickers:
        ventana.resultados.append(analizar_demo(ticker, ventana.config, overrides=ventana._overrides_actuales()))
    ventana.historial.actualizar(ventana.resultados)
    ventana._pintar_todo(ventana.resultados[0] if ventana.resultados else None)
