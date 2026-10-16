# -*- coding: utf-8 -*-
"""Empaquetado de DML-FINANCE para **macOS**: ``DML-FINANCE.app``, ``.dmg`` y ``.zip``.

Este archivo es la version macOS del empaquetador y **no sustituye** a
``empaquetar.py`` (Windows/Linux): son flujos distintos a proposito. Aqui el
resultado no es un ejecutable suelto sino un *bundle* ``.app``, que macOS trata
como una aplicacion de verdad (Dock, Launchpad, Finder, doble clic).

Uso
---
::

    python empaquetar_mac.py                  # .app + firma ad-hoc + .dmg + .zip
    python empaquetar_mac.py --app            # solo el .app
    python empaquetar_mac.py --sin-firma      # sin firmar (no recomendado)
    python empaquetar_mac.py --dmg            # ademas el .dmg
    python empaquetar_mac.py --zip            # ademas el .zip
    python empaquetar_mac.py --instalar       # copia el .app a /Applications
    python empaquetar_mac.py --desinstalar    # deshace --instalar
    python empaquetar_mac.py --limpiar        # borra build/ y dist/ antes de empezar
    python empaquetar_mac.py --consola        # compila con terminal (para depurar)

Salida (modo completo):

* ``dist/DML-FINANCE.app``                  <- la aplicacion (doble clic).
* ``dist/DML-FINANCE-1.0.0-macOS-arm64.dmg``<- instalador con arrastrar a Aplicaciones.
* ``dist/DML-FINANCE-1.0.0-macOS-arm64.zip``<- el .app comprimido, para adjuntar.
* ``dist/LEEME-EJECUTABLE.txt``             <- instrucciones para quien lo recibe.

Aviso importante sobre Gatekeeper
---------------------------------
El ``.app`` se firma en modo **ad-hoc**: es gratis y no necesita cuenta de Apple,
pero **no sustituye a la notarizacion**. En el Mac de destino, la primera vez,
macOS mostrara "no se puede abrir porque proviene de un desarrollador no
identificado". La forma de abrirlo esta en ``INSTALACION-MAC.md`` y resumida en el
LEEME. Si necesitas que se abra sin ningun aviso, hace falta un certificado
Developer ID y notarizar (el flujo esta documentado en la guia).

Requisito de plataforma
-----------------------
PyInstaller **no puede generar un ``.app`` desde Linux o Windows**: el bundle se
construye con herramientas de macOS. Por eso este script aborta con un mensaje
claro si no se ejecuta en Darwin.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence

RAIZ = Path(__file__).resolve().parent
NOMBRE = "DML-FINANCE"
RECURSOS = RAIZ / "recursos"
LOGO = RECURSOS / "DML-Icon.png"
ICNS = RECURSOS / "icono.icns"
PNG = RECURSOS / "icono.png"
CONFIG = RAIZ / "config.yaml"
LEEME = RAIZ / "LEEME-EJECUTABLE.txt"
SPEC_MAC = RAIZ / "DML-FINANCE-mac.spec"

IDENTIFICADOR = "com.dmlfinance.analizador"
VERSION = "1.0.0"
ES_MAC = sys.platform == "darwin"


# --------------------------------------------------------------------------
# Argumentos
# --------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="empaquetar_mac.py",
        description="Genera DML-FINANCE.app, su .dmg y su .zip para macOS.",
    )
    parser.add_argument("--app", action="store_true",
                        help="construye solo el .app (sin .dmg ni .zip)")
    parser.add_argument("--dmg", action="store_true", help="crea ademas el .dmg")
    parser.add_argument("--zip", dest="zip_salida", nargs="?", const="", default=None,
                        metavar="ARCHIVO", help="crea ademas el .zip")
    parser.add_argument("--limpiar", action="store_true", help="borra build/ y dist/ antes de empezar")
    parser.add_argument("--consola", action="store_true", help="compila con terminal (util para depurar)")
    parser.add_argument("--sin-firma", action="store_true",
                        help="no firma el .app (macOS lo bloqueara con mas insistencia)")
    parser.add_argument("--identidad", default="-", metavar="CERT",
                        help="certificado para firmar (por defecto '-' = ad-hoc; "
                             "usa 'Developer ID Application: ...' para firma real)")
    parser.add_argument("--runtime", action="store_true",
                        help="activa el hardened runtime (solo necesario para notarizar; "
                             "puede impedir el arranque con firma ad-hoc)")
    parser.add_argument("--sin-poda", action="store_true",
                        help="no borra los qml/plugins de Qt que la aplicacion no usa")
    parser.add_argument("--universal", action="store_true",
                        help="intenta un binario universal2 (requiere un Python universal2)")
    parser.add_argument("--instalar", action="store_true", help="copia el .app a /Applications")
    parser.add_argument("--desinstalar", action="store_true",
                        help="borra el .app de /Applications y los datos del usuario")
    return parser


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

def ruta_app() -> Path:
    """Ruta del ``.app`` que produce PyInstaller (``dist/DML-FINANCE.app``)."""
    return RAIZ / "dist" / f"{NOMBRE}.app"


def ruta_ejecutable(app: Optional[Path] = None) -> Path:
    """Ruta del ejecutable dentro del bundle.

    La estructura de un ``.app`` es fija: ``Contents/MacOS/`` es el punto de
    entrada y PyInstaller coloca el contenido de ``COLLECT`` en
    ``Contents/Frameworks/``.
    """
    base = app if app is not None else ruta_app()
    return base / "Contents" / "MacOS" / NOMBRE


def ruta_interna(app: Optional[Path] = None) -> Path:
    """Carpeta interna del bundle, donde viven Python, Qt y ``config.yaml``."""
    base = app if app is not None else ruta_app()
    return base / "Contents" / "Frameworks"


def carpeta_datos_nombre() -> str:
    """Carpeta de datos del usuario (coincide con la que elige la aplicacion).

    ``dml/core/config.py`` prueba ``DML_FINANCE_HOME`` y luego ``~/.dml_finance``.
    Se usa el mismo nombre para que la guia y la aplicacion no se contradigan.
    """
    return str(Path.home() / ".dml_finance")


def ruta_registro() -> Path:
    """Archivo donde se anota lo instalado, para poder desinstalar sin ambiguedad.

    Se guarda en la carpeta de datos del usuario, que **no se borra** al
    desinstalar salvo que se pida expresamente.
    """
    return Path(carpeta_datos_nombre()) / "instalado.json"


# --------------------------------------------------------------------------
# Icono
# --------------------------------------------------------------------------

def asegurar_icns() -> Optional[Path]:
    """Genera ``recursos/icono.icns`` si hace falta y devuelve su ruta.

    Se reutiliza ``generar_icns.py`` (que a su vez usa ``iconutil`` en macOS o su
    propio escritor). Si no hay logo ni ``.icns``, se empaqueta sin icono: es
    preferible una app sin icono a una que no se construye.
    """
    if ICNS.is_file() and LOGO.is_file() and ICNS.stat().st_mtime >= LOGO.stat().st_mtime:
        return ICNS
    try:
        import generar_icns

        generado = generar_icns.generar_icns(LOGO, ICNS, forzar=True)
        return generado
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo generar el .icns ({exc}).")
        return ICNS if ICNS.is_file() else None


# --------------------------------------------------------------------------
# Receta efectiva
# --------------------------------------------------------------------------

def construir_receta(consola: bool, icono: Optional[Path], universal: bool) -> str:
    """Devuelve la receta de macOS con las opciones de la linea de comandos.

    Se parte de ``DML-FINANCE-mac.spec`` y se sustituyen solo las opciones que
    dependen de los argumentos. Se hace por texto (y no con opciones de
    PyInstaller) porque, cuando se le pasa una receta, PyInstaller **ignora**
    ``--windowed``, ``--console`` y ``--name``.
    """
    receta = SPEC_MAC.read_text(encoding="utf-8")
    if consola:
        receta = receta.replace("console=False", "console=True", 1)
    if icono is None:
        receta = receta.replace("    icon=str(RECURSOS / 'icono.icns'),\n", "")
    if universal:
        receta = receta.replace("target_arch=None,", "target_arch='universal2',", 1)
    return receta


def escribir_receta(consola: bool, icono: Optional[Path], universal: bool) -> Path:
    """Escribe la receta efectiva en ``build/`` y devuelve su ruta.

    Se escribe en ``build/`` (y no junto al proyecto) para no ensuciar la receta
    versionada y dejar constancia de con que opciones se construyo.
    """
    destino = RAIZ / "build" / "receta-mac-efectiva.spec"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(construir_receta(consola, icono, universal), encoding="utf-8")
    return destino


def comando(receta: Path) -> List[str]:
    """Orden de PyInstaller para una receta concreta."""
    return [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(receta)]


# --------------------------------------------------------------------------
# Limpieza del bundle
# --------------------------------------------------------------------------

#: Carpetas de Qt que la aplicacion no usa. En macOS PyInstaller copia los
#: plugins y los modulos QML completos; como la aplicacion es de widgets
#: clasicos, se pueden quitar. A diferencia de Linux, aqui **no se borran
#: librerias .dylib sueltas**: en macOS cada libreria va firmada y quitar un
#: framework rompe la firma del bundle entero.
PODA_MAC = (
    Path("PySide6") / "Qt" / "qml",
    Path("PySide6") / "Qt" / "plugins" / "qmltooling",
    Path("PySide6") / "Qt" / "plugins" / "imageformats" / "libqpdf.dylib",
    Path("PySide6") / "Qt" / "plugins" / "generic" / "libqtuiotouchplugin.dylib",
)


def podar_app(app: Path) -> int:
    """Borra del ``.app`` los componentes de Qt que la aplicacion no usa.

    Returns:
        Los MB liberados (aproximados).
    """
    interno = ruta_interna(app)
    if not interno.is_dir():
        return 0
    antes = _tamano(interno)
    for relativa in PODA_MAC:
        objetivo = interno / relativa
        try:
            if objetivo.is_dir():
                shutil.rmtree(objetivo, ignore_errors=True)
            elif objetivo.is_file():
                objetivo.unlink()
        except OSError as exc:  # noqa: BLE001
            print(f"  Aviso: no se pudo borrar {relativa}: {exc}")
    # Los .DS_Store y las carpetas __pycache__ no aportan nada y ensucian el .app.
    for basura in list(interno.rglob(".DS_Store")) + list(interno.rglob("__pycache__")):
        if basura.is_dir():
            shutil.rmtree(basura, ignore_errors=True)
        else:
            basura.unlink(missing_ok=True)
    return int((antes - _tamano(interno)) / 1024 / 1024)


def _tamano(carpeta: Path) -> int:
    """Tamano en bytes de una carpeta (nunca lanza)."""
    try:
        return sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    except OSError:  # pragma: no cover
        return 0


# --------------------------------------------------------------------------
# Firma de codigo (ad-hoc)
# --------------------------------------------------------------------------

#: Derechos que se le conceden a la aplicacion al firmarla.
#:
#: Qt y Python necesitan los tres primeros; ``disable-library-validation`` es el
#: que permite que el proceso cargue los frameworks de Qt, que llevan su propia
#: firma. Sin el, la app arranca y muere al cargar la primera libreria de Qt.
DERECHOS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
"""


def firmar_app(app: Path, identidad: str = "-", runtime: bool = False) -> bool:
    """Firma el ``.app`` (ad-hoc por defecto) y comprueba el resultado.

    Firma **cada binario y libreria por dentro hacia fuera** y despues el bundle.
    Es necesario porque ``codesign --deep`` esta obsoleto para firmar y porque
    PyInstaller deja cientos de ``.so``/``.dylib`` propios; si no se firman, la
    firma del bundle no es valida.

    Args:
        app: ruta del ``.app``.
        identidad: ``"-"`` para firma ad-hoc, o el nombre de un certificado
            Developer ID para la firma real.
        runtime: activa el *hardened runtime* (``--options=runtime``). Solo es
            necesario para **notarizar**; se deja desactivado por defecto porque
            restringe la carga de bibliotecas y puede impedir el arranque.

    Returns:
        ``True`` si la verificacion final pasa.
    """
    if not ES_MAC:
        print("  (la firma de codigo solo existe en macOS; se omite)")
        return False
    if not shutil.which("codesign"):
        print("  Aviso: no hay 'codesign' (instala las Command Line Tools de Xcode).")
        return False

    adjunta = identidad == "-"
    derechos = app.parent / "derechos.plist"
    try:
        derechos.write_text(DERECHOS, encoding="utf-8")
    except OSError:
        derechos = None

    # 1) Todo lo firmable, de dentro hacia fuera. Los enlaces simbolicos se saltan:
    #    firmar un enlace firma el destino y corrompe la estructura.
    candidatos: List[Path] = [app]
    for ruta in app.rglob("*"):
        if ruta.is_symlink() or not ruta.is_file():
            continue
        if ruta.suffix in (".so", ".dylib") or _es_macho(ruta):
            candidatos.append(ruta)
    # Primero los mas profundos (asi las dependencias quedan firmadas antes).
    candidatos.sort(key=lambda p: len(p.parts), reverse=True)

    firmados, fallos = 0, 0
    for ruta in candidatos:
        orden = ["codesign", "--force", "--sign", identidad]
        # El "hardened runtime" SOLO es obligatorio para notarizar. Con firma
        # ad-hoc se deja DESACTIVADO a proposito: activarlo restringe la carga de
        # bibliotecas y hay casos documentados en los que la app deja de arrancar.
        # Por eso es una opcion (--runtime) y no el comportamiento por defecto.
        if runtime:
            orden.append("--options=runtime")
        orden.append("--timestamp" if not adjunta else "--timestamp=none")
        if ruta == app and derechos is not None:
            orden += ["--entitlements", str(derechos)]
        orden.append(str(ruta))
        resultado = subprocess.run(orden, capture_output=True, text=True, check=False)
        if resultado.returncode == 0:
            firmados += 1
        else:
            fallos += 1
            if ruta == app:
                print(f"  Aviso: fallo la firma del bundle: {resultado.stderr.strip()[:200]}")

    if derechos is not None:
        derechos.unlink(missing_ok=True)

    # 2) Verificacion: es lo unico que demuestra que la firma sirve.
    #    Se verifica el bundle (que incluye el sello de sus componentes). ``--deep``
    #    esta obsoleto para firmar, pero sigue siendo valido para verificar.
    verificacion = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=1", str(app)],
        capture_output=True, text=True, check=False,
    )
    tipo = "ad-hoc" if adjunta else f"con identidad '{identidad}'"
    print(f"  Firma {tipo}: {firmados} archivos firmados, {fallos} fallos")
    if verificacion.returncode == 0:
        print("  Verificacion de la firma: [OK]")
        return True
    print(f"  Verificacion de la firma: [FALLO]\n    {verificacion.stderr.strip()[:400]}")
    return False


def _es_macho(ruta: Path) -> bool:
    """True si el archivo es un binario Mach-O (lo que macOS puede firmar).

    Se miran los numeros magicos; no vale la extension, porque los ejecutables de
    PyInstaller no llevan ninguna.
    """
    try:
        with ruta.open("rb") as f:
            magia = f.read(4)
    except OSError:
        return False
    return magia in (
        b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",   # Mach-O 32/64 big-endian
        b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",   # Mach-O 32/64 little-endian
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",   # fat/universal
    )


# --------------------------------------------------------------------------
# Informe
# --------------------------------------------------------------------------

def _version_macos() -> str:
    """Version de macOS del equipo de compilacion."""
    try:
        return platform.mac_ver()[0] or "desconocida"
    except Exception:  # noqa: BLE001
        return "desconocida"


def informar(app: Path) -> None:
    """Imprime un resumen del bundle y de sus puntos debiles conocidos."""
    print("\nmacOS")
    print("-" * 60)
    print(f"  Version de macOS     : {_version_macos()}")
    print(f"  Arquitectura         : {platform.machine()}")
    ejecutable = ruta_ejecutable(app)
    if ejecutable.is_file():
        print(f"  Ejecutable           : {ejecutable.relative_to(app)}")
        if shutil.which("lipo"):
            arquitecturas = subprocess.run(["lipo", "-archs", str(ejecutable)],
                                           capture_output=True, text=True, check=False)
            if arquitecturas.returncode == 0:
                print(f"  Arquitecturas reales : {arquitecturas.stdout.strip()}")
            if "arm64" not in arquitecturas.stdout and "x86_64" in arquitecturas.stdout:
                print("  Aviso: el binario es solo x86_64; en Apple Silicon correra")
                print("         por Rosetta 2 (mas lento).")
    print(f"  Tamano del .app      : {_tamano(app) / 1024 / 1024:.0f} MB")
    print("  Gatekeeper           : el .app va firmado ad-hoc, SIN notarizar.")
    print("                         El primer arranque en otro Mac pedira confirmacion")
    print("                         (ver INSTALACION-MAC.md).")


# --------------------------------------------------------------------------
# Paquetes: .dmg y .zip
# --------------------------------------------------------------------------

def crear_dmg(app: Path, salida: Optional[str] = None) -> Optional[Path]:
    """Crea un ``.dmg`` con la aplicacion y un enlace a ``/Applications``.

    El diseno es el habitual de macOS: se abre el ``.dmg``, se ve la app junto a la
    carpeta Aplicaciones y se arrastra una sobre otra para instalar. Se hace con
    ``hdiutil``, que viene con macOS, sin dependencias de terceros.

    Returns:
        La ruta del ``.dmg``, o ``None`` si no se pudo crear.
    """
    if not ES_MAC:
        print("El .dmg solo se puede crear en macOS (necesita hdiutil).", file=sys.stderr)
        return None
    if not shutil.which("hdiutil"):
        print("No se encontro 'hdiutil'.", file=sys.stderr)
        return None

    destino = Path(salida) if salida else (
        RAIZ / "dist" / f"{NOMBRE}-{VERSION}-macOS-{platform.machine()}.dmg")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_file():
        destino.unlink()

    # Se prepara una carpeta de escenario: el .dmg contiene exactamente eso.
    escenario = RAIZ / "build" / "dmg"
    shutil.rmtree(escenario, ignore_errors=True)
    escenario.mkdir(parents=True, exist_ok=True)
    copia = escenario / app.name
    # "ditto" conserva permisos, enlaces y recursos de macOS mejor que copytree.
    subprocess.run(["ditto", str(app), str(copia)], check=False)
    if not copia.is_dir():
        shutil.copytree(app, copia, symlinks=True)
    # Enlace a /Applications para poder arrastrar (el gesto que espera el usuario).
    enlace = escenario / "Aplicaciones"
    try:
        enlace.symlink_to("/Applications")
    except OSError:
        pass
    if LEEME.is_file():
        shutil.copy2(LEEME, escenario / LEEME.name)

    resultado = subprocess.run(
        ["hdiutil", "create", "-volname", NOMBRE, "-srcfolder", str(escenario),
         "-ov", "-format", "UDZO", "-quiet", str(destino)],
        capture_output=True, text=True, check=False,
    )
    shutil.rmtree(escenario, ignore_errors=True)
    if resultado.returncode != 0 or not destino.is_file():
        print(f"hdiutil fallo: {resultado.stderr.strip()[:300]}", file=sys.stderr)
        return None
    print(f"\nDMG listo:\n  {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")
    print("\nQuien lo reciba: abrir el .dmg y arrastrar DML-FINANCE a Aplicaciones.")
    return destino


def crear_zip(app: Path, salida: Optional[str] = None) -> Optional[Path]:
    """Crea un ``.zip`` con el ``.app`` y el LEEME.

    Se usa ``ditto -c -k --sequesterRsrc --keepParent``, que es la forma correcta de
    comprimir un ``.app`` en macOS: conserva la estructura, los enlaces y los
    permisos, y al descomprimir con el Finder el bundle queda intacto. Un
    ``zipfile`` de Python tambien valdria, pero pierde el bit de ejecucion de los
    binarios internos y la app no arrancaria.
    """
    destino = Path(salida) if salida else (
        RAIZ / "dist" / f"{NOMBRE}-{VERSION}-macOS-{platform.machine()}.zip")
    if destino.suffix.lower() != ".zip":
        destino = destino.with_suffix(".zip")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_file():
        destino.unlink()

    if ES_MAC and shutil.which("ditto"):
        resultado = subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(destino)],
            capture_output=True, text=True, check=False,
        )
        if resultado.returncode != 0 or not destino.is_file():
            print(f"ditto fallo: {resultado.stderr.strip()[:300]}", file=sys.stderr)
            return None
    else:
        # Respaldo portable (util para probar en Linux, no para distribuir en Mac).
        print("Aviso: sin 'ditto' el ZIP puede perder permisos; en macOS usa ditto.")
        with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for archivo in sorted(app.rglob("*")):
                if archivo.is_file() and not archivo.is_symlink():
                    zf.write(archivo, archivo.relative_to(app.parent))
    if LEEME.is_file():
        _anadir_leeme_al_zip(destino, LEEME)

    print(f"\nZIP listo:\n  {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")
    return destino


def _anadir_leeme_al_zip(destino: Path, leeme: Path) -> None:
    """Añade el LEEME al ZIP ya creado (se abre en modo 'append')."""
    try:
        with zipfile.ZipFile(destino, "a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(leeme, leeme.name)
    except Exception:  # noqa: BLE001 - el ZIP ya es util sin el LEEME
        pass


# --------------------------------------------------------------------------
# LEEME
# --------------------------------------------------------------------------

def escribir_leeme(app: Path) -> None:
    """Escribe el LEEME que acompaña al .dmg y al .zip."""
    texto = f"""DML-FINANCE en macOS - como se abre
===================================

1) INSTALAR
   Abre "{NOMBRE}-{VERSION}-macOS-{platform.machine()}.dmg" y arrastra
   **DML-FINANCE** a la carpeta **Aplicaciones**.
   (O descomprime el .zip y mueve DML-FINANCE.app a Aplicaciones.)

2) LA PRIMERA VEZ: macOS lo bloqueara
   El programa no esta notarizado por Apple (eso requiere una cuenta de
   desarrollador de pago), asi que macOS mostrara un aviso del tipo
   "no se puede abrir porque proviene de un desarrollador no identificado".

   Para abrirlo, elige UNA de estas dos formas:

   a) Clic derecho sobre el icono -> "Abrir" -> "Abrir" otra vez.
      (Solo hace falta la primera vez.)

   b) Desde Terminal:
        xattr -dr com.apple.quarantine /Applications/{NOMBRE}.app

3) USARLO
   Escribe un ticker (por ejemplo NVDA) y pulsa "Analizar" o Enter.
   Para exportar a Excel, el boton "Exportar a Excel" (o Cmd+E).

La aplicacion NO genera ningun Excel por si sola: solo cuando se lo pides.

Datos y cache
-------------
Preferencias, cache y trazas se guardan en:
    ~/.dml_finance

Si esa carpeta no se pudiera escribir, la aplicacion usa como respaldo:
    ~/Library/Application Support/DML-FINANCE
    (y, en ultimo caso, una carpeta temporal)

Claves de API opcionales (no obligatorias)
------------------------------------------
Se leen de variables de entorno:
    FRED_API_KEY, FMP_API_KEY, FINNHUB_API_KEY

Requisitos
----------
macOS 14 (Sonoma) o superior. La version la impone Qt 6.12, no el programa:
para macOS 12 o 13 habria que recompilar con una version anterior de PySide6.
(no lleva la arquitectura x86_64).

Herramienta de analisis: no constituye asesoria financiera.
"""
    try:
        LEEME.write_text(texto, encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo escribir el LEEME ({exc})")


# --------------------------------------------------------------------------
# Instalar / desinstalar
# --------------------------------------------------------------------------

def instalar(app: Path, destino: Path = Path("/Applications")) -> bool:
    """Copia el ``.app`` a ``/Applications`` y lo registra para poder desinstalarlo.

    No usa ``sudo``: si la carpeta no es escribible, avisa de que hay que moverla a
    mano. Solo se registra lo que **este script** ha instalado, para que
    ``--desinstalar`` nunca borre algo que no le corresponde.
    """
    if not app.is_dir():
        print(f"No existe {app}: empaqueta antes de instalar.", file=sys.stderr)
        return False
    objetivo = destino / app.name
    if not os.access(destino, os.W_OK):
        print(f"No se puede escribir en {destino}.\n"
              f"Arrastra {app.name} a Aplicaciones desde el Finder.", file=sys.stderr)
        return False
    try:
        if objetivo.exists():
            shutil.rmtree(objetivo, ignore_errors=True)
        # "ditto" conserva la firma y los enlaces; copytree puede romper la firma.
        if ES_MAC and shutil.which("ditto"):
            subprocess.run(["ditto", str(app), str(objetivo)], check=False)
        else:
            shutil.copytree(app, objetivo, symlinks=True)
    except OSError as exc:  # noqa: BLE001
        print(f"No se pudo instalar en {destino}: {exc}", file=sys.stderr)
        return False

    try:
        registro = ruta_registro()
        registro.parent.mkdir(parents=True, exist_ok=True)
        registro.write_text(json.dumps({
            "app": str(objetivo),
            "identificador": IDENTIFICADOR,
            "version": VERSION,
            "instalado": date.today().isoformat(),
        }, indent=2), encoding="utf-8")
    except OSError:
        pass
    print(f"Instalado en {objetivo}")
    print("Ya aparece en Launchpad y en el Finder.")
    return True


def desinstalar() -> bool:
    """Borra el ``.app`` instalado y, si se confirma, los datos del usuario.

    La cache y las preferencias **no se borran** por defecto: se pregunta. Asi se
    evita destruir datos sin querer.
    """
    registro = ruta_registro()
    if not registro.is_file():
        print("No hay constancia de ninguna instalacion hecha con este script.\n"
              "Si quieres borrarlo a mano, arrastra DML-FINANCE.app a la Papelera.")
        return False
    try:
        datos = json.loads(registro.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo leer {registro}: {exc}", file=sys.stderr)
        return False

    app = Path(datos.get("app", ""))
    if app.is_dir():
        shutil.rmtree(app, ignore_errors=True)
        print(f"Eliminado: {app}")
    else:
        print(f"No estaba instalado (o ya se borro): {app}")

    try:
        registro.unlink(missing_ok=True)
    except OSError:
        pass

    carpeta = Path(carpeta_datos_nombre())
    if carpeta.is_dir():
        respuesta = input(f"¿Borrar tambien tus datos ({carpeta})? [s/N]: ").strip().lower()
        if respuesta in ("s", "si", "sí", "y", "yes"):
            shutil.rmtree(carpeta, ignore_errors=True)
            print(f"Eliminado: {carpeta}")
        else:
            print(f"Se conservan tus datos en {carpeta}")
    return True


# --------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = construir_parser().parse_args(argv)

    # --desinstalar necesita que exista el registro, no macOS en si.
    if args.desinstalar:
        return 0 if desinstalar() else 1

    if not ES_MAC:
        print(
            "Este empaquetador genera un .app de macOS y solo funciona en macOS.\n"
            f"Sistema actual: {platform.system()} ({sys.platform}).\n\n"
            "PyInstaller no puede crear un bundle .app desde Linux o Windows: el\n"
            "formato lo impone macOS. Opciones:\n"
            "  * En Linux (Fedora):  python empaquetar.py --tar\n"
            "  * En Windows:         python empaquetar.py --zip\n"
            "  * En macOS:           python empaquetar_mac.py\n",
            file=sys.stderr,
        )
        return 2

    try:
        import PyInstaller  # noqa: F401
    except Exception:
        print("PyInstaller no esta instalado.\n\nInstalalo con:\n"
              "    pip install pyinstaller\n", file=sys.stderr)
        return 2

    if args.consola:
        print("Aviso: --consola deja una terminal abierta; es solo para depurar.")

    print(f"Sistema: macOS {_version_macos()} · Python {platform.python_version()} "
          f"· {platform.machine()}")
    if platform.machine() == "arm64":
        print("Arquitectura arm64 (Apple Silicon): correcto.")
    elif args.universal:
        print("Se pedira universal2; requiere un Python universal2, no el de Homebrew.")
    else:
        print("Aviso: no es arm64. Si distribuyes a Apple Silicon, conviene compilar en un Mac M-series.")

    if args.limpiar:
        for carpeta in ("build", "dist"):
            ruta = RAIZ / carpeta
            if ruta.is_dir():
                shutil.rmtree(ruta, ignore_errors=True)
                print(f"Eliminado {ruta}")

    icono = asegurar_icns()
    if icono is None:
        print("Aviso: se empaqueta sin icono (falta recursos/icono.icns).")
    receta = escribir_receta(args.consola, icono, args.universal)
    print(f"Receta efectiva: {receta}")

    orden = comando(receta)
    print("Ejecutando:\n  " + " ".join(orden) + "\n")
    resultado = subprocess.call(orden, cwd=str(RAIZ))
    if resultado != 0:
        print("\nEl empaquetado fallo. Revisa la salida de PyInstaller.", file=sys.stderr)
        return resultado

    app = ruta_app()
    if not app.is_dir():
        print(f"\nNo se genero {app}", file=sys.stderr)
        return 1
    print(f"\nAplicacion generada:\n  {app}  ({_tamano(app) / 1024 / 1024:.0f} MB)")

    if not args.sin_poda:
        liberados = podar_app(app)
        if liberados:
            print(f"  Componentes de Qt no usados eliminados: {liberados} MB")

    if not args.sin_firma:
        if args.runtime and args.identidad == "-":
            print("Aviso: --runtime con firma ad-hoc puede impedir el arranque de la app.")
        firmar_app(app, args.identidad, runtime=args.runtime)

    escribir_leeme(app)

    if args.instalar:
        instalar(app)

    if not args.app:
        crear_dmg(app)
        crear_zip(app, args.zip_salida or None)

    informar(app)
    print("\nAntes de distribuirlo, comprueba el .app:")
    print(f"  tests/verificar_mac.sh {app}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
