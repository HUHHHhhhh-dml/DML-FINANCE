# -*- coding: utf-8 -*-
"""Genera los iconos de la aplicacion a partir del logo ``recursos/DML-Icon.png``.

Produce:

* ``recursos/icono.ico`` — icono multi-resolucion (16..256 px) que usan el
  ejecutable de PyInstaller, el acceso directo del escritorio y la ventana.
* ``recursos/icono.png`` — version de 256 px con fondo transparente (referencia
  y usada por los sitios donde se necesita un PNG).

Se dibuja una **placa redondeada** detras del logo para que la marca se lea bien
tanto en el menu de inicio (fondo claro) como en la barra de tareas (fondo
oscuro), y se recorta el logo a su contenido real para que quede centrado y con
un margen uniforme.

Uso::

    python generar_icono.py            # regenera recursos/icono.ico y .png
    python generar_icono.py --ver      # solo muestra el resultado (diagnostico)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent
RECURSOS = RAIZ / "recursos"
LOGO = RECURSOS / "DML-Icon.png"

#: Tamano base de trabajo (potencia de dos para que los escalados sean exactos).
TAMANO_BASE = 256

#: Resoluciones incluidas en el ``.ico`` (Windows elige la que necesita).
TAMANOS_ICO: List[Tuple[int, int]] = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

#: Placa redondeada: fondo claro y borde suave (coincide con el tema claro de la app).
PLACA = (244, 246, 249, 255)
PLACA_BORDE = (201, 209, 220, 255)
#: Margen respecto al lado de la placa.
MARGEN_PLACA = 6
#: Radio de la placa (proporcion del lado, 0.22 = esquinas "estilo Windows 11").
RADIO_PLACA = 0.22
#: Proporcion del hueco util que ocupa el logo (el resto es aire).
PROPORCION_LOGO = 0.70


def _cargar_logo(ruta: Optional[Path] = None) -> Image.Image:
    """Carga el logo y lo recorta a su contenido visible (RGBA)."""
    origen = Path(ruta or LOGO)
    if not origen.is_file():
        raise FileNotFoundError(
            f"No se encontro el logo {origen}. Coloca 'DML-Icon.png' en la carpeta recursos/."
        )
    imagen = Image.open(origen).convert("RGBA")
    recorte = imagen.getchannel("A").getbbox()
    return imagen.crop(recorte) if recorte else imagen


def dibujar(tamano: int = TAMANO_BASE, ruta_logo: Optional[Path] = None) -> Image.Image:
    """Dibuja el icono a un tamano dado: placa redondeada + logo centrado.

    Args:
        tamano: lado del icono cuadrado en pixeles.
        ruta_logo: logo alternativo (por defecto ``recursos/DML-Icon.png``).

    Returns:
        Una imagen RGBA de ``tamano`` x ``tamano``.
    """
    tamano = max(int(tamano), 8)
    escala = tamano / TAMANO_BASE
    lienzo = Image.new("RGBA", (tamano, tamano), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(lienzo)

    # 1) Placa redondeada de fondo (con un borde fino que la separa del escritorio).
    margen = max(1, round(MARGEN_PLACA * escala))
    radio = max(2, round(TAMANO_BASE * RADIO_PLACA * escala))
    borde = max(1, round(1.5 * escala))
    caja = (margen, margen, tamano - margen - 1, tamano - margen - 1)
    dibujo.rounded_rectangle(caja, radius=radio, fill=PLACA, outline=PLACA_BORDE, width=borde)

    # 2) Logo centrado y escalado al hueco disponible (conservando la proporcion).
    #    La marca es mas alta que ancha, asi que se limita por el lado que mas
    #    sobresaldria para dejarla siempre dentro de la placa y con aire.
    logo = _cargar_logo(ruta_logo)
    ancho, alto = logo.size
    disponible_alto = max(1, round((tamano - 2 * (margen + 1) - 2 * max(1, round(4 * escala))) * PROPORCION_LOGO))
    disponible_ancho = max(1, round((tamano - 2 * (margen + 1)) * PROPORCION_LOGO))
    factor = min(disponible_ancho / ancho, disponible_alto / alto)
    nuevo = (max(1, round(ancho * factor)), max(1, round(alto * factor)))
    logo = logo.resize(nuevo, Image.LANCZOS)
    posicion = ((tamano - nuevo[0]) // 2, (tamano - nuevo[1]) // 2)
    lienzo.alpha_composite(logo, posicion)
    return lienzo


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Escribe ``recursos/icono.ico`` (multi-resolucion) y ``recursos/icono.png``."""
    parser = argparse.ArgumentParser(
        prog="generar_icono.py", description="Genera los iconos de DML-FINANCE a partir de recursos/DML-Icon.png"
    )
    parser.add_argument("--logo", default=str(LOGO), help="ruta del logo de origen (PNG)")
    parser.add_argument("--ver", action="store_true", help="solo comprueba que el logo se puede leer (no escribe nada)")
    args = parser.parse_args(argv)

    ruta_logo = Path(args.logo)
    base = dibujar(TAMANO_BASE, ruta_logo)
    if args.ver:
        print(f"Logo leido correctamente: {ruta_logo} -> icono de {base.size[0]}x{base.size[1]} px")
        return 0

    RECURSOS.mkdir(parents=True, exist_ok=True)
    png = RECURSOS / "icono.png"
    base.save(png, format="PNG", optimize=True)

    ico = RECURSOS / "icono.ico"
    # Pillow genera todas las resoluciones a partir de la imagen base.
    base.save(ico, format="ICO", sizes=TAMANOS_ICO)
    print(f"Icono generado: {ico} ({ico.stat().st_size / 1024:.1f} KB, {len(TAMANOS_ICO)} resoluciones)")
    print(f"PNG de referencia: {png} ({png.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
