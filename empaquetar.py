# -*- coding: utf-8 -*-
"""Empaquetado de DML-FINANCE como ejecutable distribuible (Windows y Linux).

Uso
---
::

    python empaquetar.py                    # ejecutable en dist/ + lanzador en el escritorio
    python empaquetar.py --unico            # un solo archivo (arranque lento)
    python empaquetar.py --sin-acceso       # no copia el lanzador al escritorio del usuario
    python empaquetar.py --limpiar          # borra build/ y dist/ antes de empaquetar
    python empaquetar.py --consola          # mantiene una consola (util para depurar)
    python empaquetar.py --tar              # ademas deja el .tar.gz listo para compartir
    python empaquetar.py --zip              # ademas deja el .zip listo para compartir
    python empaquetar.py --rpm              # ademas genera el .rpm (solo Linux)
    python empaquetar.py --instalar         # instala el .desktop en el menu de aplicaciones

Resultado en **Linux** (modo por defecto, ``--onedir``):

* ``dist/DML-FINANCE/DML-FINANCE``          <- el programa (doble clic en el gestor de archivos).
* ``dist/DML-FINANCE/DML-FINANCE.sh``       <- lanzador de respaldo (arranca en su carpeta).
* ``dist/DML-FINANCE/DML-FINANCE.desktop``  <- entrada de escritorio para el menu de aplicaciones.
* ``dist/DML-FINANCE/DML-FINANCE.png``      <- icono de la entrada de escritorio.
* ``dist/DML-FINANCE/config.yaml``          <- umbrales editables por el usuario.
* ``dist/DML-FINANCE/LEEME-EJECUTABLE.txt`` <- instrucciones.

Resultado en **Windows** (modo por defecto, ``--onedir``), como antes:

* ``dist/DML-FINANCE/DML-FINANCE.exe``      <- el programa (doble clic).
* Un acceso directo **DML-FINANCE** en el escritorio, con el icono del programa.

Diferencias de plataforma (por que el .exe no se comporta igual que un ELF)
---------------------------------------------------------------------------
=================  =================================  ===============================
                   Windows                            Linux
=================  =================================  ===============================
Binario            ``DML-FINANCE.exe``                ``DML-FINANCE`` (ELF)
Icono del binario  Embebido en el ``.exe``            No existe: va en ``.desktop`` + PNG
Lanzador           Acceso directo ``.lnk``            Archivo ``.desktop``
Paquete            ``.zip``                           ``.tar.gz`` (conserva permisos/enlaces)
Integracion        (no aplica)                        ``.rpm`` y ``hicolor``
=================  =================================  ===============================

Se usa ``--onedir`` por defecto porque **arranca en 1-3 s**, frente a los ~20-30 s
que tarda un ``--onefile`` al descomprimirse en cada ejecucion.

Requisito de distribucion (Linux)
---------------------------------
El paquete es **portatil en Fedora 44 o superior**. PyInstaller enlaza el binario
contra la glibc del sistema donde se compila y Fedora no mantiene compatibilidad
hacia atras, asi que un paquete construido en Fedora 44 **no arranca** en Fedora
43 o anteriores. La funcion :func:`verificar_glibc` mide el requisito real del
paquete ya construido y lo informa al terminar.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

RAIZ = Path(__file__).resolve().parent
NOMBRE = "DML-FINANCE"
RECURSOS = RAIZ / "recursos"
ICONO = RECURSOS / "icono.ico"
LOGO = RECURSOS / "DML-Icon.png"
PNG = RECURSOS / "icono.png"
CONFIG = RAIZ / "config.yaml"
LEEME = RAIZ / "LEEME-EJECUTABLE.txt"

ES_WINDOWS = sys.platform.startswith("win")
ES_LINUX = sys.platform.startswith("linux")
SUFIJO = ".exe" if ES_WINDOWS else ""


# --------------------------------------------------------------------------
# Argumentos
# --------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    """Argumentos del empaquetador."""
    parser = argparse.ArgumentParser(
        prog="empaquetar.py", description="Genera el ejecutable de DML-FINANCE y su lanzador."
    )
    parser.add_argument("--unico", action="store_true",
                        help="genera un unico archivo (--onefile, arranque lento)")
    parser.add_argument("--limpiar", action="store_true", help="borra build/ y dist/ antes de empaquetar")
    parser.add_argument("--consola", action="store_true", help="mantiene la consola visible (util para depurar)")
    parser.add_argument("--sin-icono", action="store_true", help="no usa recursos/icono.ico (Windows)")
    parser.add_argument("--sin-acceso", action="store_true",
                        help="no copia el lanzador al escritorio del usuario (el .desktop del paquete si se genera)")
    parser.add_argument("--escritorio", default=None, help="carpeta alternativa para el lanzador")
    parser.add_argument("--sin-poda", action="store_true",
                        help="no borra los componentes de Qt que la aplicacion no usa")
    parser.add_argument("--completo", action="store_true",
                        help="no aligera el paquete (conserva todo lo que deja PyInstaller)")
    parser.add_argument("--tar", dest="tar_salida", nargs="?", const="", default=None, metavar="ARCHIVO",
                        help="crea ademas un .tar.gz listo para compartir (solo Linux)")
    parser.add_argument("--zip", dest="zip_salida", nargs="?", const="", default=None, metavar="ARCHIVO",
                        help="crea ademas un ZIP listo para compartir")
    parser.add_argument("--rpm", dest="rpm", action="store_true",
                        help="crea ademas un .rpm instalable (solo Linux; requiere rpm-build)")
    parser.add_argument("--instalar", action="store_true",
                        help="instala el .desktop y el icono en el menu de aplicaciones (solo Linux)")
    return parser


def limpiar() -> None:
    """Borra los directorios generados por PyInstaller."""
    for carpeta in ("build", "dist"):
        ruta = RAIZ / carpeta
        if ruta.is_dir():
            shutil.rmtree(ruta, ignore_errors=True)
            print(f"Eliminado {ruta}")


# --------------------------------------------------------------------------
# Iconos
# --------------------------------------------------------------------------

def asegurar_icono() -> Optional[Path]:
    """Genera los iconos a partir del logo si no existen y devuelve el del binario.

    En Windows hace falta ``icono.ico``; en Linux el binario no lleva icono, pero
    se necesitan los PNG para el ``.desktop`` y el ``hicolor``. En ambos casos el
    icono se regenera si el logo es mas reciente.
    """
    necesario = ICONO if ES_WINDOWS else PNG
    if necesario.is_file() and LOGO.is_file() and necesario.stat().st_mtime >= LOGO.stat().st_mtime:
        return necesario if ES_WINDOWS else None
    _regenerar_icono()
    if not necesario.is_file():
        return None
    return necesario if ES_WINDOWS else None


def _regenerar_icono() -> None:
    """Regenera ``recursos/icono.ico`` y ``recursos/icono.png`` desde el logo."""
    try:
        import generar_icono

        generar_icono.main([])
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo generar el icono desde {LOGO.name} ({exc})")


# --------------------------------------------------------------------------
# Receta de PyInstaller
# --------------------------------------------------------------------------

def construir_receta(unico: bool, consola: bool, icono: Optional[Path]) -> str:
    """Devuelve el texto de la receta de PyInstaller para estas opciones.

    Se parte de ``DML-FINANCE.spec`` (que es la receta versionada y legible) y se
    sustituyen las tres unicas opciones que dependen de la linea de comandos:

    * ``COLLECT`` (``--onedir``) pasa a un unico ``EXE`` con ``a.binaries`` y
      ``a.datas`` embebidos (``--onefile``);
    * ``console=False`` pasa a ``True`` (``--consola``);
    * el icono del ``EXE`` (``--sin-icono``).

    Se hace asi, y no con opciones de la linea de comandos, porque PyInstaller
    **ignora** ``--onefile``, ``--console`` y ``--name`` cuando recibe una receta:
    generar la receta es la forma fiable de que la opcion se aplique.

    La receta es multiplataforma: detecta el sistema por ``sys.platform`` para
    embeber el icono solo en Windows y para activar ``upx`` solo si esta instalado.
    """
    receta = (RAIZ / "DML-FINANCE.spec").read_text(encoding="utf-8")
    if consola:
        receta = receta.replace("console=False", "console=True", 1)
    if icono is None:
        receta = receta.replace("    icon=_ICONO_RUTA,\n", "")
    if unico:
        # En un fichero unico no hay COLLECT: los binarios y los datos van dentro
        # del propio ejecutable.
        receta = receta.replace(
            "exe = EXE(\n    pyz,\n    a.scripts,\n    [],\n",
            "exe = EXE(\n    pyz,\n    a.scripts,\n    a.binaries,\n    a.datas,\n",
            1,
        )
        receta = "\n".join(
            linea for linea in receta.splitlines() if "exclude_binaries" not in linea
        ) + "\n"
        receta = receta.split("coll = COLLECT(")[0].rstrip() + "\n"
    return receta


def escribir_receta(unico: bool, consola: bool, icono: Optional[Path]) -> Path:
    """Escribe la receta efectiva en ``build/`` y devuelve su ruta.

    Se escribe aparte para no ensuciar ``DML-FINANCE.spec`` (que sigue siendo la
    receta versionada, legible y portable) y para que quede constancia exacta de
    con que opciones se construyo el ejecutable.
    """
    destino = RAIZ / "build" / "receta-efectiva.spec"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(construir_receta(unico, consola, icono), encoding="utf-8")
    return destino


def comando(receta: Path) -> List[str]:
    """Comando de PyInstaller que ejecuta una receta concreta."""
    return [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(receta)]


def ejecutable_resultante(unico: bool) -> Path:
    """Ruta del ejecutable generado."""
    if unico:
        return RAIZ / "dist" / f"{NOMBRE}{SUFIJO}"
    return RAIZ / "dist" / NOMBRE / f"{NOMBRE}{SUFIJO}"


# --------------------------------------------------------------------------
# Aligerado del paquete
# --------------------------------------------------------------------------

#: Nombres que **nunca** deben viajar en el paquete: son datos de quien lo genero
#: (cache de datos, logs, preferencias) o restos de una ejecucion. Si el receptor
#: recibe la cache del autor, el programa arrancaria con datos de otro equipo.
NO_COMPARTIR = {".dml_cache", ".dml_finance", ".dml_datos", "autotest.txt"}

#: Componentes de Qt que la aplicacion no usa, con su tamano aproximado. La
#: aplicacion es de *widgets* clasicos: no hay QML, ni Quick, ni PDF, ni teclado
#: virtual. Cada entrada se comprueba contra el resultado del autotest antes de
#: borrarla (ver el README): si algo se necesitara, el autotest fallaria.
PODA_QT_LIB = (
    "libQt6Quick",              # ~9 MB
    "libQt6Qml",                # ~9 MB
    "libQt6Pdf",                # ~4 MB
    "libQt6VirtualKeyboard",    # ~0.7 MB
)

#: Traducciones de Qt: se conservan las de espanol (0.2 MB) y se borran las otras
#: 97 (~6.8 MB). Sin las de espanol, los dialogos nativos de Qt ("Abrir",
#: "Guardar", "Cancelar") apareceran en ingles.
IDIOMAS_QT = ("es",)


def podar_paquete(carpeta: Path, idiomas: Iterable[str] = IDIOMAS_QT) -> int:
    """Borra del paquete los componentes de Qt que la aplicacion no usa.

    Args:
        carpeta: carpeta del paquete (``dist/DML-FINANCE``).
        idiomas: codigos de idioma cuyas traducciones de Qt se conservan.

    Returns:
        Los MB liberados (aproximados).
    """
    interno = carpeta / "_internal"
    if not interno.is_dir():
        return 0
    qt = interno / "PySide6" / "Qt"
    if not qt.is_dir():
        return 0

    antes = _tamano(interno)

    # 1) Librerias de Qt no usadas.
    for prefijo in PODA_QT_LIB:
        for so in (qt / "lib").glob(f"{prefijo}*.so*"):
            try:
                so.unlink()
            except OSError as exc:  # noqa: BLE001
                print(f"  Aviso: no se pudo borrar {so.name}: {exc}")

    # 1b) PyInstaller deja en la raiz de ``_internal/`` enlaces simbolicos a los
    #     .so de Qt (``libQt6Qml.so.6 -> PySide6/Qt/lib/libQt6Qml.so.6``). Al
    #     borrar el destino quedan enlaces rotos: no rompen nada (el autotest
    #     pasa), pero son basura que confunde y que hace fallar a herramientas que
    #     siguen enlaces al copiar (por ejemplo ``shutil.copytree`` sin symlinks).
    for enlace in interno.iterdir():
        try:
            if enlace.is_symlink() and not enlace.exists():
                enlace.unlink()
        except OSError:  # noqa: BLE001
            pass

    # 2) Traducciones: solo las de los idiomas pedidos (mas el catalogo generico).
    traducciones = qt / "translations"
    if traducciones.is_dir():
        patron = re.compile(r"^[a-z0-9_]+_([a-z]{2,3}(?:_[A-Z]{2})?)\.qm$")
        conservar = {f"qt_{i}.qm" for i in idiomas} | {f"qtbase_{i}.qm" for i in idiomas}
        for qm in traducciones.glob("*.qm"):
            if qm.name in conservar:
                continue
            coincidencia = patron.match(qm.name)
            if coincidencia and coincidencia.group(1).split("_")[0] in idiomas:
                continue
            try:
                qm.unlink()
            except OSError:  # noqa: BLE001
                pass
        if not any(traducciones.iterdir()):
            shutil.rmtree(traducciones, ignore_errors=True)

    return int((antes - _tamano(interno)) / 1024 / 1024)


def _tamano(carpeta: Path) -> int:
    """Tamano en bytes de todos los archivos de una carpeta (nunca lanza)."""
    try:
        return sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    except OSError:  # pragma: no cover
        return 0


def _copia_limpia(origen: Path, destino: Path) -> List[str]:
    """Copia el paquete a ``destino`` saltandose los datos de ejecucion.

    Se copia en lugar de borrar sobre el original: ``dist/`` se puede seguir
    usando para probar sin dejar de tener un paquete limpio garantizado.

    Returns:
        La lista de nombres omitidos (para informar al usuario).
    """
    omitidos: List[str] = []
    destino.mkdir(parents=True, exist_ok=True)
    for elemento in origen.iterdir():
        if elemento.name in NO_COMPARTIR:
            omitidos.append(elemento.name)
            continue
        if elemento.is_dir():
            shutil.copytree(elemento, destino / elemento.name, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(elemento, destino / elemento.name)
    return omitidos


# --------------------------------------------------------------------------
# Entrada de escritorio y lanzador (Linux)
# --------------------------------------------------------------------------

def _carpeta_escritorio(preferido: Optional[str] = None) -> Path:
    """Localiza el escritorio del usuario en Windows o Linux."""
    if preferido:
        return Path(preferido)
    if ES_WINDOWS:
        candidatos = []
        perfil = os.environ.get("USERPROFILE")
        if perfil:
            candidatos.append(Path(perfil) / "Desktop")
            candidatos.append(Path(perfil) / "Escritorio")
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if onedrive:
            candidatos.insert(0, Path(onedrive) / "Desktop")
            candidatos.insert(1, Path(onedrive) / "Escritorio")
        for candidato in candidatos:
            if candidato.is_dir():
                return candidato
        return candidatos[0] if candidatos else RAIZ

    # Linux: XDG_*_DIR, con ~/Escritorio y ~/Desktop como respaldo.
    config = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    try:
        escritorios = (Path(config) / "user-dirs.dirs").read_text(encoding="utf-8")
        coincidencia = re.search(r'XDG_DESKTOP_DIR="([^"]+)"', escritorios)
        if coincidencia:
            ruta = Path(os.path.expandvars(coincidencia.group(1)))
            if ruta.is_dir():
                return ruta
    except Exception:  # noqa: BLE001 - el archivo es opcional
        pass
    for candidato in (Path.home() / "Escritorio", Path.home() / "Desktop"):
        if candidato.is_dir():
            return candidato
    return Path.home()


def texto_desktop(destino_exe: Path, icono: Optional[Path] = None) -> str:
    """Devuelve el contenido de la entrada de escritorio (``.desktop``).

    ``%U`` permite abrir la aplicacion desde el gestor de archivos; el
    ``Path=`` fija el directorio de trabajo para que encuentre ``config.yaml``.
    """
    linea_icono = str(icono) if icono is not None else str(destino_exe.parent / f"{NOMBRE}.png")
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={NOMBRE}\n"
        "GenericName=Analizador financiero\n"
        "Comment=Analizador cuantitativo de acciones con parrilla de decision de 12 criterios\n"
        f"Exec=\"{destino_exe}\" %U\n"
        f"Path={destino_exe.parent}\n"
        f"Icon={linea_icono}\n"
        "Terminal=false\n"
        "Categories=Office;Finance;Qt;\n"
        "Keywords=finanzas;acciones;bolsa;analisis;trading;\n"
        "StartupNotify=true\n"
        "StartupWMClass=DML-FINANCE\n"
    )


def escribir_lanzador(destino_exe: Path) -> Optional[Path]:
    """Escribe ``DML-FINANCE.sh`` junto al ejecutable (Linux).

    Es el equivalente practico de un ``.exe``: se puede ejecutar con doble clic
    desde el gestor de archivos, y garantiza el directorio de trabajo correcto
    (para que se lea ``config.yaml``) aunque se invoque desde otro sitio.
    """
    if not ES_LINUX:
        return None
    lanzador = destino_exe.parent / f"{NOMBRE}.sh"
    contenido = (
        "#!/bin/sh\n"
        "# Lanzador de DML-FINANCE. Ejecutalo con doble clic o desde una terminal.\n"
        'AQUI=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'cd "$AQUI" || exit 1\n'
        f'exec "$AQUI/{destino_exe.name}" "$@"\n'
    )
    try:
        lanzador.write_text(contenido, encoding="utf-8")
        lanzador.chmod(0o755)
        return lanzador
    except OSError as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo escribir el lanzador ({exc})")
        return None


def escribir_desktop_en_paquete(destino_exe: Path) -> Optional[Path]:
    """Escribe ``DML-FINANCE.desktop`` y su icono **dentro** del paquete (Linux).

    Esto no tiene nada que ver con ``--sin-acceso``: la entrada debe viajar
    siempre con el paquete, porque es parte de lo que se distribuye y sin ella el
    receptor no puede integrarlo en su menu. ``--sin-acceso`` solo controla si
    ademas se copia al escritorio del usuario.
    """
    if not ES_LINUX:
        return None
    icono: Optional[Path] = None
    if PNG.is_file():
        icono = destino_exe.parent / f"{NOMBRE}.png"
        try:
            shutil.copy2(PNG, icono)
        except OSError:  # noqa: BLE001
            icono = None
    entrada = destino_exe.parent / f"{NOMBRE}.desktop"
    try:
        entrada.write_text(texto_desktop(destino_exe, icono), encoding="utf-8")
        return entrada
    except OSError as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo escribir el .desktop del paquete ({exc})")
        return None


def escribir_desktop(destino_exe: Path, escritorio: Optional[str] = None) -> Optional[Path]:
    """Copia la entrada de escritorio al escritorio del usuario (Linux).

    Devuelve la ruta del ``.desktop`` o ``None``. Se marca como ejecutable, que es
    lo que algunos entornos (KDE, XFCE) necesitan para ofrecer "Abrir" directamente.
    """
    if not ES_LINUX:
        return None
    icono = destino_exe.parent / f"{NOMBRE}.png"
    try:
        carpeta = _carpeta_escritorio(escritorio)
        entrada = carpeta / f"{NOMBRE}.desktop"
        entrada.write_text(texto_desktop(destino_exe, icono if icono.is_file() else None),
                           encoding="utf-8")
        entrada.chmod(0o755)
        return entrada
    except OSError as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo crear la entrada de escritorio ({exc})")
        return None


def instalar_en_menu() -> Optional[Path]:
    """Instala el ``.desktop`` y el icono en el menu de aplicaciones del usuario.

    Escribe en ``~/.local/share/applications`` y ``~/.local/share/icons/hicolor``,
    que son rutas de usuario: **no necesita sudo** y la aplicacion aparece en el
    menu sin instalarla en el sistema. Es la alternativa ligera al ``.rpm``.
    """
    if not ES_LINUX:
        print("--instalar solo tiene sentido en Linux.")
        return None
    exe = ejecutable_resultante(False)
    if not exe.is_file():
        print(f"No existe {exe}: empaqueta antes de instalar.", file=sys.stderr)
        return None
    datos = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    aplicaciones = datos / "applications"
    aplicaciones.mkdir(parents=True, exist_ok=True)
    entrada = aplicaciones / f"{NOMBRE}.desktop"
    entrada.write_text(texto_desktop(exe, _instalar_iconos(datos)), encoding="utf-8")

    # Refresca la base de datos de aplicaciones si la herramienta existe.
    for orden in (["update-desktop-database", str(aplicaciones)],
                  ["gtk-update-icon-cache", "-f", "-t", str(datos / "icons" / "hicolor")]):
        if shutil.which(orden[0]):
            subprocess.run(orden, capture_output=True, check=False)
    return entrada


def _instalar_iconos(datos: Path) -> Optional[Path]:
    """Copia el icono a ``hicolor`` en los tamanos habituales y devuelve su ruta.

    Instalar el PNG suelto (sin ``hicolor``) tambien funciona, pero la barra de
    tareas y el conmutador de ventanas eligen mejor el tamano si existe el arbol
    de temas de iconos.
    """
    if not PNG.is_file():
        return None
    hicolor = datos / "icons" / "hicolor"
    try:
        from PIL import Image

        with Image.open(PNG) as imagen:
            for tamano in (16, 24, 32, 48, 64, 128, 256):
                carpeta = hicolor / f"{tamano}x{tamano}" / "apps"
                carpeta.mkdir(parents=True, exist_ok=True)
                imagen.resize((tamano, tamano), Image.LANCZOS).save(carpeta / f"{NOMBRE}.png")
        # Con el arbol hicolor instalado, el .desktop referencia el icono por su
        # nombre de tema (lo resuelve el escritorio), no por una ruta absoluta.
        return Path(NOMBRE)
    except Exception:  # noqa: BLE001 - sin Pillow se usa la ruta directa
        carpeta = hicolor / "256x256" / "apps"
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"{NOMBRE}.png"
        try:
            shutil.copy2(PNG, destino)
            return destino
        except OSError:
            return None


# --------------------------------------------------------------------------
# Verificacion de glibc (portabilidad)
# --------------------------------------------------------------------------

def glibc_sistema() -> Optional[str]:
    """Version de glibc del sistema que compila, o ``None`` si no se puede saber."""
    if not ES_LINUX:
        return None
    try:
        salida = subprocess.run(["ldd", "--version"], capture_output=True, text=True, check=False)
        coincidencia = re.search(r"(\d+\.\d+)$", salida.stdout.strip().splitlines()[0])
        return coincidencia.group(1) if coincidencia else None
    except Exception:  # noqa: BLE001
        return None


def glibc_requerida(carpeta: Path) -> Optional[str]:
    """Mayor version de ``GLIBC_x.y`` que exige el paquete ya construido.

    Es el dato que decide en que Fedora arranca el paquete: PyInstaller enlaza
    contra la glibc de la maquina de compilacion, y Fedora no garantiza
    compatibilidad hacia atras entre versiones. Se inspeccionan los simbolos de
    los binarios y de todas las bibliotecas empaquetadas.
    """
    if not ES_LINUX or not shutil.which("objdump"):
        return None
    patron = re.compile(r"GLIBC_(\d+\.\d+)")
    mayor: Optional[tuple] = None
    archivos = [f for f in carpeta.rglob("*") if f.is_file() and (f.suffix == ".so" or ".so." in f.name)]
    exe = carpeta / f"{NOMBRE}{SUFIJO}"
    if exe.is_file():
        archivos.append(exe)
    for archivo in archivos[:4000]:
        try:
            salida = subprocess.run(["objdump", "-T", str(archivo)],
                                    capture_output=True, text=True, check=False)
        except Exception:  # noqa: BLE001
            continue
        for encontrado in patron.findall(salida.stdout):
            partes = tuple(int(p) for p in encontrado.split("."))
            if mayor is None or partes > mayor:
                mayor = partes
    return ".".join(str(p) for p in mayor) if mayor else None


def _fedora_minima(glibc: Optional[str]) -> str:
    """Primera version de Fedora que incluye esa glibc (tabla aproximada)."""
    tabla = {
        "2.43": "Fedora 44",
        "2.42": "Fedora 44",
        "2.41": "Fedora 43",
        "2.40": "Fedora 42",
        "2.39": "Fedora 40",
        "2.38": "Fedora 39",
        "2.37": "Fedora 37",
        "2.36": "Fedora 36",
        "2.35": "Fedora 35",
        "2.34": "Fedora 34",
    }
    if not glibc:
        return "desconocida"
    if glibc in tabla:
        return tabla[glibc]
    partes = tuple(int(p) for p in glibc.split("."))
    candidatas = [(tuple(int(p) for p in k.split(".")), v) for k, v in tabla.items() if tuple(int(p) for p in k.split(".")) <= partes]
    return max(candidatas)[1] if candidatas else "desconocida"


def informar_portabilidad(carpeta: Path) -> None:
    """Imprime el requisito real de glibc del paquete construido."""
    sistema = glibc_sistema()
    necesaria = glibc_requerida(carpeta)
    print("\nPortabilidad (Linux)")
    print("-" * 60)
    if sistema:
        print(f"  glibc de compilacion : {sistema}")
    if necesaria:
        print(f"  glibc requerida      : {necesaria}  ->  {_fedora_minima(necesaria)} o superior")
        if sistema and tuple(int(p) for p in necesaria.split(".")) >= tuple(int(p) for p in sistema.split(".")):
            print("  Aviso: el paquete pide la glibc del sistema de compilacion;")
            print("         no arrancara en versiones anteriores de Fedora.")
    else:
        print("  glibc requerida      : no se pudo determinar (falta objdump)")


# --------------------------------------------------------------------------
# Paquetes para compartir (.tar.gz / .zip / .rpm)
# --------------------------------------------------------------------------

def _preparar_paquete_limpio() -> Optional[Path]:
    """Copia ``dist/<NOMBRE>`` a ``build/paquete-limpio`` y la devuelve.

    La copia existe para no tocar el paquete que el usuario esta probando: se
    omite lo que no debe viajar (cache, logs, preferencias del autor) y la poda
    de Qt ya se aplico durante el build, asi que aqui no hay nada mas que quitar.
    """
    carpeta = RAIZ / "dist" / NOMBRE
    if not carpeta.is_dir():
        print(f"No existe {carpeta}: empaqueta antes de generar el paquete.", file=sys.stderr)
        return None
    trabajo = RAIZ / "build" / "paquete-limpio"
    shutil.rmtree(trabajo, ignore_errors=True)
    omitidos = _copia_limpia(carpeta, trabajo / NOMBRE)
    if omitidos:
        print("Datos de ejecucion excluidos del paquete: " + ", ".join(sorted(omitidos)))
    return trabajo / NOMBRE


def crear_tar(destino_tar: Optional[str] = None, aligerar: bool = True) -> Optional[Path]:
    """Empaqueta ``dist/<NOMBRE>`` en un ``.tar.gz`` listo para compartir (Linux).

    Se usa ``tar.gz`` y **no** ZIP porque es el unico que conserva los permisos de
    ejecucion y los enlaces simbolicos que PyInstaller deja en ``_internal/``: el
    receptor descomprime y el binario ya es ejecutable, sin ``chmod`` manual.
    """
    limpio = _preparar_paquete_limpio()
    if limpio is None:
        return None
    salida = Path(destino_tar) if destino_tar else (RAIZ / "dist" / f"{NOMBRE}-{platform.machine()}.tar.gz")
    if not salida.name.endswith((".tar.gz", ".tgz")):
        salida = salida.with_suffix(".tar.gz")
    salida.parent.mkdir(parents=True, exist_ok=True)
    if salida.is_file():
        salida.unlink()

    with tarfile.open(salida, "w:gz", compresslevel=6) as tf:
        tf.add(limpio, arcname=NOMBRE, recursive=True)

    shutil.rmtree(RAIZ / "build" / "paquete-limpio", ignore_errors=True)
    print(f"\ntar.gz listo para compartir:\n  {salida}  ({salida.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"  (la carpeta dist/{NOMBRE} ocupa {_tamano(RAIZ / 'dist' / NOMBRE) / 1024 / 1024:.0f} MB sin comprimir)")
    print("\nEn el equipo de destino:")
    print(f"  tar -xzf {salida.name}")
    print(f"  cd {NOMBRE} && ./{NOMBRE}")
    return salida


def crear_zip(destino_zip: Optional[str] = None, aligerar: bool = True) -> Optional[Path]:
    """Empaqueta ``dist/<NOMBRE>`` en un ZIP listo para compartir.

    El ZIP contiene una unica carpeta ``DML-FINANCE/`` con el ejecutable, su
    ``_internal/``, ``config.yaml`` y el LEEME.

    Aviso (Linux): el ZIP **si** guarda el permiso 0755, porque ``zipfile`` lo
    escribe en ``external_attr``. El problema es que no todas las herramientas lo
    restauran al descomprimir (``unzip`` si, el modulo ``zipfile`` de Python no).
    Por eso se recomienda :func:`crear_tar`, que no depende de eso.
    """
    limpio = _preparar_paquete_limpio()
    if limpio is None:
        return None
    salida = Path(destino_zip) if destino_zip else (RAIZ / "dist" / f"{NOMBRE}.zip")
    if salida.suffix.lower() != ".zip":
        salida = salida.with_suffix(".zip")
    salida.parent.mkdir(parents=True, exist_ok=True)

    ejecutable = limpio / f"{NOMBRE}{SUFIJO}"
    if not ejecutable.is_file():
        print(f"El paquete no contiene {ejecutable.name}: se aborta.", file=sys.stderr)
        shutil.rmtree(RAIZ / "build" / "paquete-limpio", ignore_errors=True)
        return None

    if salida.is_file():
        salida.unlink()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for archivo in sorted(limpio.rglob("*")):
            if archivo.is_file():
                zf.write(archivo, archivo.relative_to(limpio.parent))
    shutil.rmtree(RAIZ / "build" / "paquete-limpio", ignore_errors=True)

    print(f"\nZIP listo para compartir:\n  {salida}  ({salida.stat().st_size / 1024 / 1024:.0f} MB)")
    if ES_LINUX:
        # El ZIP si guarda el permiso 0755 (Python lo escribe en external_attr),
        # pero no todas las herramientas lo restauran al descomprimir: `unzip`
        # si, y el modulo zipfile de Python no. Por eso se prefiere el .tar.gz.
        print("\nAviso: en Linux usa preferiblemente --tar (conserva permisos y enlaces")
        print("       en cualquier herramienta). Si repartes el ZIP y el binario no")
        print(f"       queda ejecutable: chmod +x {NOMBRE}/{NOMBRE}")
    return salida


#: Plantilla del ``.spec`` de RPM. Se genera desde aqui para que las rutas, la
#: version y el requisito de glibc salgan del propio entorno de compilacion.
PLANTILLA_RPM = """\
# Generado por empaquetar.py el {fecha}. No editar a mano: vuelve a generarlo.
%global _build_id_links none
Name:           {nombre_min}
Version:        {version}
Release:        1%{{?dist}}
Summary:        Analizador cuantitativo de acciones con parrilla de decision
License:        Propietario
URL:            https://localhost/{nombre}
BuildArch:      {arch}
Requires:       glibc >= {glibc}
# Bibliotecas que Qt6 exige y que PyInstaller NO puede empaquetar (son del
# sistema). Estan comprobadas una a una en un Fedora 44 limpio con
# tests/verificar_contenedor.sh: sin ellas el programa no arranca.
Requires:       fontconfig
Requires:       freetype
Requires:       libxkbcommon
Requires:       libxkbcommon-x11
Requires:       libxcb
Requires:       dbus-libs
Requires:       mesa-libGL
Requires:       mesa-libEGL
# Plugins de la plataforma xcb (X11). Fedora ya los instala en cualquier
# escritorio, pero se declaran para que el paquete funcione en instalaciones
# minimas.
Requires:       xcb-util
Requires:       xcb-util-wm
Requires:       xcb-util-image
Requires:       xcb-util-keysyms
Requires:       xcb-util-renderutil
Requires:       xcb-util-cursor
Requires:       libwayland-cursor
AutoReqProv:    no

%description
DML-FINANCE analiza acciones (precios, fundamentales, riesgo, valoracion) y
resume el resultado en una parrilla de decision de 12 criterios, con exportacion
a Excel. Incluye su propio interprete de Python y las bibliotecas que necesita.

Herramienta de analisis: no constituye asesoria financiera.

%install
rm -rf %{{buildroot}}
mkdir -p %{{buildroot}}%{{_libdir}}/{nombre}
cp -a %{{_sourcedir}}/{nombre}/. %{{buildroot}}%{{_libdir}}/{nombre}/
# El enlace apunta al mismo %{{_libdir}} con el que se creo la carpeta: en algunos
# sistemas _libdir es /usr/lib64, y un enlace a /usr/lib no resolveria.
mkdir -p %{{buildroot}}%{{_bindir}}
ln -s %{{_libdir}}/{nombre}/{nombre} %{{buildroot}}%{{_bindir}}/{nombre}
mkdir -p %{{buildroot}}%{{_datadir}}/applications
mkdir -p %{{buildroot}}%{{_datadir}}/icons/hicolor/256x256/apps
mkdir -p %{{buildroot}}%{{_datadir}}/icons/hicolor/128x128/apps
mkdir -p %{{buildroot}}%{{_datadir}}/icons/hicolor/64x64/apps
mkdir -p %{{buildroot}}%{{_datadir}}/icons/hicolor/48x48/apps
install -m 0644 %{{_sourcedir}}/{nombre}.desktop %{{buildroot}}%{{_datadir}}/applications/
for t in 256 128 64 48; do
  install -m 0644 %{{_sourcedir}}/icons/${{t}}.png \\
    %{{buildroot}}%{{_datadir}}/icons/hicolor/${{t}}x${{t}}/apps/{nombre}.png
done

%files
%{{_libdir}}/{nombre}
%{{_bindir}}/{nombre}
%{{_datadir}}/applications/{nombre}.desktop
%{{_datadir}}/icons/hicolor/*/apps/{nombre}.png

%changelog
* {fecha_larga} DML-FINANCE <noreply@localhost> - {version}-1
- Paquete generado automaticamente por empaquetar.py
"""


def crear_rpm(version: str = "1.0.0", aligerar: bool = True) -> Optional[Path]:
    """Genera un ``.rpm`` instalable con el paquete (solo Linux).

    Se construye con ``rpmbuild`` en ``~/rpmbuild`` (no necesita root; solo
    instalar el resultado usa ``sudo``). El ``.rpm`` se marca ``AutoReqProv: no``
    porque PyInstaller ya incluye sus propias bibliotecas y el generador
    automatico de dependencias de RPM pediria paquetes que no hacen falta.

    Returns:
        La ruta del ``.rpm`` creado, o ``None`` si no se pudo.
    """
    if not ES_LINUX:
        print("--rpm solo esta disponible en Linux.", file=sys.stderr)
        return None
    if not shutil.which("rpmbuild"):
        print("Falta rpmbuild. Instalalo con:\n    sudo dnf install rpm-build", file=sys.stderr)
        return None
    limpio = _preparar_paquete_limpio()
    if limpio is None:
        return None

    # 1) Arbol de trabajo de rpmbuild.
    rpmbuild = Path(os.environ.get("RPMBUILD_DIR") or (Path.home() / "rpmbuild"))
    for sub in ("BUILD", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (rpmbuild / sub).mkdir(parents=True, exist_ok=True)
    origen = rpmbuild / "SOURCES" / NOMBRE
    shutil.rmtree(origen, ignore_errors=True)
    shutil.copytree(limpio, origen, symlinks=True)

    # 2) Iconos y .desktop que viajan fuera del arbol de la aplicacion.
    iconos = rpmbuild / "SOURCES" / "icons"
    iconos.mkdir(parents=True, exist_ok=True)
    for tamano in (48, 64, 128, 256):
        destino = iconos / f"{tamano}.png"
        try:
            from PIL import Image

            with Image.open(PNG) as imagen:
                imagen.resize((tamano, tamano), Image.LANCZOS).save(destino)
        except Exception:  # noqa: BLE001 - sin Pillow se usa el PNG original
            shutil.copy2(PNG, destino)
    (rpmbuild / "SOURCES" / f"{NOMBRE}.desktop").write_text(
        texto_desktop(Path("/usr/bin") / NOMBRE, Path(f"/usr/share/icons/hicolor/256x256/apps/{NOMBRE}.png")),
        encoding="utf-8",
    )

    # 3) .spec del RPM.
    glibc = glibc_requerida(limpio) or glibc_sistema() or "2.34"
    hoy = date.today()
    spec = PLANTILLA_RPM.format(
        nombre=NOMBRE,
        nombre_min=NOMBRE.lower(),
        version=version,
        arch=platform.machine(),
        glibc=glibc,
        fecha=hoy.isoformat(),
        fecha_larga=hoy.strftime("%a %b %d %Y"),
    )
    ruta_spec = rpmbuild / "SPECS" / f"{NOMBRE.lower()}.spec"
    ruta_spec.write_text(spec, encoding="utf-8")

    # 4) Construccion.
    resultado = subprocess.run(
        ["rpmbuild", "-bb", "--define", f"_topdir {rpmbuild}", str(ruta_spec)],
        capture_output=True, text=True, check=False,
    )
    shutil.rmtree(RAIZ / "build" / "paquete-limpio", ignore_errors=True)
    if resultado.returncode != 0:
        print("rpmbuild fallo. Ultimas lineas:", file=sys.stderr)
        print("\n".join(resultado.stdout.splitlines()[-15:]), file=sys.stderr)
        print("\n".join(resultado.stderr.splitlines()[-15:]), file=sys.stderr)
        return None

    construidos = sorted((rpmbuild / "RPMS").rglob("*.rpm"))
    if not construidos:
        return None
    destino = RAIZ / "dist" / construidos[-1].name
    shutil.copy2(construidos[-1], destino)
    print(f"\nRPM listo:\n  {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"\nInstalar (necesita root):\n    sudo dnf install {destino}")
    return destino


# --------------------------------------------------------------------------
# Acceso directo (Windows)
# --------------------------------------------------------------------------

def crear_acceso_directo(destino_exe: Path, escritorio: Optional[str] = None,
                         icono: Optional[Path] = None) -> Optional[Path]:
    """Crea (o reemplaza) un acceso directo ``.lnk`` en el escritorio (Windows).

    Usa ``pywin32`` si esta disponible y, si no, un script de PowerShell. En
    ambos casos el acceso directo apunta al ``.exe``, arranca en su carpeta (para
    que encuentre ``config.yaml``) y lleva el icono del programa.

    Returns:
        La ruta del ``.lnk`` creado, o ``None`` si no se pudo.
    """
    if not ES_WINDOWS:
        return None
    carpeta = _carpeta_escritorio(escritorio)
    enlace = carpeta / f"{NOMBRE}.lnk"
    icono_txt = str(icono if icono is not None and icono.is_file() else destino_exe)

    # 1) pywin32 (mas fiable si esta instalado)
    try:
        import pythoncom  # type: ignore
        from win32com.client import Dispatch  # type: ignore

        pythoncom.CoInitialize()
        shell = Dispatch("WScript.Shell")
        acceso = shell.CreateShortCut(str(enlace))
        acceso.TargetPath = str(destino_exe)
        acceso.WorkingDirectory = str(destino_exe.parent)
        acceso.IconLocation = icono_txt
        acceso.Description = "DML-FINANCE - analizador cuantitativo y parrilla de decision"
        acceso.save()
        return enlace if enlace.is_file() else None
    except Exception:
        pass

    # 2) PowerShell con WScript.Shell
    guion = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{enlace}');"
        f"$s.TargetPath = '{destino_exe}';"
        f"$s.WorkingDirectory = '{destino_exe.parent}';"
        f"$s.IconLocation = '{icono_txt}';"
        "$s.Description = 'DML-FINANCE - analizador cuantitativo y parrilla de decision';"
        "$s.Save()"
    )
    try:
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", guion],
            capture_output=True, text=True, timeout=60,
        )
        if resultado.returncode == 0 and enlace.is_file():
            return enlace
        print(f"Aviso: PowerShell devolvio {resultado.returncode}: {resultado.stderr.strip()[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo crear el acceso directo con PowerShell ({exc})")

    # 3) Alternativa sin COM: un .cmd en el escritorio
    try:
        alterno = carpeta / f"{NOMBRE}.cmd"
        alterno.write_text(
            f'@echo off\r\ncd /d "{destino_exe.parent}"\r\nstart "" "{destino_exe}"\r\n',
            encoding="utf-8",
        )
        print(f"Creado lanzador alternativo: {alterno}")
        return alterno
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo crear ningun lanzador en el escritorio: {exc}")
        return None


# --------------------------------------------------------------------------
# LEEME
# --------------------------------------------------------------------------

def escribir_leeme(destino_exe: Path, lanzador: Optional[Path]) -> None:
    """Escribe un fichero de instrucciones junto al ejecutable."""
    if ES_WINDOWS:
        cuerpo = f"""1) Doble clic en:
     {destino_exe.name}

   (o en el acceso directo "{lanzador.name if lanzador else NOMBRE}" del escritorio)

2) Escribe un ticker (por ejemplo NVDA) y pulsa "Analizar" o Enter.

3) La aplicacion NO genera ningun Excel por si sola: usa el boton
   "Exportar a Excel" (o Ctrl+E) cuando lo quieras.

Ficheros de esta carpeta
------------------------
* {destino_exe.name}   el programa.
* config.yaml          umbrales y parametros (editables con cualquier editor de texto).
* _internal\\           librerias; no borrar.

Datos y cache
-------------
La cache de datos y la configuracion de matplotlib se guardan en:
    %USERPROFILE%\\.dml_finance
La cache de cada analisis, en la carpeta ".dml_cache" del directorio de trabajo
(definida en config.yaml como datos.cache_dir).
"""
    else:
        cuerpo = f"""1) Doble clic en:
     {lanzador.name if lanzador else destino_exe.name}

   (o en la entrada "{NOMBRE}" del menu de aplicaciones)

   Si el gestor de archivos no lo abre, desde una terminal:
     ./{destino_exe.name}

2) Escribe un ticker (por ejemplo NVDA) y pulsa "Analizar" o Enter.

3) La aplicacion NO genera ningun Excel por si sola: usa el boton
   "Exportar a Excel" (o Ctrl+E) cuando lo quieras.

Ficheros de esta carpeta
------------------------
* {destino_exe.name}     el programa.
* {lanzador.name if lanzador else NOMBRE + ".sh"}     lanzador (garantiza el directorio de trabajo).
* {NOMBRE}.desktop   entrada para el menu de aplicaciones.
* {NOMBRE}.png       icono de la entrada de escritorio.
* config.yaml        umbrales y parametros (editables con cualquier editor de texto).
* _internal/         librerias; no borrar.

Datos y cache
-------------
La cache de datos y la configuracion de matplotlib se guardan en:
    ~/.dml_finance
La cache de cada analisis, en la carpeta ".dml_cache" del directorio de trabajo
(definida en config.yaml como datos.cache_dir).

Requisitos del sistema
----------------------
Fedora 44 o superior (el paquete enlaza contra glibc 2.43). Necesita un entorno
grafico (X11 o Wayland) y las bibliotecas habituales de Qt:
    sudo dnf install fontconfig freetype libxkbcommon libxcb mesa-libGL mesa-libEGL

Instalacion en el menu de aplicaciones
--------------------------------------
    python empaquetar.py --instalar
o, para el sistema completo, el RPM:
    sudo dnf install DML-FINANCE-*.rpm
"""
    texto = f"""DML-FINANCE - como se usa el ejecutable
=======================================

{cuerpo}
Claves de API opcionales (no obligatorias)
------------------------------------------
Se leen de variables de entorno, nunca del codigo:
    FRED_API_KEY, FMP_API_KEY, FINNHUB_API_KEY

Primer arranque
---------------
El ejecutable tarda unos segundos mas la primera vez (carga de librerias).
Los analisis descargan datos de Internet y tardan entre 30 y 60 segundos.

Herramienta de analisis: no constituye asesoria financiera.
"""
    try:
        LEEME.write_text(texto, encoding="utf-8")
        shutil.copy2(LEEME, destino_exe.parent / LEEME.name)
        LEEME.unlink()
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo escribir el LEEME ({exc})")


# --------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Empaqueta la aplicacion y crea el lanzador."""
    args = construir_parser().parse_args(argv)

    # ``--instalar`` solo copia el .desktop y el icono del paquete ya construido:
    # no usa PyInstaller para nada. Por eso se atiende ANTES de comprobar la
    # dependencia, y asi funciona en un equipo que solo vaya a integrar el
    # paquete (por ejemplo una instalacion de usuario sin entorno de compilacion).
    if args.instalar:
        return 0 if instalar_en_menu() else 1

    try:
        import PyInstaller  # noqa: F401
    except Exception:
        print("PyInstaller no esta instalado.\n\nInstalalo con:\n    pip install pyinstaller\n", file=sys.stderr)
        return 2

    print(f"Sistema: {platform.system()} {platform.release()} · Python {platform.python_version()} "
          f"· {platform.machine()}")

    # Los paquetes para compartir (tar/zip/rpm) se construyen a partir de la
    # carpeta ``dist/DML-FINANCE/``, que solo existe en modo ``--onedir``. En
    # ``--unico`` hay un solo archivo, asi que se avisa en lugar de fallar a
    # mitad con un mensaje confuso.
    if args.unico and (args.tar_salida is not None or args.zip_salida is not None or args.rpm):
        print("Aviso: --unico genera un unico archivo; --tar, --zip y --rpm necesitan la\n"
              "       carpeta de --onedir. Se ignora la creacion de esos paquetes.", file=sys.stderr)
        args.tar_salida = None
        args.zip_salida = None
        args.rpm = False

    if args.limpiar:
        limpiar()
    icono = None if args.sin_icono else asegurar_icono()
    if icono is None and ES_WINDOWS:
        print("Aviso: se empaqueta sin icono personalizado (falta recursos/icono.ico).")
    receta = escribir_receta(args.unico, args.consola, icono)
    print(f"Receta efectiva: {receta}")
    orden = comando(receta)
    print("Ejecutando:\n  " + " ".join(orden) + "\n")
    resultado = subprocess.call(orden, cwd=str(RAIZ))
    if resultado != 0:
        print("\nEl empaquetado fallo. Revisa la salida de PyInstaller.", file=sys.stderr)
        return resultado

    destino = ejecutable_resultante(args.unico)
    if not destino.is_file():
        print(f"\nNo se encontro el ejecutable esperado en {destino}", file=sys.stderr)
        return 1
    print(f"\nEjecutable generado:\n  {destino}  ({destino.stat().st_size / 1024 / 1024:.0f} MB)")

    # Poda de componentes de Qt que la aplicacion no usa (solo --onedir).
    if not args.unico and not args.sin_poda and not args.completo:
        liberados = podar_paquete(destino.parent)
        if liberados:
            print(f"  Componentes de Qt no usados eliminados: {liberados} MB")
            print("  (verifica con: ./DML-FINANCE --autotest)")

    if not args.unico:
        destino_cfg = destino.parent / "config.yaml"
        if not destino_cfg.is_file() and CONFIG.is_file():
            try:
                shutil.copy2(CONFIG, destino_cfg)
                print(f"Configuracion copiada: {destino_cfg}")
            except Exception as exc:  # noqa: BLE001
                print(f"Aviso: no se pudo copiar config.yaml ({exc})")

    lanzador: Optional[Path] = None
    if ES_WINDOWS:
        # En Windows el acceso directo es el unico lanzador y va al escritorio.
        if not args.sin_acceso:
            lanzador = crear_acceso_directo(destino, args.escritorio, icono)
            if lanzador is not None:
                print(f"Acceso directo creado:\n  {lanzador}")
    else:
        # En Linux hay dos cosas distintas: el lanzador y el .desktop DENTRO del
        # paquete (siempre, para poder distribuirlo) y la copia al escritorio del
        # usuario (solo si no se pide --sin-acceso).
        lanzador = escribir_lanzador(destino)
        if lanzador is not None:
            print(f"Lanzador creado:\n  {lanzador}")
        entrada_paquete = escribir_desktop_en_paquete(destino)
        if entrada_paquete is not None:
            print(f"Entrada de escritorio en el paquete:\n  {entrada_paquete}")
        if not args.sin_acceso:
            entrada = escribir_desktop(destino, args.escritorio)
            if entrada is not None:
                print(f"Entrada de escritorio creada:\n  {entrada}")
                print("  (si el escritorio muestra un aviso de seguridad, marcala como \"Permitir ejecutar\")")

    escribir_leeme(destino, lanzador)

    if not args.unico:
        informar_portabilidad(destino.parent)

    if args.tar_salida is not None:
        crear_tar(args.tar_salida or None, aligerar=not args.completo)
    if args.zip_salida is not None:
        crear_zip(args.zip_salida or None, aligerar=not args.completo)
    if args.rpm:
        crear_rpm(aligerar=not args.completo)

    print("\nListo. Comprueba el paquete antes de distribuirlo con:")
    print(f"  cd {destino.parent} && QT_QPA_PLATFORM=offscreen ./{destino.name} --autotest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
