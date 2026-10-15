# -*- coding: utf-8 -*-
"""Configuracion centralizada de ``logging``.

La aplicacion escribe trazas en consola y, opcionalmente, en un archivo dentro
del directorio de datos del usuario. Nunca se escribe en el directorio de
trabajo sin que el usuario lo pida.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

FORMATO = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
FECHA = "%H:%M:%S"

LOG = logging.getLogger("dml.log")

_configurado = False


def _destino_por_defecto() -> Optional[Path]:
    """Archivo de trazas por defecto, dentro del directorio de datos del usuario.

    Devuelve ``None`` si esa carpeta no admite escritura: quedarse sin archivo de
    trazas es aceptable, impedir que la aplicacion arranque no lo es.
    """
    from .config import ruta_archivo_datos

    return ruta_archivo_datos("dml-finance.log")


def configurar_logging(
    verbose: bool = False,
    archivo: Optional[Path] = None,
    silencioso: Optional[bool] = None,
) -> logging.Logger:
    """Configura el logger raiz de DML-FINANCE.

    Siempre se deja un archivo de trazas en la carpeta de datos del usuario
    (rotativo, 2 MB x 3): es la unica forma de diagnosticar un problema cuando la
    aplicacion se abre con doble clic desde el acceso directo, donde no hay
    consola que leer. Un archivo de texto de unos pocos KB es un precio pequeno
    por poder averiguar por que fallo.

    Args:
        verbose: activa el nivel ``DEBUG``.
        archivo: archivo de trazas; por defecto ``<datos del usuario>/dml-finance.log``.
        silencioso: no anade salida por consola. Si es ``None`` (lo normal) la
            consola se activa **solo si existe realmente**: en un ejecutable
            compilado con ``--windowed``, ``sys.stderr`` puede ser ``None`` y un
            ``StreamHandler`` sobre ``None`` descarta todas las trazas en
            silencio.
    """
    global _configurado
    raiz = logging.getLogger("dml")
    raiz.setLevel(logging.DEBUG if verbose else logging.INFO)
    if _configurado:
        return raiz
    raiz.handlers.clear()
    raiz.propagate = False

    formato = logging.Formatter(FORMATO, datefmt=FECHA)
    hay_consola = sys.stderr is not None and sys.stdout is not None
    if silencioso is None:
        silencioso = not hay_consola
    if not silencioso and hay_consola:
        consola = logging.StreamHandler(stream=sys.stderr)
        consola.setLevel(logging.DEBUG if verbose else logging.INFO)
        consola.setFormatter(formato)
        raiz.addHandler(consola)

    destino = Path(archivo) if archivo is not None else _destino_por_defecto()
    if destino is not None:
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            rotativo = logging.handlers.RotatingFileHandler(
                destino, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            rotativo.setLevel(logging.DEBUG)
            rotativo.setFormatter(formato)
            raiz.addHandler(rotativo)
        except Exception as exc:  # noqa: BLE001 - depende del sistema de archivos
            # Quedarse sin archivo de trazas es aceptable; impedir el arranque no.
            if hay_consola:
                print(f"Aviso: no se pudo abrir el archivo de trazas {destino}: {exc}", file=sys.stderr)
    if not raiz.handlers:
        # Sin consola y sin archivo: al menos que ``logging`` no falle ni ensucie.
        raiz.addHandler(logging.NullHandler())
    _configurado = True
    return raiz
