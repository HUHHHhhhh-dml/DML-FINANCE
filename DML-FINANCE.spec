# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller de DML-FINANCE (fuente unica del empaquetado).

Se puede usar de dos formas, con resultados identicos:

* ``python empaquetar.py`` — flujo recomendado: genera el icono desde el logo si
  hace falta, comprueba el resultado y crea el lanzador (acceso directo o
  ``.desktop``).
* ``pyinstaller DML-FINANCE.spec`` — empaquetado directo de la receta.

Las rutas se calculan respecto a la raiz del proyecto (la carpeta que contiene
``main.py``), subiendo desde la posicion de este archivo: asi la receta funciona
igual si se ejecuta desde la raiz del proyecto, si ``empaquetar.py`` genera una
copia efectiva en ``build/``, o si el proyecto se clona en otra carpeta. No hay
ninguna ruta absoluta escrita a mano.

Multiplataforma (Windows / Linux / macOS)
----------------------------------------
La receta se adapta al sistema donde se ejecuta:

* **Windows**: el icono viaja **embebido** en el ``.exe`` (``icon=[...icono.ico]``)
  y el escritorio usa un acceso directo ``.lnk``.
* **Linux**: un binario ELF **no lleva iconos embebidos**; el icono se resuelve
  por escritorio con un ``.desktop`` + PNG instalado en ``hicolor``. Aqui se
  empaquetan los PNG en ``recursos/`` para que la ventana y el alt-tab muestren
  el logo, y ``empaquetar.py`` genera el ``.desktop``.
* ``upx`` solo se activa si la herramienta esta realmente instalada (en Fedora
  viene en el paquete ``upx``); si no, PyInstaller solo avisaria y perderia tiempo.

Antes de empaquetar por primera vez (o tras cambiar el logo):

    python generar_icono.py
"""

import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _raiz_proyecto(desde: Path) -> Path:
    """Sube desde ``desde`` hasta la carpeta que contiene ``main.py``."""
    actual = Path(desde).resolve()
    for candidata in [actual, *actual.parents]:
        if (candidata / "main.py").is_file():
            return candidata
    return actual


RAIZ = _raiz_proyecto(SPECPATH)
RECURSOS = RAIZ / "recursos"
ES_WINDOWS = sys.platform.startswith("win")
UPX_DISPONIBLE = shutil.which("upx") is not None

hiddenimports = [
    'yfinance',
    'statsmodels.api',
    'statsmodels.stats.stattools',
    'statsmodels.stats.diagnostic',
    'scipy.stats',
    'openpyxl',
    'cloudscraper',
    'matplotlib.backends.backend_qtagg',
    # curl_cffi es una extension binaria (_wrapper.abi3.so). Tanto yfinance 1.7
    # como cloudscraper pueden usarla como motor HTTP; si PyInstaller no ve el
    # import dinamico, el analisis falla en tiempo de ejecucion y no en el build.
    'curl_cffi',
]
hiddenimports += collect_submodules('dml')

# config.yaml queda editable junto al binario; los iconos viajan en recursos/
# para que la ventana y la barra de tareas muestren el logo dentro del paquete.
datas = [
    (str(RAIZ / 'config.yaml'), '.'),
    (str(RECURSOS / 'icono.ico'), 'recursos'),
    (str(RECURSOS / 'icono.png'), 'recursos'),
    (str(RECURSOS / 'DML-Icon.png'), 'recursos'),
]

# Datos que no son codigo y que las dependencias leen en tiempo de ejecucion.
# Sin ellos el programa arranca pero falla al primer acceso a la red:
#   * certifi/cacert.pem  -> almacen de autoridades de certificacion (HTTPS).
#   * cloudscraper/...    -> lista de user-agents que usa el scraping.
for _paquete in ('certifi', 'cloudscraper', 'curl_cffi'):
    for _origen, _destino in collect_data_files(_paquete):
        _entrada = (str(_origen), _destino)
        if _entrada not in datas:
            datas.append(_entrada)

a = Analysis(
    [str(RAIZ / 'main.py')],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Aligerar el ejecutable: nada de esto lo usa la aplicacion.
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'IPython', 'notebook', 'pytest', 'playwright'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# El icono embebido solo tiene sentido en Windows: un binario ELF no lleva
# recursos de icono, asi que en Linux se pasa ``None`` y el icono se resuelve por
# escritorio (``.desktop`` + PNG en ``hicolor``). La linea conserva el mismo
# formato en ambas ramas para que ``empaquetar.py --sin-icono`` pueda quitarla.
_ICONO_RUTA = str(RECURSOS / 'icono.ico') if ES_WINDOWS else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DML-FINANCE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=UPX_DISPONIBLE,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICONO_RUTA,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=UPX_DISPONIBLE,
    upx_exclude=[],
    name='DML-FINANCE',
)
