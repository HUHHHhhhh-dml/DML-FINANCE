# DML-FINANCE

**Analizador cuantitativo de acciones con parrilla de decision de inversion — aplicación de escritorio en Python 3.10+**

DML-FINANCE descarga datos de mercado de un *ticker* (por ejemplo `NVDA`), calcula
un conjunto de modelos financieros y lo muestra **todo dentro del mismo programa**,
organizado en pestañas, con una **parrilla de 12 criterios binarios** y una decision
final (COMPRAR / MANTENER / NO INVERTIR).

> **La aplicacion NO genera ningun Excel por si sola.** Solo existe un boton
> **“Exportar a Excel”** que abre un dialogo cuando el usuario lo pide. La unica
> escritura automatica es la cache local por dia, en una carpeta oculta
> (`.dml_cache`).
>
> Herramienta de analisis, **no** asesoria financiera.

---

## 1. Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
```

Opcional (respaldo de Investing.com con navegador headless — paso 2 del pliego):

```bash
pip install playwright
playwright install chromium
```

Opcional (claves de API). Nunca se escriben en el codigo ni en `config.yaml`, solo
en variables de entorno o en un `.env` que no se versiona:

| Variable          | Para que sirve                                            |
|-------------------|-----------------------------------------------------------|
| `FRED_API_KEY`    | Tasas de FRED por la API oficial (si falta, usa el CSV publico `fredgraph.csv`) |
| `FMP_API_KEY`     | Multiplos fundamentales desde Financial Modeling Prep      |
| `FINNHUB_API_KEY` | PER desde Finnhub                                          |

## 2. Ejecucion

```bash
python main.py                  # abre la interfaz (uso normal)
python main.py NVDA             # abre la interfaz y analiza NVDA
python main.py NVDA AAPL MSFT   # varios tickers + tabla comparativa
python main.py --demo           # interfaz con datos FICTICIOS marcados como DEMO, sin conexion
python main.py -v               # trazas detalladas (nivel DEBUG)
python main.py --modo excel --indice ^IXIC --meses 120 --tema claro
```

No hace falta navegador ni servidor externo: la aplicacion se abre directamente en
una ventana Qt (PySide6).

## 3. Flujo de trabajo

1. **Barra superior fija**: campo *Ticker* (admite varios separados por comas),
   boton **Analizar** (o `Enter`), selector de **modo** (`estandar` / `excel`),
   selector de **indice** (`^GSPC`, `^IXIC`, `^DJI`), **meses** de historia (60 por
   defecto), **Actualizar datos** (ignora la cache), **Exportar a Excel**,
   **Cancelar**, cambio de **tema** y **Limpiar cache**.
2. **Descarga y calculo en hilos** (`QThread`): la ventana nunca se congela;
   hay **barra de progreso con su porcentaje** (visible desde el primer momento,
   con avance suave entre pasos), contador de tickers terminados (`2 de 3`) y
   mensajes de estado (“Consultando Investing.com…”, etc.). Cada ticker se aisla:
   si uno falla, el resto se analiza igualmente.
3. **Historial de analisis** (panel lateral): cada ticker analizado se guarda en
   memoria; al pulsarlo se recargan **todas** las pestañas con sus resultados.
4. **Panel “Parametros”** (panel lateral derecho): `r`, `q`, `sigma`, `T`, `K`,
   meses de pronostico, umbrales (Beta max., R² min., margen, Delta min., cortes
   de decision) y **activacion/desactivacion de los 12 criterios**. Al cambiar
   cualquier control se **recalcula en vivo sin volver a descargar**. Solo se
   aplican los controles que el usuario ha tocado: un dato `N/D` no impone el
   valor por defecto del control. El **modo**, el **indice** y los **meses** se
   editan en la barra superior (fuente unica de esos tres valores), y el boton
   **Restablecer valores de mercado** devuelve `r`, `q`, `sigma`, `T` y `K` a los
   valores calculados con los datos descargados.
5. **Datos faltantes**: se muestran como `N/D` con icono/tooltip que explica el
   motivo y las fuentes intentadas. La **captura manual** de las tasas no ocurre
   durante la descarga (Qt no permite abrir dialogos desde un hilo de trabajo):
   cuando el analisis termina, la ventana pregunta —en el hilo de la interfaz— por
   las tasas que ninguna fuente pudo dar, las registra como `manual` y recalcula
   en el acto. Ver el paso 5 de la seccion 7.

## 4. Pestanas

| # | Pestana | Contenido |
|---|---------|-----------|
| 1 | **Principal** | Tarjetas (accion, bolsa, fecha, spot, strike/forward, time to maturity, dividendo `q`, tasa libre `r`, costo de mantener `b`, volatilidad `sigma`, rendimiento esperado), la **parrilla de 12 indicadores** en verde/rojo, la calificacion promedio y la **decision final** en un indicador grande con color, grafico del precio historico con spot, forward y precio objetivo, y tabla comparativa cuando hay varios tickers |
| 2 | **Econometrico** | Todo el proceso MCO de `Precio ~ periodo`: datos usados, coeficientes con error estandar, `t` y `p-value`, R², R² ajustado, F y su p-value, error estandar de la regresion, Durbin-Watson, Jarque-Bera y Breusch-Pagan, tabla de residuos, pronostico a `T` meses con intervalo de confianza al 95 %, veredicto de fiabilidad (Alta/Media/Baja) con justificacion y graficos (precio vs tendencia, residuos, histograma) |
| 3 | **Griegas** | Parametros de entrada, `d1`, `d2`, prima, Delta, Gamma, Vega, Theta, Rho, Elasticidad (lambda), Vanna, Vomma y sensibilidad a `b` (Call y Put), pruebas de **paridad Put-Call** y de **diferencias finitas**, y grafico interactivo de Delta y prima frente al precio del subyacente |
| 4 | **CAPM** | Tabla mensual (precio, TLR, rendimientos, PRH, indice, rendimiento de mercado), Beta por covarianza y por regresion, Beta publicada y sus diferencias, PRH, `Rend_CAPM`, precio objetivo y dispersion accion vs mercado con recta de regresion |
| 5 | **PER** | PER de la empresa vs PER del sector, diferencia y veredicto |
| 6 | **EPS** | EPS actual vs EPS estimado (forecast), sorpresa y veredicto |
| 7 | **Price to FCF** | Capitalizacion / FCF de la empresa vs multiplo del sector (menor es mejor) |
| 8 | **Renta PER** | `1/PER` frente a la TLR, diferencial en puntos base |
| 9 | **RDR** | Rendimiento vs riesgo, cociente Rend/Riesgo, VaR 95/99, Sharpe, Treynor y maxima caida |
| 10 | **Bonos y tasas** | T-Bill 4 semanas (TLR), bonos a 10 y 30 anios, historico mensual con grafico y diferencias entre fuentes (Investing vs respaldo, en puntos base) |
| 11 | **Fuentes y avisos** | Cada dato con fuente, URL, fecha/hora, metodo (API / scraping / respaldo / manual / calculo / demo) y todos los avisos |

Todas las tablas permiten **ordenar**, **copiar celdas con `Ctrl+C`** (formato TSV,
pegable en Excel) y **redimensionar columnas**; los numeros se formatean como
porcentajes (`2` decimales) o importes, y cada encabezado y cada metrica lleva un
*tooltip* con su formula (p. ej. `Rend_CAPM = TLR + Beta x PRH`).

## 5. Boton “Exportar a Excel”

Solo al pulsarlo se abre **“Guardar como…”** y se genera un `.xlsx`
(`openpyxl`) que replica **todas** las pestañas del analisis en pantalla. Antes de
pedir el archivo se pregunta, con **botones en espanol** (no dependen de que la
traduccion de Qt este instalada):

| Pregunta | Botones | Efecto |
|----------|---------|--------|
| Alcance de la exportacion (solo con **2 o mas** analisis) | **Todos** / **Solo este** / **Cancelar** | exporta todos los analisis o unicamente el seleccionado en el historial |
| Formulas o valores | **Formulas** / **Solo valores** / **Cancelar** | escribe formulas reales de Excel (recomendado) o un informe estatico |

* **Con formulas** (por defecto: CAPM, Beta, PER, Renta PER, RDR,
  Black-Scholes y las griegas se escriben como **formulas reales de Excel** con
  entradas en celdas azules) o **solo valores**.

Al terminar se muestra la ruta y un boton **“Abrir carpeta”**.

Detalles tecnicos de la exportacion:

* Las funciones de Excel posteriores a 2007 se escriben con el prefijo OOXML
  obligatorio (`_xlfn.NORM.S.DIST`, `_xlfn.STDEV.S`); sin el, Excel mostraria
  `#NAME?`. El libro se verifico **recalculandolo de verdad** con LibreOffice:
  Beta, `Rend_CAPM`, precio objetivo, PER y la prima de Black-Scholes coinciden
  con el calculo en Python y no queda ninguna celda de error.
* Las celdas de entrada van en azul `0000CC`, y cada formula lleva un comentario
  con su explicacion.

## 6. Modos de calculo (`estandar` vs `excel`)

* **`estandar` (por defecto)** — formulas corregidas y coherentes.
* **`excel`** — replica fiel de la metodologia del libro de referencia,
  **incluidas sus inconsistencias**, para poder comparar. Cada punto donde
  difiere del estandar se marca con una advertencia visible `[MODO EXCEL]` y cada
  correccion se etiqueta `[ESTÁNDAR]`.

| Punto | `estandar` [ESTÁNDAR] | `excel` |
|-------|----------------------|---------|
| Rendimiento mensual de la TLR | `TLR/12` | `TLR/365 x 28` |
| Beta | covarianza y varianza muestrales (`ddof=1`) | `COVAR` poblacional / `VAR` muestral |
| PRH | prima de riesgo de **mercado** `E[Rm − Rf]` anualizada | promedio mensual de `(R_accion − R_TLR)` |
| Sigma en Black-Scholes | anual (`sigma_mensual x sqrt(12)`) | mensual sin anualizar (se avisa) |
| Delta y Gamma | factor `e^((b−r)T)` | `e^(−rT)` |
| Prima Put | descuenta con `r` | mezcla `r` con `b` |
| Precio proyectado por TRG | `Spot x (1 + TRG)^meses` | `PROMEDIO(precios) x (1 + TRG)` (se avisa de la inconsistencia de escala) |

## 7. Obtencion de datos y respaldos

Para **cada dato** se guarda valor, fuente, URL, fecha/hora de consulta y metodo
(`API`, `scraping`, `respaldo`, `manual`, `calculo`, `demo`). Si un dato no se
obtiene, se muestra `N/D` con el motivo: **nunca se inventan datos**.

**Precios y fundamentales** — `yfinance` (con respaldo de la API publica
`v8/finance/chart` de Yahoo), serie de cierres **mensuales** de los ultimos 60
meses (configurable). Se valida que el ultimo cierre mensual sea coherente con el
spot y se avisa si la diferencia es anormal (mes en curso incompleto).

**Tasas de referencia (Investing.com en primer lugar)**, en este orden:

1. **Investing.com** con cabeceras de navegador. En orden de eficacia
   **comprobada**: `urllib` → `cloudscraper` → `requests`. Cloudflare responde
   `403` a `requests` y `cloudscraper` (su huella TLS los delata) pero **acepta**
   la peticion de `urllib` con las mismas cabeceras, asi que `urllib` va primero y
   el resto son motores de reserva.
   * Las paginas usadas son `u.s.-1-month-bond-yield` (el T-Bill a 4 semanas:
     Investing.com retiro la URL `u.s.-4-week-bond-yield`, que hoy da `404`),
     `u.s.-10-year-bond-yield` y `u.s.-30-year-bond-yield`.
2. **Investing.com** con **Playwright** (navegador headless).
3. **Respaldo FRED** (`FRED_API_KEY` o `fredgraph.csv` publico):
   * TLR 4 semanas: **`DGS1MO`** (rendimiento constante, base de inversion). Si
     solo hubiera `DTB4WK` (base a **descuento**) se **convierte** a rendimiento
     equivalente de bono antes de usarla:
     `y = 365·d / (360 − d·28)`.
     **Nunca** se mezcla una tasa a descuento con rendimientos de Investing sin
     convertir (la diferencia ronda 15-20 puntos base con tipos normales).
   * 10 anios: `DGS10`. 30 anios: `DGS30`.
   * FRED bloquea a los clientes que se identifican como navegador (con
     `User-Agent` de Chrome la conexion se queda colgada); la aplicacion se
     identifica de forma honesta y transparente ante FRED. Si FRED falla por red,
     se marca como no disponible y se pasa a los respaldos sin volver a esperar
     (interruptor que se reinicia con "Actualizar datos").
4. **Respaldo Yahoo Finance**: `^TNX` y `^TYX` son exactamente el bono a 10 y 30
   anios. Para la TLR **no existe** el T-Bill a 4 semanas en Yahoo: el unico proxy
   es **`^IRX`, que es el T-Bill a 13 semanas**, asi que se usa **etiquetado como
   proxy** y con un aviso visible de la diferencia de plazo. **Nunca** se
   presenta `^IRX` como si fuera la TLR de 4 semanas.
5. Si todo falla, la aplicacion **pregunta al terminar el analisis** (siempre en el
   hilo de la interfaz, nunca desde el hilo de descarga) por las tasas que ninguna
   fuente pudo dar, y las registra como `manual` recalculando en el acto. Mientras
   tanto esos datos aparecen como `N/D` con el motivo *“requiere captura manual (se
   solicitara al terminar el analisis)”*.

Cuando se usa un respaldo se muestra la insignia **“Respaldo: FRED”** /
**“Respaldo: Yahoo Finance”** y, si ambas fuentes estan disponibles, la
**diferencia en puntos base** entre Investing.com y el respaldo, con aviso si
supera **25 pb**. Se respetan los terminos de uso: pausa configurable entre
peticiones, numero de reintentos limitado y *backoff*.

**Cache local por dia** — boton “Limpiar cache” en la barra superior. Una ruta
relativa en `datos.cache_dir` se resuelve dentro del directorio de datos del
usuario (`~/.dml_finance/.dml_cache`), no respecto al directorio de trabajo: asi el
acceso directo del escritorio no crea la cache en `C:\Windows\System32` ni la
desactiva en silencio.

**Carpeta de datos (`~/.dml_finance`)** — guarda la cache de matplotlib, la cache
de datos y el archivo de trazas. La aplicacion **nunca falla** si no puede crearla
(perfil de Windows restringido, `~/.dml_finance` perteneciente a otro usuario,
politica del equipo...): recorre estas alternativas, en orden, y usa la primera
escribible:

1. `DML_FINANCE_HOME` (variable de entorno, para elegirla a mano);
2. `%USERPROFILE%\.dml_finance`;
3. `%LOCALAPPDATA%\DML-FINANCE`;
4. el directorio temporal del sistema (ultimo recurso: la cache se pierde al
   reiniciar, pero el programa funciona).

Lo mismo vale para cada pieza por separado: si la cache o el archivo de trazas no
se pueden preparar, se trabaja **sin ellos** (con un aviso en el log) en lugar de
impedir el arranque.

## 8. Parrilla de decision (12 criterios)

| # | Criterio | Optimo |
|---|----------|--------|
| 1 | PER empresa < PER sector | menor es mejor |
| 2 | EPS actual >= EPS estimado (forecast) | mayor es mejor |
| 3 | Tecnico: senal MACD (1 mes) distinta de “Sell” | Neutral o Buy |
| 4 | Price to FCF empresa < Price to FCF sector | menor es mejor |
| 5 | `Rend_CAPM > TLR` | mayor es mejor |
| 6 | `Beta < 1.10` | menor es mejor |
| 7 | Renta PER `1/PER > TLR` | mayor es mejor |
| 8 | RDR: `Rend_CAPM > Riesgo` (desviacion estandar anual) | mayor es mejor |
| 9 | `R² del modelo econometrico > 0.70` | mayor es mejor |
| 10 | TRG: precio proyectado `> Spot x (1 + TLR + 1 %)` | mayor es mejor |
| 11 | Forward: `Spot < Strike` (precio forward). *Cumple casi siempre que `r > q`* | — |
| 12 | `Delta Call > 0.50`. *Con `K = Forward` la Delta tiende a superar 0.5* | — |

> **Matiz importante sobre el criterio 12.** El pliego afirma que con `K = Forward`
> la Delta supera 0.5. Eso es **exacto cuando `r > q`** (`b > 0`), pero no es
> cierto en general: con `K = F` se tiene `ln(S/F) = −bT`, de donde
> `d1 = σ√T/2` (constante) y
>
> ```
> Delta_call(K = F) = e^((b−r)T) · N(σ√T/2)
> ```
>
> por lo que `Delta > 0.5` si y solo si `b > b*`, con
> `b* = r − ln(2·N(σ√T/2))/T ≈ −σ²/2`. Es decir: con `b` **negativo pero pequeno
> en valor absoluto** la Delta sigue por encima de 0.5, y con `b` muy negativo
> baja de 0.5. La aplicacion usa la formula correcta y el criterio se evalua con
> el valor real, no con la regla aproximada.

Cada criterio muestra: criterio optimo, valor obtenido, valor de comparacion,
¿cumple? (SI/NO), calificacion 0/1 y la **ruta de Investing.com** de la que sale
el dato. Los criterios se pueden **activar/desactivar** desde el panel de
parametros y la calificacion se promedia **solo sobre los criterios activos**
(por defecto, los 12).

**Regla de decision**: `> 0.70` → **COMPRAR**; entre `0.40` y `0.70` →
**MANTENER**; `< 0.40` → **NO INVERTIR**.

Un dato `N/D` **nunca** se inventa: el criterio se marca como no cumplido, se
califica 0 y se anota el motivo.

## 9. Arquitectura del proyecto

```
DML-FINANCE/
├── main.py                     # punto de entrada (GUI; --demo)
├── config.yaml                 # umbrales y parametros (claves API por entorno)
├── requirements.txt
├── dml/
│   ├── analisis.py             # orquestacion: datos -> modelos -> resultado
│   ├── core/                   # config, tipos, cache, utilidades, logging
│   │   ├── config.py  tipos.py  cache.py  util.py  log.py
│   ├── data/                   # obtencion de datos (sin Qt)
│   │   ├── mercado.py          # precios, spot, serie mensual, indice
│   │   ├── proveedores.py      # Investing.com, FRED, Yahoo, captura manual
│   │   ├── tasas.py            # TLR/bonos, conversion descuento->rendimiento
│   │   ├── fundamentales.py    # PER, EPS, P/FCF, dividendo, Beta publicada
│   │   ├── ticker.py           # consolida los datos de un ticker
│   │   └── demo.py             # datos ficticios (--demo)
│   ├── models/                 # calculos financieros (sin Qt)
│   │   ├── rendimientos.py  capm.py  econometria.py  riesgo.py
│   │   ├── blackscholes.py  tecnicos.py  fundamentales.py
│   │   ├── parrilla.py         # 12 criterios y regla de decision
│   │   └── parametros.py       # parametros efectivos y strike
│   ├── export/
│   │   └── excel.py            # .xlsx con formulas reales (solo al pulsar el boton)
│   └── ui/                     # PySide6
│       ├── app.py  ventana_principal.py  worker.py  widgets.py  estilos.py
│       ├── paneles/            # historial y parametros
│       └── tabs/               # una pestana por bloque del pliego
├── recursos/                   # DML-Icon.png (logo) + icono.ico / icono.png generados
├── tests/                      # pytest
├── generar_icono.py            # genera el icono (Pillow) desde recursos/DML-Icon.png
└── empaquetar.py               # PyInstaller: .exe + acceso directo en el escritorio
```

La **logica esta separada de la interfaz**: `dml/core`, `dml/data` y `dml/models`
se pueden importar y probar sin Qt ni ventana.

## 10. Pruebas

```bash
pytest -q                       # suite completa
pytest tests/test_blackscholes.py -v
pytest tests/test_ui_arreglos.py -v   # interfaz: progreso, dialogos y parametros
```

Cubren, entre otras cosas: Beta (contra una serie sin ruido y contra `statsmodels`),
CAPM, MCO (validado contra `statsmodels`), Black-Scholes y griegas (contra
**diferencias finitas** y **paridad Put-Call**), la **conversion descuento →
rendimiento** del T-Bill, la parrilla de 12 criterios y una prueba de humo que abre
la interfaz en modo *offscreen* y comprueba que **todas** las pestañas se llenan.
La suite es **offline por construccion**: una barrera en `conftest.py` bloquea
cualquier conexion de red.

## 11. Ejecutable, acceso directo (.exe) y ZIP para compartir

Para usar el programa **sin Python y sin consola**, con un acceso directo en el
escritorio:

```bash
pip install pyinstaller
python empaquetar.py
```

Eso hace tres cosas:

1. Genera **`dist/DML-FINANCE/DML-FINANCE.exe`** (unos 26 MB) con el **logo
   `recursos/DML-Icon.png`** como icono del ejecutable, de la ventana, de la barra
   de tareas y del acceso directo.
2. Copia **`config.yaml`** junto al ejecutable, para que puedas editar los
   umbrales con cualquier editor de texto.
3. Crea un **acceso directo `DML-FINANCE` en el escritorio** que apunta al `.exe`,
   arranca en su carpeta y usa el icono del programa.

A partir de ahi basta **doble clic** en el acceso directo (o en el `.exe`). El
script tambien deja un `LEEME-EJECUTABLE.txt` en la carpeta del ejecutable.

### Icono

El icono se **genera** desde el logo (`recursos/DML-Icon.png`): se recorta a su
contenido, se centra sobre una placa redondeada y se exporta a un `.ico` de 7
resoluciones (16 a 256 px). `empaquetar.py` lo regenera solo si el `.ico` no
existe o es mas antiguo que el logo, de modo que cambiar el logo y volver a
empaquetar es suficiente. Tambien se puede forzar con
`python generar_icono.py`.

Opciones utiles:

| Comando | Que hace |
|---------|----------|
| `python empaquetar.py` | Ejecutable + acceso directo (por defecto, `--onedir`, arranca en 1-3 s) |
| `python empaquetar.py --zip` | Ademas deja **`dist/DML-FINANCE.zip`** listo para compartir (ver la seccion siguiente) |
| `python empaquetar.py --zip "D:\\otra.zip"` | El ZIP en otra ruta |
| `python empaquetar.py --completo` | No aligera el paquete (conserva todo lo que deja PyInstaller) |
| `python empaquetar.py --unico` | Un unico `.exe` de ~90 MB (arranque lento: se descomprime en cada ejecucion) |
| `python empaquetar.py --sin-acceso` | Solo el ejecutable, sin tocar el escritorio |
| `python empaquetar.py --escritorio "D:\\ruta"` | Crea el acceso directo en otra carpeta |
| `python empaquetar.py --limpiar` | Borra `build/` y `dist/` antes de empaquetar |
| `python empaquetar.py --consola` | Compila con consola (util para depurar el empaquetado) |
| `python generar_icono.py` | Regenera `recursos/icono.ico` y `recursos/icono.png` desde el logo |
| `python generar_icono.py --ver` | Solo comprueba que el logo se puede leer |

## 11.1 Compartir el programa con otra persona (ZIP)

```bash
python empaquetar.py --limpiar --sin-acceso --zip
```

Eso deja **`dist/DML-FINANCE.zip`** (unos 115 MB) con una unica carpeta
`DML-FINANCE/` dentro:

```
DML-FINANCE/
├── DML-FINANCE.exe        <- el programa (doble clic)
├── config.yaml            <- umbrales, editables con el Bloc de notas
├── LEEME-EJECUTABLE.txt   <- instrucciones para quien lo recibe
└── _internal/             <- librerias de Python y Qt; NO borrar
```

Quien lo recibe **solo tiene que descomprimir y hacer doble clic** en el `.exe`.
No necesita Python, ni instalar nada, ni permisos de administrador. Funciona en
Windows 10/11 de 64 bits.

Si prefieres hacerlo a mano, **basta con comprimir la carpeta `dist/DML-FINANCE`
entera**: el `.exe` necesita `_internal/` y `config.yaml` (sin ellos no arranca).
Pero antes **borra de esa carpeta** (si existen) los datos de ejecucion, porque
son tuyos y no deben viajar:

| Se puede borrar / omitir | Por que |
|--------------------------|---------|
| `.dml_cache/` | cache de tus analisis; el programa la recrea |
| `.dml_finance/` | tus preferencias, cache de matplotlib y tu log |
| `autotest.txt` | informe de tus pruebas |
| `DML_FINANCE_*.xlsx` | un Excel que exportaste |
| `tmp*` (carpetas sueltas) | restos temporales de matplotlib |

`--zip` ya lo hace por ti: copia el paquete **sin** esos datos y ademas quita del
`_internal/` el unico archivo que la aplicacion no usa
(`PySide6/opengl32sw.dll`, un rasterizador OpenGL por software de **20 MB**; esta
aplicacion pinta con el motor raster de Qt). El ZIP pasa de ~135 MB a ~115 MB. Si
quieres el paquete tal cual, usa `--completo`.

### Antes de enviarlo

1. Si vas a compartirlo por correo o mensajeria, el ZIP de ~115 MB suele superar el
   limite de adjuntos: subelo a Drive/OneDrive/WeTransfer y comparte el enlace.
2. Al abrirlo por primera vez, Windows puede mostrar SmartScreen ("Windows protegio
   tu PC") porque el `.exe` no esta firmado digitalmente: basta con **Mas
   informacion → Ejecutar de todas formas**. Para evitarlo habria que firmar el
   ejecutable con un certificado de *code signing* (de pago).

## 12. Comprobar que un ejecutable funciona

Los ejecutables se compilan con `--windowed` (sin consola), asi que la aplicacion
incluye una autoprueba que valida el paquete completo y **deja un informe en
disco**:

```bash
DML-FINANCE.exe --autotest           # escribe autotest.txt junto al ejecutable
DML-FINANCE.exe --demo --marca marca.json   # abre la ventana y deja un marcador de arranque
```

`--autotest` comprueba las dependencias empaquetadas, carga datos DEMO, verifica
que hay **11 pestañas**, que la parrilla muestra sus 12 filas, que el analisis
calcula los 12 criterios y que el exportador escribe un Excel de 11 hojas; termina
con `RESULTADO: OK` y codigo de salida 0 (1 si algo falla). Es la forma de validar
un build sin abrir la interfaz.

Es recomendable ejecutarlo **despues de generar el ZIP** (desde una carpeta donde
lo hayas descomprimido): es la comprobacion de que el paquete que vas a enviar
arranca de verdad tal cual.

Sin consola, las trazas se escriben en **`%USERPROFILE%\.dml_finance\dml-finance.log`**
(rotativo: 2 MB × 3 archivos), de modo que un fallo en el `.exe` se puede
diagnosticar aunque la aplicacion se abra con **doble clic** desde el acceso
directo. Si esa carpeta no se puede crear o escribir, se usa la primera
alternativa escribible (ver la seccion 7) o, en ultimo caso, se trabaja sin
archivo de trazas: **la aplicacion abre igualmente**.

## 13. Contraste con los libros de referencia

El proyecto se contrasto contra los dos libros Excel del enunciado
(`Portafolio DML FINANCE.xlsm` y `Proyecto Final - Evaluación de Proyectos de
Inversión .xlsx`). Esto es lo que hacen y como se refleja en la aplicacion:

| Elemento del libro | Como aparece en el libro | En DML-FINANCE |
|--------------------|--------------------------|----------------|
| Rendimiento mensual de la accion | `=C20/C19-1` | **Modo `excel`**: identico |
| Rendimiento mensual de la TLR | `=D20/365*28` | **Modo `excel`**: identico |
| PRH | `=AVERAGE(G20:G41)` de `(R_accion − R_TLR)` | **Modo `excel`**: identico (`[MODO EXCEL]`, avisado) |
| Beta | `=COVAR(J20:J41,L20:L41)/VAR(L20:L41)` | **Modo `excel`**: identico (COVAR poblacional / VAR muestral) |
| `Rend CAPM` | `=TLR+(Beta*PRH)` | Identico en ambos modos |
| `PRECIO OBJETIVO` | `=Spot*(1+Rend CAPM)` | Identico |
| Precio esperado por TRG | `=PROMEDIO(precios)*(1+TRG)` | **Modo `excel`**: identico; `[ESTÁNDAR]` usa `Spot*(1+TRG)^meses` |
| TRG | `=PRODUCT(V7:V65)^(1/S65)-1` | Identico: `(Π(P_t/P_{t-1}))^(1/n) − 1` |
| MCO | `=RSQ(precio, periodo)` | `Precio ~ periodo` con la bateria completa de diagnosticos |
| Forward | `=S*EXP(b*T)` | Identico (y ademas en `modo excel` se avisa si falta) |
| Strike | `=Forward` | Identico: `K = S·e^(bT)` (o manual) |
| `Delta Call > 0.5 → Bullish` | Criterio de la parrilla | Criterio 12, identico |
| `Beta < 1.10`, `R² > 0.70`, `Rendimiento > TLR`, `PER < PER sector`, `1/PER > TLR`, `Spot < Forward` | Criterios de la parrilla | Criterios 6, 9, 5, 1, 7 y 11 |
| Calificacion | `=AVERAGE(P16:P23)` | Promedio de los criterios **activos** (por defecto 12) |
| Cortes de decision | `>0.70` Comprar, `0.40–0.70` Hold, `<0.40` No invertir | Identicos |
| Griegas de referencia | `EXP(-r*T)` en Delta/Gamma, `Vanna` erronea, `sensibilidad_b` etiquetada como `b` siendo el resultado de Delta | **Modo `estandar`**: `e^((b−r)T)`, Vanna correcta y verificada por diferencias finitas; la pestana **Griegas** explica la diferencia |
| `d1`/`d2` de referencia | dividen por `sigma` en lugar de `sigma·sqrt(T)` (error del libro) | Corregido y verificado |
| Paridad Put-Call | no se comprueba | Se comprueba en pantalla (residuo ~1e-14) |

**Diferencias deliberadas** (todas visibles en la interfaz):

* El promedio del libro (`=SUM(R10:R30)/8`) divide entre 8 habiendo **6 criterios**
  rellenos, y el segundo libro promedia solo los 8 criterios que implementa. DML
  promedia **los criterios activos** (12 por defecto, configurables).
* El "Riesgo" del libro es un valor **escrito a mano** (0,1542 en la hoja NYSE),
  no una formula. DML calcula la **desviacion estandar anual de los rendimientos**
  y muestra tambien la varianza y los VaR.
* El libro usa `=YEARFRAC(fecha_emision, fecha_spot, 30/365)` (bases mezcladas)
  para `T`. DML usa **fechas reales**: `(vencimiento − hoy)/365`.
* Los criterios se amplian de **≈8 a 12** (los 12 del enunciado), con los 4
  nuevos (Price to FCF, Renta PER, RDR y TRG) ya presentes como filas en el libro
  del segundo proyecto.

## 14. Supuestos y dudas

1. **Un solo “mes” de historia y una sola divisa por analisis**: la serie mensual
   usa el ultimo cierre de cada mes calendario y los precios vienen en la divisa
   del ticker (normalmente USD); no se convierten divisas.
2. **`sigma` por defecto = desviacion tipica muestral de los rendimientos
   mensuales x sqrt(12)**; es editable y se usa siempre **anual** en
   Black-Scholes (en `modo excel` la sigma mensual se muestra, pero no entra en el
   modelo de opciones).
3. **`T` se calcula con fechas reales** `(vencimiento − hoy)/365` con vencimiento
   a 1 anio por defecto; **no** se usa `YEARFRAC` con base invalida.
4. **El sector** se toma del proveedor (yfinance); si falta, se usa
   `DESCONOCIDO` y el multiplo de referencia por defecto, dejando constancia en
   las notas.
5. **Investing.com bloquea el scraping con frecuencia**: la aplicacion prueba
   varios motores HTTP, degrada a Playwright → FRED → Yahoo → captura manual, y
   **siempre** indica en pantalla de donde vino cada tasa. Si la TLR acaba
   viniendo del proxy `^IRX` (13 semanas), se muestra un aviso visible con la
   diferencia de plazo para que el usuario pueda sustituirla por el valor exacto.
6. **Precio objetivo del CAPM**: `Spot x (1 + Rend_CAPM)`, con `Rend_CAPM` anual en
   modo estandar (coherente con la TLR anual); en modo excel se calcula con la
   TLR y la PRH mensuales, tal como hace el libro de referencia.
7. **Umbrales**: los del pliego (Beta < 1.10, R² > 0.70, margen = TLR + 1 %,
   Delta > 0.5, cortes 0.70/0.40) son los valores por defecto, todos editables en
   pantalla y en `config.yaml`.
8. **`dividend yield`**: el campo `dividendYield` de Yahoo Finance **cambia de
   escala** entre proveedores (a veces fraccion, a veces puntos porcentuales), por
   lo que la aplicacion **calcula** `dividendo anual / spot` cuando dispone de
   ambos (exacto) y solo si falta el dividendo anual interpreta el campo como
   puntos porcentuales. Asi se evitan errores de 100x en `q` y, por tanto, en
   `b = r − q`, el forward y las griegas.
   **Si no hay dividendo declarado, `q` se modela como 0** (un activo que no
   reparte dividendo, que es la convencion de Black-Scholes-Merton y lo que hace el
   libro de referencia): el dividendo es una entrada secundaria del modelo y no
   debe tumbar `b`, el strike ni las griegas. El supuesto queda registrado en la
   pestaña **Fuentes y avisos** con metodo `supuesto`, para poder distinguirlo de un
   dato descargado. Un `N/D` en la tarjeta **Dividend (q)** no es un fallo: lo que
   no se hace nunca es inventar el dividendo.
9. **Criterio 12 (Delta)**: la regla del pliego “con `K = Forward` la Delta supera
   0.5” es exacta para `b > 0` pero no en general; la aplicacion evalua la Delta
   real (ver el matiz en la seccion 8).
10. **Limite de uso**: la aplicacion es una herramienta de analisis; los datos de
    terceros estan sujetos a sus propios terminos de uso.
