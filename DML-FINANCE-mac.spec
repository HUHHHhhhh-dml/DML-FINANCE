# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller de DML-FINANCE para **macOS** (genera ``DML-FINANCE.app``).

Este archivo es independiente de la receta de Windows/Linux
(``DML-FINANCE.spec``): **no la sustituye**. En macOS el resultado no es un
ejecutable suelto sino un *bundle* (``.app``), que es una carpeta con una
estructura fija y un ``Info.plist``. Eso obliga a un ``BUNDLE()`` que no existe
en las otras plataformas.

Uso
---
::

    python empaquetar_mac.py                 # flujo recomendado (.app + firma + .dmg/.zip)
    python empaquetar_mac.py --app           # solo el .app

    # O directamente, sin el empaquetador:
    pyinstaller --noconfirm DML-FINANCE-mac.spec

**Solo funciona en macOS.** Si se ejecuta en Linux o Windows aborta al principio
con un mensaje claro: PyInstaller no puede generar un ``.app`` desde otro sistema.

Diferencias con el ``.app`` y por que
-------------------------------------
* ``Info.plist``: es el "DNI" de la aplicacion ante macOS. Aqui se declara el
  identificador, la version, que es una app de interfaz (``NSPrincipalClass``) y
  que soporta pantallas Retina (``NSHighResolutionCapable``). Sin
  ``NSPrincipalClass = NSApplication`` la interfaz **no se dibuja en Retina**.
* ``LSMinimumSystemVersion``: PySide6 6.12 no arranca en macOS antiguos, asi que
  se declara el minimo real en lugar de dejar que el sistema lo descubra
  fallando.
* ``LSApplicationCategoryType``: hace que la app aparezca en la categoria
  correcta de Launchpad y del Finder.

Antes de empaquetar por primera vez (o tras cambiar el logo):

    python generar_icns.py
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# --------------------------------------------------------------------------
# Comprobacion de plataforma: fallar pronto y con un mensaje util
# --------------------------------------------------------------------------
if not sys.platform.startswith("darwin"):
    raise SystemExit(
        "Esta receta genera un .app de macOS y solo puede ejecutarse en macOS.\n"
        f"Sistema actual: {sys.platform}.\n\n"
        "Si estas en Linux, usa la receta de Linux:\n"
        "    python empaquetar.py --tar\n"
        "Si estas en Windows:\n"
        "    python empaquetar.py --zip\n"
    )


def _raiz_proyecto(desde: Path) -> Path:
    """Sube desde ``desde`` hasta la carpeta que contiene ``main.py``."""
    actual = Path(desde).resolve()
    for candidata in [actual, *actual.parents]:
        if (candidata / "main.py").is_file():
            return candidata
    return actual


RAIZ = _raiz_proyecto(SPECPATH)
RECURSOS = RAIZ / "recursos"

#: Identificador del bundle (formato inverso de dominio). macOS lo usa para
#: preferencias, permisos y para el propio icono en el Dock.
IDENTIFICADOR = "com.dmlfinance.analizador"
VERSION = "1.0.0"

#: Version minima de macOS. PySide6 6.12 usa Qt 6.12, que ya no soporta versiones
#: anteriores a macOS 12; declararlo evita un fallo opaco al abrir la app.
MACOS_MINIMO = "12.0"

hiddenimports = [
    'yfinance',
    'statsmodels.api',
    'statsmodels.stats.stattools',
    'statsmodels.stats.diagnostic',
    'scipy.stats',
    'openpyxl',
    'cloudscraper',
    'matplotlib.backends.backend_qtagg',
    # curl_cffi es una extension binaria (en macOS, _wrapper.abi3.so) que tanto
    # yfinance como cloudscraper pueden usar como motor HTTP. Se importa de forma
    # dinamica, asi que PyInstaller no la ve: sin declararla, el fallo aparece en
    # tiempo de ejecucion y no al compilar.
    'curl_cffi',
]
hiddenimports += collect_submodules('dml')

datas = [
    (str(RAIZ / 'config.yaml'), '.'),
    (str(RECURSOS / 'icono.png'), 'recursos'),
    (str(RECURSOS / 'DML-Icon.png'), 'recursos'),
]

# Datos que no son codigo y que las dependencias leen al vuelo. Sin
# certifi/cacert.pem falla todo el HTTPS; sin el JSON de cloudscraper, el scraping.
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
    # Excluir todo lo que la aplicacion no usa (aligera el .app varios cientos de MB).
    excludes=[
        'tkinter', 'PyQt5', 'PyQt6', 'IPython', 'notebook', 'pytest', 'playwright',
        # En macOS se anaden los modulos que PySide6 trae y aqui no se usan: la
        # aplicacion es de widgets clasicos (no hay QML/Quick ni PDF ni WebEngine).
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtVirtualKeyboard',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DML-FINANCE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # En macOS UPX rompe la firma de codigo: nunca usarlo.
    console=False,      # App de ventana: sin terminal.
    disable_windowed_traceback=False,
    argv_emulation=False,   # True rompe Qt; en macOS moderno no hace falta.
    target_arch=None,       # Se hereda la arquitectura del Python que compila (arm64).
    codesign_identity=None,  # La firma ad-hoc la hace empaquetar_mac.py al final.
    entitlements_file=None,
    icon=None,          # El icono del .app va en Info.plist, via BUNDLE.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DML-FINANCE',
)

# --------------------------------------------------------------------------
# El bundle de macOS
# --------------------------------------------------------------------------
# ``BUNDLE`` envuelve la carpeta de COLLECT en la estructura estandar:
#
#     DML-FINANCE.app/
#     └── Contents/
#         ├── Info.plist          <- metadatos (los de abajo)
#         ├── MacOS/              <- punto de entrada del bundle
#         ├── Frameworks/         <- aqui acaba el contenido de COLLECT
#         └── Resources/          <- el .icns
#
# Sin ``NSPrincipalClass = NSApplication`` la ventana se renderiza a baja
# resolucion en pantallas Retina, que es el fallo tipico de empaquetar Qt en Mac.
app = BUNDLE(
    coll,
    name='DML-FINANCE.app',
    icon=str(RECURSOS / 'icono.icns'),
    bundle_identifier=IDENTIFICADOR,
    version=VERSION,
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': MACOS_MINIMO,
        'LSApplicationCategoryType': 'public.app-category.finance',
        'CFBundleDisplayName': 'DML-FINANCE',
        'CFBundleName': 'DML-FINANCE',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'NSHumanReadableCopyright': 'DML-FINANCE - herramienta de analisis; '
                                    'no constituye asesoria financiera.',
        # La app no necesita permisos especiales (ni camara, ni contactos): no se
        # declaran claves de privacidad, asi que macOS no mostrara avisos por ellas.
        'LSMultipleInstancesProhibited': False,
    },
)
