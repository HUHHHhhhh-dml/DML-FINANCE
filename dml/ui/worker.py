# -*- coding: utf-8 -*-
"""Hilos de trabajo para que la ventana nunca se congele.

La descarga de datos y el calculo de los modelos se ejecutan en un ``QThread``
que emite senales de progreso, estado y finalizacion. La interfaz solo se
actualiza en el hilo principal, conectada a esas senales.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from ..analisis import analizar_demo, analizar_ticker
from ..core.cache import Cache
from ..core.tipos import Fuentes, ResultadoAnalisis
from ..core.util import ahora_iso

LOG = logging.getLogger("dml.ui.worker")


class TrabajadorAnalisis(QThread):
    """Hilo que analiza uno o varios tickers.

    Signals:
        progreso: ``(mensaje, fraccion)`` con la barra de progreso.
        estado: mensaje corto para la barra de estado.
        ticker_terminado: ``(ticker, completados, total)`` por cada ticker
            terminado, para informar del avance sin repintar la interfaz.
        terminado_ok: ``(list[ResultadoAnalisis], Fuentes)``.
        fallo: mensaje de error legible.
    """

    progreso = Signal(str, float)
    estado = Signal(str)
    ticker_terminado = Signal(str, int, int)
    terminado_ok = Signal(list, object)
    fallo = Signal(str)

    def __init__(
        self,
        tickers: Sequence[str],
        config: Dict[str, Any],
        cache: Optional[Cache] = None,
        overrides: Optional[Dict[str, Any]] = None,
        demo: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.tickers = [t.strip().upper() for t in tickers if str(t).strip()]
        self.config = config
        self.cache = cache
        self.overrides = overrides or {}
        self.demo = demo
        self._cancelado = False

    def cancelar(self) -> None:
        """Pide al hilo que se detenga en la siguiente comprobacion."""
        self._cancelado = True
        LOG.info("Analisis cancelado por el usuario")

    @property
    def cancelado(self) -> bool:
        """True si se solicito la cancelacion."""
        return self._cancelado

    def run(self) -> None:  # noqa: D401 - metodo de QThread
        """Ejecuta el analisis completo (nunca lanza: emite ``fallo``).

        Cada ticker se aisla: si uno falla, se registra el motivo, se avisa a la
        interfaz y se continua con el resto (los que si se pudieron analizar se
        muestran igualmente).
        """
        fuentes = Fuentes()
        resultados: List[ResultadoAnalisis] = []
        total = max(len(self.tickers), 1)
        for posicion, ticker in enumerate(self.tickers):
            if self._cancelado:
                self.estado.emit("Analisis cancelado")
                return
            base = posicion / total

            def _progreso(mensaje: str, fraccion: float, _base: float = base) -> None:
                self.progreso.emit(mensaje, min(_base + fraccion / total, 1.0))

            def _estado(mensaje: str, _ticker: str = ticker) -> None:
                self.estado.emit(f"[{_ticker}] {mensaje}")

            try:
                if self.demo:
                    self.progreso.emit(f"Generando datos DEMO de {ticker}...", base + 0.1)
                    resultado = analizar_demo(
                        ticker or "DEMO", self.config, overrides=self.overrides, fuentes=fuentes
                    )
                else:
                    # permitir_manual=False: Qt no permite abrir dialogos en un
                    # hilo de trabajo. La ventana pregunta despues, si hace falta.
                    resultado = analizar_ticker(
                        ticker,
                        config=self.config,
                        cache=self.cache,
                        fuentes=fuentes,
                        progreso=_progreso,
                        overrides=self.overrides,
                        permitir_manual=False,
                    )
            except Exception as exc:  # un ticker roto no debe tumbar el resto
                LOG.error("El analisis de %s fallo: %s", ticker, exc)
                LOG.debug(traceback.format_exc())
                resultado = ResultadoAnalisis(ticker=ticker.upper(), fecha_analisis=ahora_iso(), demo=self.demo)
                resultado.advertencias.append(f"No se pudo analizar {ticker}: {exc}")
                resultado.decision = "N/D"

            if self._cancelado:
                self.estado.emit("Analisis cancelado")
                return
            resultados.append(resultado)
            # El avance real del ticker completo se comunica aparte del mensaje
            # de estado: la ventana lo usa para el contador "(2 de 3)" sin
            # repintar las pestanas en cada paso.
            self.ticker_terminado.emit(ticker, posicion + 1, total)
            self.progreso.emit(f"{ticker}: analisis completado", base + 1.0 / total)

        if self._cancelado:
            self.estado.emit("Analisis cancelado")
            return
        try:
            self.terminado_ok.emit(resultados, fuentes)
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudieron entregar los resultados: %s", exc)
            self.fallo.emit(str(exc))


class TrabajadorRecalculo(QThread):
    """Hilo que recalcula un analisis ya descargado (panel de parametros).

    Como no hay red, se ejecuta en un hilo para mantener la interfaz fluida
    incluso con series largas.
    """

    terminado_ok = Signal(list, object)

    def __init__(
        self,
        resultados: Sequence[ResultadoAnalisis],
        config: Dict[str, Any],
        overrides: Optional[Dict[str, Any]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.resultados = list(resultados)
        self.config = config
        self.overrides = overrides or {}

    def run(self) -> None:  # noqa: D401 - metodo de QThread
        """Recalcula cada resultado conservando los datos de origen."""
        from ..analisis import analizar_datos

        fuentes = Fuentes()
        salida: List[ResultadoAnalisis] = []
        for resultado in self.resultados:
            datos = getattr(resultado, "_datos", None)
            if datos is None:
                salida.append(resultado)
                continue
            try:
                salida.append(analizar_datos(datos, self.config, self.overrides, fuentes))
            except Exception as exc:  # pragma: no cover - defensivo
                LOG.error("No se pudo recalcular %s: %s", resultado.ticker, exc)
                salida.append(resultado)
        self.terminado_ok.emit(salida, fuentes)


class TrabajadorExcel(QThread):
    """Hilo que genera el libro de Excel cuando el usuario lo pide."""

    terminado_ok = Signal(str)
    fallo = Signal(str)

    def __init__(
        self,
        resultados: Sequence[ResultadoAnalisis],
        ruta: str,
        con_formulas: bool = True,
        fuentes: Optional[Fuentes] = None,
        imagenes: Optional[Dict[str, Any]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.resultados = list(resultados)
        self.ruta = ruta
        self.con_formulas = con_formulas
        self.fuentes = fuentes
        self.imagenes = imagenes

    def run(self) -> None:  # noqa: D401 - metodo de QThread
        """Escribe el .xlsx y emite la ruta final."""
        try:
            from pathlib import Path

            from ..export.excel import exportar_excel

            ruta = exportar_excel(
                self.resultados,
                Path(self.ruta),
                con_formulas=self.con_formulas,
                fuentes=self.fuentes,
                imagenes=self.imagenes,
            )
            self.terminado_ok.emit(str(ruta))
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("La exportacion a Excel fallo: %s", exc)
            LOG.debug(traceback.format_exc())
            self.fallo.emit(str(exc))
