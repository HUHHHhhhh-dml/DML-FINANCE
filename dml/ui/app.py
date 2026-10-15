# -*- coding: utf-8 -*-
"""Arranque de la aplicacion de escritorio.

``crear_app`` prepara la ``QApplication`` (tema, fuente, metadatos) y
``ejecutar`` abre la ventana principal. Toda la inicializacion pesada se hace
aqui para que ``dml.ui`` se pueda importar sin efectos secundarios.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ..core.cache import Cache
from ..core.config import cargar_config, ruta_config, ruta_datos_app

LOG = logging.getLogger("dml.ui.app")

TEMA_DEFECTO = "oscuro"


def crear_app(argv: Optional[Sequence[str]] = None, tema: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
    """Crea (o reutiliza) la ``QApplication`` con el estilo de DML-FINANCE.

    Args:
        argv: argumentos para Qt (se ignoran los de la aplicacion).
        tema: ``oscuro`` o ``claro``; si falta se lee de la configuracion.
        config: configuracion efectiva.

    Returns:
        La instancia de ``QApplication``.
    """
    from PySide6.QtWidgets import QApplication

    from .widgets import aplicar_icono, aplicar_tema_global

    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv) if argv is not None else [])
    app.setApplicationName("DML-FINANCE")
    app.setApplicationDisplayName("DML-FINANCE")
    app.setOrganizationName("DML")
    app.setApplicationVersion("2.0.0")
    # El icono se fija en la aplicacion (barra de tareas, alt-tab y dialogos).
    aplicar_icono(None)

    config = config or cargar_config()
    tema = tema or str(((config.get("ui") or {}).get("tema", TEMA_DEFECTO)))
    aplicar_tema_global(app, tema)
    return app


def _cache_de(config: Dict[str, Any]) -> Optional[Cache]:
    """Crea la cache local por dia si esta activada en la configuracion.

    Una ruta **relativa** en ``datos.cache_dir`` se resuelve dentro del directorio
    de datos del usuario (:func:`ruta_datos_app`) y no respecto al directorio de
    trabajo: un acceso directo de Windows puede arrancar el programa con
    ``C:\\Windows\\System32`` como directorio actual y entonces la cache se
    escribiria (o fallaria) en un sitio imprevisible, desactivandose en silencio y
    obligando a descargar todo en cada ejecucion. Una ruta absoluta se respeta.
    """
    datos = config.get("datos", {}) or {}
    if not datos.get("cache", True):
        LOG.info("La cache esta desactivada en config.yaml")
        return None
    # La cache nunca debe impedir arrancar: si no se puede preparar, se trabaja sin
    # ella (y queda constancia en el log) en lugar de dejar al usuario sin ventana.
    try:
        carpeta = Path(str(datos.get("cache_dir", ".dml_cache") or ".dml_cache"))
        if not carpeta.is_absolute():
            # Se cuelga **siempre** de la carpeta de datos, aunque esta sea la de
            # ultimo recurso (junto al ejecutable): asi la cache queda en una
            # subcarpeta y nunca como un directorio suelto al lado del programa, que
            # es lo que se comparte.
            carpeta = ruta_datos_app() / carpeta
        return Cache(
            directorio=str(carpeta),
            ttl_horas=float(datos.get("cache_ttl_horas", 24) or 24),
            activa=True,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("No se pudo preparar la cache (%s): se trabaja sin cache", exc)
        return None


def ejecutar(
    argv: Optional[Sequence[str]] = None,
    demo: bool = False,
    tickers: Optional[Sequence[str]] = None,
    config: Optional[Dict[str, Any]] = None,
    tema: Optional[str] = None,
    marca: Optional[str] = None,
) -> int:
    """Abre la ventana principal y entra en el bucle de eventos de Qt.

    Args:
        argv: argumentos de Qt.
        demo: arranca en modo demostracion (datos ficticios, sin conexion).
        tickers: tickers que se analizan automaticamente al abrir.
        config: configuracion efectiva.
        tema: fuerza el tema inicial.
        marca: si se indica, escribe ese archivo en cuanto la ventana esta
            construida y visible. Sirve para verificar el arranque de un
            ejecutable compilado con ``--windowed``, donde no hay consola.

    Returns:
        El codigo de salida de ``QApplication.exec()``.
    """
    config = config or cargar_config()
    app = crear_app(argv=argv, tema=tema, config=config)
    cache = _cache_de(config)

    from .ventana_principal import VentanaPrincipal

    ventana = VentanaPrincipal(config=config, cache=cache, demo=demo)

    if tickers:
        ventana.campo_ticker.setText(", ".join(str(t) for t in tickers))

    ventana.show()
    app.processEvents()

    if marca:
        _escribir_marca(marca, ventana, config)

    if tickers:
        ventana.analizar()
    elif demo:
        from .ventana_principal import cargar_demo_en_ventana

        try:
            cargar_demo_en_ventana(ventana, ["DEMO"])
        except Exception as exc:  # pragma: no cover - proteccion de la interfaz
            LOG.error("No se pudieron cargar los datos DEMO: %s", exc)

    return int(app.exec())


def _escribir_marca(ruta: str, ventana: Any, config: Dict[str, Any]) -> None:
    """Escribe un fichero marcador que confirma que la ventana se ha construido.

    Se usa para verificar el arranque de un ejecutable ``--windowed`` (sin
    consola): si el archivo aparece con ``estado=ok``, la aplicacion ha cargado,
    la ventana esta creada y las pestanas existen.
    """
    import json
    from pathlib import Path

    try:
        pestanas = [ventana.pestanas.tabText(i) for i in range(ventana.pestanas.count())]
        datos = {
            "estado": "ok",
            "version": "2.0.0",
            "congelado": bool(getattr(sys, "frozen", False)),
            "visible": bool(ventana.isVisible()),
            "tema": ventana.tema,
            "pestanas": pestanas,
            "analisis_en_memoria": len(getattr(ventana, "resultados", []) or []),
            "python": sys.version.split()[0],
            "ejecutable": sys.executable,
            "config": str(ruta_config() or ""),
        }
        destino = Path(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        LOG.info("Marca de arranque escrita en %s", destino)
    except Exception as exc:  # pragma: no cover - solo diagnostico
        LOG.error("No se pudo escribir la marca de arranque: %s", exc)
