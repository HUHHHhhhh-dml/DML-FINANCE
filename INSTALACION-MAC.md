# DML-FINANCE en macOS — empaquetado y distribución

Guía de la versión **macOS** del empaquetado. Es **independiente** de
[INSTALACION-FEDORA.md](INSTALACION-FEDORA.md): no la sustituye ni la modifica.
Windows sigue usando `empaquetar.py` con su `.exe`, Linux/Fedora usa
`empaquetar.py` con `.tar.gz` y `.rpm`, y macOS usa **`empaquetar_mac.py`** con
`.app`. Cada plataforma tiene su receta y su flujo, a propósito.

---

## 0. Aviso honesto: qué está verificado y qué no

Este empaquetado se escribió en un equipo **Fedora Linux**. Eso significa:

**Verificado aquí (ejecutado de verdad):**

- El `.icns` se genera y su estructura se valida bloque a bloque: 8 tipos
  (`ic07`–`ic14`), cada PNG con el tamaño correcto, releído por Pillow.
- La receta `DML-FINANCE-mac.spec` es sintácticamente válida y **aborta con un
  mensaje claro** si se ejecuta fuera de macOS.
- La lógica de rutas del bundle, las sustituciones de opciones, la detección de
  binarios Mach-O y los derechos de firma (parseados como `plist` real).
- Que **Fedora y Windows siguen intactos**: 341 tests pasan y `dist/` conserva
  sus tres artefactos.

**NO verificado (necesita una Mac, y no tengo ninguna):**

- Que PyInstaller construya el `.app` sin fallos.
- Que la firma ad-hoc verifique (`codesign --verify`).
- Que la ventana se dibuje y que la app arranque de verdad.
- Los tamaños finales del `.app`, `.dmg` y `.zip`.

Los pasos 5 y 6 del checklist están pensados exactamente para cerrar ese hueco en
tu Mac. Nada de lo que sigue está inventado, pero **la primera compilación hay que
correrla allí**.

---

## 1. Comparativa de herramientas para macOS

Requisitos reales: PySide6 6.12 (Qt 6), pila científica (`numpy`, `pandas`,
`scipy`, `statsmodels`), `matplotlib` embebido, y salida en `.xlsx`.

| Criterio | **PyInstaller 6.22** | py2app | Briefcase | Nuitka |
|---|---|---|---|---|
| Salida nativa | **`.app`** (vía `BUNDLE`) | `.app` | `.app` + `.dmg` | `.app` (con `--macos-create-app-bundle`) |
| Soporte PySide6/Qt | Excelente (hooks oficiales, ver [Qt for Python](https://doc.qt.io/qtforpython-6/deployment/deployment-pyinstaller.html)) | Bueno, con *recipes* por paquete | Bueno | Bueno, pero compila todo a C |
| `Info.plist` | `info_plist={...}` en el spec | `setup.py` | `pyproject.toml` | Limitado |
| Universal2 (Intel+ARM) | Sí, si el Python es universal2 | Sí | Sí | Sí |
| Firma y notarización | `codesign` + `notarytool` aparte | `codesign` aparte | Integrado | `codesign` aparte |
| `.dmg` | No; se hace con `hdiutil` (implementado) | No | Sí | No |
| Reutiliza tu receta | **Sí** (misma estructura, más `BUNDLE`) | No, hay que reescribirla | No | No |
| Madurez en Qt | La mejor documentada | Menor | Media | Media |
| Curva de aprendizaje | **Nula** (ya la usabas) | Media | Media | Alta |

### Recomendación: **PyInstaller con `BUNDLE` (implementado)**

1. **Coherencia con lo que ya funciona.** Windows y Fedora usan PyInstaller y
   están probados. Añadir una tercera herramienta multiplica los sitios donde
   buscar fallos.
2. **Qt + PyInstaller es la combinación mejor documentada**, y este proyecto es
   Qt de arriba abajo.
3. **py2app exigiría reescribir la receta entera** y su manejo de Qt es menos
   predecible; no compensa por un solo destino.
4. El `.dmg` no lo da ninguna de las dos: se resuelve con `hdiutil`, que viene con
   macOS, y así no hay dependencias de terceros.

### Una decisión que quizá quieras revisar: **arm64 solamente**

Se ha configurado para **Apple Silicon**. Un `.app` que solo trae arm64 **no
arranca en Mac con Intel**. Es la elección correcta si tus destinatarios tienen
Mac de 2020 en adelante (y el soporte de Intel en macOS termina con Tahoe 26).

Si necesitas ambos, `--universal` está implementado, pero **requiere un Python
universal2**: el de Homebrew es de una sola arquitectura y `target_arch` no
servirá. La forma fiable es compilar con el Python oficial de
[python.org](https://www.python.org/downloads/macos/) (que es universal2) o con
conda. Si además quieres reducir tamaño, `lipo` puede adelgazar los frameworks de
Qt, que es donde está el grueso.

---

## 2. La diferencia que manda en macOS: el modelo de confianza

Esto es lo que hay que entender antes de prometer nada, y es **lo que hace que
macOS no se parezca ni a Windows ni a Fedora**.

Windows avisa con SmartScreen y se salta con "Ejecutar de todas formas". Fedora
no pone ninguna barrera. **macOS es el más estricto de los tres**: el sistema
exige que el código esté firmado y, si la app llegó por Internet, además
*notarizado* por Apple. Sin eso, macOS **se niega a abrirla** con un mensaje que
además es engañoso ("está dañada" o "desarrollador no identificado").

Los tres niveles son:

| Nivel | Qué es | Coste | Qué ve el receptor |
|---|---|---|---|
| **Sin firma** | Nada | 0 | No abre con doble clic; hay que forzarlo |
| **Firma ad-hoc** (`-`) | Firma local, sin identidad | **0** | Aviso la 1ª vez; se abre con clic derecho → Abrir |
| **Developer ID + notarización** | Apple valida la app | 99 USD/año | **Abre sin ningún aviso** |

**Lo implementado por defecto es la firma ad-hoc.** Es gratis, no requiere cuenta
de Apple y sobrevive a que el usuario mueva la app de sitio. Pero conviene tener
claro que:

- Ad-hoc **no** sustituye a la notarización: el receptor verá un aviso la primera
  vez.
- Con firma ad-hoc, **el hardened runtime se deja desactivado a propósito**.
  Activarlo restringe la carga de bibliotecas y hay casos documentados en los que
  la app deja de arrancar (por ejemplo, con `disable-library-validation`). Solo es
  obligatorio para notarizar, así que se activa con `--runtime` cuando toque.
- El flujo real de firma+notarización está en la sección 6.

**Por qué se firman los binarios uno a uno y no con `--deep`:** `codesign --deep`
está obsoleto para firmar y da resultados poco fiables con bundles que tienen
cientos de `.so` dentro (justo el caso de PyInstaller). `empaquetar_mac.py` firma
cada Mach-O de dentro hacia fuera y el bundle al final, que es el procedimiento
correcto.

---

## 3. Qué se añadió para macOS (sin tocar lo demás)

| Archivo | Qué es |
|---|---|
| `empaquetar_mac.py` | **Nuevo.** El empaquetador: `.app`, firma ad-hoc, `.dmg`, `.zip`, instalar/desinstalar. |
| `DML-FINANCE-mac.spec` | **Nuevo.** Receta de PyInstaller para macOS (con `BUNDLE` e `Info.plist`). No sustituye a `DML-FINANCE.spec`. |
| `generar_icns.py` | **Nuevo.** Genera `recursos/icono.icns`. Usa `iconutil` en la Mac y, si no está, un escritor ICNS propio (así se pudo validar en Linux). |
| `tests/verificar_mac.sh` | **Nuevo.** Verificación del `.app` en la Mac. |
| `recursos/icono.icns` | Generado (192 KB, 8 resoluciones). |
| `dml/core/config.py` | **Cambio aditivo y solo-macOS**: se añade `~/Library/Application Support/DML-FINANCE` como candidato de datos. En Fedora y Windows la lista no cambia. |

**Nada de lo anterior reemplaza al empaquetado de Windows ni de Fedora.** Los
archivos `empaquetar.py` y `DML-FINANCE.spec` siguen siendo los mismos.

### Estructura de un `.app` y por qué el `config.yaml` importa

```
DML-FINANCE.app/
└── Contents/
    ├── Info.plist          <- el "DNI" de la app ante macOS
    ├── MacOS/DML-FINANCE   <- punto de entrada (lo que se ejecuta)
    ├── Frameworks/         <- Python, Qt y _internal (el equivalente a _internal/)
    └── Resources/icono.icns
```

Un `.app` es una carpeta, y macOS la trata como un archivo. Eso tiene una
consecuencia práctica: **si el usuario mueve la app a `/Applications`, el
`config.yaml` de dentro ya no es editable** (esa carpeta requiere permisos de
administrador). Por eso la aplicación busca sus datos en `~/.dml_finance` (y, como
respaldo, en `~/Library/Application Support/DML-FINANCE`), que sí es del usuario.
El `config.yaml` sigue viajando dentro para que la app arranque con los valores
correctos; si quieres cambiarlos, usa `~/.dml_finance` o edita el de dentro antes
de copiar la app.

### Claves del `Info.plist` y por qué están

| Clave | Por qué |
|---|---|
| `NSPrincipalClass = NSApplication` | **Sin esto la ventana se dibuja pixelada en pantallas Retina.** Es el fallo clásico de empaquetar Qt en Mac. |
| `NSHighResolutionCapable = true` | Activa el renderizado a resolución nativa. |
| `LSMinimumSystemVersion = 14.0` | **Lo impone PySide6 6.12**, cuya rueda es `macosx_14_0`: en macOS 12 o 13 Qt ni siquiera se instala. Declararlo evita un fallo opaco al cargar Qt. |
| `LSApplicationCategoryType` | Coloca la app en la categoría correcta de Launchpad y Finder. |
| `CFBundleIdentifier` | Identidad de la app (`com.dmlfinance.analizador`). |

### Requisito de versión de macOS (importante)

**La aplicación necesita macOS 14 (Sonoma) o superior**, y no es una decisión
libre: la impone PySide6. Cada versión de Qt sube su versión mínima, y se puede
comprobar en las etiquetas de sus ruedas en PyPI:

| PySide6 | Etiqueta de la rueda | macOS mínimo |
|---|---|---|
| 6.6 / 6.7 | `macosx_11_0_universal2` | 11 |
| 6.8 / 6.9 | `macosx_12_0_universal2` | 12 |
| 6.10 | `macosx_13_0_universal2` | 13 |
| **6.12** (la que usa el proyecto) | `macosx_14_0_universal2` | **14** |

Si necesitas dar soporte a macOS 12 o 13, **hay que bajar la versión de PySide6**
(no basta con cambiar `LSMinimumSystemVersion`, que solo describe el bundle).
Con `PySide6==6.10.*` el mínimo pasa a macOS 13 y con `6.8.*` a macOS 12; el
código de la interfaz no debería necesitar cambios, pero **eso hay que probarlo**.

---

## 4. Construir el `.app` (en la Mac)

### 4.0 La vía sin Mac propio: compilarlo en GitHub Actions

Si no quieres preparar el entorno en un Mac, el repositorio incluye un flujo que
lo hace en la nube. Los runners de macOS son **gratis para repositorios
públicos**, y este lo es.

1. Entra en la pestaña **Actions** del repositorio.
2. Elige **"macOS (.app + .dmg + .zip)"** en la lista de la izquierda.
3. Pulsa **Run workflow**.
4. Opcional: escribe la etiqueta (`v1.0.0`) y marca **publicar_en_release** para
   que adjunte el `.dmg` y el `.zip` a esa release automáticamente.
5. En unos minutos tendrás el `.dmg` y el `.zip` como artefactos descargables de
   la ejecución.

Con la opción 4 **no hace falta descargar ni subir nada a mano**: los archivos
aparecen en la release. El flujo también ejecuta la autoprueba y
`tests/verificar_mac.sh`, así que si algo falla lo verás en el registro.

### 4.1 Preparar la Mac (una sola vez)

```bash
# 1) Herramientas de linea de comandos de Xcode (dan codesign, hdiutil, lipo...)
xcode-select --install

# 2) Python 3.10+ (el de Homebrew o el de python.org)
python3 --version

# 3) Entorno del proyecto
cd ~/ruta/al/proyecto
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt pyinstaller
```

Comprueba que estás en arm64 si vas a distribuir a Apple Silicon:

```bash
uname -m          # debe decir arm64
python3 -c "import platform; print(platform.machine())"
```

### 4.2 Generar el icono y la aplicación

```bash
source venv/bin/activate

# Icono .icns (se genera solo si falta o si el logo cambio)
python generar_icns.py

# Todo: .app + firma ad-hoc + .dmg + .zip
python empaquetar_mac.py

# O por pasos:
python empaquetar_mac.py --app          # solo el .app, sin paquetes
python empaquetar_mac.py --dmg --zip    # solo los distributibles
python empaquetar_mac.py --limpiar      # borra build/ y dist/ antes
python empaquetar_mac.py --consola      # con terminal, para depurar
```

Salida esperada en `dist/`:

```
dist/
├── DML-FINANCE.app
├── DML-FINANCE-1.0.0-macOS-arm64.dmg
├── DML-FINANCE-1.0.0-macOS-arm64.zip
└── LEEME-EJECUTABLE.txt
```

### 4.3 Opciones disponibles

| Comando | Qué hace |
|---|---|
| `python empaquetar_mac.py` | `.app` + firma ad-hoc + `.dmg` + `.zip` |
| `python empaquetar_mac.py --app` | Solo el `.app` (sin `.dmg` ni `.zip`) |
| `python empaquetar_mac.py --sin-firma` | No firma (macOS lo bloqueará con más insistencia) |
| `python empaquetar_mac.py --identidad "Developer ID Application: ..."` | Firma real para notarizar (ver sección 6) |
| `python empaquetar_mac.py --runtime` | Activa el hardened runtime (solo para notarizar) |
| `python empaquetar_mac.py --universal` | Intenta universal2 (requiere Python universal2) |
| `python empaquetar_mac.py --sin-poda` | No borra los componentes de Qt no usados |
| `python empaquetar_mac.py --instalar` | Copia el `.app` a `/Applications` |
| `python empaquetar_mac.py --desinstalar` | Deshace lo anterior (pregunta antes de borrar tus datos) |
| `pyinstaller --noconfirm DML-FINANCE-mac.spec` | La receta directamente, sin el empaquetador |

---

## 5. Distribuir

### 5.1 El `.dmg` (recomendado para entregar a una persona)

`empaquetar_mac.py` crea el `.dmg` con `hdiutil`, con la app y un enlace a
Aplicaciones para poder **arrastrar y soltar**. Es el gesto que espera cualquier
usuario de Mac.

```bash
hdiutil attach dist/DML-FINANCE-1.0.0-macOS-arm64.dmg   # para inspeccionarlo
```

### 5.2 El `.zip`

Se usa `ditto -c -k --sequesterRsrc --keepParent`, que es la forma correcta de
comprimir un `.app`: conserva la estructura, los enlaces y el bit de ejecución.
**Un `zipfile` de Python no sirve para distribuir un `.app`** (el bundle quedaría
sin permiso de ejecución interno y la app no arrancaría). El `.zip` va bien para
adjuntar por correo o subir a un servicio.

### 5.3 Verificar el paquete antes de entregarlo

```bash
tests/verificar_mac.sh
tests/verificar_mac.sh dist/DML-FINANCE.app
DML_SIN_GUI=1 tests/verificar_mac.sh      # sin la pregunta de abrir la app
```

El script comprueba: estructura del bundle, las claves del `Info.plist`,
`plutil -lint`, la arquitectura real con `lipo` (incluido `QtCore`), la firma con
`codesign --verify`, lo que dirá Gatekeeper (`spctl`) y el autotest con un `HOME`
limpio. Termina con `RESULTADO: OK` si todo está bien.

### 5.4 Probar en una Mac limpia

Lo que de verdad reproduce la experiencia del receptor:

1. **Otra cuenta de usuario** (`Ajustes del Sistema → Usuarios`), sin
   `~/.dml_finance` previo, y ejecuta el `.dmg` desde ahí.
2. **Una máquina virtual** con macOS (UTM, Parallels o VMware Fusion) sin Python
   ni dependencias, descargando el `.dmg` desde un navegador para que se le ponga
   el atributo de cuarentena real.
3. **El peor caso, que es el útil:** copia el `.dmg` por AirDrop o descárgalo, y
   comprueba que aparece el aviso de Gatekeeper y que se resuelve con clic derecho
   → Abrir. Si esto funciona, funciona en cualquier Mac.

---

## 6. Firma real y notarización (opcional, de pago)

Esto es lo único que elimina el aviso de Gatekeeper. Requiere una cuenta de Apple
Developer (99 USD/año).

```bash
# 1) Firmar con tu certificado Developer ID
python empaquetar_mac.py --identidad "Developer ID Application: TU NOMBRE (TEAMID)" --runtime

# 2) Comprimir para notarizar (notarytool exige un zip o un dmg)
ditto -c -k --keepParent dist/DML-FINANCE.app dist/DML-FINANCE-notarizar.zip

# 3) Guardar las credenciales una sola vez
xcrun notarytool store-credentials "dml-finance" \
    --apple-id "tu@apple.id" --team-id "TEAMID" --password "contrasena-de-app"

# 4) Notarizar y esperar el resultado
xcrun notarytool submit dist/DML-FINANCE-notarizar.zip \
    --keychain-profile "dml-finance" --wait

# 5) Engrapar el ticket a la app (para que funcione sin conexion)
xcrun stapler staple dist/DML-FINANCE.app
xcrun stapler validate dist/DML-FINANCE.app

# 6) Volver a crear el .dmg con la app ya notarizada
python empaquetar_mac.py --dmg
```

Con esto, `spctl -a -vvv -t exec dist/DML-FINANCE.app` dirá `accepted` y la app
abrirá con doble clic en cualquier Mac.

---

## 7. Checklist de verificación antes de distribuir

### Fase 1 — En la Mac, preparación

- [ ] **1.** `xcode-select -p` devuelve una ruta (herramientas instaladas).
- [ ] **2.** `uname -m` dice `arm64` si el destino es Apple Silicon.
- [ ] **3.** `python3 -c "import PySide6, yfinance; print('ok')"` funciona en el venv.

### Fase 2 — Icono (verificable en cualquier sistema)

- [ ] **4.** `python generar_icns.py`
      → `ICNS: ... (192 KB)` y `[OK] estructura valida`, con los 8 bloques.
- [ ] **5.** Abre `recursos/icono.icns` con Vista Previa (en la Mac) → se ve el logo.

### Fase 3 — Construcción

- [ ] **6.** `python empaquetar_mac.py`
      → termina con `Aplicacion generada:` y `Aplicacion generada: ... MB`.
- [ ] **7.** El informe dice `Arquitectura arm64 (Apple Silicon): correcto`.
- [ ] **8.** La poda reporta MB liberados (indica que Qt se limpió).
- [ ] **9.** La firma dice `Verificacion de la firma: [OK]`.
      → Si dice `[FALLO]`, mira la sección 8.

### Fase 4 — Verificación automática

- [ ] **10.** `tests/verificar_mac.sh`
      → `RESULTADO: OK - el .app esta correctamente construido`.
- [ ] **11.** `codesign -dv dist/DML-FINANCE.app` muestra `Signature=adhoc`.
- [ ] **12.** `lipo -archs dist/DML-FINANCE.app/Contents/MacOS/DML-FINANCE` dice `arm64`.

### Fase 5 — Prueba funcional (imprescindible)

- [ ] **13.** `QT_QPA_PLATFORM=offscreen dist/DML-FINANCE.app/Contents/MacOS/DML-FINANCE --autotest`
      → **`RESULTADO: OK`**: 11 pestañas, 12 criterios, 11 hojas de Excel.
- [ ] **14.** Doble clic en el `.app` → **la ventana abre nítida** (si se ve
      pixelada, falta `NSPrincipalClass`: revisa el paso 10).
- [ ] **15.** El icono del Dock y del conmutador de ventanas es el logo.
- [ ] **16.** Analiza un ticker real con Internet (`NVDA`) y exporta con **Cmd+E**.
      → Se genera un `.xlsx` de 11 hojas.
      *Este paso es el único que valida `cloudscraper`, `certifi` y `curl_cffi`
      contra la red real; el autotest usa datos DEMO.*
- [ ] **17.** Abre una pestaña con gráficos (Econométrico o Griegas) → matplotlib
      dibuja sin fallos de fuentes.
- [ ] **18.** Cierra la app y comprueba que existe `~/.dml_finance/dml-finance.log`.

### Fase 6 — Prueba como receptor (la que más falla)

- [ ] **19.** Copia el `.dmg` a otra cuenta de usuario o a una VM y ábrelo.
- [ ] **20.** Aparece el aviso de Gatekeeper → se resuelve con **clic derecho →
      Abrir → Abrir**. Si no se resuelve, prueba:
      `xattr -dr com.apple.quarantine /Applications/DML-FINANCE.app`
- [ ] **21.** Arrastra la app a Aplicaciones desde el `.dmg` y ábrela desde ahí.
- [ ] **22.** Sin conexión a Internet, la app abre igual (solo fallarán los análisis).

### Fase 7 — Entrega

- [ ] **23.** `shasum -a 256 dist/DML-FINANCE-*.dmg` y entrega el hash.
- [ ] **24.** Comprueba que el `.app` no lleva tus datos:
      `find dist/DML-FINANCE.app -name ".dml_cache" -o -name "dml-finance.log"`
      → sin resultados.
- [ ] **25.** Comprueba que sí lleva lo crítico:
      ```bash
      find dist/DML-FINANCE.app -name "cacert.pem" -o -name "browsers.json" -o -name "config.yaml"
      ```
      → los tres aparecen. Sin `cacert.pem` falla todo el HTTPS.

---

## 8. Problemas conocidos y soluciones

| Síntoma | Causa | Solución |
|---|---|---|
| "La app está dañada y no se puede abrir" | Cuarentena de macOS sobre una app no notarizada | `xattr -dr com.apple.quarantine /Applications/DML-FINANCE.app` |
| "Desarrollador no identificado" | Firma ad-hoc, sin notarizar | Clic derecho → Abrir (una vez), o notarizar (sección 6) |
| La ventana se ve pixelada/borrosa | Falta `NSPrincipalClass = NSApplication` | Revisa el spec; el paso 10 del checklist lo detecta |
| `PermissionError` al arrancar | La app intenta escribir junto al ejecutable (en `/Applications` no puede) | La app ya usa `~/.dml_finance`; comprueba que existe y es escribible |
| `codesign failed: resource fork, Finder information, or similar detritus not allowed` | Basura de Finder en el bundle | `xattr -cr dist/DML-FINANCE.app` y vuelve a firmar |
| `library not loaded: @rpath/...` | Framework de Qt mal enlazado | Recompila desde cero (`--limpiar`); PyInstaller debe encontrar Qt completo |
| Falla al cargar un `.so` de Qt tras la firma | Un binario quedó sin firmar | Revisa el informe de firma; usa `--sin-poda` para descartar que la poda rompió algo |
| `The application cannot be opened for an unexpected reason` | Cuarentena + firma inválida | `codesign --verify --deep --strict --verbose=2` para ver el detalle |
| En Intel no arranca | Se compiló solo arm64 | Compila en un Mac Intel o usa `--universal` con Python universal2 |
| `target_arch` no hace nada | El Python no es universal2 (p. ej. Homebrew) | Usa el Python de python.org o conda |

---

## 9. Desinstalar

```bash
python empaquetar_mac.py --desinstalar
```

Borra el `.app` **solo si lo instaló este script** (lo comprueba contra el
registro que deja `--instalar` en `~/.dml_finance/instalado.json`), así que no
puede llevarse por delante otra cosa. Después **pregunta** antes de borrar tus
datos: la caché y las preferencias se conservan salvo que lo confirmes.

A mano: arrastra `DML-FINANCE.app` a la Papelera y, si quieres, borra
`~/.dml_finance`.

---

## 10. Referencia rápida

```bash
# Construir todo (en la Mac)
source venv/bin/activate
python empaquetar_mac.py

# Verificar
python generar_icns.py --verificar
tests/verificar_mac.sh

# Instalar / desinstalar
python empaquetar_mac.py --instalar
python empaquetar_mac.py --desinstalar

# Receta directa
pyinstaller --noconfirm DML-FINANCE-mac.spec

# Si algo va mal, el registro de trazas esta en:
~/.dml_finance/dml-finance.log                  # lo habitual
~/Library/Application Support/DML-FINANCE/      # solo si ~/.dml_finance no es escribible
```
