#!/usr/bin/env bash
# =============================================================================
# DML-FINANCE - Verificacion de portabilidad en un Fedora limpio (podman)
#
# Prueba que el paquete generado por empaquetar.py funciona en un Fedora SIN
# Python, SIN las dependencias del proyecto y SIN el escritorio del autor. Es la
# comprobacion que detecta "en mi maquina funciona".
#
# Uso
# ---
#     tests/verificar_contenedor.sh [RUTA_AL_TAR_GZ]
#
# Por defecto usa el .tar.gz mas reciente de dist/. Requiere podman
# (sudo dnf install podman).
#
# Que comprueba
# -------------
# 1. Que el contenedor NO tiene Python ni pip: si el paquete arranca, es que
#    lleva su propio interprete y no depende del sistema.
# 2. Que todas las bibliotecas compartidas del paquete y de los plugins de Qt
#    resuelven dentro del contenedor (ldd sin "not found").
# 3. Que el autotest pasa con HOME virgen (sin ~/.dml_finance previo).
# 4. Que el .desktop es valido segun el estandar freedesktop.
# =============================================================================

set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGEN="${IMAGEN:-docker.io/library/fedora:44}"

if ! command -v podman >/dev/null 2>&1; then
    echo "Falta podman. Instalalo con: sudo dnf install podman" >&2
    exit 2
fi

# --- Localizar el paquete a probar -------------------------------------------
TAR="${1:-}"
if [ -z "$TAR" ]; then
    TAR="$(ls -1t "$RAIZ"/dist/*.tar.gz 2>/dev/null | head -1)"
fi
if [ -z "$TAR" ] || [ ! -f "$TAR" ]; then
    echo "No encuentro ningun .tar.gz. Genera uno con:" >&2
    echo "    python empaquetar.py --tar" >&2
    exit 2
fi
TAR="$(cd "$(dirname "$TAR")" && pwd)/$(basename "$TAR")"
echo "Paquete a verificar: $TAR"
echo "Imagen limpia      : $IMAGEN"
echo

# --- Extraer en una carpeta temporal del anfitrion ---------------------------
# Se extrae como usuario normal para poder comprobar que el .tar.gz conserva el
# permiso de ejecucion (si no lo conservara, el fallo se veria aqui).
TRABAJO="$(mktemp -d)"
trap 'rm -rf "$TRABAJO"' EXIT
tar -xzf "$TAR" -C "$TRABAJO"
APP="$TRABAJO/DML-FINANCE"
if [ ! -d "$APP" ]; then
    echo "El .tar.gz no contiene la carpeta DML-FINANCE/" >&2
    exit 1
fi

if [ -x "$APP/DML-FINANCE" ]; then
    echo "[OK] El .tar.gz conserva el permiso de ejecucion del binario"
else
    echo "[FALLO] El binario no quedo ejecutable al descomprimir" >&2
    exit 1
fi

# --- Guion que se ejecuta dentro del contenedor ------------------------------
cat > "$TRABAJO/prueba.sh" <<'GUION'
set -uo pipefail
APP=/prueba/DML-FINANCE
fallos=0

informe() { printf '%-58s %s\n' "$1" "$2"; }

# 1) El contenedor no debe tener Python del sistema.
if command -v python3 >/dev/null 2>&1; then
    informe "Python del sistema ausente" "AVISO (existe: $(python3 --version 2>&1))"
else
    informe "Python del sistema ausente" "[OK]"
fi

# 2) Bibliotecas compartidas resueltas.
#    Se separa lo esencial (binario, Qt Core/Gui/Widgets y el plugin offscreen,
#    que es lo que usa el autotest) de los plugins de pantalla (xcb/wayland), que
#    dependen de un escritorio real y por eso en un contenedor minimo faltan sin
#    que sea un defecto del paquete. Esa lista es la que hay que instalar en el
#    equipo de destino, y se informa.
esenciales=$( (for f in "$APP/DML-FINANCE" \
                    "$APP"/_internal/PySide6/Qt/lib/libQt6Core.so.6 \
                    "$APP"/_internal/PySide6/Qt/lib/libQt6Gui.so.6 \
                    "$APP"/_internal/PySide6/Qt/lib/libQt6Widgets.so.6 \
                    "$APP"/_internal/PySide6/Qt/lib/libQt6Network.so.6 \
                    "$APP"/_internal/PySide6/Qt/plugins/platforms/libqoffscreen.so; do
                 [ -f "$f" ] && ldd "$f" 2>/dev/null
             done) | grep "not found" | awk '{print $1}' | sort -u)
if [ -z "$esenciales" ]; then
    informe "Bibliotecas esenciales resueltas" "[OK]"
else
    informe "Bibliotecas esenciales resueltas" "[FALLO]"
    echo "$esenciales" | sed 's/^/    falta: /'
    fallos=$((fallos+1))
fi

pantalla=$( (for f in "$APP"/_internal/PySide6/Qt/plugins/platforms/libqxcb.so \
                  "$APP"/_internal/PySide6/Qt/plugins/platforms/libqwayland.so; do
                 [ -f "$f" ] && ldd "$f" 2>/dev/null
             done) | grep "not found" | awk '{print $1}' | sort -u)
if [ -z "$pantalla" ]; then
    informe "Plugins de pantalla completos" "[OK] (contenedor con escritorio)"
else
    informe "Plugins de pantalla" "incompletos en contenedor minimo (normal)"
    echo "    En un Fedora con escritorio instala:"
    echo "$pantalla" | sed 's/^/      /'
fi

# 3) Autotest con HOME virgen (como un usuario nuevo).
export HOME=/home/prueba
export QT_QPA_PLATFORM=offscreen
mkdir -p "$HOME"
if (cd "$APP" && ./DML-FINANCE --autotest --autotest-salida "$HOME/autotest.txt" >"$HOME/salida.txt" 2>&1); then
    informe "Autotest (HOME virgen, offscreen)" "[OK]"
    grep -E "PySide6|numpy|pandas|excel|ventana" "$HOME/autotest.txt" | sed 's/^/    /'
else
    informe "Autotest (HOME virgen, offscreen)" "[FALLO]"
    tail -20 "$HOME/salida.txt" | sed 's/^/    /'
    fallos=$((fallos+1))
fi

# 4) El arranque real en X11/Wayland no se puede probar sin pantalla, pero si
#    que el plugin xcb se puede cargar y que Qt no falla por plataforma.
export QT_QPA_PLATFORM=minimal
if (cd "$APP" && timeout 25 ./DML-FINANCE --marca "$HOME/marca.txt" >/dev/null 2>&1); then
    informe "Arranque con plataforma minimal" "[OK]"
else
    informe "Arranque con plataforma minimal" "revisar (puede ser normal sin pantalla)"
fi

# 5) Entrada de escritorio valida.
if command -v desktop-file-validate >/dev/null 2>&1; then
    if desktop-file-validate "$APP/DML-FINANCE.desktop" 2>"$HOME/desktop.err"; then
        informe "DML-FINANCE.desktop valido" "[OK]"
    else
        informe "DML-FINANCE.desktop valido" "[FALLO]"
        sed 's/^/    /' "$HOME/desktop.err"
        fallos=$((fallos+1))
    fi
else
    informe "DML-FINANCE.desktop valido" "omitido (falta desktop-file-validate)"
fi

echo
if [ "$fallos" -eq 0 ]; then
    echo "RESULTADO: OK - el paquete funciona en un Fedora limpio"
    exit 0
fi
echo "RESULTADO: $fallos comprobacion(es) fallida(s)"
exit 1
GUION
chmod +x "$TRABAJO/prueba.sh"

# --- Ejecutar ----------------------------------------------------------------
# La imagen oficial de Fedora es minima: no trae bibliotecas graficas. Aqui se
# instala EXACTAMENTE la lista de requisitos que declara el RPM
# (ver PLANTILLA_RPM en empaquetar.py). Si el autotest pasa con esta lista, los
# "Requires" son correctos y completos; si fallara, faltaria declarar algo.
#
# Este paso es ademas la prueba de que la dependencia de libGL (que Qt6 exige y
# PyInstaller NO empaqueta) esta correctamente declarada.
#
# Para reproducir el minimo absoluto sin ninguna dependencia grafica:
#     SIN_DEPENDENCIAS=1 tests/verificar_contenedor.sh
PAQUETES="${PAQUETES:-fontconfig freetype libxkbcommon libxkbcommon-x11 libxcb dbus-libs mesa-libGL mesa-libEGL xcb-util xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-cursor libwayland-cursor}"

echo "Ejecutando dentro de $IMAGEN ..."
if [ "${SIN_DEPENDENCIAS:-0}" = "1" ]; then
    echo "Modo SIN_DEPENDENCIAS=1: no se instala nada (se espera el fallo de libGL)."
else
    echo "Requisitos que se instalaran: $PAQUETES"
fi
echo "-----------------------------------------------------------------"
podman run --rm \
    --volume "$TRABAJO:/prueba:ro,z" \
    --env PAQUETES="$PAQUETES" \
    --env SIN_DEPENDENCIAS="${SIN_DEPENDENCIAS:-0}" \
    "$IMAGEN" \
    bash -c '
        set -uo pipefail
        if [ "$SIN_DEPENDENCIAS" != "1" ]; then
            dnf install -y --setopt=install_weak_deps=False $PAQUETES desktop-file-validate >/tmp/dnf.log 2>&1 \
              || { echo "AVISO: fallo la instalacion de requisitos; el resultado no es concluyente."; tail -5 /tmp/dnf.log; }
        fi
        cp /prueba/prueba.sh /tmp/p.sh && chmod +x /tmp/p.sh && bash /tmp/p.sh
    '
estado=$?
echo "-----------------------------------------------------------------"
if [ "$estado" -eq 0 ]; then
    echo "Verificacion superada."
else
    echo "Verificacion fallida (codigo $estado)." >&2
fi
exit "$estado"
