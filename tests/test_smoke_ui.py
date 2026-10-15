# -*- coding: utf-8 -*-
"""Prueba de humo de la interfaz grafica (PySide6) en modo **offscreen**.

La prueba:

1. Fija ``QT_QPA_PLATFORM=offscreen`` **antes** de importar PySide6 (no se abre
   ninguna ventana real en el servidor de integracion).
2. Construye la ventana principal real
   (:class:`dml.ui.ventana_principal.VentanaPrincipal`).
3. La rellena con el equivalente a ``--demo`` usando un analizador **falso y sin
   red** (``monkeypatch`` sobre ``dml.analisis.analizar_demo``), de modo que la
   prueba es determinista y no descarga nada.
4. Comprueba que existen **todas** las pestanas por su nombre y que cada una se
   ha poblado: filas en las tablas, texto en las etiquetas o una figura con
   contenido dibujado.

Si el modulo de la interfaz todavia no existe, la prueba **falla** con un
mensaje explicito en lugar de saltarse en silencio.
"""

from __future__ import annotations

import os

import pytest

# --------------------------------------------------------------------------
# 1. Plataforma offscreen ANTES de importar PySide6
# --------------------------------------------------------------------------
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

try:
    pytest.importorskip("PySide6", reason="PySide6 es necesario para la prueba de humo de la interfaz")
    from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QWidget  # noqa: E402
except Exception:  # pragma: no cover - solo si el stack de Qt no esta instalado
    QApplication = QLabel = QTableWidget = QWidget = None  # type: ignore[assignment]

#: Pestanas exigidas por el pliego (nombre interno -> descripcion legible).
PESTANAS_ESPERADAS = {
    "principal": "Principal (resumen y parrilla de decision)",
    "econometrico": "Econometrico (MCO de Precio ~ periodo)",
    "griegas": "Griegas (Black-Scholes-Merton)",
    "capm": "CAPM (Beta, prima de riesgo y precio objetivo)",
    "per": "PER (empresa frente al sector)",
    "eps": "EPS (actual frente al estimado)",
    "pfcf": "Price to Free Cash Flow",
    "renta_per": "Renta PER",
    "rdr": "RDR (rendimiento sobre riesgo)",
    "bonos": "Bonos y tasas",
    "fuentes": "Fuentes y avisos",
}

#: Textos que no cuentan como contenido (ponian la pestana "vacia" en el diseno).
TEXTOS_VACIOS = {
    "", "-", "--", "N/D", "n/d", "Sin datos", "sin datos", "No disponible",
    "Sin analisis", "Pendiente", "Listo.",
}


# --------------------------------------------------------------------------
# Fixtures de Qt
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_qt():
    """``QApplication`` unica para toda la sesion (obligatorio en Qt)."""
    aplicacion = QApplication.instance()
    if aplicacion is None:
        aplicacion = QApplication([])
    yield aplicacion
    aplicacion.processEvents()


@pytest.fixture
def ventana(app_qt, monkeypatch):
    """Ventana principal vacia, construida con la configuracion del proyecto."""
    from dml.analisis import analizar_demo as analizar_demo_real
    from dml.core.config import cargar_config
    from dml.ui.ventana_principal import VentanaPrincipal

    resultado_real = analizar_demo_real("DEMO", cargar_config(None))
    llamadas = {"n": 0}

    def analizador_falso(*args, **kwargs):
        """Analizador offline: devuelve siempre el analisis DEMO ya calculado."""
        llamadas["n"] += 1
        return resultado_real

    # ``cargar_demo_en_ventana`` y el hilo de trabajo importan la funcion desde
    # ``dml.analisis``; se sustituye ahi para que ninguna ruta toque la red.
    monkeypatch.setattr("dml.analisis.analizar_demo", analizador_falso)

    config = cargar_config(None)
    config.setdefault("ui", {})["guardar_geometria"] = False
    principal = VentanaPrincipal(config=config, demo=True)
    principal.llamadas_al_analizador = llamadas
    principal.analizador_falso = analizador_falso
    yield principal
    principal.close()
    principal.deleteLater()
    app_qt.processEvents()


# --------------------------------------------------------------------------
# Utilidades de inspeccion
# --------------------------------------------------------------------------
def _tiene_figura_dibujada(widget: QWidget) -> bool:
    """True si el widget contiene una figura de matplotlib con contenido."""
    for hijo in [widget] + widget.findChildren(QWidget):
        figura = (
            getattr(hijo, "figura", None)
            or getattr(hijo, "figure", None)
            or getattr(hijo, "fig", None)
            or getattr(getattr(hijo, "canvas", None), "figure", None)
        )
        if figura is None:
            continue
        try:
            ejes = list(getattr(figura, "axes", []))
        except Exception:  # pragma: no cover - defensivo
            continue
        for eje in ejes:
            if (eje.lines or getattr(eje, "collections", []) or getattr(eje, "patches", [])
                    or getattr(eje, "images", []) or eje.texts):
                return True
    return False


def _resumen_poblado(pestana: QWidget) -> dict:
    """Cuenta filas de tabla, textos no vacios y figuras dibujadas de una pestana."""
    filas = 0
    textos = 0
    for tabla in pestana.findChildren(QTableWidget):
        filas += tabla.rowCount()
    for etiqueta in pestana.findChildren(QLabel):
        texto = (etiqueta.text() or "").strip()
        if texto and texto not in TEXTOS_VACIOS and len(texto) > 1:
            textos += 1
    return {"filas": filas, "textos": textos, "figuras": _tiene_figura_dibujada(pestana)}


# ==========================================================================
# 1. Construccion de la ventana y existencia de las pestanas
# ==========================================================================
def test_la_ventana_se_construye_offscreen(ventana):
    """La ventana principal se crea con las 11 pestanas y sin errores de Qt."""
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    assert ventana.isEnabled()
    assert "DML-FINANCE" in ventana.windowTitle()
    assert ventana.demo is True
    assert ventana.pestanas.count() == len(PESTANAS_ESPERADAS)
    assert len(ventana.tabs) == len(PESTANAS_ESPERADAS)


@pytest.mark.parametrize("nombre", sorted(PESTANAS_ESPERADAS))
def test_existe_la_pestana_por_su_nombre(ventana, nombre):
    """Cada pestana del pliego existe en la ventana."""
    assert nombre in ventana.tabs, (
        f"falta la pestana '{nombre}' ({PESTANAS_ESPERADAS[nombre]}); "
        f"pestanas encontradas: {sorted(ventana.tabs)}"
    )
    assert ventana.tabs[nombre] is not None
    assert hasattr(ventana.tabs[nombre], "cargar"), f"la pestana '{nombre}' no implementa cargar()"


def test_los_titulos_de_las_pestanas_no_estan_vacios(ventana):
    """Cada pestana declara un titulo visible en el QTabWidget."""
    titulos = [ventana.pestanas.tabText(i).strip() for i in range(ventana.pestanas.count())]
    assert all(titulos), f"hay pestanas sin titulo: {titulos}"
    assert len(set(titulos)) == len(titulos), f"hay titulos duplicados: {titulos}"


# ==========================================================================
# 2. Rellenado equivalente a ``--demo``
# ==========================================================================
@pytest.fixture
def ventana_con_demo(ventana):
    """Carga los datos DEMO (sincrono) en la ventana principal."""
    from dml.ui.ventana_principal import cargar_demo_en_ventana

    cargar_demo_en_ventana(ventana, ["DEMO"])
    QApplication.processEvents()
    return ventana


def test_la_carga_demo_no_usa_la_red_y_rellena_resultados(ventana_con_demo):
    """El analizador falso se usa y deja resultados listos para pintar."""
    assert ventana_con_demo.llamadas_al_analizador["n"] >= 1
    assert len(ventana_con_demo.resultados) == 1
    resultado = ventana_con_demo.resultados[0]
    assert resultado.ticker == "DEMO"
    assert resultado.precios is not None and len(resultado.precios) > 0
    assert resultado.criterios, "el analisis DEMO deberia traer la parrilla de criterios"
    assert resultado.calificacion is not None
    assert resultado.decision


def test_todas_las_pestanas_quedan_pobladas(ventana_con_demo):
    """Ninguna pestana se queda vacia tras cargar el analisis DEMO."""
    vacias = []
    detalles = {}
    for nombre in sorted(PESTANAS_ESPERADAS):
        pestana = ventana_con_demo.tabs[nombre]
        resumen = _resumen_poblado(pestana)
        detalles[nombre] = resumen
        tiene_resultado = getattr(pestana, "resultado", None) is not None
        # Una pestana esta poblada si pinta contenido; el atributo ``resultado``
        # solo lo conservan las que heredan el comportamiento de ``TabBase``.
        poblada = resumen["filas"] > 0 or resumen["textos"] > 0 or resumen["figuras"]
        if not poblada:
            vacias.append((nombre, PESTANAS_ESPERADAS[nombre], resumen, tiene_resultado))
    assert not vacias, f"pestanas sin poblar: {vacias}\nresumen completo: {detalles}"


def test_la_pestana_principal_muestra_la_tabla_de_precios(ventana_con_demo):
    """La pestana Principal pinta la tabla mensual y la parrilla de decision."""
    principal = ventana_con_demo.tabs["principal"]
    tablas = principal.findChildren(QTableWidget)
    assert tablas, "la pestana Principal deberia tener al menos una tabla"
    total_filas = sum(t.rowCount() for t in tablas)
    assert total_filas > 0, "las tablas de la pestana Principal estan vacias"

    resultado = ventana_con_demo.resultados[0]
    assert resultado.tabla is not None
    # La parrilla tiene 12 criterios y se muestran en alguna tabla
    numeros = {c.numero for c in resultado.criterios}
    assert numeros == set(range(1, 13))


def test_la_pestana_de_fuentes_muestra_la_procedencia(ventana_con_demo):
    """La pestana de Fuentes y avisos no puede quedar vacia."""
    pestana = ventana_con_demo.tabs["fuentes"]
    resumen = _resumen_poblado(pestana)
    assert resumen["textos"] > 0 or resumen["filas"] > 0, f"la pestana de fuentes esta vacia: {resumen}"


def test_la_ventana_admite_recarga_de_los_mismos_resultados(ventana_con_demo):
    """Volver a pintar los mismos resultados no rompe ninguna pestana."""
    ventana_con_demo._pintar_todo(ventana_con_demo.resultados[0])
    QApplication.processEvents()
    assert ventana_con_demo.pestanas.count() == len(PESTANAS_ESPERADAS)
    for nombre in PESTANAS_ESPERADAS:
        resumen = _resumen_poblado(ventana_con_demo.tabs[nombre])
        assert resumen["filas"] > 0 or resumen["textos"] > 0 or resumen["figuras"], (
            f"la pestana '{nombre}' se vacio al repintar: {resumen}"
        )


def test_el_analizador_de_la_ventana_es_offline(ventana):
    """La funcion de analisis de la ventana es la sustituida por la prueba."""
    import dml.analisis as analisis

    assert analisis.analizar_demo is ventana.analizador_falso
    resultado = analisis.analizar_demo("DEMO", ventana.config)
    assert resultado.ticker == "DEMO"
    assert ventana.llamadas_al_analizador["n"] >= 1
