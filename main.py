#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DML-FINANCE - punto de entrada de la aplicacion de escritorio.

Uso
---
::

    python main.py                 # abre la interfaz (recomendado)
    python main.py NVDA            # abre la interfaz y analiza NVDA
    python main.py NVDA AAPL MSFT  # varios tickers: tabla comparativa
    python main.py --demo          # interfaz con datos ficticios, sin conexion
    python main.py -v              # trazas detalladas (nivel DEBUG)

La aplicacion **no genera ningun archivo Excel por si sola**: para exportar hay
que pulsar el boton "Exportar a Excel" (o Ctrl+E) dentro del programa. La unica
escritura automatica es la cache local por dia, en una carpeta oculta.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def _preparar_entorno() -> None:
    """Fija ``MPLCONFIGDIR`` antes de importar matplotlib.

    matplotlib guarda ahi su cache de fuentes y de estilos. Se apunta al directorio
    de datos del usuario para que **no deje residuos** ni en el directorio de
    trabajo ni en el del ejecutable.

    ``--onedir`` y ``--onefile`` no se comportan igual:

    * ``--onedir``: las fuentes estan en ``_internal/matplotlib/...`` y siempre en
      el mismo sitio, asi que una cache persistente es valida y ahorra trabajo.
    * ``--onefile``: PyInstaller extrae la aplicacion en una carpeta temporal
      distinta en cada arranque. Para que la cache no apunte a fuentes ya
      borradas, **su propio hook** pone ``MPLCONFIGDIR`` en una carpeta temporal
      que borra al salir. Si se detecta esa situacion (la variable apunta dentro
      del directorio de la aplicacion) se respeta el hook: sustituirla por una
      cache persistente romperia la apertura de fuentes.
    """
    from dml.core.config import _directorio_escribible, directorio_aplicacion, ruta_datos_app

    actual = os.environ.get("MPLCONFIGDIR")
    if actual:
        try:
            if Path(actual).resolve().is_relative_to(directorio_aplicacion().resolve()):
                # Lo fijo el hook de PyInstaller para un --onefile: no se toca.
                return
        except Exception:  # pragma: no cover - rutas no comparables
            return

    try:
        import tempfile

        for candidata in (ruta_datos_app() / "matplotlib", Path(tempfile.gettempdir()) / "dml-matplotlib"):
            if _directorio_escribible(candidata):
                os.environ["MPLCONFIGDIR"] = str(candidata)
                return
    except Exception:  # pragma: no cover - depende del sistema de archivos
        pass


_preparar_entorno()

LOG = logging.getLogger("dml.main")


def construir_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos de la linea de comandos."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="DML-FINANCE: analizador cuantitativo de acciones con parrilla de decision de 12 criterios.",
        epilog="Herramienta de analisis; no constituye asesoria financiera.",
    )
    parser.add_argument("tickers", nargs="*", help="tickers a analizar al abrir la interfaz (por ejemplo NVDA)")
    parser.add_argument("--demo", action="store_true", help="arranca con datos ficticios marcados como DEMO (sin conexion)")
    parser.add_argument("--modo", choices=("estandar", "excel"), default=None, help="modo de calculo inicial")
    parser.add_argument("--indice", default=None, help="indice de mercado: ^GSPC, ^IXIC o ^DJI")
    parser.add_argument("--meses", type=int, default=None, help="meses de historico mensual (por defecto 60)")
    parser.add_argument("--tema", choices=("oscuro", "claro"), default=None, help="tema inicial de la interfaz")
    parser.add_argument("--config", default=None, help="ruta alternativa del archivo config.yaml")
    parser.add_argument("--sin-cache", action="store_true", help="desactiva la cache local por dia")
    parser.add_argument(
        "--autotest",
        action="store_true",
        help="comprueba el arranque completo (ventana + pestanas + libros) y sale con codigo 0/1; no abre ventana",
    )
    parser.add_argument(
        "--autotest-salida",
        default=None,
        help="archivo donde dejar el informe de --autotest (por defecto, junto al ejecutable)",
    )
    parser.add_argument(
        "--marca",
        default=None,
        help="escribe un fichero marcador en cuanto la ventana esta construida y visible (diagnostico de arranque)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="traza detallada (nivel DEBUG)")
    return parser


def autotest(config: dict, ruta_informe: Optional[str] = None) -> int:
    """Comprueba que la aplicacion (o el ejecutable empaquetado) funciona de verdad.

    Construye la ventana en modo *offscreen*, carga datos DEMO, verifica que las
    11 pestanas existen y se rellenan, que el analisis calcula los 12 criterios y
    que el exportador a Excel escribe un libro valido. Escribe un informe y
    devuelve 0 si todo esta bien y 1 si algo falla.

    Es la forma de validar un ``.exe`` compilado con ``--windowed``, donde no hay
    consola donde leer el resultado.
    """
    from dml.core.config import directorio_aplicacion

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lineas: list[str] = []

    def anotar(texto: str) -> None:
        lineas.append(texto)

    fallos: list[str] = []
    try:
        from PySide6 import QtCore  # noqa: F401

        anotar(f"PySide6        : OK ({QtCore.__version__})")
    except Exception as exc:  # noqa: BLE001
        fallos.append(f"PySide6 no disponible: {exc}")
    for modulo in ("numpy", "pandas", "scipy", "statsmodels", "matplotlib", "openpyxl", "yaml", "yfinance", "requests", "cloudscraper"):
        try:
            import importlib

            mod = importlib.import_module(modulo)
            anotar(f"{modulo:15s}: OK {getattr(mod, '__version__', '')}")
        except Exception as exc:  # noqa: BLE001
            anotar(f"{modulo:15s}: FALTA ({type(exc).__name__})")
            fallos.append(f"falta la dependencia {modulo}")

    try:
        from dml.analisis import analizar_demo
        from dml.core.cache import Cache
        from dml.core.config import directorio_aplicacion, ruta_config, ruta_datos_app
        from dml.core.tipos import Fuentes

        base = directorio_aplicacion()
        anotar(f"config.yaml    : {ruta_config() or 'no encontrado (se usan los valores por defecto)'}")
        # La cache de la prueba vive en la carpeta de datos, no junto al ejecutable:
        # asi la autoprueba no deja restos en el paquete que se comparte.
        cache = Cache(directorio=str(ruta_datos_app() / ".dml_cache_autotest"), ttl_horas=1)
        resultado = analizar_demo("DEMO", config, fuentes=Fuentes())
        anotar(
            f"analisis DEMO  : spot={resultado.spot} calificacion={resultado.calificacion} "
            f"decision={resultado.decision} criterios={len(resultado.criterios)}"
        )
        if len(resultado.criterios) != 12:
            fallos.append(f"se esperaban 12 criterios y hay {len(resultado.criterios)}")
        if resultado.decision not in {"COMPRAR", "MANTENER", "NO INVERTIR"}:
            fallos.append(f"decision inesperada: {resultado.decision}")

        from PySide6.QtWidgets import QApplication, QTableWidget

        from dml.ui.ventana_principal import VentanaPrincipal, cargar_demo_en_ventana

        app = QApplication.instance() or QApplication([])
        ventana = VentanaPrincipal(config=config, cache=cache, demo=True)
        cargar_demo_en_ventana(ventana, ["DEMO"])
        pestanas = ventana.pestanas.count()
        anotar(f"ventana        : {pestanas} pestanas")
        if pestanas != 11:
            fallos.append(f"se esperaban 11 pestanas y hay {pestanas}")
        filas = sum(t.rowCount() for t in ventana.tabs["principal"].findChildren(QTableWidget))
        anotar(f"parrilla       : {filas} filas en la pestana Principal")
        if filas < 12:
            fallos.append(f"la parrilla solo muestra {filas} filas")
        app.processEvents()
        ventana.close()

        from dml.export.excel import exportar_excel

        # El libro de prueba tambien se crea en la carpeta de datos y se borra al
        # terminar: la autoprueba no debe dejar nada en el paquete.
        carpeta_temporal = ruta_datos_app()
        destino = carpeta_temporal / ".autotest.xlsx"
        exportar_excel([resultado, resultado], destino, con_formulas=True, fuentes=Fuentes())
        import openpyxl

        libro = openpyxl.load_workbook(destino)
        anotar(f"excel          : {len(libro.sheetnames)} hojas -> {libro.sheetnames}")
        if len(libro.sheetnames) != 11:
            fallos.append(f"el Excel tiene {len(libro.sheetnames)} hojas en vez de 11")
        libro.close()  # sin cerrarlo, Windows no deja borrarlo
        destino.unlink(missing_ok=True)
        shutil.rmtree(carpeta_temporal / ".dml_cache_autotest", ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        import traceback

        fallos.append(f"{type(exc).__name__}: {exc}")
        anotar(traceback.format_exc())

    anotar("")
    anotar("RESULTADO: OK" if not fallos else f"RESULTADO: FALLOS -> {fallos}")
    informe = "\n".join(lineas)
    ruta = Path(ruta_informe) if ruta_informe else (directorio_aplicacion() / "autotest.txt")
    try:
        ruta.write_text(informe, encoding="utf-8")
    except Exception:
        ruta = Path.home() / "dml_finance_autotest.txt"
        try:
            ruta.write_text(informe, encoding="utf-8")
        except Exception:
            pass
    try:
        print(informe)
    except Exception:
        pass
    return 0 if not fallos else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Punto de entrada: prepara la configuracion y abre la interfaz grafica."""
    args = construir_parser().parse_args(argv)

    from dml.core.log import configurar_logging

    configurar_logging(verbose=args.verbose)

    from dml.core.config import cargar_config

    overrides = {}
    if args.modo:
        overrides["general"] = {**(overrides.get("general") or {}), "modo": args.modo}
    if args.indice:
        overrides["general"] = {**(overrides.get("general") or {}), "indice": args.indice}
    if args.meses:
        overrides["general"] = {**(overrides.get("general") or {}), "meses": int(args.meses)}
    if args.sin_cache:
        overrides["datos"] = {"cache": False}
    if args.tema:
        overrides["ui"] = {"tema": args.tema}

    config = cargar_config(Path(args.config) if args.config else None, overrides or None)

    if args.autotest:
        return autotest(config, args.autotest_salida)

    try:
        from dml.ui.app import ejecutar
    except Exception as exc:
        print(
            "No se pudo cargar la interfaz grafica (PySide6).\n"
            f"Detalle: {exc}\n\n"
            "Instala las dependencias con:\n    pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        return 2

    return ejecutar(
        argv=[sys.argv[0]],
        demo=args.demo,
        tickers=args.tickers,
        config=config,
        tema=args.tema,
        marca=args.marca,
    )


if __name__ == "__main__":
    sys.exit(main())
