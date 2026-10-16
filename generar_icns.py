# -*- coding: utf-8 -*-
"""Genera ``recursos/icono.icns`` (icono de macOS) a partir del logo.

Por que existe este archivo
---------------------------
Un ``.app`` de macOS **no admite un PNG como icono**: el ``Info.plist`` referencia
un ``.icns``, que es un contenedor con varias resoluciones y unos codigos de tipo
concretos. ``generar_icono.py`` produce ``.ico`` (Windows) y ``.png``, pero no
``.icns``: esta es la pieza que faltaba para macOS.

Se usa una de dos vias, en este orden:

1. **``iconutil``** (solo macOS). Es la herramienta de Apple y la mas fiable:
   se le da la carpeta ``icono.iconset`` con los nombres que Apple exige y ella
   empaqueta el ``.icns``.
2. **Escritor propio en Python puro**. Funciona en cualquier sistema, asi que el
   ``.icns`` se puede **generar y verificar en Linux** (que es donde se desarrollo
   esto), y la Mac no depende de nada mas que Pillow.

Uso
---
::

    python generar_icns.py                  # recursos/icono.icns desde el logo
    python generar_icns.py --verificar      # solo comprueba el .icns existente
    python generar_icns.py --logo otro.png --salida otro.icns

El formato ICNS, en una frase
-----------------------------
Un archivo ICNS es ``b"icns"`` + tamano total (4 bytes, big-endian) + una lista de
bloques, y cada bloque es el codigo de tipo (4 bytes ASCII) + su tamano + los
datos (que para los tipos modernos son un PNG completo).
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

RAIZ = Path(__file__).resolve().parent
RECURSOS = RAIZ / "recursos"
LOGO = RECURSOS / "DML-Icon.png"
SALIDA = RECURSOS / "icono.icns"

#: Cabecera de un archivo ICNS y de cada bloque: 4 bytes ASCII + 4 de tamano.
_CABECERA = struct.Struct(">4sI")

#: Resoluciones que necesita un icono de aplicacion de macOS.
#:
#: Cada entrada es ``(codigo, pixeles)``. Los codigos de 1 bit (``is32``, ``il32``,
#: ``ih32``, ``it32``) son el formato antiguo y solo los usan versiones previas a
#: 10.7; se incluyen porque algunos visores de terceros los buscan. Los ``*p``
#: (``ic11``..``ic14``) son los que Apple prefiere hoy: llevan la marca de
#: "plantilla" que hace que Finder y el Dock redondeen el icono.
TIPOS_ICNS: Tuple[Tuple[bytes, int], ...] = (
    (b"ic07", 128),
    (b"ic08", 256),
    (b"ic09", 512),
    (b"ic10", 1024),
    (b"ic11", 32),
    (b"ic12", 64),
    (b"ic13", 256),
    (b"ic14", 512),
)

#: Nombres que exige ``iconutil`` para la carpeta ``.iconset``.
NOMBRES_ICONSET: Tuple[Tuple[str, int], ...] = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


# --------------------------------------------------------------------------
# Escritura del ICNS (Python puro)
# --------------------------------------------------------------------------

def bloques_icns(imagenes: Sequence[Tuple[bytes, bytes]]) -> bytes:
    """Monta el contenido de un ICNS a partir de pares ``(codigo, png)``.

    Args:
        imagenes: lista de ``(codigo de tipo, bytes del PNG)``.

    Returns:
        El archivo ICNS completo, listo para escribir en disco.
    """
    cuerpo = bytearray()
    for codigo, png in imagenes:
        if len(codigo) != 4:
            raise ValueError(f"El codigo ICNS debe tener 4 bytes, no {codigo!r}")
        # El tamano del bloque incluye la propia cabecera (4 + 4 bytes).
        cuerpo += _CABECERA.pack(codigo, len(png) + 8)
        cuerpo += png
    return _CABECERA.pack(b"icns", len(cuerpo) + 8) + bytes(cuerpo)


def generar_icns(logo: Path, salida: Path, forzar: bool = False) -> Optional[Path]:
    """Genera ``salida`` (``.icns``) a partir de la imagen ``logo``.

    Se regenera solo si el logo es mas reciente, salvo que ``forzar`` sea cierto.

    Returns:
        La ruta del ``.icns``, o ``None`` si no se pudo generar.
    """
    if not logo.is_file():
        print(f"No se encontro el logo {logo}", file=sys.stderr)
        return None
    if salida.is_file() and not forzar and salida.stat().st_mtime >= logo.stat().st_mtime:
        return salida

    try:
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        print(f"Falta Pillow para generar el .icns ({exc}).\n"
              f"Instalalo con:\n    pip install pillow", file=sys.stderr)
        return None

    salida.parent.mkdir(parents=True, exist_ok=True)

    # 1) Via preferida en macOS: iconutil (lo hace Apple, no nosotros).
    if sys.platform == "darwin" and shutil.which("iconutil"):
        resultado = _con_iconutil(logo, salida, Image)
        if resultado is not None:
            return resultado

    # 2) Escritor propio: funciona en cualquier sistema.
    try:
        with Image.open(logo) as original:
            # El logo es grande (4096 px) y con transparencia: se pasa a RGBA una
            # sola vez para no repetir la conversion en cada tamano.
            base = original.convert("RGBA")
            imagenes: List[Tuple[bytes, bytes]] = []
            for codigo, pixeles in TIPOS_ICNS:
                imagenes.append((codigo, _png_de(base, pixeles)))
        salida.write_bytes(bloques_icns(imagenes))
        print(f"ICNS generado: {salida} ({salida.stat().st_size / 1024:.1f} KB, "
              f"{len(imagenes)} resoluciones)")
        return salida
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo generar el .icns: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _png_de(base, pixeles: int) -> bytes:
    """Devuelve un PNG cuadrado de ``pixeles`` a partir de una imagen RGBA."""
    import io

    from PIL import Image

    redimensionada = base.resize((pixeles, pixeles), Image.LANCZOS)
    buffer = io.BytesIO()
    redimensionada.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _con_iconutil(logo: Path, salida: Path, Image) -> Optional[Path]:
    """Genera el ICNS con ``iconutil`` (solo macOS). ``None`` si no lo consigue."""
    try:
        with tempfile.TemporaryDirectory() as temporal:
            iconset = Path(temporal) / "icono.iconset"
            iconset.mkdir(parents=True, exist_ok=True)
            with Image.open(logo) as original:
                base = original.convert("RGBA")
                for nombre, pixeles in NOMBRES_ICONSET:
                    base.resize((pixeles, pixeles), Image.LANCZOS).save(iconset / nombre)
            resultado = subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(salida)],
                capture_output=True, text=True, check=False,
            )
            if resultado.returncode == 0 and salida.is_file():
                print(f"ICNS generado con iconutil: {salida} "
                      f"({salida.stat().st_size / 1024:.1f} KB, {len(NOMBRES_ICONSET)} resoluciones)")
                return salida
            print(f"Aviso: iconutil fallo ({resultado.returncode}): "
                  f"{resultado.stderr.strip()[:200]}. Se usa el escritor propio.")
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso: no se pudo usar iconutil ({exc}). Se usa el escritor propio.")
    return None


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------

def leer_bloques(ruta: Path) -> List[Tuple[str, int]]:
    """Devuelve ``(codigo, tamanio)`` de cada bloque de un ICNS.

    Sirve para comprobar que el archivo esta bien formado sin depender de macOS.
    """
    datos = ruta.read_bytes()
    if len(datos) < 8 or datos[:4] != b"icns":
        raise ValueError("no empieza por la firma 'icns'")
    (total,) = struct.unpack(">I", datos[4:8])
    if total != len(datos):
        raise ValueError(f"el tamano declarado ({total}) no coincide con el real ({len(datos)})")
    bloques: List[Tuple[str, int]] = []
    posicion = 8
    while posicion < len(datos):
        if posicion + 8 > len(datos):
            raise ValueError("bloque truncado: falta la cabecera")
        codigo, tamanio = _CABECERA.unpack(datos[posicion:posicion + 8])
        if tamanio < 8 or posicion + tamanio > len(datos):
            raise ValueError(f"bloque {codigo!r} con tamanio invalido ({tamanio})")
        bloques.append((codigo.decode("ascii", "replace"), tamanio))
        posicion += tamanio
    return bloques


def verificar(ruta: Path) -> bool:
    """Comprueba que ``ruta`` es un ICNS valido y con las resoluciones esperadas."""
    if not ruta.is_file():
        print(f"No existe {ruta}", file=sys.stderr)
        return False
    try:
        bloques = leer_bloques(ruta)
    except Exception as exc:  # noqa: BLE001
        print(f"[FALLO] {ruta.name}: {exc}", file=sys.stderr)
        return False

    codigos = {codigo for codigo, _ in bloques}
    esperados = {codigo.decode() for codigo, _ in TIPOS_ICNS}
    faltan = esperados - codigos
    print(f"ICNS: {ruta} ({ruta.stat().st_size / 1024:.1f} KB)")
    print(f"  bloques  : {len(bloques)} ({', '.join(codigo for codigo, _ in bloques)})")
    if faltan:
        print(f"  [FALLO] faltan resoluciones: {', '.join(sorted(faltan))}", file=sys.stderr)
        return False
    # Que Pillow lo pueda releer es una segunda opinion independiente del formato.
    try:
        from PIL import Image

        with Image.open(ruta) as imagen:
            print(f"  relectura: OK ({imagen.format}, {imagen.size[0]}x{imagen.size[1]})")
    except Exception as exc:  # noqa: BLE001
        print(f"  [AVISO] Pillow no pudo releerlo: {exc}")
    print("  [OK] estructura valida")
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generar_icns.py",
        description="Genera el icono .icns de macOS a partir de recursos/DML-Icon.png",
    )
    parser.add_argument("--logo", default=str(LOGO), help="imagen de origen (por defecto el logo)")
    parser.add_argument("--salida", default=str(SALIDA), help="ruta del .icns a escribir")
    parser.add_argument("--forzar", action="store_true", help="regenera aunque el .icns sea reciente")
    parser.add_argument("--verificar", action="store_true", help="solo comprueba el .icns existente")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = construir_parser().parse_args(argv)
    ruta = Path(args.salida)
    if args.verificar:
        return 0 if verificar(ruta) else 1
    generado = generar_icns(Path(args.logo), ruta, forzar=args.forzar)
    if generado is None:
        return 1
    return 0 if verificar(generado) else 1


if __name__ == "__main__":
    sys.exit(main())
