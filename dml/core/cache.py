# -*- coding: utf-8 -*-
"""Cache local por dia para no repetir peticiones de red.

La cache vive en un directorio oculto del usuario (``.dml_cache``) y es la
**unica** escritura en disco que la aplicacion realiza sin que el usuario la
pida (el pliego lo permite de forma explicita). Cualquier otro archivo se crea
solo al pulsar "Exportar a Excel".
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .util import json_default

LOG = logging.getLogger("dml.cache")


class Cache:
    """Cache en disco de pares clave/valor JSON con caducidad configurable.

    Args:
        directorio: carpeta donde se guardan las entradas.
        ttl_horas: horas de validez de cada entrada (24 = cache "por dia").
        activa: si es ``False``, :meth:`obtener` siempre llama al productor.
    """

    def __init__(self, directorio: Path | str = ".dml_cache", ttl_horas: float = 24.0, activa: bool = True) -> None:
        self.directorio = Path(directorio)
        self.ttl_segundos = float(ttl_horas) * 3600.0
        self.activa = bool(activa)
        self.aciertos = 0
        self.fallos = 0
        try:
            self.directorio.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - depende del sistema de archivos
            LOG.warning("No se pudo crear la cache en %s: %s", self.directorio, exc)
            self.activa = False

    # ------------------------------------------------------------------ rutas
    def ruta(self, clave: str) -> Path:
        """Ruta del archivo de una clave (hash estable y legible)."""
        resumen = hashlib.sha1(clave.encode("utf-8")).hexdigest()[:20]
        limpio = "".join(c if c.isalnum() or c in "-_." else "_" for c in clave)[:40]
        return self.directorio / f"{limpio}-{resumen}.json"

    # ------------------------------------------------------------- operacion
    def leer(self, clave: str) -> Tuple[bool, Any]:
        """Lee una entrada. Devuelve ``(valido, valor)``."""
        if not self.activa:
            return False, None
        archivo = self.ruta(clave)
        if not archivo.is_file():
            return False, None
        try:
            edad = time.time() - archivo.stat().st_mtime
            if self.ttl_segundos > 0 and edad > self.ttl_segundos:
                return False, None
            with open(archivo, "r", encoding="utf-8") as fh:
                return True, json.load(fh)
        except Exception as exc:
            LOG.debug("Entrada de cache ilegible %s: %s", archivo.name, exc)
            return False, None

    def escribir(self, clave: str, valor: Any) -> None:
        """Guarda una entrada (ignora silenciosamente los fallos de escritura)."""
        if not self.activa:
            return
        archivo = self.ruta(clave)
        try:
            temporal = archivo.with_suffix(".tmp")
            with open(temporal, "w", encoding="utf-8") as fh:
                json.dump(valor, fh, default=json_default, ensure_ascii=False)
            temporal.replace(archivo)
        except Exception as exc:
            LOG.debug("No se pudo escribir la cache %s: %s", archivo.name, exc)

    def obtener(self, clave: str, productor: Callable[[], Any]) -> Any:
        """Devuelve el valor cacheado o el resultado de ``productor()``.

        Si el productor devuelve ``None`` no se cachea (para no fijar un fallo
        temporal de red durante 24 horas).
        """
        valido, guardado = self.leer(clave)
        if valido:
            self.aciertos += 1
            LOG.debug("Cache HIT: %s", clave)
            return guardado
        self.fallos += 1
        LOG.debug("Cache MISS: %s", clave)
        valor = productor()
        if valor is not None:
            self.escribir(clave, valor)
        return valor

    # ------------------------------------------------------------ mantenimiento
    def limpiar(self) -> int:
        """Borra todas las entradas. Devuelve cuantas se eliminaron."""
        borrados = 0
        if not self.directorio.is_dir():
            return 0
        for archivo in self.directorio.glob("*.json"):
            try:
                archivo.unlink()
                borrados += 1
            except Exception as exc:  # pragma: no cover
                LOG.debug("No se pudo borrar %s: %s", archivo, exc)
        return borrados

    def destruir(self) -> bool:
        """Elimina el directorio completo de cache."""
        try:
            if self.directorio.is_dir():
                shutil.rmtree(self.directorio)
            self.directorio.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as exc:  # pragma: no cover
            LOG.warning("No se pudo limpiar la cache: %s", exc)
            return False

    def inventario(self) -> List[Dict[str, Any]]:
        """Lista de entradas con su tamano y antiguedad (para la interfaz)."""
        filas: List[Dict[str, Any]] = []
        if not self.directorio.is_dir():
            return filas
        ahora = time.time()
        for archivo in sorted(self.directorio.glob("*.json")):
            try:
                st = archivo.stat()
                filas.append(
                    {
                        "Archivo": archivo.name,
                        "KB": round(st.st_size / 1024.0, 1),
                        "Edad (h)": round((ahora - st.st_mtime) / 3600.0, 2),
                    }
                )
            except Exception:  # pragma: no cover
                continue
        return filas

    def estadisticas(self) -> Dict[str, Any]:
        """Resumen de uso de la cache (aciertos, fallos, entradas)."""
        entradas = len(list(self.directorio.glob("*.json"))) if self.directorio.is_dir() else 0
        return {
            "directorio": str(self.directorio),
            "activa": self.activa,
            "entradas": entradas,
            "aciertos": self.aciertos,
            "fallos": self.fallos,
        }
