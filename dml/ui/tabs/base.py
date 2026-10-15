# -*- coding: utf-8 -*-
"""Clase base de las pestanas de la aplicacion.

Cada pestana hereda de :class:`TabBase`, implementa :meth:`cargar` para pintar un
:class:`~dml.core.tipos.ResultadoAnalisis` y, opcionalmente, :meth:`refrescar_tema`
para redibujar sus graficos. Toda la logica de calculo vive en
:mod:`dml.analisis`; las pestanas solo presentan.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ...core.tipos import ND, ResultadoAnalisis
from ...core.util import fmt_num, fmt_pct

LOG = logging.getLogger("dml.ui.tabs")


class TabBase(QWidget):
    """Base comun de todas las pestanas.

    Args:
        config: configuracion efectiva (solo lectura para pintar umbrales).
        parent: widget padre.
    """

    #: Titulo de la pestana (lo usa la ventana principal).
    titulo: str = "Pestana"

    def __init__(self, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config: Dict[str, Any] = config or {}
        self.resultado: Optional[ResultadoAnalisis] = None
        self.resultados: List[ResultadoAnalisis] = []
        # El tema activo sale de la configuracion para que el primer pintado (que
        # ocurre antes de que la ventana pida el cambio de tema) ya use la paleta
        # correcta.
        self.tema_actual = str((self.config.get("ui") or {}).get("tema", "oscuro"))
        #: Tema con el que se pintaron los graficos de esta pestana (``None`` =
        #: nunca se han pintado con un tema concreto).
        self._tema_graficado: Optional[str] = None

        # Toda pestana va dentro de un area con desplazamiento. El contenido
        # (tablas, tarjetas, graficos) suele ser mas alto y mas ancho que la
        # ventana -sobre todo con los paneles laterales abiertos o el zoom de
        # pantalla al 125 %-, y sin esto lo que sobraba quedaba **fuera de la vista
        # y sin forma de llegar a el**.
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.setSpacing(0)
        #: Contenedor desplazable: la pestana en si sigue siendo hija del
        #: ``QTabWidget`` (no se puede reparentar), asi que el contenido va en un
        #: widget aparte que es el que se desplaza.
        self._contenido = QWidget()
        self._area = self.scroll(self._contenido)
        exterior.addWidget(self._area)

        # ``self._caja`` sigue siendo la caja donde cada pestana anade sus bloques:
        # ahora cuelga del contenido del area, de modo que las pestanas no cambian.
        self._caja = QVBoxLayout(self._contenido)
        self._caja.setContentsMargins(8, 8, 8, 8)
        self._caja.setSpacing(6)

    # ------------------------------------------------------------------ API
    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta los resultados. Debe reimplementarse en cada pestana.

        Args:
            resultados: todos los analisis disponibles (para tablas comparativas).
            actual: el ticker seleccionado, que es el que se muestra en detalle.
        """
        self.resultados = list(resultados)
        self.resultado = actual if actual is not None else (resultados[0] if resultados else None)

    def refrescar_tema(self, tema: str) -> None:
        """Redibuja los graficos al cambiar de tema.

        Recorre los hijos que exponen ``aplicar_tema`` (los lienzos de matplotlib)
        y solo actua la primera vez que se pide cada tema: volver a pedir el mismo
        tema no repinta nada, que es lo que hace que el cambio de tema sea
        inmediato.
        """
        if self._tema_graficado == tema:
            return
        self.tema_actual = tema
        for grafico in self.findChildren(QWidget):
            if hasattr(grafico, "aplicar_tema"):
                try:
                    grafico.aplicar_tema(tema)  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover - defensivo
                    LOG.debug("No se pudo aplicar el tema a %s", type(grafico).__name__)
        self._tema_graficado = tema

    # --------------------------------------------------------------- eventos
    def _graficos_al_dia(self, tema: Optional[str] = None) -> bool:
        """Marca/consulta si los graficos ya estan pintados con el tema ``tema``.

        Se llama **al final** de un pintado para dejar constancia del tema usado
        (``self._graficos_al_dia(tema)``) y **al principio** de
        :meth:`refrescar_tema` para no repetir trabajo; en ese segundo caso hay
        que negar el resultado, como muestran las pestanas.
        """
        if tema is None:
            return self._tema_graficado == self.tema_actual
        self._tema_graficado = tema
        return True

    def _refrescar_graficos(self, tema: str, *lienzos: Any) -> bool:
        """Aplica el tema a ``lienzos`` si hacia falta. Devuelve si hubo trabajo.

        Es el atajo para las pestanas que tienen **varios** graficos o que ya
        construyen su figura en otro metodo: aplica el tema a los lienzos (sean
        ``GraficoDML`` o paneles que expongan ``aplicar_tema``), marca la pestana
        como al dia y evita repetir el trabajo si el tema no cambio.

        Args:
            tema: tema pedido.
            *lienzos: lienzos/paneles a repintar (se ignoran los ``None``).

        Returns:
            ``True`` si habia algo que repintar, ``False`` si ya estaba al dia.
        """
        if self._tema_graficado == tema:
            return False
        self.tema_actual = tema
        for lienzo in lienzos:
            if lienzo is None:
                continue
            try:
                lienzo.aplicar_tema(tema)
            except Exception:  # pragma: no cover - defensivo
                LOG.debug("No se pudo aplicar el tema a %s", type(lienzo).__name__)
        self._tema_graficado = tema
        return True

    def showEvent(self, evento: Any) -> None:  # noqa: N802 - API de Qt
        """Pinta los graficos si el tema activo cambio mientras estaba oculta.

        Al cambiar de tema solo se repintan las pestanas visibles (es la parte
        lenta del cambio); el resto se actualizan aqui, al mostrarse por primera
        vez. Asi el cambio de tema es inmediato y ninguna pestana se queda con
        los colores antiguos.
        """
        super().showEvent(evento)
        if self._tema_graficado is None or self._tema_graficado != self.tema_actual:
            try:
                self.refrescar_tema(self.tema_actual)
            except Exception:  # pragma: no cover - defensivo
                LOG.debug("No se pudo refrescar el tema de %s al mostrarse", type(self).__name__)

    # -------------------------------------------------------------- ayudas UI
    def add(self, widget: QWidget, estirar: int = 0) -> QWidget:
        """Anade un widget a la caja vertical de la pestana."""
        self._caja.addWidget(widget, estirar)
        return widget

    def add_titulo(self, texto: str, subtitulo: str = "") -> QLabel:
        """Anade un titulo (y un subtitulo opcional) a la pestana."""
        etiqueta = QLabel(texto)
        etiqueta.setObjectName("titulo")
        self._caja.addWidget(etiqueta)
        if subtitulo:
            sub = QLabel(subtitulo)
            sub.setObjectName("subtitulo")
            sub.setWordWrap(True)
            self._caja.addWidget(sub)
        return etiqueta

    def add_aviso(self, texto: str) -> QLabel:
        """Anade una etiqueta de advertencia."""
        etiqueta = QLabel(texto)
        etiqueta.setObjectName("aviso")
        etiqueta.setWordWrap(True)
        self._caja.addWidget(etiqueta)
        return etiqueta

    @staticmethod
    def scroll(widget: QWidget) -> QScrollArea:
        """Envuelve un widget en un area con desplazamiento.

        Las dos barras se piden **solo si hacen falta**. La horizontal no se puede
        desactivar: las tablas anchas (11 columnas en la parrilla de criterios)
        necesitan mas ancho del que tiene la pestana cuando los paneles laterales
        estan abiertos, y sin esa barra el contenido se recortaria por la derecha
        sin forma de verlo.
        """
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Fondo transparente: el del area lo pone el QSS de la pestana.
        area.viewport().setAutoFillBackground(False)
        area.setWidget(widget)
        return area

    # ------------------------------------------------------------- formateo
    @staticmethod
    def num(valor: Any, decimales: int = 4) -> str:
        """Formatea un numero o devuelve ``N/D``."""
        return fmt_num(valor, decimales)

    @staticmethod
    def pct(valor: Any, decimales: int = 2) -> str:
        """Formatea una fraccion como porcentaje o devuelve ``N/D``."""
        return fmt_pct(valor, decimales)

    @staticmethod
    def texto(valor: Any) -> str:
        """Convierte cualquier valor en texto mostrable (``N/D`` si falta)."""
        if valor is None:
            return ND
        if isinstance(valor, float):
            return fmt_num(valor, 4)
        return str(valor)

    def advertencias(self) -> List[str]:
        """Advertencias del resultado actual (mas las de su origen DEMO)."""
        if self.resultado is None:
            return []
        return list(self.resultado.advertencias)

    def sin_datos(self) -> bool:
        """True si todavia no hay ningun analisis cargado."""
        return self.resultado is None


class TabConGrafico(TabBase):
    """Pestana con **un** grafico que se repinta al cambiar de tema.

    Seis de las pestanas (CAPM, PER, EPS, P/FCF, Renta PER y RDR) siguen
    exactamente el mismo patron: ``cargar`` vacia la caja, muestra el estado vacio
    o construye los bloques, y cada bloque crea su ``GraficoDML`` y llama a
    ``_dibujar_grafico``. Esta clase aporta ese ``cargar`` y un
    :meth:`refrescar_tema` que se salta el trabajo cuando el grafico ya esta
    pintado con el tema pedido.

    Contrato de la subclase:

    * ``_limpiar()``, ``_mostrar_vacio()``, ``_construir(resultado)`` y
      ``_dibujar_grafico(resultado)``, exactamente como ya los implementa cada
      pestana.
    * Llamar a :meth:`_grafico_al_dia` al final de ``_dibujar_grafico``.
    """

    #: Lienzo principal de la pestana (lo asigna ``_construir``).
    _grafico: Optional[Any] = None

    def cargar(self, resultados: Sequence[ResultadoAnalisis], actual: Optional[ResultadoAnalisis] = None) -> None:
        """Pinta el analisis seleccionado (o un estado vacio informativo)."""
        super().cargar(resultados, actual)
        self._limpiar()  # type: ignore[attr-defined]
        if self.resultado is None:
            self._mostrar_vacio()  # type: ignore[attr-defined]
            return
        self._construir(self.resultado)  # type: ignore[attr-defined]

    def refrescar_tema(self, tema: str) -> None:
        """Aplica el tema a los lienzos y redibuja el grafico de la pestana.

        Se salta el redibujado si el grafico ya esta pintado con ese tema (por
        ejemplo al volver a la misma pestana o al repintar el mismo analisis), que
        es lo que hace que el cambio de tema sea inmediato.
        """
        self.tema_actual = tema
        super().refrescar_tema(tema)
        if self._tema_graficado == tema or self._grafico is None:
            return
        try:
            self._dibujar_grafico(self.resultado)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensivo
            LOG.debug("No se pudo redibujar el grafico de %s con el tema %s", type(self).__name__, tema)

    def _grafico_al_dia(self, tema: Optional[str] = None) -> None:
        """Deja constancia del tema con el que se acaba de dibujar el grafico."""
        self._tema_graficado = tema or self.tema_actual


class TabMensaje(TabBase):
    """Pestana que solo muestra un mensaje (se usa cuando falta el modulo)."""

    titulo = "No disponible"

    def __init__(self, mensaje: str, config: Optional[Dict[str, Any]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(config, parent)
        etiqueta = QLabel(mensaje)
        etiqueta.setWordWrap(True)
        self.add(etiqueta)
        self.add_titulo("N/D", mensaje)
