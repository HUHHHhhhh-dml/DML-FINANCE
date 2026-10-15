# -*- coding: utf-8 -*-
"""Panel lateral "Parametros": edicion en vivo de los parametros del analisis.

Al cambiar cualquier control se emite la senal ``cambio`` con el diccionario de
*overrides* que la ventana principal pasa a :func:`dml.analisis.analizar_datos`. El
recalculo **no vuelve a descargar** datos: reutiliza los que ya estan en
memoria.

Solo viajan como *override* los controles que el usuario ha tocado: un dato
``N/D`` deja el control en su valor por defecto y ese valor **no** debe sustituir
al dato real cuando exista (ver :meth:`PanelParametros.overrides`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.tipos import Params, ResultadoAnalisis
from ...core.util import a_float
from ..widgets import casilla, giro_decimal

LOG = logging.getLogger("dml.ui.parametros")

#: Nombres cortos de los 12 criterios para las casillas de activacion.
NOMBRES_CRITERIOS = {
    1: "1. PER < PER sector",
    2: "2. EPS >= EPS estimado",
    3: "3. MACD != Sell",
    4: "4. P/FCF < P/FCF sector",
    5: "5. Rend_CAPM > TLR",
    6: "6. Beta < Beta max.",
    7: "7. Renta PER > TLR",
    8: "8. Rend_CAPM > Riesgo",
    9: "9. R2 > R2 min.",
    10: "10. TRG > Spot x (1+TLR+1%)",
    11: "11. Spot < Strike (Forward)",
    12: "12. Delta Call > Delta min.",
}


class PanelParametros(QScrollArea):
    """Panel editable con todos los parametros del modelo.

    Signals:
        cambio: emite el diccionario de overrides cuando el usuario modifica
            algo (con un pequeno retardo para no recalcular en cada tecla).
    """

    cambio = Signal(dict)

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config: Dict[str, Any] = config or {}
        self._cargando = False
        self._cargado = False
        self._conectado = False
        self._ultimo_resultado: Optional[ResultadoAnalisis] = None
        #: Controles que el usuario ha editado a mano (solo esos van como override).
        self._editados: set = set()
        #: Ultimo valor cargado de cada campo, para detectar ediciones reales.
        self._valores_cargados: Dict[str, float] = {}
        self._temporizador = QTimer(self)
        self._temporizador.setSingleShot(True)
        self._temporizador.setInterval(350)
        self._temporizador.timeout.connect(self._emitir)

        self.setWidgetResizable(True)
        contenedor = QWidget()
        self.setWidget(contenedor)
        caja = QVBoxLayout(contenedor)
        caja.setContentsMargins(8, 8, 8, 8)
        caja.setSpacing(8)

        ayuda = QLabel(
            "Los cambios se recalculan en vivo sin volver a descargar datos. "
            "Deja un campo en su valor actual para usar el dato de mercado."
        )
        ayuda.setWordWrap(True)
        ayuda.setObjectName("subtitulo")
        caja.addWidget(ayuda)

        caja.addWidget(self._grupo_mercado())
        caja.addWidget(self._grupo_opciones())
        caja.addWidget(self._grupo_umbrales())
        caja.addWidget(self._grupo_criterios())
        caja.addStretch(1)
        # Valores iniciales tomados de la configuracion (config.yaml o linea de
        # comandos), para que el panel refleje el modo/indice/umbrales activos
        # antes de que se cargue el primer analisis.
        self._aplicar_config_inicial()

        boton = QPushButton("Restablecer valores de mercado")
        boton.setToolTip("Devuelve r, q, sigma, T y K a los valores calculados con los datos descargados")
        boton.clicked.connect(self.restablecer)
        caja.addWidget(boton)

    def _aplicar_config_inicial(self) -> None:
        """Coloca en los controles los valores de la configuracion.

        El modo, el indice y los meses **no** se ponen aqui: los edita la barra
        superior de la ventana, que es la fuente autoritativa de esos tres valores.
        """
        general = self.config.get("general", {}) or {}
        umbrales = self.config.get("umbrales", {}) or {}
        reglas = self.config.get("decision", {}) or {}
        bs = self.config.get("black_scholes", {}) or {}
        self._cargando = True
        try:
            self._poner(self.sp_pronostico, general.get("meses_pronostico"))
            self._poner(self.sp_beta, umbrales.get("beta_max"))
            self._poner(self.sp_r2, umbrales.get("r2_min"))
            self._poner(self.sp_margen, umbrales.get("trg_extra_tlr"))
            self._poner(self.sp_delta, umbrales.get("delta_call_min"))
            self._poner(self.sp_comprar, reglas.get("comprar_min"))
            self._poner(self.sp_mantener, reglas.get("mantener_min"))
            posicion_strike = self.cb_strike.findData(str(bs.get("strike_modo", "forward")))
            self.cb_strike.setCurrentIndex(posicion_strike if posicion_strike >= 0 else 0)
            self.sp_k.setEnabled(self.cb_strike.currentData() == "manual")
        finally:
            self._cargando = False

    # ------------------------------------------------------------------ grupos
    @staticmethod
    def _forma(grupo: QGroupBox) -> QFormLayout:
        """``QFormLayout`` que deja crecer al campo y no estruja la etiqueta.

        Con la politica por defecto, el campo se queda con su ancho minimo y las
        etiquetas largas ("Margen sobre TLR") se recortan: en un panel estrecho se
        veian como "Margen sobre TL...". Aqui la etiqueta ocupa lo que necesita y
        el campo se lleva el resto.
        """
        forma = QFormLayout(grupo)
        forma.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        forma.setRowWrapPolicy(QFormLayout.DontWrapRows)
        forma.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        forma.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        forma.setContentsMargins(10, 8, 10, 8)
        forma.setHorizontalSpacing(10)
        forma.setVerticalSpacing(6)
        return forma

    def _grupo_mercado(self) -> QGroupBox:
        """Grupo con los parametros de mercado que edita este panel (r, q, sigma)."""
        grupo = QGroupBox("Mercado")
        forma = self._forma(grupo)
        self.sp_r = giro_decimal(-0.5, 1.0, 0.0001, 4, sufijo=" (r)", tooltip="Tasa libre de riesgo anual (TLR del T-Bill a 4 semanas)")
        self.sp_q = giro_decimal(0.0, 1.0, 0.0001, 4, sufijo=" (q)", tooltip="Dividend yield anual de la accion")
        self.sp_sigma = giro_decimal(0.0001, 5.0, 0.005, 4, sufijo=" (σ)", tooltip="Volatilidad anual; por defecto, sigma de los rendimientos mensuales x sqrt(12)")
        self.sp_t = giro_decimal(0.01, 30.0, 0.25, 4, sufijo=" años", tooltip="Tiempo al vencimiento en años, calculado con fechas reales /365")
        forma.addRow("Tasa libre (r)", self.sp_r)
        forma.addRow("Dividendo (q)", self.sp_q)
        forma.addRow("Volatilidad (σ)", self.sp_sigma)
        forma.addRow("Vencimiento (T)", self.sp_t)
        return grupo

    def _grupo_opciones(self) -> QGroupBox:
        """Grupo con el strike y el horizonte del pronostico."""
        grupo = QGroupBox("Opciones")
        forma = self._forma(grupo)
        self.cb_strike = QComboBox()
        self.cb_strike.addItem("Forward: K = S x e^(bT)", "forward")
        self.cb_strike.addItem("Manual", "manual")
        self.cb_strike.setToolTip("El pliego define el strike como el precio forward; se puede fijar manualmente")
        self.sp_k = giro_decimal(0.0001, 1e7, 1.0, 4, tooltip="Strike price K usado en Black-Scholes")
        self.sp_pronostico = giro_decimal(1, 120, 1, 0, sufijo=" meses", tooltip="Horizonte del pronostico econometrico")
        forma.addRow("Strike", self.cb_strike)
        forma.addRow("K manual", self.sp_k)
        forma.addRow("Pronostico", self.sp_pronostico)
        return grupo

    def _grupo_umbrales(self) -> QGroupBox:
        """Grupo con los umbrales de la parrilla y de la decision."""
        grupo = QGroupBox("Umbrales de la parrilla")
        forma = self._forma(grupo)
        self.sp_beta = giro_decimal(0.0, 5.0, 0.01, 2, tooltip="Criterio 6: la Beta debe ser menor que este valor")
        self.sp_r2 = giro_decimal(0.0, 1.0, 0.01, 2, tooltip="Criterio 9: el R2 del modelo econometrico debe superar este valor")
        self.sp_margen = giro_decimal(0.0, 1.0, 0.005, 4, tooltip="Criterio 10: margen de seguridad sumado a la TLR (por defecto 1%)")
        self.sp_delta = giro_decimal(0.0, 1.0, 0.01, 2, tooltip="Criterio 12: la Delta del call debe superar este valor")
        self.sp_comprar = giro_decimal(0.0, 1.0, 0.01, 2, tooltip="Calificacion por encima de la cual la decision es COMPRAR")
        self.sp_mantener = giro_decimal(0.0, 1.0, 0.01, 2, tooltip="Calificacion minima para MANTENER; por debajo, NO INVERTIR")
        forma.addRow("Beta maxima", self.sp_beta)
        forma.addRow("R2 minimo", self.sp_r2)
        forma.addRow("Margen sobre TLR", self.sp_margen)
        forma.addRow("Delta minima", self.sp_delta)
        forma.addRow("Comprar si >", self.sp_comprar)
        forma.addRow("Mantener si >=", self.sp_mantener)
        return grupo

    def _grupo_criterios(self) -> QGroupBox:
        """Grupo con las casillas de activacion de los 12 criterios."""
        grupo = QGroupBox("Criterios activos")
        caja = QVBoxLayout(grupo)
        self.casillas: Dict[int, QCheckBox] = {}
        for numero, texto in NOMBRES_CRITERIOS.items():
            casilla_criterio = casilla(
                texto, True, f"Activa o desactiva el criterio {numero} en el promedio de la calificacion"
            )
            caja.addWidget(casilla_criterio)
            self.casillas[numero] = casilla_criterio
        return grupo

    # ------------------------------------------------------------------ datos
    def cargar(self, resultado: Optional[ResultadoAnalisis], config: Optional[Dict[str, Any]] = None) -> None:
        """Rellena el panel con los parametros efectivos de un resultado."""
        self._cargando = True
        try:
            if config is not None:
                self.config = config
            if resultado is None:
                return
            self._ultimo_resultado = resultado
            p = resultado.params or Params()
            self._poner(self.sp_r, p.r if p.r is not None else resultado.tlr, "r")
            self._poner(self.sp_q, p.q, "q")
            sigma = p.sigma if p.sigma is not None else (resultado.riesgo.sigma_anual if resultado.riesgo else None)
            self._poner(self.sp_sigma, sigma, "sigma")
            self._poner(self.sp_t, p.T, "T")
            self._poner(self.sp_k, resultado.strike, "strike")
            self._poner(self.sp_pronostico, p.meses_pronostico, "meses_pronostico")
            self._poner(self.sp_beta, p.beta_max, "beta_max")
            self._poner(self.sp_r2, p.r2_min, "r2_min")
            self._poner(self.sp_margen, p.margen_tlr_extra, "trg_extra_tlr")
            self._poner(self.sp_delta, p.delta_call_min, "delta_call_min")
            self._poner(self.sp_comprar, p.comprar_min, "comprar_min")
            self._poner(self.sp_mantener, p.mantener_min, "mantener_min")
            posicion_k = self.cb_strike.findData(resultado.strike_modo)
            self.cb_strike.setCurrentIndex(posicion_k if posicion_k >= 0 else 0)
            self._editados.discard(self.cb_strike)
            self.sp_k.setEnabled(resultado.strike_modo == "manual")
            for criterio in resultado.criterios:
                casilla_criterio = self.casillas.get(criterio.numero)
                if casilla_criterio is not None:
                    casilla_criterio.setChecked(bool(criterio.activo))
            self._conectar()
            self._cargado = True
        finally:
            self._cargando = False

    def _poner(self, control: QDoubleSpinBox, valor: Any, clave: str = "") -> None:
        """Coloca un valor calculado en un control, sin marcarlo como editado.

        Si ``valor`` es ``None`` (dato ``N/D``) el control **no se toca** y, sobre
        todo, no se marca como editado: de lo contrario su valor por defecto
        (recortado al minimo del rango) se enviaria como *override* y sustituiria
        al dato real. Ese era el motivo de que una sigma ausente acabara siendo
        ``0.0001`` dentro de Black-Scholes.

        Args:
            control: control a actualizar.
            valor: valor efectivo del analisis (``None`` si es ``N/D``).
            clave: clave de override, necesaria para recordar el valor cargado.
        """
        numero = a_float(valor)
        if numero is None:
            return
        control.setValue(numero)
        self._editados.discard(control)
        if clave:
            self._valores_cargados[clave] = control.value()

    def _conectar(self) -> None:
        """Conecta las senales de los controles una unica vez.

        Los controles se crean en el constructor y no se recrean, asi que basta
        con conectarlos la primera vez que se carga un resultado: volver a
        conectarlos duplicaria las emisiones y volver a desconectarlos genera
        avisos de PySide6 cuando la conexion no existe.
        """
        if self._conectado:
            return
        controles = [
            self.sp_r, self.sp_q, self.sp_sigma, self.sp_t, self.sp_k,
            self.sp_pronostico, self.sp_beta, self.sp_r2, self.sp_margen, self.sp_delta,
            self.sp_comprar, self.sp_mantener,
        ]
        for control in controles:
            control.valueChanged.connect(self._programar)
        self.cb_strike.currentIndexChanged.connect(self._programar)
        for casilla_criterio in self.casillas.values():
            casilla_criterio.toggled.connect(self._programar)
        self._conectado = True

    # ------------------------------------------------------------- overrides
    #: Mapa ``{clave de override: atributo del control}`` de los campos numericos.
    #: No incluye ``modo``, ``indice`` ni ``meses``: los edita la barra superior.
    MAPA_CONTROLES: Dict[str, str] = {
        "r": "sp_r",
        "q": "sp_q",
        "sigma": "sp_sigma",
        "T": "sp_t",
        "strike": "sp_k",
        "meses_pronostico": "sp_pronostico",
        "beta_max": "sp_beta",
        "r2_min": "sp_r2",
        "trg_extra_tlr": "sp_margen",
        "delta_call_min": "sp_delta",
        "comprar_min": "sp_comprar",
        "mantener_min": "sp_mantener",
    }

    def overrides(self) -> Dict[str, Any]:
        """Devuelve los overrides con **solo** los valores que ha tocado el usuario.

        Se envian unicamente los controles editados a mano. Es la diferencia entre
        "usar el dato calculado" y "imponer el valor por defecto del control": al
        cargar un analisis los controles se rellenan con los valores efectivos,
        pero un dato ``N/D`` deja el control en su valor por defecto y enviarlo
        sustituiria al dato real (por ejemplo sigma = 0.0001 en Black-Scholes).

        Si el panel todavia no se ha cargado con un analisis devuelve un
        diccionario vacio: los controles seguirian en sus valores por defecto y
        contaminarian el primer analisis.
        """
        if not self._cargado:
            return {}
        salida: Dict[str, Any] = {}
        for clave, atributo in self.MAPA_CONTROLES.items():
            control = getattr(self, atributo, None)
            if control is not None and control in self._editados:
                salida[clave] = control.value()
        if self.cb_strike in self._editados:
            salida["strike_modo"] = self.cb_strike.currentData()
            # El strike manual solo tiene sentido si el modo es manual.
            if self.cb_strike.currentData() != "manual":
                salida.pop("strike", None)
        # Las casillas de criterios se envian siempre: definen que entra en la
        # calificacion y su valor por defecto (las 12 activas) es el correcto.
        salida["criterios_activos"] = {
            numero: bool(casilla.isChecked()) for numero, casilla in self.casillas.items()
        }
        return salida

    def restablecer(self) -> None:
        """Devuelve los parametros de mercado a los valores calculados.

        Se vacia la marca de "editado": a partir de aqui el analisis vuelve a usar
        los valores estimados con los datos descargados, que es justo lo que el
        boton promete.
        """
        if self._ultimo_resultado is None:
            return
        self._editados.clear()
        self.cargar(self._ultimo_resultado, self.config)
        self._cargado = True
        self._emitir()

    def _programar(self, *_args: Any) -> None:
        """Programa un recalculo con retardo (evita recalcular en cada tecla)."""
        if self._cargando:
            return
        self._marcar_tocados()
        self.sp_k.setEnabled(self.cb_strike.currentData() == "manual")
        self._temporizador.start()

    def _marcar_tocados(self) -> None:
        """Anota los controles cuyo valor ya no es el que se cargo del analisis.

        Qt no informa en ``valueChanged`` de "quien" cambio el valor, pero la
        comparacion con el ultimo valor cargado distingue una edicion del usuario
        de una escritura programatica: solo lo que difiere cuenta como override.
        """
        for clave, atributo in self.MAPA_CONTROLES.items():
            control = getattr(self, atributo, None)
            if control is None or clave not in self._valores_cargados:
                continue
            if self._valores_cargados[clave] != control.value():
                self._editados.add(control)

    def _emitir(self) -> None:
        """Emite la senal ``cambio`` con los overrides actuales."""
        if self._cargando:
            return
        overrides = self.overrides()
        LOG.debug("Cambio de parametros: %s", {k: v for k, v in overrides.items() if k != "criterios_activos"})
        self.cambio.emit(overrides)
