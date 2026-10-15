# -*- coding: utf-8 -*-
"""Tipos de datos compartidos por toda la aplicacion.

Este modulo es la *interfaz estable* entre la capa de datos, los modelos
financieros, la interfaz grafica y la exportacion. No importa Qt ni ninguna
dependencia de presentacion: solo ``dataclasses``, ``typing`` y ``pandas``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

ND = "N/D"

# --------------------------------------------------------------------------
# Procedencia de los datos (seccion 2 del pliego: fuente, URL, fecha, metodo)
# --------------------------------------------------------------------------


@dataclass
class Fuente:
    """Procedencia de un dato: fuente, URL, fecha/hora y metodo de obtencion.

    Attributes:
        dato: nombre legible del dato ("TLR 4 semanas", "Spot NVDA", ...).
        valor: valor textual ya formateado (puede ser ``N/D``).
        fuente: nombre de la fuente ("Investing.com", "FRED", "Yahoo Finance"...).
        url: URL consultada, si aplica.
        consultado: fecha y hora ISO de la consulta.
        metodo: ``API``, ``scraping``, ``respaldo``, ``manual``, ``calculo`` o ``N/D``.
        advertencia: motivo por el que el dato falta o aviso asociado.
        categoria: agrupacion para la pestana "Fuentes y avisos".
    """

    dato: str
    valor: Any = None
    fuente: str = ""
    url: str = ""
    consultado: str = ""
    metodo: str = ""
    advertencia: str = ""
    categoria: str = "general"

    @property
    def ok(self) -> bool:
        """True si el dato tiene un valor utilizable."""
        return self.valor is not None and str(self.valor).strip() not in {"", ND}

    @property
    def es_respaldo(self) -> bool:
        """True si el dato se obtuvo de una fuente de respaldo."""
        return self.metodo == "respaldo" or "respaldo" in (self.fuente or "").lower()


class Fuentes:
    """Registro acumulativo de la procedencia de todos los datos del analisis."""

    def __init__(self) -> None:
        self._items: List[Fuente] = []

    def add(
        self,
        dato: str,
        valor: Any = None,
        fuente: str = "",
        url: str = "",
        metodo: str = "",
        advertencia: str = "",
        categoria: str = "general",
    ) -> Fuente:
        """Registra una fuente y devuelve el objeto creado."""
        from .util import ahora_iso

        item = Fuente(
            dato=dato,
            valor=valor,
            fuente=fuente,
            url=url,
            consultado=ahora_iso(),
            metodo=metodo or "N/D",
            advertencia=advertencia,
            categoria=categoria,
        )
        self._items.append(item)
        return item

    def extender(self, otras: "Fuentes") -> None:
        """Incorpora los registros de otro objeto :class:`Fuentes`."""
        if otras is not None:
            self._items.extend(otras.items())

    @property
    def items(self) -> List[Fuente]:
        """Lista de registros en orden de insercion."""
        return list(self._items)

    def como_dataframe(self) -> pd.DataFrame:
        """Devuelve el registro como ``DataFrame`` listo para la interfaz."""
        filas = [
            {
                "Dato": f.dato,
                "Valor": f.valor if f.valor is not None else ND,
                "Fuente": f.fuente or ND,
                "Metodo": f.metodo,
                "URL": f.url,
                "Consultado": f.consultado,
                "Advertencia": f.advertencia,
                "Categoria": f.categoria,
            }
            for f in self._items
        ]
        return pd.DataFrame(filas, columns=["Dato", "Valor", "Fuente", "Metodo", "URL", "Consultado", "Advertencia", "Categoria"])

    def por_metodo(self, metodo: str) -> List[Fuente]:
        """Filtra los registros por metodo de obtencion."""
        return [f for f in self._items if f.metodo == metodo]

    def faltantes(self) -> List[Fuente]:
        """Registros sin valor utilizable (los que se mostraran como N/D)."""
        return [f for f in self._items if not f.ok]

    def advertencias(self) -> List[str]:
        """Mensajes de advertencia deduplicados, en orden de aparicion."""
        vistas: List[str] = []
        for f in self._items:
            if f.advertencia and f.advertencia not in vistas:
                vistas.append(f.advertencia)
        return vistas

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._items)

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self._items)


@dataclass
class Evidence:
    """Un dato numerico o una serie temporal con su procedencia.

    En la interfaz, ``ok`` falso se pinta como ``N/D`` con un icono de
    advertencia cuyo tooltip muestra ``fuente``, ``metodo``, ``url`` y
    ``nota``.
    """

    value: Optional[float] = None
    serie: Optional[pd.Series] = None
    fuente: str = ""
    url: str = ""
    metodo: str = ""
    consultado: str = ""
    nota: str = ""

    @property
    def ok(self) -> bool:
        """True si hay un valor escalar o una serie con datos."""
        from .util import a_float

        if self.value is not None and a_float(self.value) is not None:
            return True
        return self.serie is not None and len(self.serie) > 0

    @property
    def es_respaldo(self) -> bool:
        """True si el dato proviene de una fuente de respaldo."""
        return self.metodo == "respaldo"

    def texto(self, decimales: int = 4) -> str:
        """Representacion corta del dato para tablas y tooltips."""
        from .util import fmt_num

        return fmt_num(self.value, decimales) if self.value is not None else ND


@dataclass
class Tasas:
    """Tasas de referencia de EE.UU. (en fraccion anual) y sus series mensuales.

    ``metodos`` guarda, por clave, el metodo realmente usado para cada tasa:
    ``investing``, ``fred`` (respaldo), ``yahoo`` (respaldo) o ``manual``.
    """

    tbill_4w: Optional[float] = None
    ust_10y: Optional[float] = None
    ust_30y: Optional[float] = None
    ev_tbill_4w: Evidence = field(default_factory=Evidence)
    ev_ust_10y: Evidence = field(default_factory=Evidence)
    ev_ust_30y: Evidence = field(default_factory=Evidence)
    serie_tbill_mensual: Optional[pd.Series] = None
    serie_10y_mensual: Optional[pd.Series] = None
    serie_30y_mensual: Optional[pd.Series] = None
    metodos: Dict[str, str] = field(default_factory=dict)
    diferencias_pb: Dict[str, float] = field(default_factory=dict)
    advertencias: List[str] = field(default_factory=list)
    #: Tasas que no se pudieron obtener y quedan pendientes de captura manual.
    pendientes_manual: List[str] = field(default_factory=list)

    @property
    def tlr(self) -> Optional[float]:
        """Tasa libre de riesgo de referencia: T-Bill de 4 semanas."""
        return self.tbill_4w

    def metodo_de(self, clave: str) -> str:
        """Metodo usado para la tasa ``clave`` (tbill_4w, ust_10y, ust_30y)."""
        return self.metodos.get(clave, "N/D")


@dataclass
class Fundamental:
    """Multiplos y datos fundamentales de la empresa y de su sector."""

    sector: str = "DESCONOCIDO"
    industria: str = ""
    per: Optional[float] = None
    per_sector: Optional[float] = None
    eps: Optional[float] = None
    eps_forecast: Optional[float] = None
    p_fcf: Optional[float] = None
    p_fcf_sector: Optional[float] = None
    dividend_rate: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    free_cash_flow: Optional[float] = None
    beta_publicada: Optional[float] = None
    nombre: str = ""
    bolsa: str = ""
    moneda: str = "USD"
    ev_per: Evidence = field(default_factory=Evidence)
    ev_per_sector: Evidence = field(default_factory=Evidence)
    ev_eps: Evidence = field(default_factory=Evidence)
    ev_eps_forecast: Evidence = field(default_factory=Evidence)
    ev_p_fcf: Evidence = field(default_factory=Evidence)
    ev_p_fcf_sector: Evidence = field(default_factory=Evidence)
    ev_dividendo: Evidence = field(default_factory=Evidence)
    ev_beta_publicada: Evidence = field(default_factory=Evidence)
    notas: List[str] = field(default_factory=list)


@dataclass
class TablaTicker:
    """Tabla mensual del analisis: precios, rendimientos, TLR e indice."""

    index: pd.Index = field(default_factory=lambda: pd.Index([], dtype="datetime64[ns]"))
    precio: List[float] = field(default_factory=list)
    r_accion: List[Optional[float]] = field(default_factory=list)
    r_mercado: List[Optional[float]] = field(default_factory=list)
    tlr_anual: List[Optional[float]] = field(default_factory=list)
    tlr_mensual: List[Optional[float]] = field(default_factory=list)
    prh_mensual: List[Optional[float]] = field(default_factory=list)
    indice: List[Optional[float]] = field(default_factory=list)

    def como_dataframe(self) -> pd.DataFrame:
        """Devuelve la tabla mensual como ``DataFrame``."""
        return pd.DataFrame(
            {
                "Fecha": list(self.index),
                "Precio": self.precio,
                "R_Accion": self.r_accion,
                "Indice": self.indice,
                "R_Mercado": self.r_mercado,
                "TLR_anual": self.tlr_anual,
                "TLR_mensual": self.tlr_mensual,
                "PRH_mensual": self.prh_mensual,
            }
        )


@dataclass
class MetricasRiesgo:
    """Metricas de riesgo calculadas sobre los rendimientos mensuales.

    Todas las desviaciones y ratios se expresan en terminos **anuales**
    (``sigma_anual = sigma_mensual * sqrt(12)``), salvo ``sigma_mensual``.
    """

    sigma_mensual: Optional[float] = None
    sigma_anual: Optional[float] = None
    riesgo_total: Optional[float] = None
    riesgo_sistematico: Optional[float] = None
    riesgo_no_sistematico: Optional[float] = None
    var_95: Optional[float] = None
    var_99: Optional[float] = None
    sharpe: Optional[float] = None
    treynor: Optional[float] = None
    max_drawdown: Optional[float] = None
    nota_sigma: str = ""


@dataclass
class ResultadoOLS:
    """Resultado completo del modelo econometrico MCO de Precio ~ periodo."""

    n: int = 0
    metodo: str = ""
    intercepto: float = 0.0
    pendiente: float = 0.0
    se_intercepto: float = 0.0
    se_pendiente: float = 0.0
    t_intercepto: float = 0.0
    t_pendiente: float = 0.0
    p_intercepto: float = 0.0
    p_pendiente: float = 0.0
    r2: float = 0.0
    r2_ajustado: float = 0.0
    f_stat: float = 0.0
    f_pvalue: float = 0.0
    se_regresion: float = 0.0
    durbin_watson: float = 0.0
    jarque_bera: float = 0.0
    jarque_bera_p: float = 0.0
    breusch_pagan: float = 0.0
    breusch_pagan_p: float = 0.0
    residuos: List[float] = field(default_factory=list)
    ajustados: List[float] = field(default_factory=list)
    periodos: List[int] = field(default_factory=list)
    precios: List[float] = field(default_factory=list)
    meses_pronostico: int = 12
    pronostico_precio: Optional[float] = None
    pronostico_li: Optional[float] = None
    pronostico_ls: Optional[float] = None
    veredicto: str = ND
    justificacion: str = ""

    def como_dataframe_coeficientes(self) -> pd.DataFrame:
        """Tabla de coeficientes con errores estandar, t y p-value."""
        return pd.DataFrame(
            [
                {
                    "Coeficiente": "Intercepto",
                    "Valor": self.intercepto,
                    "Error estandar": self.se_intercepto,
                    "t": self.t_intercepto,
                    "p-value": self.p_intercepto,
                },
                {
                    "Coeficiente": "Pendiente (periodo)",
                    "Valor": self.pendiente,
                    "Error estandar": self.se_pendiente,
                    "t": self.t_pendiente,
                    "p-value": self.p_pendiente,
                },
            ]
        )

    def como_dataframe_residuos(self) -> pd.DataFrame:
        """Tabla de residuos y valores ajustados por periodo."""
        return pd.DataFrame(
            {
                "Periodo": self.periodos,
                "Precio observado": self.precios,
                "Precio ajustado": self.ajustados,
                "Residuo": self.residuos,
            }
        )


@dataclass
class Criterio:
    """Un criterio binario de la parrilla de decision."""

    numero: int
    nombre: str
    optimo: str = ""
    valor: Any = None
    comparacion: Any = None
    cumple: bool = False
    calificacion: int = 0
    fuente: str = ""
    ruta: str = ""
    nota: str = ""
    activo: bool = True
    unidad: str = "numero"   # numero | porcentaje | moneda | texto
    formula: str = ""


@dataclass
class Params:
    """Parametros efectivos del analisis expuestos y editables en la interfaz.

    Cualquier cambio aqui recalcula los modelos sin volver a descargar datos.
    """

    modo: str = "estandar"          # estandar | excel
    meses: int = 60
    indice: str = "^GSPC"
    r: Optional[float] = None       # TLR anual (fraccion)
    q: Optional[float] = None       # dividend yield anual (fraccion)
    sigma: Optional[float] = None   # volatilidad anual (fraccion)
    T: Optional[float] = None       # tiempo al vencimiento en anios
    strike: Optional[float] = None  # K usado (forward o manual)
    strike_modo: str = "forward"    # forward | manual
    beta_max: float = 1.10
    r2_min: float = 0.70
    margen_tlr_extra: float = 0.01
    delta_call_min: float = 0.50
    comprar_min: float = 0.70
    mantener_min: float = 0.40
    meses_pronostico: int = 12
    criterios_activos: Dict[int, bool] = field(default_factory=dict)
    vencimiento: Optional[date] = None


@dataclass
class DatosTicker:
    """Todo lo que la capa de datos entrega a los modelos para un ticker."""

    ticker: str
    nombre: str = ""
    bolsa: str = ""
    moneda: str = "USD"
    sector: str = ""
    spot: Evidence = field(default_factory=Evidence)
    precios_mensuales: Evidence = field(default_factory=Evidence)
    precios_diarios: Evidence = field(default_factory=Evidence)
    indice_nombre: str = "^GSPC"
    indice_mensual: Evidence = field(default_factory=Evidence)
    tasas: Tasas = field(default_factory=Tasas)
    fundamentales: Fundamental = field(default_factory=Fundamental)
    macd_datos: Optional[pd.DataFrame] = None
    macd_senal: str = ND
    macd_detalle: str = ""
    advertencias: List[str] = field(default_factory=list)
    demo: bool = False


@dataclass
class Estados:
    """Cadenas de estado de un dato, con formula y explicacion para tooltips."""

    tlr: str = "N/D"
    per: str = "N/D"
    eps: str = "N/D"
    pfcf: str = "N/D"
    renta_per: str = "N/D"
    rdr: str = "N/D"
    capm: str = "N/D"
    beta: str = "N/D"
    r2: str = "N/D"
    trg: str = "N/D"
    forward: str = "N/D"
    delta: str = "N/D"
    tecnico: str = "N/D"

    def como_diccionario(self) -> Dict[str, str]:
        """Diccionario con el estado de cada criterio."""
        return {
            "PER": self.per,
            "EPS": self.eps,
            "Tecnico": self.tecnico,
            "Price to FCF": self.pfcf,
            "CAPM": self.capm,
            "Beta": self.beta,
            "Renta PER": self.renta_per,
            "RDR": self.rdr,
            "R2": self.r2,
            "TRG": self.trg,
            "Forward": self.forward,
            "Delta": self.delta,
        }


@dataclass
class ResultadoAnalisis:
    """Resultado completo del analisis de un ticker, listo para pintar en la interfaz."""

    ticker: str
    fecha_analisis: str = ""
    modo: str = "estandar"
    nombre: str = ""
    bolsa: str = ""
    moneda: str = "USD"
    sector: str = ""
    demo: bool = False

    spot: Optional[float] = None
    precios: Optional[pd.Series] = None
    indice_nombre: str = "^GSPC"
    indice_precios: Optional[pd.Series] = None
    tabla: TablaTicker = field(default_factory=TablaTicker)
    fundamentales: Fundamental = field(default_factory=Fundamental)
    tasas: Tasas = field(default_factory=Tasas)

    tlr: Optional[float] = None
    tlr_mensual_valor: Optional[float] = None
    beta_cov: Optional[float] = None
    beta_ols: Optional[float] = None
    beta_publicada: Optional[float] = None
    prh: Optional[float] = None
    prh_mensual_promedio: Optional[float] = None
    rend_capm: Optional[float] = None
    precio_objetivo: Optional[float] = None
    trg_valor: Optional[float] = None
    precio_proyectado_trg: Optional[float] = None

    ols: Optional[ResultadoOLS] = None
    riesgo: MetricasRiesgo = field(default_factory=MetricasRiesgo)

    q: Optional[float] = None
    b: Optional[float] = None
    T: Optional[float] = None
    strike: Optional[float] = None
    strike_modo: str = "forward"
    vencimiento: Optional[date] = None
    griegas_call: Dict[str, Optional[float]] = field(default_factory=dict)
    griegas_put: Dict[str, Optional[float]] = field(default_factory=dict)
    paridad: Dict[str, Any] = field(default_factory=dict)
    griegas_fd: Dict[str, Any] = field(default_factory=dict)

    macd_senal: str = ND
    macd_detalle: str = ""
    macd_datos: Optional[pd.DataFrame] = None

    ruta_investing: Dict[str, str] = field(default_factory=dict)
    estados: Estados = field(default_factory=Estados)
    criterios: List[Criterio] = field(default_factory=list)
    calificacion: Optional[float] = None
    decision: str = ND
    params: Params = field(default_factory=Params)
    advertencias: List[str] = field(default_factory=list)
    #: Datos de origen en memoria: permiten recalcular sin volver a descargar.
    _datos: Any = field(default=None, repr=False, compare=False)

    @property
    def criterios_activos(self) -> List[Criterio]:
        """Criterios que participan en la calificacion."""
        return [c for c in self.criterios if c.activo]

    def manuales_pendientes(self) -> List[str]:
        """Tasas que no se obtuvieron y quedaron pendientes de captura manual.

        La interfaz las usa para preguntar al usuario **en el hilo principal**
        (Qt no permite abrir dialogos desde un hilo de trabajo).
        """
        if self.tasas is None:
            return []
        return list(getattr(self.tasas, "pendientes_manual", []) or [])

    def resumen(self) -> Dict[str, Any]:
        """Resumen corto usado por la barra de estado y la tabla comparativa."""
        return {
            "Ticker": self.ticker,
            "Calificacion": self.calificacion,
            "Decision": self.decision,
            "Spot": self.spot,
            "Precio objetivo": self.precio_objetivo,
            "Modo": self.modo,
        }
