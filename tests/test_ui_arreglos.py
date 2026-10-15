# -*- coding: utf-8 -*-
"""Pruebas de la interfaz para los arreglos solicitados.

Cubren, sin red y en modo *offscreen*:

1. **Progreso del analisis**: la barra se ve y muestra el porcentaje desde el
   primer momento, avanza con el latido y termina en el 100 %.
2. **Dialogo de exportacion**: los botones dicen "Todos", "Solo este" y
   "Cancelar" (nada de "Yes"/"No"/"Cancel"), y cada uno hace lo que promete.
3. **Panel de parametros**: solo se envian como *override* los controles que el
   usuario ha tocado de verdad, y "Restablecer" los deja de enviar. Antes, un
   dato ``N/D`` hacia que el valor por defecto del control (recortado al minimo)
   sustituyera al dato real.
4. **Historial**: anadir varios analisis de golpe no dispara repintados y el
   resumen inferior queda sincronizado.
"""

from __future__ import annotations

import gc
import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.qpa.*=false")

pytest.importorskip("PySide6", reason="PySide6 es necesario para las pruebas de interfaz")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def app_qt():
    """``QApplication`` unica para todo el modulo (obligatorio en Qt)."""
    aplicacion = QApplication.instance()
    if aplicacion is None:
        aplicacion = QApplication([])
    yield aplicacion
    aplicacion.processEvents()


@pytest.fixture
def ventana(app_qt, monkeypatch):
    """Ventana principal en modo DEMO, sin red y sin guardar el tema en disco.

    Se sustituye ``analizar_demo`` por un analizador **offline** que respeta el
    ticker pedido: asi las pruebas pueden construir varios analisis distintos
    (necesario para el historial y para el dialogo de alcance) sin tocar la red.
    """
    from dml.analisis import analizar_demo as analizar_demo_real
    from dml.core.config import cargar_config
    from dml.ui.ventana_principal import VentanaPrincipal

    config = cargar_config(None)
    config.setdefault("ui", {})["guardar_geometria"] = False

    def analizador_falso(ticker="DEMO", *args, **kwargs):
        """Devuelve un analisis DEMO del ticker solicitado, sin conexion."""
        kwargs.pop("fuentes", None)
        return analizar_demo_real(str(ticker or "DEMO"), config, **kwargs)

    monkeypatch.setattr("dml.analisis.analizar_demo", analizador_falso)

    principal = VentanaPrincipal(config=config, demo=True)
    yield principal

    # Liberacion **explicita** de todo lo que cuelga de la ventana. Cada ventana
    # crea 11 pestanas con sus lienzos de matplotlib y varias tablas con modelos
    # propios; dejar que Qt los destruya "cuando pueda" hace que 27 ventanas
    # seguidas acumulen cientos de objetos C++ y la suite acabe muriendo con una
    # violacion de acceso. Con ``processEvents`` + ``gc.collect`` se comprueba que
    # cada ventana se libera antes de construir la siguiente.
    principal.close()
    principal.setParent(None)
    principal.deleteLater()
    app_qt.processEvents()
    app_qt.sendPostedEvents(None, QEvent.DeferredDelete)
    app_qt.processEvents()
    gc.collect()


def _esperar(condicion, app_qt, milisegundos: int = 15000) -> bool:
    """Procesa eventos hasta que ``condicion()`` se cumpla o se agote el tiempo."""
    import time

    limite = time.monotonic() + milisegundos / 1000.0
    while time.monotonic() < limite:
        app_qt.processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return bool(condicion())


# ==========================================================================
# 1. Progreso del analisis
# ==========================================================================
def test_la_barra_de_progreso_empieza_visible_y_a_cero(ventana):
    """Al empezar un analisis la barra (y su porcentaje) quedan visibles y a cero."""
    ventana.show()
    try:
        ventana._reiniciar_progreso(1)

        assert ventana.progreso.isVisible(), "la barra de progreso debe verse al iniciar el analisis"
        assert ventana.etiqueta_progreso.isVisible(), "el porcentaje debe verse al iniciar el analisis"
        assert ventana.progreso.value() == 0
        assert ventana.etiqueta_progreso.text() == "0 %"
    finally:
        ventana.hide()


def test_el_porcentaje_sigue_al_avance_real(ventana):
    """Cada aviso del hilo se refleja en la barra y en la etiqueta de porcentaje."""
    ventana._reiniciar_progreso(1)
    ventana._actualizar_progreso("Descargando serie mensual...", 0.12)
    assert ventana.progreso.value() == 12
    assert ventana.etiqueta_progreso.text() == "12 %"

    ventana._actualizar_progreso("Consultando Investing.com...", 0.52)
    assert ventana.progreso.value() == 52
    assert ventana.etiqueta_progreso.text() == "52 %"
    assert "Investing" in ventana.etiqueta_estado.text()


def test_el_progreso_nunca_retrocede(ventana):
    """Un aviso con una fraccion menor no hace retroceder la barra."""
    ventana._reiniciar_progreso(1)
    ventana._actualizar_progreso("paso largo", 0.80)
    ventana._actualizar_progreso("paso corto", 0.20)
    assert ventana.progreso.value() == 80


def test_el_latido_avanza_la_barra_sin_pasarse_del_techo(ventana, monkeypatch):
    """El latido rellena los huecos entre avisos, pero no inventa el 100 %."""
    from dml.ui.ventana_principal import TOPE_TRABAJANDO

    class TrabajadorFalso:
        """Trabajador que se declara siempre en ejecucion."""

        def isRunning(self) -> bool:  # noqa: N802 - API de Qt
            return True

    ventana._trabajador = TrabajadorFalso()  # type: ignore[assignment]
    ventana._reiniciar_progreso(1)
    ventana._actualizar_progreso("paso en curso", 0.60)

    ventana._tic_progreso()
    primero = ventana.progreso.value()
    assert 0 < primero <= TOPE_TRABAJANDO, f"el latido debe avanzar sin llegar al 100 % (valor {primero})"

    # Con el techo alcanzado, el latido no inventa progreso.
    ventana._actualizar_progreso("casi listo", 1.0)
    ventana._tic_progreso()
    assert ventana.progreso.value() <= 100


def test_al_terminar_el_progreso_muestra_el_cien_por_ciento(ventana):
    """Al concluir, la barra marca el 100 % antes de ocultarse."""
    ventana._reiniciar_progreso(1)
    ventana._concluir_progreso()
    assert ventana.progreso.value() == 100
    assert ventana.etiqueta_progreso.text() == "100 %"


def test_el_analisis_demo_deja_el_progreso_completo(ventana, app_qt):
    """Un analisis completo deja la barra en el 100 % y oculta las etiquetas."""
    ventana.campo_ticker.setText("DEMO")
    ventana.analizar()
    terminado = _esperar(lambda: ventana._trabajador is not None and not ventana._trabajador.isRunning(), app_qt)
    assert terminado, "el analisis DEMO no termino a tiempo"
    app_qt.processEvents()

    assert ventana.progreso.value() == 100
    assert ventana.resultados, "el analisis no dejo resultados"
    # Se oculta pasados unos milisegundos (QTimer.singleShot), no en el acto.
    assert _esperar(lambda: not ventana.progreso.isVisible(), app_qt, 3000)


# ==========================================================================
# 2. Dialogo de exportacion
# ==========================================================================
def _pulsar_boton(registro: dict, texto: str):
    """Devuelve un ``exec`` que pulsa el boton con ese texto.

    Se pulsa con ``click()`` (no con ``done()``) porque es lo que hace un usuario:
    asi ``clickedButton()`` devuelve el boton correcto y el codigo bajo prueba
    puede distinguir "Todos" de "Solo este".
    """

    def _exec(self) -> int:  # noqa: A003 - firma de Qt
        registro["botones"] = [b.text().replace("&", "") for b in self.buttons()]
        for boton in self.buttons():
            if boton.text().replace("&", "") == texto:
                registro["pulsado"] = texto
                boton.click()
                return 0
        raise AssertionError(f"no existe un boton con el texto {texto!r}: {registro['botones']}")

    return _exec


def _cerrar_con(registro: dict, texto: str):
    """Devuelve un ``exec`` que cierra el dialogo pulsando ``texto`` (o Escape si no esta)."""

    def _exec(self) -> int:  # noqa: A003 - firma de Qt
        registro["botones"] = [b.text().replace("&", "") for b in self.buttons()]
        for boton in self.buttons():
            if boton.text().replace("&", "") == texto:
                boton.click()
                return 0
        self.reject()
        return 0

    return _exec


def test_el_dialogo_de_alcance_usa_botones_en_espanol(ventana, monkeypatch):
    """Los botones son "Todos", "Solo este" y "Cancelar" (no "Yes"/"No"/"Cancel")."""
    registro: dict = {}
    monkeypatch.setattr(QMessageBox, "exec", _cerrar_con(registro, "Cancelar"))
    ventana.resultados = [object(), object()]  # type: ignore[list-item]
    assert ventana._preguntar_alcance_exportacion() is None, "Cancelar debe abortar la exportacion"
    # Se comprueba el conjunto: Qt puede reordenar los botones segun su rol.
    assert set(registro["botones"]) == {"Todos", "Solo este", "Cancelar"}, registro["botones"]
    assert not {"Yes", "No", "Cancel", "&Yes", "&No"} & set(registro["botones"]), registro["botones"]


def test_elegir_todos_exporta_todos_los_analisis(ventana, monkeypatch):
    """El boton "Todos" devuelve la lista completa."""
    from dml.analisis import analizar_demo

    ventana.resultados = [analizar_demo("DEMO", ventana.config), analizar_demo("DEMO2", ventana.config)]
    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Todos"))
    elegidos = ventana._preguntar_alcance_exportacion()
    assert elegidos is not None and len(elegidos) == 2


def test_elegir_solo_este_exporta_el_seleccionado(ventana, monkeypatch):
    """El boton "Solo este" devuelve solo el analisis seleccionado en el historial."""
    from dml.analisis import analizar_demo
    from dml.ui.ventana_principal import cargar_demo_en_ventana

    cargar_demo_en_ventana(ventana, ["DEMO", "DEMO2"])
    assert len(ventana.resultados) == 2
    ventana.historial.lista.setCurrentRow(1)

    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Solo este"))
    elegidos = ventana._preguntar_alcance_exportacion()
    assert elegidos is not None and len(elegidos) == 1
    assert elegidos[0].ticker == ventana.resultados[1].ticker


def test_un_solo_analisis_no_pregunta_el_alcance(ventana, monkeypatch):
    """Con un unico analisis no tiene sentido preguntar por el alcance."""
    from dml.analisis import analizar_demo

    ventana.resultados = [analizar_demo("DEMO", ventana.config)]

    def prohibido(*_a, **_k):  # pragma: no cover - no debe llamarse
        raise AssertionError("no se debe preguntar el alcance con un solo analisis")

    monkeypatch.setattr(QMessageBox, "exec", prohibido)
    assert len(ventana._preguntar_alcance_exportacion() or []) == 1


def test_el_dialogo_de_formulas_usa_botones_en_espanol(ventana, monkeypatch):
    """El dialogo de formulas ofrece "Formulas", "Solo valores" y "Cancelar"."""
    registro: dict = {}
    monkeypatch.setattr(QMessageBox, "exec", _cerrar_con(registro, "Cancelar"))
    assert ventana._preguntar_formulas() is None
    assert set(registro["botones"]) == {"Formulas", "Solo valores", "Cancelar"}, registro["botones"]


def test_elegir_formulas_devuelve_true(ventana, monkeypatch):
    """El boton "Formulas" pide el libro con formulas reales."""
    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Formulas"))
    assert ventana._preguntar_formulas() is True


def test_elegir_solo_valores_devuelve_false(ventana, monkeypatch):
    """El boton "Solo valores" pide el informe estatico."""
    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Solo valores"))
    assert ventana._preguntar_formulas() is False


def test_cancelar_el_dialogo_de_formulas_no_exporta(ventana, monkeypatch):
    """Cancelar en el dialogo de formulas detiene la exportacion."""
    from dml.analisis import analizar_demo

    ventana.resultados = [analizar_demo("DEMO", ventana.config)]
    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Cancelar"))
    assert ventana._preguntar_formulas() is None


def test_exportar_pregunta_antes_de_pedir_el_archivo(ventana, monkeypatch):
    """El alcance y el formato se preguntan antes del "Guardar como..."."""
    from dml.analisis import analizar_demo

    ventana.resultados = [analizar_demo("DEMO", ventana.config), analizar_demo("DEMO2", ventana.config)]
    monkeypatch.setattr(QMessageBox, "exec", _pulsar_boton({}, "Cancelar"))
    llamado = {"n": 0}

    def file_dialog_prohibido(*_a, **_k):  # pragma: no cover - no debe llamarse
        llamado["n"] += 1
        return None

    monkeypatch.setattr(QFileDialog, "exec", file_dialog_prohibido)
    ventana.exportar_excel()
    assert llamado["n"] == 0, "no se debe abrir el guardar-como si el usuario cancela antes"


# ==========================================================================
# 3. Panel de parametros: solo lo que el usuario toca
# ==========================================================================
def test_sin_ediciones_el_panel_no_envia_overrides(ventana):
    """Cargar un analisis no convierte sus valores en overrides."""
    from dml.analisis import analizar_demo

    resultado = analizar_demo("DEMO", ventana.config)
    ventana.parametros.cargar(resultado, ventana.config)
    overrides = ventana.parametros.overrides()

    for clave in ("r", "q", "sigma", "T", "strike", "beta_max"):
        assert clave not in overrides, f"{clave} no deberia enviarse sin edicion del usuario"
    # Las casillas de criterios si se envian: definen la calificacion.
    assert len(overrides.get("criterios_activos", {})) == 12


def test_el_panel_no_envia_modo_indice_ni_meses(ventana):
    """Modo, indice y meses los edita la barra superior, no el panel."""
    from dml.analisis import analizar_demo

    resultado = analizar_demo("DEMO", ventana.config)
    ventana.parametros.cargar(resultado, ventana.config)
    overrides = ventana.parametros.overrides()
    for clave in ("modo", "indice", "meses"):
        assert clave not in overrides, f"{clave} lo fija la barra superior"


def test_la_barra_superior_es_la_fuente_de_modo_indice_y_meses(ventana):
    """Los tres controles de la barra si viajan como override (y con su valor)."""
    ventana.combo_modo.setCurrentIndex(ventana.combo_modo.findData("excel"))
    ventana.combo_indice.setCurrentIndex(ventana.combo_indice.findData("^DJI"))
    ventana.spin_meses.setValue(84)

    overrides = ventana._overrides_actuales()
    assert overrides["modo"] == "excel"
    assert overrides["indice"] == "^DJI"
    assert overrides["meses"] == 84


def test_editar_un_control_lo_envia_como_override(ventana):
    """Al mover la sigma, ese valor (y solo ese) pasa al recalculo."""
    from dml.analisis import analizar_demo

    resultado = analizar_demo("DEMO", ventana.config)
    panel = ventana.parametros
    panel.cargar(resultado, ventana.config)
    assert "sigma" not in panel.overrides()

    panel.sp_sigma.setValue(0.33)
    panel._marcar_tocados()
    overrides = panel.overrides()
    assert overrides.get("sigma") == pytest.approx(0.33, rel=1e-6)
    assert "r" not in overrides and "q" not in overrides


def test_un_dato_ausente_no_se_convierte_en_override(ventana):
    """Un dato ``N/D`` deja el control quieto: no impone su valor por defecto.

    Es el caso que hacia que una sigma desconocida acabara valiendo 0,0001 en
    Black-Scholes y que la TLR ausente se evaluara como 0 %.
    """
    from dml.analisis import analizar_demo
    from dml.core.tipos import ResultadoAnalisis

    resultado = analizar_demo("DEMO", ventana.config)
    vacio = ResultadoAnalisis(ticker="VACIO")
    vacio.tlr = None
    panel = ventana.parametros
    panel.cargar(vacio, ventana.config)
    assert "r" not in panel.overrides(), "la TLR ausente no debe enviarse como 0"

    panel.cargar(resultado, ventana.config)
    assert "sigma" not in panel.overrides()


def test_restablecer_deja_de_enviar_los_valores_editados(ventana):
    """Tras "Restablecer", el analisis vuelve a usar los valores de mercado."""
    from dml.analisis import analizar_demo

    resultado = analizar_demo("DEMO", ventana.config)
    panel = ventana.parametros
    panel.cargar(resultado, ventana.config)
    panel.sp_sigma.setValue(0.42)
    panel._marcar_tocados()
    assert "sigma" in panel.overrides()

    panel.restablecer()
    assert "sigma" not in panel.overrides()


# ==========================================================================
# 4. Historial: rellenar de golpe sin repintar
# ==========================================================================
def test_anadir_varios_analisis_de_golpe_no_avisa_por_cada_uno(ventana, app_qt):
    """``sin_avisar`` bloquea la senal mientras se rellena el historial."""
    from dml.analisis import analizar_demo

    avisos: list = []
    ventana.historial.seleccionado.connect(lambda fila: avisos.append(fila))
    ventana.historial.limpiar()

    with ventana.historial.sin_avisar():
        for ticker in ("DEMO", "DEMO2", "DEMO3"):
            ventana.historial.agregar(analizar_demo(ticker, ventana.config))
    app_qt.processEvents()

    assert len(ventana.historial.resultados()) == 3
    assert avisos == [], f"no deberia avisar mientras se bloquea la senal: {avisos}"
    assert "DEMO3" in ventana.historial.resumen.text(), "el resumen debe quedar sincronizado"


def test_el_resumen_del_historial_se_sincroniza_al_mostrar(ventana, app_qt):
    """``sincronizar_resumen`` refleja la fila seleccionada."""
    from dml.analisis import analizar_demo

    ventana.historial.limpiar()
    ventana.historial.agregar(analizar_demo("DEMO", ventana.config))
    ventana.historial.agregar(analizar_demo("DEMO2", ventana.config))
    ventana.historial.lista.setCurrentRow(0)
    ventana.historial.sincronizar_resumen()
    assert "DEMO:" in ventana.historial.resumen.text()


# ==========================================================================
# 5. Desplazamiento de las pestanas
# ==========================================================================
def test_todas_las_pestanas_tienen_area_con_desplazamiento(ventana):
    """Cada pestana envuelve su contenido en un ``QScrollArea``.

    Sin el, lo que no cabia en la ventana quedaba fuera de la vista y **no habia
    forma de llegar a ello**: le pasaba a Principal, Bonos, Fuentes, Econometrico
    y Griegas (las otras seis ya se envolvian a si mismas).
    """
    from PySide6.QtWidgets import QScrollArea

    sin_scroll = [nombre for nombre, pestana in ventana.tabs.items() if not pestana.findChildren(QScrollArea)]
    assert not sin_scroll, f"pestanas sin area de desplazamiento: {sin_scroll}"


def test_el_contenido_largo_se_puede_desplazar(ventana, app_qt):
    """Con contenido mas alto que la pestana, la barra vertical permite bajar."""
    from PySide6.QtWidgets import QScrollArea

    from dml.ui.ventana_principal import cargar_demo_en_ventana

    ventana.resize(1200, 700)
    ventana.show()
    try:
        cargar_demo_en_ventana(ventana, ["DEMO"])
        app_qt.processEvents()
        desplazables = []
        for nombre, pestana in ventana.tabs.items():
            area = pestana.findChildren(QScrollArea)[0]
            barra = area.verticalScrollBar()
            if barra.maximum() <= 0:
                continue
            desplazables.append(nombre)
            # La barra debe llegar de verdad al final (ultimo bloque visible).
            barra.setValue(barra.maximum())
            app_qt.processEvents()
            assert barra.value() == barra.maximum(), f"{nombre}: la barra no llega al final"
        assert desplazables, "ninguna pestana necesito desplazamiento (¿se ha perdido el area?)"
        assert "principal" in desplazables, "la pestana Principal deberia poder desplazarse"
    finally:
        ventana.hide()


# ==========================================================================
# 6. Tema: no se repinta dos veces el mismo tema
# ==========================================================================
def test_cambiar_de_tema_no_repinta_dos_veces_el_mismo(ventana, monkeypatch):
    """``refrescar_tema`` es idempotente: pedir el tema ya aplicado no redibuja."""
    from dml.ui.tabs.principal import TabPrincipal

    pestana = TabPrincipal(ventana.config)
    llamadas = {"n": 0}
    original = pestana.refrescar_tema

    def contar(tema: str) -> None:
        llamadas["n"] += 1
        original(tema)

    monkeypatch.setattr(pestana, "refrescar_tema", contar)
    pestana.cargar([], None)
    pestana.refrescar_tema("claro")
    pestana.refrescar_tema("claro")
    pestana.refrescar_tema("oscuro")
    assert llamadas["n"] == 3
    # El guardia interno evita que el segundo "claro" vuelva a dibujar.
    assert pestana._tema_graficado == "oscuro"


def test_el_cambio_de_tema_aplica_la_paleta_y_el_qss(ventana, app_qt):
    """El tema cambia el QSS de la aplicacion y el texto del boton."""
    tema_inicial = ventana.tema
    ventana.cambiar_tema()
    assert ventana.tema != tema_inicial
    assert app_qt.styleSheet(), "deberia haber una hoja de estilo aplicada"
    assert ventana.boton_tema.text() in {"Tema claro", "Tema oscuro"}
    assert f"[tema {ventana.tema}]" in ventana.windowTitle()
    ventana.cambiar_tema()
    assert ventana.tema == tema_inicial
