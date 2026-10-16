#!/usr/bin/env bash
# =============================================================================
# DML-FINANCE - Verificacion del .app de macOS antes de distribuirlo
#
# Comprueba las cosas que SOLO se pueden comprobar en una Mac: estructura del
# bundle, Info.plist, arquitectura real del binario, firma de codigo, Gatekeeper
# y el autotest con HOME limpio.
#
# Uso
# ---
#     tests/verificar_mac.sh                          # usa dist/DML-FINANCE.app
#     tests/verificar_mac.sh /ruta/DML-FINANCE.app
#     tests/verificar_mac.sh --sin-autotest           # solo estructura y firma
#
# Requiere macOS. En Linux solo comprueba el .icns y avisa de que el resto no
# aplica (asi el script es util tambien desde el equipo de desarrollo).
# =============================================================================

set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${1:-$RAIZ/dist/DML-FINANCE.app}"
AUTOTEST=1
[ "${1:-}" = "--sin-autotest" ] && { APP="$RAIZ/dist/DML-FINANCE.app"; AUTOTEST=0; }

FALLOS=0
OK="[OK]"
MAL="[FALLO]"

informe() { printf '%-52s %s\n' "$1" "$2"; }
fallo()   { informe "$1" "$MAL"; FALLOS=$((FALLOS+1)); }

echo "DML-FINANCE - verificacion del .app de macOS"
echo "============================================="
echo "Aplicacion: $APP"
echo

# ---------------------------------------------------------------------------
# 0) El icono .icns se puede comprobar en cualquier sistema
# ---------------------------------------------------------------------------
if [ -f "$RAIZ/recursos/icono.icns" ]; then
    if command -v python3 >/dev/null 2>&1; then
        if python3 "$RAIZ/generar_icns.py" --verificar >/dev/null 2>&1; then
            informe "Icono .icns valido" "$OK"
        else
            fallo "Icono .icns valido"
        fi
    else
        informe "Icono .icns valido" "(sin python3 para comprobarlo)"
    fi
else
    fallo "Existe recursos/icono.icns"
fi

# ---------------------------------------------------------------------------
# A partir de aqui hace falta macOS
# ---------------------------------------------------------------------------
if [ "$(uname -s)" != "Darwin" ]; then
    echo
    echo "Este equipo no es macOS ($(uname -s))."
    echo "La estructura del .app, la firma y el autotest SOLO se pueden comprobar"
    echo "en una Mac. Ejecuta este script alli:"
    echo "    tests/verificar_mac.sh"
    echo
    [ "$FALLOS" -eq 0 ] && echo "Comprobaciones posibles: OK" || echo "Comprobaciones posibles: $FALLOS fallo(s)"
    exit "$FALLOS"
fi

echo "macOS $(sw_vers -productVersion) · $(uname -m)"
echo

if [ ! -d "$APP" ]; then
    echo "No existe $APP. Genera antes el bundle con:" >&2
    echo "    python empaquetar_mac.py" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# 1) Estructura del bundle
# ---------------------------------------------------------------------------
EJECUTABLE="$APP/Contents/MacOS/DML-FINANCE"
PLIST="$APP/Contents/Info.plist"

[ -f "$PLIST" ]        && informe "Existe Contents/Info.plist" "$OK"        || fallo "Existe Contents/Info.plist"
[ -x "$EJECUTABLE" ]   && informe "Existe Contents/MacOS/DML-FINANCE" "$OK" || fallo "Existe Contents/MacOS/DML-FINANCE"
[ -f "$APP/Contents/Resources/icono.icns" ] \
    && informe "Icono dentro del bundle" "$OK" \
    || informe "Icono dentro del bundle" "(no encontrado; el .app usara el generico)"

# ---------------------------------------------------------------------------
# 2) Info.plist (las claves que de verdad afectan al funcionamiento)
# ---------------------------------------------------------------------------
leer_plist() { /usr/libexec/PlistBuddy -c "Print :$1" "$PLIST" 2>/dev/null; }

NS_PRINCIPAL="$(leer_plist NSPrincipalClass)"
[ "$NS_PRINCIPAL" = "NSApplication" ] \
    && informe "NSPrincipalClass = NSApplication" "$OK (Retina)" \
    || fallo "NSPrincipalClass = NSApplication (esta: '${NS_PRINCIPAL:-vacio}')"

RETINA="$(leer_plist NSHighResolutionCapable)"
[ "$RETINA" = "true" ] && informe "NSHighResolutionCapable" "$OK" || fallo "NSHighResolutionCapable"

IDENT="$(leer_plist CFBundleIdentifier)"
[ -n "$IDENT" ] && informe "CFBundleIdentifier ($IDENT)" "$OK" || fallo "CFBundleIdentifier"

MINIMO="$(leer_plist LSMinimumSystemVersion)"
[ -n "$MINIMO" ] && informe "LSMinimumSystemVersion ($MINIMO)" "$OK" || informe "LSMinimumSystemVersion" "(no declarado)"

CATEGORIA="$(leer_plist LSApplicationCategoryType)"
[ -n "$CATEGORIA" ] && informe "Categoria ($CATEGORIA)" "$OK" || informe "Categoria" "(no declarada)"

VER_PLIST="$(leer_plist CFBundleShortVersionString)"
[ -n "$VER_PLIST" ] && informe "Version ($VER_PLIST)" "$OK" || informe "Version" "(no declarada)"

# El plist debe ser XML valido (plutil -lint lo verifica).
if plutil -lint "$PLIST" >/dev/null 2>&1; then
    informe "Info.plist es XML valido" "$OK"
else
    fallo "Info.plist es XML valido"
fi

# ---------------------------------------------------------------------------
# 3) Arquitectura real del binario
# ---------------------------------------------------------------------------
if command -v lipo >/dev/null 2>&1; then
    ARCHS="$(lipo -archs "$EJECUTABLE" 2>/dev/null)"
    case "$ARCHS" in
        *arm64*) informe "Arquitecturas del binario ($ARCHS)" "$OK" ;;
        *)       fallo "Arquitecturas del binario ($ARCHS): no incluye arm64" ;;
    esac
    if [ "$(uname -m)" = "arm64" ] && [ "${ARCHS#*arm64}" != "$ARCHS" ]; then
        informe "Compatible con este Mac (Apple Silicon)" "$OK"
    fi
    # Los modulos de Qt tambien deben ser arm64; se muestrea el mas importante.
    QT_CORE="$(find "$APP/Contents/Frameworks/Qt/lib" -name "QtCore" -type f 2>/dev/null | head -1)"
    if [ -n "$QT_CORE" ]; then
        QT_ARCHS="$(lipo -archs "$QT_CORE" 2>/dev/null)"
        case "$QT_ARCHS" in
            *arm64*) informe "QtCore es arm64 ($QT_ARCHS)" "$OK" ;;
            *)       fallo "QtCore no es arm64 ($QT_ARCHS)" ;;
        esac
    fi
else
    informe "Arquitectura del binario" "(sin lipo)"
fi

# ---------------------------------------------------------------------------
# 4) Firma de codigo
# ---------------------------------------------------------------------------
if command -v codesign >/dev/null 2>&1; then
    if codesign --verify --deep --strict "$APP" >/dev/null 2>&1; then
        informe "Firma valida (codesign --verify)" "$OK"
        DETALLE="$(codesign -dv "$APP" 2>&1 | grep -E 'Signature|Identifier|TeamIdentifier' | head -3)"
        [ -n "$DETALLE" ] && echo "$DETALLE" | sed 's/^/    /'
    else
        fallo "Firma valida (codesign --verify)"
        codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -5 | sed 's/^/    /'
    fi
    # Un .app firmado ad-hoc no tiene equipo: es lo esperado aqui.
    if codesign -dv "$APP" 2>&1 | grep -q "Signature=adhoc"; then
        informe "Tipo de firma" "ad-hoc (esperado sin cuenta de Apple)"
    fi
else
    informe "Firma de codigo" "(sin codesign; instala: xcode-select --install)"
fi

# Gatekeeper: se informa de lo que vera el receptor, no es un fallo del build.
if command -v spctl >/dev/null 2>&1; then
    if spctl -a -vvv -t exec "$APP" >/dev/null 2>&1; then
        informe "Gatekeeper (spctl)" "$OK (aceptado)"
    else
        informe "Gatekeeper (spctl)" "rechazado: normal sin notarizar"
        echo "    El receptor debe usar clic derecho -> Abrir la primera vez."
        echo "    Para que se abra sin avisos hay que notarizar (ver INSTALACION-MAC.md)."
    fi
fi

# ---------------------------------------------------------------------------
# 5) Autotest con HOME limpio (como un usuario nuevo)
# ---------------------------------------------------------------------------
# Se distinguen TRES cosas, que antes se confundian en un unico mensaje:
#   a) el ejecutable no arranca (codigo 126/127 o senal),
#   b) arranca y la autoprueba informa de fallos (codigo 1 + informe),
#   c) todo bien.
# En los dos primeros casos se vuelca el INFORME, que es donde esta la causa:
# la autoprueba escribe que dependencia falta, y sin el informe solo se sabe que
# "algo fallo".
if [ "$AUTOTEST" = "1" ]; then
    HOME_PRUEBA="$(mktemp -d)"
    INFORME="$HOME_PRUEBA/autotest.txt"
    SALIDA="$HOME_PRUEBA/salida.txt"
    # Se entra en la carpeta del bundle (donde vive config.yaml) para reproducir
    # el arranque real. Si no se puede, se aborta en vez de ejecutar desde un
    # directorio que no es el de la aplicacion, que daria un resultado enganoso.
    ( cd "$APP/Contents/Frameworks" 2>/dev/null \
        || cd "$APP/Contents/MacOS" 2>/dev/null \
        || { echo "No se pudo entrar en el bundle"; exit 125; }
      HOME="$HOME_PRUEBA" QT_QPA_PLATFORM=offscreen "$EJECUTABLE" --autotest \
          --autotest-salida "$INFORME" >"$SALIDA" 2>&1 )
    CODIGO=$?

    if grep -q "RESULTADO: OK" "$INFORME" 2>/dev/null; then
        informe "Autotest con HOME limpio" "$OK"
        grep -E "PySide6|numpy|pandas|ventana|excel" "$INFORME" | sed 's/^/    /'
    elif [ -f "$INFORME" ]; then
        # El ejecutable arranco y dejo informe: la autoprueba encontro fallos.
        fallo "Autotest con HOME limpio (codigo $CODIGO)"
        echo "    La aplicacion arranco y dejo informe, pero la autoprueba fallo."
        echo "    --- informe completo ---"
        sed 's/^/    /' "$INFORME"
    else
        # No hay informe: el ejecutable no llego a ejecutar la autoprueba.
        fallo "Autotest con HOME limpio (codigo $CODIGO, sin informe)"
        echo "    El ejecutable no llego a generar el informe. Salida:"
        tail -25 "$SALIDA" 2>/dev/null | sed 's/^/    /'
        echo "    Trazas: $HOME_PRUEBA/.dml_finance/dml-finance.log"
    fi

    # Las trazas de la aplicacion, si las hubo: suelen decir la causa exacta.
    for registro in "$HOME_PRUEBA/.dml_finance/dml-finance.log" \
                    "$HOME_PRUEBA/Library/Application Support/DML-FINANCE/dml-finance.log"; do
        [ -f "$registro" ] || continue
        echo "    --- ultimas lineas de $registro ---"
        tail -20 "$registro" | sed 's/^/    /'
    done
    rm -rf "$HOME_PRUEBA"
fi

# ---------------------------------------------------------------------------
# 6) Arranque grafico real (lo que un contenedor nunca puede probar)
# ---------------------------------------------------------------------------
if [ "${DML_SIN_GUI:-0}" != "1" ]; then
    echo
    read -r -p "¿Abrir la aplicacion ahora para comprobar la ventana? [s/N] " RESPUESTA
    if [ "$RESPUESTA" = "s" ] || [ "$RESPUESTA" = "S" ]; then
        open "$APP" && echo "    Abierta. Comprueba: la ventana se dibuja nitida, el icono"
        echo "    del Dock es el logo, y 'Exportar a Excel' (Cmd+E) genera 11 hojas."
    fi
fi

# ---------------------------------------------------------------------------
echo
if [ "$FALLOS" -eq 0 ]; then
    echo "RESULTADO: OK - el .app esta correctamente construido"
else
    echo "RESULTADO: $FALLOS comprobacion(es) fallida(s)"
fi
exit "$FALLOS"
