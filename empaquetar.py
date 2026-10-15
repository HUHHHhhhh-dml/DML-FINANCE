# -*- coding: utf-8 -*-
"""Empaquetado de DML-FINANCE como ejecutable + acceso directo en el escritorio.

Uso
---
::

    python empaquetar.py                 # ejecutable en dist/ + acceso directo en el escritorio
    python empaquetar.py --unico         # un solo archivo .exe (arranque mas lento)
    python empaquetar.py --sin-acceso    # no crea el acceso directo
    python empaquetar.py --limpiar       # borra build/ y dist/ antes de empaquetar
    python empaquetar.py --consola       # mantiene una consola (util para depurar)

Resultado (modo por defecto, ``--onedir``):

* ``dist/DML-FINANCE/DML-FINANCE.exe``  <- el programa (doble clic).
* ``dist/DML-FINANCE/config.yaml``      <- umbrales editables por el usuario.
* Un acceso directo **DML-FINANCE** en el escritorio, con el icono del programa.

Se usa ``--onedir`` por defecto porque **arranca en 1-3 s**, frente a los ~20-30 s
que tarda un ``--onefile`` al descomprimirse en cada ejecucion.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence

RAIZ = Path(__file__).resolve().parent
NOMBRE = "DML-FINANCE"
RECURSOS = RAIZ / "recursos"
ICONO = RECURSOS / "icono.ico"
LOGO = RECURSOS / "DML-Icon.png"
CONFIG = RAIZ / "config.yaml"
LEEME = RAIZ / "LEEME-EJECUTABLE.txt"


def construir_parser() -> argparse.ArgumentParser:
    """Argumentos del empaquetador."""
    parser = argparse.ArgumentParser(
        prog="empaquetar.py", description="Genera el ejecutable de DML-FINANCE y su acceso directo."
    )
    parser.add_argument("--unico", action="store_true", help="genera un unico archivo .exe (--onefile, arranque lento)")
    parser.add_argument("--limpiar", action="store_true", help="borra build/ y dist/ antes de empaquetar")
    parser.add_argument("--consola", action="store_true", help="mantiene la consola visible (util para depurar)")
    parser.add_argument("--sin-icono", action="store_true", help="no usa recursos/icono.ico")
    parser.add_argument("--sin-acceso", action="store_true", help="no crea el acceso directo en el escritorio")
    parser.add_argument("--escritorio", default=None, help="carpeta alternativa para el acceso directo")
    parser.add_argument("--zip", dest="zip_salida", nargs="?", const="", default=None, metavar="ARCHIVO",
                        help="crea ademas un ZIP listo para compartir (por defecto dist/DML-FINANCE.zip)")
    parser.add_argument("--completo", action="store_true",
                        help="no aligera el paquete (conserva todo lo que deja PyInstaller)")
    return parser


def limpiar() -> None:
    """Borra los directorios generados por PyInstaller."""
    for carpeta in ("build", "dist"):
        ruta = RAIZ / carpeta
        if ruta.is_dir():
            shutil.rmtree(ruta, ignore_errors=True)
            print(f"Eliminado {ruta}")


def asegurar_icono() -> Optional[Path]:
    """Genera el icono a partir del logo si no existe y devuelve su ruta."""
    if ICONO.is_file() and LOGO.is_file():
        # Si el logo cambio despues del .ico, se regenera para no distribuir el antiguo.
        if ICONO.stat().st_mtime < LOGO.stat().st_mtime:
            _regenerar_icono()
        return ICONO
    _regenerar_icono()
    return ICONO if ICONO.is_file() else None


def _regenerar_icono() -> None:
    """Regenera ``recursos/icono.ico`` y ``recursos/icono.png`` desde el logo."""
    try:
        import generar_icono

        generar_icono.main([])
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo generar el icono desde {LOGO.name} ({exc})")


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
    """
    receta = (RAIZ / "DML-FINANCE.spec").read_text(encoding="utf-8")
    if consola:
        receta = receta.replace("console=False", "console=True", 1)
    if icono is None:
        receta = receta.replace("    icon=[str(RECURSOS / 'icono.ico')],\n", "")
    if unico:
        # En un fichero unico no hay COLLECT: los binarios y los datos van dentro
        # del propio EXE.
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
    """Ruta del .exe generado."""
    if unico:
        return RAIZ / "dist" / f"{NOMBRE}.exe"
    return RAIZ / "dist" / NOMBRE / f"{NOMBRE}.exe"


# --------------------------------------------------------------------------
# Paquete listo para compartir (ZIP)
# --------------------------------------------------------------------------

#: Nombres que **nunca** deben viajar en el paquete: son datos de quien lo genero
#: (cache de datos, logs, preferencias) o restos de una ejecucion. Si el amigo
#: recibe la cache del autor, el programa arrancaria con datos de otro equipo.
NO_COMPARTIR = {".dml_cache", ".dml_finance", "autotest.txt"}

#: Archivos que se pueden borrar del paquete porque la aplicacion no los usa.
#: ``opengl32sw.dll`` es un rasterizador OpenGL **por software** (20 MB) que solo
#: se carga si algo pide un contexto OpenGL; esta aplicacion pinta con el motor
#: raster de Qt (widgets y lienzos de matplotlib), asi que no se usa nunca.
#: Se puede desactivar con ``--completo``.
ALIGERAR = (Path("PySide6") / "opengl32sw.dll",)


def aligerar_paquete(carpeta: Path) -> int:
    """Borra del paquete los archivos prescindibles. Devuelve los MB liberados."""
    liberados = 0
    for relativa in ALIGERAR:
        archivo = carpeta / "_internal" / relativa
        if archivo.is_file():
            try:
                tamano = archivo.stat().st_size
                archivo.unlink()
                liberados += tamano
                print(f"  - {relativa} ({tamano / 1024 / 1024:.1f} MB)")
            except Exception as exc:  # noqa: BLE001
                print(f"  Aviso: no se pudo borrar {relativa}: {exc}")
    return int(liberados / 1024 / 1024)


def _copia_limpia(origen: Path, destino: Path) -> List[str]:
    """Copia el paquete a ``destino`` saltandose los datos de ejecucion.

    Se copia en lugar de borrar sobre el original: ``dist/`` se puede seguir
    usando para probar sin dejar de tener un ZIP limpio garantizado.

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
            shutil.copytree(elemento, destino / elemento.name, dirs_exist_ok=True)
        else:
            shutil.copy2(elemento, destino / elemento.name)
    return omitidos


def crear_zip(destino_zip: Optional[str] = None, aligerar: bool = True) -> Optional[Path]:
    """Empaqueta ``dist/<NOMBRE>`` en un ZIP listo para compartir.

    El ZIP contiene una unica carpeta ``DML-FINANCE/`` con el ejecutable, su
    ``_internal/``, ``config.yaml`` y el LEEME: el amigo solo tiene que
    descomprimirlo y hacer doble clic en el ``.exe``.

    Args:
        destino_zip: ruta del ZIP; por defecto ``dist/DML-FINANCE.zip``.
        aligerar: borra los archivos prescindibles (ver :data:`ALIGERAR`).

    Returns:
        La ruta del ZIP creado, o ``None`` si no se pudo.
    """
    carpeta = RAIZ / "dist" / NOMBRE
    if not carpeta.is_dir():
        print(f"No existe {carpeta}: empaqueta antes de generar el ZIP.", file=sys.stderr)
        return None
    salida = Path(destino_zip) if destino_zip else (RAIZ / "dist" / f"{NOMBRE}.zip")
    if salida.suffix.lower() != ".zip":
        salida = salida.with_suffix(".zip")
    salida.parent.mkdir(parents=True, exist_ok=True)

    # 1) Copia limpia (sin cache, logs ni preferencias del autor).
    trabajo = RAIZ / "build" / "paquete-limpio"
    shutil.rmtree(trabajo, ignore_errors=True)
    omitidos = _copia_limpia(carpeta, trabajo / NOMBRE)
    if omitidos:
        print("Datos de ejecucion excluidos del paquete: " + ", ".join(sorted(omitidos)))

    # 2) Aligerado (solo afecta a la copia).
    if aligerar:
        print("Archivos prescindibles:")
        liberados = aligerar_paquete(trabajo / NOMBRE)
        print(f"  ({liberados} MB liberados)")

    # 3) Comprobacion basica: que el ejecutable siga en su sitio.
    ejecutable = trabajo / NOMBRE / f"{NOMBRE}.exe"
    if not ejecutable.is_file():
        print(f"El paquete no contiene {ejecutable.name}: se aborta.", file=sys.stderr)
        return None

    # 4) ZIP (DEFLATE; el contenido ya viene comprimido en su mayoria).
    if salida.is_file():
        salida.unlink()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for archivo in sorted((trabajo / NOMBRE).rglob("*")):
            if archivo.is_file():
                zf.write(archivo, archivo.relative_to(trabajo))
    shutil.rmtree(trabajo, ignore_errors=True)

    original = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    print(f"\nZIP listo para compartir:\n  {salida}  ({salida.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"  (la carpeta dist/{NOMBRE} ocupa {original / 1024 / 1024:.0f} MB sin comprimir)")
    print("\nContenido: la carpeta DML-FINANCE con el .exe, _internal/, config.yaml y el LEEME.")
    print("Tu amigo solo tiene que descomprimirla y hacer doble clic en DML-FINANCE.exe.")
    return salida


def _escritorio(preferido: Optional[str] = None) -> Path:
    """Localiza el escritorio del usuario (con o sin OneDrive)."""
    if preferido:
        return Path(preferido)
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


def crear_acceso_directo(destino_exe: Path, escritorio: Optional[str] = None, icono: Optional[Path] = None) -> Optional[Path]:
    """Crea (o reemplaza) un acceso directo ``.lnk`` en el escritorio.

    Usa ``pywin32`` si esta disponible y, si no, un script de PowerShell. En
    ambos casos el acceso directo apunta al ``.exe``, arranca en su carpeta (para
    que encuentre ``config.yaml``) y lleva el icono del programa.

    Returns:
        La ruta del ``.lnk`` creado, o ``None`` si no se pudo.
    """
    carpeta = _escritorio(escritorio)
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
            capture_output=True,
            text=True,
            timeout=60,
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


def escribir_leeme(destino_exe: Path, acceso: Optional[Path]) -> None:
    """Escribe un fichero de instrucciones junto al ejecutable."""
    texto = f"""DML-FINANCE - como se usa el ejecutable
=======================================

1) Doble clic en:
     {destino_exe.name}

   (o en el acceso directo "{acceso.name if acceso else NOMBRE}" del escritorio)

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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Empaqueta la aplicacion y crea el acceso directo."""
    args = construir_parser().parse_args(argv)
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        print("PyInstaller no esta instalado.\n\nInstalalo con:\n    pip install pyinstaller\n", file=sys.stderr)
        return 2

    if args.limpiar:
        limpiar()
    icono = None if args.sin_icono else asegurar_icono()
    if icono is None:
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

    if not args.unico:
        destino_cfg = destino.parent / "config.yaml"
        if not destino_cfg.is_file() and CONFIG.is_file():
            try:
                shutil.copy2(CONFIG, destino_cfg)
                print(f"Configuracion copiada: {destino_cfg}")
            except Exception as exc:  # noqa: BLE001
                print(f"Aviso: no se pudo copiar config.yaml ({exc})")

    acceso = None
    if not args.sin_acceso:
        acceso = crear_acceso_directo(destino, args.escritorio, icono)
        if acceso is not None:
            print(f"Acceso directo creado:\n  {acceso}")

    escribir_leeme(destino, acceso)

    # ZIP listo para compartir (con --zip).
    if args.zip_salida is not None:
        crear_zip(args.zip_salida or None, aligerar=not args.completo)

    print("\nListo: puedes abrir DML-FINANCE con doble clic en el acceso directo del escritorio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
