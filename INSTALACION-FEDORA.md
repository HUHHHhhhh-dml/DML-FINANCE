# DML-FINANCE en Fedora — empaquetado y distribución

Guía de la migración de Windows a **Fedora 44** (`x86_64`, Python 3.14).
Cubre la comparativa de herramientas, los cambios ya aplicados, cómo construir el
paquete, cómo distribuirlo y cómo verificarlo antes de entregarlo.

Todo lo que aparece aquí **está construido y probado** en este equipo: el
`.tar.gz` y el `.rpm` que genera `empaquetar.py` pasaron el autotest en un
contenedor Fedora 44 limpio, sin Python del sistema.

---

## 1. Comparativa de herramientas de empaquetado

Requisitos reales del proyecto, que son los que deciden la elección:

- Interfaz **PySide6 6.12** (Qt 6), con `matplotlib` embebido.
- Pila científica pesada: `numpy`, `pandas`, `scipy`, `statsmodels`.
- HTTP y scraping: `yfinance`, `requests`, `cloudscraper`, `curl_cffi`.
- Escritura de `.xlsx` con `openpyxl`.
- **Un solo destino**: Fedora 44 x86_64. No hay que cubrir macOS ni Windows en Linux.

| Criterio | **PyInstaller 6.22** | Nuitka 2.x | Briefcase | cx_Freeze |
|---|---|---|---|---|
| Enfoque | Congela bytecode + empaqueta binarios | **Compila a C** y luego enlaza | Empaquetador multiplataforma (proyecto *briefcase*) | Congela como PyInstaller |
| Soporte PySide6 | Excelente (hooks oficiales) | Bueno, con más ajustes | Bueno | Bueno |
| Pila `scipy`/`pandas` | Resuelta por hooks | Resuelve, pero compila mucho | Resuelve | Resuelve |
| Tiempo de build | **~1 min** (medido aquí) | 10-40 min (compila todo a C) | Minutos, más andamiaje | Minutos |
| Formato de salida | `onedir` o `onefile` + **`.spec`** | `onedir`/`onefile` | AppImage, `.deb`, `.rpm`, `.msi` | `onedir` |
| Arranque | 1-3 s (`onedir`) | Algo mejor (código nativo) | 1-3 s | 1-3 s |
| Tamaño resultante | ~551 MB (171 MB comprimido, medido) | Algo menor | Similar | Similar |
| `.rpm` | **No lo genera**: se hace con `rpmbuild` (ya implementado) | No | Sí, pero con su propio andamiaje | No |
| Depuración de faltantes | `--autotest` + `ldd` (implementado) | Más difícil (binario C) | Media | Media |
| Riesgo de regresión | **Bajo**: se reutiliza la receta ya probada en Windows | Medio-alto: pocos usuarios con esta combinación | Medio | Medio |
| Curva de aprendizaje | Nula: el proyecto **ya lo usaba** | Alta | Media | Baja |

### Recomendación: **PyInstaller 6.22 (ya implementado)**

Razones concretas, no genéricas:

1. **La receta ya existía y estaba depurada en Windows.** Cambiar de herramienta
   tira ese trabajo y reintroduce los fallos de importaciones ocultas que el
   proyecto ya había resuelto.
2. **Es el único caso con riesgo casi nulo**: se reutiliza `DML-FINANCE.spec`,
   ahora hecho multiplataforma.
3. **El objetivo es un ejecutable + un paquete, no un AppImage ni un `.deb`.** El
   `.rpm` se resuelve con `rpmbuild`, que es la herramienta nativa de Fedora y da
   control total (dependencias, iconos, `.desktop`).
4. **Tiempo de build medido: ~1 minuto.** Nuitka, compilando `numpy`, `scipy` y
   `PySide6` a C, tardaría órdenes de magnitud más en cada iteración.

**Cuándo cambiaría de opinión:** si necesitaras distribuir en varias
distribuciones a la vez (Debian + Fedora + AppImage), Briefcase tendría sentido.
Si el arranque en 1-3 s fuera insuficiente, Nuitka. Ninguno es el caso.

---

## 2. La limitación que define la distribución: glibc

Es el punto más importante de esta guía y el que hay que entender antes de
prometer compatibilidad.

PyInstaller **no empaqueta glibc**: el binario se enlaza dinámicamente contra la
glibc del sistema donde se compila. Y Fedora no mantiene compatibilidad hacia
atrás entre versiones. Medido en el paquete real con `objdump`:

```
glibc de compilacion : 2.43
glibc requerida      : 2.43  ->  Fedora 44 o superior
```

**Consecuencia: el paquete compilado aquí funciona en Fedora 44 y posteriores, y
NO arranca en Fedora 43 o anteriores** (`version 'GLIBC_2.43' not found`).

Curiosidad que conviene conocer, porque el análisis reveló que la restricción no
viene de lo que uno esperaría. De las 1.5 GB analizadas, **solo tres bibliotecas
del sistema** exigen glibc 2.43:

| Biblioteca | Tamaño | La arrastra |
|---|---|---|
| `libglib-2.0.so.0` | 1.4 MB | `libpango`, `libtinysparql` (vía `libgtk-3` de Qt) |
| `libpixman-1.so.0` | 0.7 MB | `libcairo` |
| `liblcms2.so.2` | 0.4 MB | `libglycin-2` |

El propio Python, Qt, `numpy` y `scipy` se conforman con **glibc 2.38** (Fedora
39). Es decir: **2.5 MB de bibliotecas GTK son los que fijan el mínimo en Fedora
44.** Si alguna vez necesitas ampliar la compatibilidad a Fedora 39-43, hay dos
vías, ambas ya exploradas:

- **Compilar en un contenedor `fedora:43`** (o en la Fedora más antigua que
  quieras soportar). Es la forma estándar y la que garantiza el resultado.
- Excluir el *platform theme* de GTK, que es quien trae esos 2.5 MB. No se ha
  hecho porque el ahorro de espacio es irrelevante y porque las versiones de las
  bibliotecas quedarían fijadas a las de esta máquina.

`empaquetar.py` **mide y reporta esto automáticamente** en cada build
(`informar_portabilidad`), así que nunca hay que averiguarlo a mano.

---

## 3. Qué se modificó para Fedora

### 3.1 `DML-FINANCE.spec` (receta de PyInstaller)

Este archivo **faltaba** en el workspace: el `.gitignore` lo excluía con `*.spec`
y nunca se versionó, así que no viajó al copiar el proyecto. Sin él,
`empaquetar.py` abortaba con `FileNotFoundError`. Ya está recuperado.

Cambios aplicados para que la misma receta sirva en Windows y Linux:

| Cambio | Motivo |
|---|---|
| **Icono condicional** (`icon=_ICONO_RUTA`) | Un binario ELF **no lleva iconos embebidos**; en Windows sí. Se resuelve con `sys.platform`. |
| `upx=UPX_DISPONIBLE` | `upx` no está instalado por defecto. Antes se pedía siempre y PyInstaller solo avisaba. |
| **`collect_data_files`** para `certifi`, `cloudscraper`, `curl_cffi` | Sin `certifi/cacert.pem` **falla todo el HTTPS**; sin el JSON de `cloudscraper`, el scraping. |
| `curl_cffi` en `hiddenimports` | Es una extensión binaria (`_wrapper.abi3.so`) que se importa dinámicamente: PyInstaller no la ve y el fallo aparecería **en tiempo de ejecución**, no en el build. |
| `icono.png` en `datas` | La UI (`dml/ui/widgets.py`) ya prueba `.ico` → `.png` → logo, así que en Linux usa el PNG. |
| Comentarios y docstring actualizados | Explican la diferencia Windows/Linux donde importa. |

### 3.2 `empaquetar.py` (orquestador)

Reescrito manteniendo **compatibilidad total con Windows** (la misma orden sigue
generando el `.exe` y el acceso directo) y añadiendo Linux:

| Función nueva | Qué hace |
|---|---|
| Detección de plataforma | `SUFIJO` vacío en Linux, `.exe` en Windows; la salida se adapta. |
| `escribir_lanzador()` | Crea **`DML-FINANCE.sh`**: el equivalente práctico al `.exe` (fija el directorio de trabajo para que lea `config.yaml`). |
| `texto_desktop()` / `escribir_desktop()` | Genera el **`.desktop`** y lo valida contra el estándar freedesktop. |
| `podar_paquete()` | Elimina **48 MB** de Qt que la aplicación no usa (medido). |
| `crear_tar()` | Paquete **`.tar.gz`** portátil. |
| `crear_rpm()` | Genera el `.spec` del RPM y lo construye con `rpmbuild`. |
| `instalar_en_menu()` | Instala el `.desktop` en `~/.local/share/applications` **sin root**. |
| `glibc_requerida()` / `informar_portabilidad()` | Mide el requisito real de glibc del paquete y lo traduce a versión de Fedora. |
| `podar_paquete()`: limpieza de enlaces | PyInstaller deja en `_internal/` enlaces simbólicos a los `.so` de Qt; al podarlos quedaban **8 enlaces rotos**. Se detectó con `shutil.copytree` y ahora se eliminan. |
| `--instalar` antes de comprobar PyInstaller | La opción solo copia el `.desktop` y el icono del paquete ya construido: no usa PyInstaller. Antes fallaba en un equipo sin entorno de compilación. |
| `escribir_desktop_en_paquete()` | El `.desktop` **siempre** se genera dentro del paquete, aunque se use `--sin-acceso` (que ahora solo controla la copia al escritorio del usuario). Antes, `--sin-acceso` dejaba el paquete sin entrada de escritorio, y el receptor no podía integrarlo. |

La compatibilidad con los argumentos de Windows se conserva (`--unico`,
`--limpiar`, `--consola`, `--sin-icono`, `--sin-acceso`, `--escritorio`,
`--completo`), y se añaden `--tar`, `--zip`, `--rpm`, `--instalar`, `--sin-poda`.

### 3.3 `.gitignore`

Se añadió la excepción `!DML-FINANCE.spec` para que la receta **se versione** y no
se vuelva a perder en el próximo transporte. El resto de `.spec` generados
(`build/receta-efectiva.spec`) siguen ignorados porque `build/` ya lo está.

### 3.4 Poda de Qt: por qué 48 MB y no 28

La primera medición dio 28 MB. Al aplicarla en el build real fueron **48 MB**,
porque además de las bibliotecas hay plugins y componentes QML asociados:

| Elemento eliminado | Motivo |
|---|---|
| `libQt6Quick*`, `libQt6Qml*` | La aplicación usa **widgets clásicos**, no QML. No existe ni la carpeta `qml/`. |
| `libQt6Pdf*` | No se abre ni genera PDF. |
| `libQt6VirtualKeyboard*` | No hay teclado en pantalla. |
| 97 de las 99 traducciones de Qt (~6.8 MB) | **Se conservan `qt_es.qm` y `qtbase_es.qm` (0.2 MB)**: sin ellas, los diálogos nativos de Qt ("Abrir", "Guardar", "Cancelar") saldrían en inglés. |

**Todo esto está verificado, no supuesto:** cada build se valida con
`--autotest`, que construye la ventana completa con las 11 pestañas. Si la poda
rompiera algo, el autotest fallaría. Se puede desactivar con `--sin-poda`.

### 3.5 `tests/verificar_contenedor.sh` (nuevo)

Prueba el paquete en un Fedora limpio con `podman`. Es la comprobación que
detecta el clásico "en mi máquina funciona" y el origen de la lista de
dependencias del RPM.

---

## 4. Construir el paquete

### 4.1 Preparar el entorno (una sola vez)

```bash
cd ~/Documents/DML-FINANCE/Proyectos/DML-FINANCE
source venv/bin/activate
pip install pyinstaller          # 6.22.3; ya instalado en este equipo
```

Si hubiera que recrear el entorno desde cero:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt pyinstaller
```

### 4.2 Generar ejecutable, lanzador y `.desktop`

**Un solo comando genera todo lo que hace falta para distribuir** (la secuencia
que se usó para producir los artefactos ya verificados):

```bash
source venv/bin/activate
python empaquetar.py --limpiar --sin-acceso --tar --rpm
```

- `--limpiar` borra `build/` y `dist/` para no arrastrar restos.
- `--sin-acceso` no toca tu escritorio: el `.desktop` se genera **dentro** del
  paquete y además puedes integrarlo luego con `--instalar`.
- `--tar` y `--rpm` producen los dos paquetes distribuibles.

Y las variantes sueltas, por si quieres hacerlo por pasos:

```bash
python empaquetar.py                                  # ejecutable + lanzador + .desktop en el escritorio
python empaquetar.py --tar                            # solo el .tar.gz
python empaquetar.py --rpm                            # solo el .rpm
python empaquetar.py --instalar                       # integra el .desktop en el menu del usuario
```

Salida real de un build en este equipo:

```
Sistema: Linux 7.2.9-201.fc44.x86_64 · Python 3.14.8 · x86_64
Ejecutable generado:
  dist/DML-FINANCE/DML-FINANCE  (27 MB)
  Componentes de Qt no usados eliminados: 48 MB
Lanzador creado:
  dist/DML-FINANCE/DML-FINANCE.sh

Portabilidad (Linux)
------------------------------------------------------------
  glibc de compilacion : 2.43
  glibc requerida      : 2.43  ->  Fedora 44 o superior

tar.gz listo para compartir:
  dist/DML-FINANCE-x86_64.tar.gz  (171 MB)
```

### 4.3 Contenido de `dist/DML-FINANCE/`

```
DML-FINANCE/
├── DML-FINANCE             <- el programa (ELF, 27 MB)
├── DML-FINANCE.sh          <- lanzador: doble clic o ./DML-FINANCE.sh
├── DML-FINANCE.desktop     <- entrada para el menu de aplicaciones
├── DML-FINANCE.png         <- icono de la entrada
├── config.yaml             <- umbrales, editables con cualquier editor
├── LEEME-EJECUTABLE.txt    <- instrucciones para quien lo recibe
└── _internal/              <- Python, Qt y librerias; NO borrar
```

`DML-FINANCE.sh` es el equivalente al `.exe` de Windows: se puede ejecutar con
doble clic desde el gestor de archivos y garantiza el directorio de trabajo
correcto.

### 4.4 Opciones de `dist/` que se generan

| Comando | Producto | Tamaño medido |
|---|---|---|
| `python empaquetar.py` | `dist/DML-FINANCE/` (onedir) | 551 MB sin comprimir |
| `python empaquetar.py --tar` | `dist/DML-FINANCE-x86_64.tar.gz` | **171 MB** |
| `python empaquetar.py --zip` | `dist/DML-FINANCE.zip` | ~171 MB |
| `python empaquetar.py --rpm` | `dist/dml-finance-1.0.0-1.fc44.x86_64.rpm` | **121 MB** |
| `python empaquetar.py --instalar` | entrada en el menú del usuario | — |

---

## 5. Distribución

### 5.1 Portabilidad: qué significa exactamente

El paquete es **portátil en Fedora 44 o superior**: lleva dentro su propio
intérprete de Python 3.14, Qt 6 y toda la pila científica. **No necesita Python,
ni pip, ni `requirements.txt`, ni permisos de administrador.**

Lo único que toma del sistema son bibliotecas gráficas que Qt exige y que
PyInstaller no puede empaquetar. Verificado en contenedor limpio:

```bash
sudo dnf install fontconfig freetype libxkbcommon libxkbcommon-x11 libxcb \
    dbus-libs mesa-libGL mesa-libEGL xcb-util xcb-util-wm xcb-util-image \
    xcb-util-keysyms xcb-util-renderutil xcb-util-cursor libwayland-cursor
```

En cualquier Fedora con escritorio (Workstation, KDE) **ya están instaladas**: la
lista solo importa en instalaciones mínimas o contenedores. El RPM las declara
como `Requires`, así que `dnf` las resuelve solo.

> **`libGL.so.1` es la más crítica.** Fue la única dependencia que faltó en la
> primera prueba en contenedor y hacía fallar el arranque de la interfaz. La
> aporta `mesa-libGL`.

### 5.2 Empaquetar la carpeta final

`empaquetar.py --tar` ya lo hace, pero si prefieres hacerlo a mano:

```bash
cd dist
# Si has EJECUTADO el programa desde esta carpeta, borra antes tus datos:
rm -rf DML-FINANCE/.dml_cache DML-FINANCE/.dml_finance DML-FINANCE/autotest.txt
tar -czf DML-FINANCE-x86_64.tar.gz DML-FINANCE/
sha256sum DML-FINANCE-x86_64.tar.gz > DML-FINANCE-x86_64.tar.gz.sha256
```

Ese `rm` es importante: si abriste el programa desde `dist/DML-FINANCE/`, ahí
estarán tu caché de análisis, tus preferencias y tu log de trazas. **`--tar` ya
los excluye automáticamente** (constante `NO_COMPARTIR` de `empaquetar.py`), pero
un `tar` hecho a mano no sabe nada de ellos y los repartiría.

**Usa `.tar.gz` para Linux.** El ZIP que produce Python **sí** guarda el permiso
0755 (lo escribe en `external_attr`), pero **no todas las herramientas lo
restauran al descomprimir**: `unzip` sí y el módulo `zipfile` de Python no
(comprobado). Con `tar.gz` no hay ambigüedad: conserva permisos y los enlaces
simbólicos de `_internal/` con cualquier herramienta, y tu script de verificación
lo comprueba explícitamente.

Para distribuir con integridad, entrega también el `sha256`:

```bash
cd DML-FINANCE-x86_64
tar -xzf DML-FINANCE-x86_64.tar.gz
cd DML-FINANCE && ./DML-FINANCE
```

### 5.3 Probar en una máquina limpia (contenedor o VM)

**Contenedor (ya implementado, es lo más rápido):**

```bash
tests/verificar_contenedor.sh                       # usa el .tar.gz mas reciente
tests/verificar_contenedor.sh dist/DML-FINANCE-x86_64.tar.gz
SIN_DEPENDENCIAS=1 tests/verificar_contenedor.sh    # reproduce el fallo de libGL a proposito
```

Qué comprueba y por qué cada cosa importa:

| Comprobación | Qué detecta |
|---|---|
| `Python del sistema ausente` | Si el paquete arranca sin Python, de verdad es autónomo. |
| `Bibliotecas esenciales resueltas` | `ldd` sobre el binario y Qt: símbolos sin resolver. |
| `Plugins de pantalla completos` | `libqxcb`/`libqwayland`: informa qué falta y qué paquete lo aporta. |
| `Autotest (HOME virgen)` | Arranque real con un `~` sin `.dml_finance`, como un usuario nuevo. |
| `Arranque con plataforma minimal` | Que Qt inicializa sin pantalla física. |
| `DML-FINANCE.desktop valido` | Cumple el estándar freedesktop. |

Resultado obtenido en este equipo:

```
Python del sistema ausente                     [OK]
Bibliotecas esenciales resueltas               [OK]
Plugins de pantalla completos                  [OK]
Autotest (HOME virgen, offscreen)              [OK]
DML-FINANCE.desktop valido                     [OK]

RESULTADO: OK - el paquete funciona en un Fedora limpio
```

**Máquina virtual (prueba gráfica real, la que no puede hacer un contenedor):**
un contenedor no tiene servidor gráfico, así que **no puede validar que la ventana
se dibuje en X11 o Wayland**. Para eso hace falta una VM:

```bash
# Opcion A: descargar la ISO de Fedora Workstation 44 e instalarla en GNOME Boxes
# Opcion B: Fedora Cloud Base + escritorio minimo
sudo dnf install @workstation-product-environment    # dentro de la VM
```

En la VM, copia el `.tar.gz`, descomprime y ejecuta `./DML-FINANCE`. Comprueba
que la ventana abre, que se ven los iconos y que el menú muestra la aplicación.

### 5.4 `.desktop`: integrarlo en el sistema

**Opción A — solo para tu usuario, sin root (recomendada):**

```bash
python empaquetar.py --instalar
```

Instala en `~/.local/share/applications/` y el icono en
`~/.local/share/icons/hicolor/` en los tamaños 16→256 px, y refresca las cachés
con `update-desktop-database` y `gtk-update-icon-cache`. La aplicación aparece en
el menú de GNOME/KDE como cualquier otra.

`--instalar` ya usa **el nombre del tema** como `Icon=DML-FINANCE` cuando el árbol
`hicolor` está disponible, que es la forma correcta (permite al escritorio elegir
el tamaño adecuado) en vez de una ruta absoluta.

**Opción B — el `.desktop` del paquete portátil:**

El archivo `dist/DML-FINANCE/DML-FINANCE.desktop` ya está generado y se puede
copiar a mano. Contiene rutas absolutas al ejecutable, así que **solo vale si la
carpeta no se mueve de sitio**:

```bash
cp dist/DML-FINANCE/DML-FINANCE.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications
```

> En GNOME, los `.desktop` que se copian al **Escritorio** a mano aparecen como
> archivos de texto o con un aviso de "no es de confianza". GNOME ya no ejecuta
> lanzadores desde el escritorio por diseño. Para eso existe `--instalar` (menú de
> aplicaciones) o el RPM. En KDE y XFCE el `.desktop` del escritorio sí funciona
> directamente.

### 5.5 RPM básico (ya implementado)

```bash
python empaquetar.py --rpm
```

`empaquetar.py` genera el `.spec` de RPM y lo construye en `~/rpmbuild` (o donde
señale `RPMBUILD_DIR`), **sin necesidad de root**: solo instalar el resultado usa
`sudo`. Estructura del paquete:

```
/usr/lib64/DML-FINANCE/          <- la aplicacion completa
/usr/bin/DML-FINANCE             <- enlace simbolico (queda en el PATH)
/usr/share/applications/DML-FINANCE.desktop
/usr/share/icons/hicolor/{48,64,128,256}x{...}/apps/DML-FINANCE.png
```

Detalles de implementación que conviene conocer:

- **`AutoReqProv: no`**. PyInstaller ya incluye sus propias bibliotecas; el
  generador automático de dependencias de RPM pediría paquetes de Python y Qt que
  el paquete no necesita (y que podrían impedir la instalación).
- **El enlace apunta al mismo `%{_libdir}`** con el que se crea la carpeta. En
  `x86_64`, `%{_libdir}` es `/usr/lib64`; un enlace a `/usr/lib` no resolvería.
- **`glibc >= 2.43`** se calcula del paquete real, no se escribe a mano.

Instalación y desinstalación:

```bash
sudo dnf install dist/dml-finance-1.0.0-1.fc44.x86_64.rpm
DML-FINANCE                       # ya esta en el PATH

sudo dnf remove dml-finance       # desinstalar
```

Verificado en contenedor limpio: `dnf` resolvió las dependencias (49 paquetes),
el enlace `/usr/bin/DML-FINANCE` quedó correcto y el autotest pasó **desde la
ruta instalada**.

---

## 6. Checklist de verificación antes de distribuir

Ejecútalo en orden. Cada paso tiene su criterio de aceptación; si uno falla, no
sigas.

### Fase 1 — Build

- [ ] **1.** `source venv/bin/activate && pip install pyinstaller`
      → `pyinstaller 6.22.3` o superior (necesario: Python 3.14).
- [ ] **2.** `python empaquetar.py --limpiar --sin-acceso --tar`
      → termina con `Ejecutable generado:` y `tar.gz listo para compartir:`.
- [ ] **3.** El resumen de portabilidad dice `glibc requerida: 2.43 -> Fedora 44 o superior`.
      → Si dice una glibc mayor que la de tu Fedora, el paquete no arrancará aquí.

### Fase 2 — Verificación del paquete (antes de comprimir)

- [ ] **4.** `cd dist/DML-FINANCE && QT_QPA_PLATFORM=offscreen ./DML-FINANCE --autotest`
      → **`RESULTADO: OK`** y código de salida 0. Es la prueba más importante:
      valida las 11 pestañas, los 12 criterios y las 11 hojas de Excel.
- [ ] **5.** El informe menciona `config.yaml` con la ruta **de dentro del paquete**.
      → Si no encuentra `config.yaml`, arrancará con valores por defecto.
- [ ] **6.** `ls -l dist/DML-FINANCE/DML-FINANCE` → permisos `-rwxr-xr-x`.
- [ ] **7.** `desktop-file-validate dist/DML-FINANCE/DML-FINANCE.desktop`
      → sin salida (válido). Requiere `desktop-file-utils`.

### Fase 3 — Portabilidad (contenedor limpio)

- [ ] **8.** `tests/verificar_contenedor.sh`
      → **`RESULTADO: OK - el paquete funciona en un Fedora limpio`**.
- [ ] **9.** Confirma que el `.tar.gz` conserva el permiso de ejecución
      (el propio script lo verifica: `[OK] El .tar.gz conserva el permiso`).

### Fase 4 — Prueba gráfica real (VM, obligatoria antes de entregar)

Un contenedor no tiene pantalla: **los pasos 10-13 solo se pueden hacer en una VM
o en un equipo de escritorio.**

- [ ] **10.** Descomprime el `.tar.gz` en una ruta limpia y ejecuta
      `./DML-FINANCE` (o doble clic en `DML-FINANCE.sh`).
      → La ventana abre y se dibuja correctamente.
- [ ] **11.** El icono de la ventana y de la barra de tareas es el logo.
- [ ] **12.** Analiza un ticker real con Internet (`NVDA`) y exporta a Excel
      (Ctrl+E). → El `.xlsx` se abre y tiene 11 hojas.
      *Este paso es el único que valida `cloudscraper`, `certifi` y `curl_cffi`
      contra la red real: el autotest usa datos DEMO.*
- [ ] **13.** Entra en una pestaña con gráficos (Econométrico o Griegas).
      → matplotlib dibuja sin fallos de fuentes.

### Fase 5 — Integración (opcional)

- [ ] **14.** `python empaquetar.py --instalar` y busca DML-FINANCE en el menú.
- [ ] **15.** `python empaquetar.py --rpm`
      → genera `dist/dml-finance-1.0.0-1.fc44.x86_64.rpm`.
- [ ] **16.** `rpm -qpR dist/*.rpm` → lista `glibc >= 2.43`, `mesa-libGL`, etc.
- [ ] **17.** En una VM limpia: `sudo dnf install ./dml-finance-*.rpm` y luego
      `DML-FINANCE` desde cualquier directorio.

### Fase 6 — Entrega

- [ ] **18.** Genera el hash: `sha256sum dist/DML-FINANCE-x86_64.tar.gz`.
- [ ] **19.** Comprueba que **no viajan tus datos**:
      `tar -tzf dist/DML-FINANCE-x86_64.tar.gz | grep -E "\.dml_cache|\.dml_finance|autotest\.txt"`
      → sin resultados (`--tar` ya los excluye).
- [ ] **20.** Comprueba que **sí viajan los datos críticos**:
      ```bash
      tar -tzf dist/DML-FINANCE-x86_64.tar.gz | grep -E "cacert.pem|browsers.json|config.yaml|DML-FINANCE\.desktop"
      ```
      → los cuatro aparecen. Sin `cacert.pem` falla todo el HTTPS.
- [ ] **21.** Avisa al destinatario del requisito **Fedora 44 o superior** y de la
      línea de `dnf install` de la sección 5.1.

---

## 7. Problemas conocidos y soluciones

| Síntoma | Causa | Solución |
|---|---|---|
| `version 'GLIBC_2.43' not found` | Se ejecuta en Fedora 43 o anterior | Compilar en esa Fedora, o usar Fedora 44+. No hay otra salida. |
| `libGL.so.1: cannot open shared object file` | Falta `mesa-libGL` | `sudo dnf install mesa-libGL` |
| `could not load the Qt platform plugin "xcb"` | Faltan las `libxcb-*` | La lista de la sección 5.1 |
| Los diálogos de Qt salen en inglés | Se podaron las traducciones `_es` | No uses `--sin-poda`; revisa `IDIOMAS_QT` en `empaquetar.py` |
| La ventana no abre y no hay mensaje | Se compiló sin consola | Mira `~/.dml_finance/dml-finance.log`; o recompila con `--consola` |
| `FileNotFoundError: DML-FINANCE.spec` | Falta la receta | Ya resuelto: el archivo está y ahora se versiona |
| El `.desktop` no aparece en el menú | Caché sin refrescar | `update-desktop-database ~/.local/share/applications` |
| GNOME no ejecuta el `.desktop` del Escritorio | GNOME lo prohíbe por diseño | Usa `--instalar` (menú) o el RPM |

---

## 8. Referencia rápida

```bash
# Construir todo
source venv/bin/activate
python empaquetar.py --limpiar --sin-acceso --tar --rpm

# Validar
cd dist/DML-FINANCE && QT_QPA_PLATFORM=offscreen ./DML-FINANCE --autotest
cd ../.. && tests/verificar_contenedor.sh

# Integrar
python empaquetar.py --instalar                 # menu del usuario, sin root
sudo dnf install dist/dml-finance-*.rpm         # sistema completo

# Receta de PyInstaller directa (sin empaquetar.py)
PYTHONPATH=. pyinstaller --noconfirm DML-FINANCE.spec
```
