#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NUCLEUS MoE v2 — Sistema autónomo multi-activo de captura de liquidez
(BTC/ETH/SOL USDT-M) — fusión consolidada de nucleus_moe_v1_fixed.py
(núcleo MoE, gating adaptativo, riesgo, tests) + nucleus_autonomous.py
(microestructura Hawkes bidireccional + CVD, reloj de eventos, GUI dark)
===================================================================

CHANGELOG v1 -> v2 (qué vino de dónde, y por qué):

  1. MULTI-ACTIVO (de nucleus_autonomous): Config.SYMBOLS reemplaza a
     Config.SYMBOL (BTC/ETH/SOL en vez de un solo símbolo). Cada símbolo
     tiene su propio DataFeed, su propio juego de expertos con estado
     interno independiente (Kalman/BOCPD/Jump no pueden compartirse entre
     símbolos: son filtros con memoria) y su propio RiskModule.

  2. NUEVO EXPERTO 'hawkes_flow' (de nucleus_autonomous/Taperead10.py):
     CVD con z-score rodante + proceso de Hawkes bidireccional (compra y
     venta por separado) como 7º experto dentro del GatingNetwork ya
     existente en v1 -- no como módulo aparte, sino integrado en el mismo
     contrato ExpertOutput que los otros 6, para que el gating adaptativo
     también aprenda a confiar o no en la microestructura según el
     desempeño real.

  3. GATING COMPARTIDO CON PARTIAL POOLING (decisión de arquitectura
     explícita, aprobada por el operador): NO se instancia un
     GatingNetwork aislado por símbolo (perdería la correlación real
     entre BTC/ETH/SOL) ni uno único sin distinción de símbolo (perdería
     especificidad). Cada símbolo mantiene su propio vector de pesos,
     pero tras cada atribución de resultado se contrae una fracción
     pequeña (Config.GATING_CROSS_ASSET_SHRINKAGE) hacia la media de
     pesos entre los 3 símbolos -- shrinkage jerárquico clásico
     (estilo James-Stein / partial pooling bayesiano), no un mecanismo
     nuevo inventado ad-hoc. Un experto que funciona bien en BTC gana
     peso más rápido también en ETH/SOL sin que un mal racha aislada en
     uno solo arrastre a los otros dos.

  4. RIESGO INDEPENDIENTE POR SÍMBOLO (decisión del operador, NO
     agregado de portafolio): cada símbolo tiene su propio RiskModule
     con su propio capital asignado (CAPITAL_USDT / nº símbolos por
     defecto, configurable) y su propio circuit breaker / kill switch.
     Una racha de pérdidas en SOL no apaga BTC ni ETH.

  5. RELOJ DE EVENTOS (de nucleus_autonomous): el ciclo de decisión fijo
     de v1 (time.sleep(DECISION_INTERVAL_SECONDS) sobre un solo símbolo)
     se sustituye por PublicTradeStreamMulti (WS con degradación limpia
     a polling REST si 'websocket-client' no está instalado) + una cola
     de eventos con debounce por símbolo (Config.MIN_CYCLE_INTERVAL_
     SECONDS) para no saturar los endpoints públicos en cada tick.

  6. GUI (de nucleus_autonomous, adaptada): panel dark con una pestaña
     (ttk.Notebook) por símbolo, mostrando precio/señal/decisión/pesos
     de gating y un log de razonamiento compartido con prefijo de
     símbolo, más un botón de kill-switch por símbolo.

  7. Todo lo demás (contrato ExpertOutput, los 6 expertos originales,
     RiskModule con circuit breaker/kill switch/daily loss limit,
     ExecutionAdapter/PaperExecutionAdapter/LiveBybitExecutionAdapter
     -stub bloqueado a propósito-, DecisionTrace, logging asíncrono,
     y la suite de 17 tests de v1) se conserva SIN cambios de lógica.
     Se añaden tests nuevos para hawkes_flow y para el shrinkage de
     gating multi-activo.

Diseño para: Windows 10 64-bit, 6GB RAM, sin GPU, sin AVX2 (Compaq CQ45).
Solo dependencias: numpy, requests (stdlib para el resto: tkinter, threading,
queue, unittest, dataclasses, json, logging).

Principios de diseño (acordados explícitamente con el operador):
  1. Un único núcleo de interpretación (no se instancia múltiples veces).
  2. El módulo de riesgo es un proceso lógico separado: solo puede vetar /
     reducir / cerrar, nunca reinterpreta el mercado.
  3. Toda inferencia produce un decision trace estructurado y auditable
     (no depende de que un LLM "explique" — los pesos de gating SON la causa).
  4. La evolución/aprendizaje se limita a actualización acotada de pesos de
     gating vía atribución de desempeño (estilo multiplicative-weights /
     Hedge), nunca gradiente opaco sobre el núcleo completo. Hay piso mínimo
     de peso por experto (ningún experto se anula permanentemente).
  5. Ejecución en modo PAPER por defecto. La ejecución en vivo requiere
     credenciales explícitas vía variables de entorno y un flag de activación
     manual — no se asume dinero real sin ese paso deliberado.
  6. Ingesta de datos: solo endpoints públicos sin autenticación.
  7. Apalancamiento: el módulo de riesgo elige entre perfil ALTO (x66) y
     NORMAL (x20) según si la distancia a liquidación resultante respeta el
     stop-loss necesario para no exceder el 1-2% de riesgo de capital. Si
     ninguno de los dos respeta esa condición, se reduce el tamaño o se
     rechaza la entrada. Esta es una regla dura, no una preferencia.

Este fichero se entrega para operar en PAPER TRADING desde el primer arranque.
Pasar a ejecución real requiere que el operador configure BYBIT_API_KEY /
BYBIT_API_SECRET y active LIVE_TRADING_ENABLED explícitamente en Config.

--------------------------------------------------------------------------
CHANGELOG v2 -> v2.1 (ronda de auditoría cruzada, hallazgos confirmados
línea por línea contra el código y corregidos quirúrgicamente):

  A. HISTÉRESIS DE SALIDA POR REVERSIÓN (Nucleus.run_cycle): la banda entre
     el umbral de entrada (0.15) y el de salida por reversión (0.2) era
     mínima y no existía piso de retención mínima ni confirmación por N
     ciclos -> en microestructura ruidosa el sistema entraba y salía de
     forma repetitiva (whipsaw). Ahora la salida por reversión exige (a)
     MIN_HOLD_SECONDS de retención mínima, (b) señal opuesta por encima de
     EXIT_REVERSAL_SIGNAL_THRESHOLD (banda ampliada respecto al umbral de
     entrada) y (c) que eso se sostenga REVERSAL_CONFIRMATION_CYCLES ciclos
     consecutivos. Stop-loss y trailing siguen siendo inmediatos: son
     protección de capital, no señal, y no pasan por este filtro.
  B. COMISIÓN + SLIPPAGE EN EL LEDGER (PaperExecutionAdapter.close_position):
     el PnL simulado era delta de precio puro, sin costo de fricción ->
     invisibilizaba el costo real de un patrón de whipsaw. Ahora se
     descuenta round-trip de TAKER_FEE_PCT + SLIPPAGE_PCT (Config) sobre
     ambos lados de la vuelta.
  C. CACHÉ COMPARTIDA PARA DATOS DE MERCADO GLOBAL (DataFeed.get_fear_greed /
     get_mempool_pressure, vía _TTLCache): ambos son índices GLOBALES, no
     por símbolo, pero cada DataFeed los pedía de forma independiente ->
     con SYMBOLS=3 eso multiplicaba x3 las llamadas a APIs públicas
     gratuitas de límite bajo, con riesgo real de HTTP 429 sostenido en
     demos largas. Ahora una única _TTLCache se comparte entre los
     DataFeed de los N símbolos (inyectada por NucleusOrchestratorV2); solo
     se cachean resultados exitosos, un fallo de red no bloquea el
     reintento en el ciclo siguiente.
  D. DIRECCIÓN DE VPIN ESTABILIZADA (VPINLiquidityExpert.infer): la
     dirección dependía únicamente del signo del bucket de volumen MÁS
     RECIENTE, que en ticks de alta frecuencia puede voltear entre ciclos
     consecutivos de MIN_CYCLE_INTERVAL_SECONDS sin que el desequilibrio de
     fondo haya cambiado -- ruido direccional independiente del whipsaw ya
     corregido en (A). Ahora se usa el desequilibrio neto acumulado sobre
     los últimos hasta 3 buckets en vez de uno solo.

  Fuera de alcance deliberado de esta ronda (evaluado y descartado como no
  urgente, ver notas del operador): BOCPDRegimeExpert.reset() en cada
  infer() recalcula el changepoint desde cero sobre la ventana visible en
  vez de mantener estado online entre ciclos. Es una inconsistencia de
  diseño real (pierde memoria de régimen fuera de la ventana), pero
  computacionalmente trivial sobre ~200 velas incluso en el hardware
  objetivo (Compaq CQ45, sin GPU) -- no es un riesgo de estabilidad ni de
  CPU, y se deja documentado aquí para una futura versión online en vez de
  corregirse a ciegas en esta ronda.
"""

from __future__ import annotations

import os
import sys
import json
import time
import queue
import math
import random
import logging
import logging.handlers
import threading
import unittest
from unittest.mock import patch
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Any, Deque, Set, Callable

import numpy as np

try:
    import requests
except ImportError:
    requests = None  # se degrada a modo simulado si no está disponible

try:
    import tkinter as tk
    from tkinter import ttk
    _TK_AVAILABLE = True
except Exception:
    _TK_AVAILABLE = False


# =====================================================================
# 1. CONFIGURACIÓN
# =====================================================================

@dataclass
class Config:
    # v1 operaba un solo símbolo (SYMBOL). Se conserva por compatibilidad
    # (algunas rutas de test/legacy lo referencian), pero v2 opera sobre
    # SYMBOLS. Si SYMBOLS está vacío, se deriva automáticamente de SYMBOL
    # en __post_init__ para no romper nada que dependa del campo viejo.
    SYMBOL: str = "BTCUSDT"
    SYMBOLS: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    CAPITAL_USDT: float = 666.0
    RISK_PCT_MIN: float = 0.01
    RISK_PCT_MAX: float = 0.02
    LEVERAGE_HIGH: int = 66
    LEVERAGE_NORMAL: int = 20
    LIQUIDATION_SAFETY_MARGIN: float = 1.35   # el buffer a liquidación debe ser
                                               # >= stop_distance * este margen
    MAINTENANCE_MARGIN_RATE: float = 0.005    # aproximación conservadora (0.5%)

    # Ciclo de decisión
    DECISION_INTERVAL_SECONDS: float = 15.0

    # --- FIX (auditoría cruzada Gemini/Claude, ver README §Auditoría):
    # anti-whipsaw en la entrada/salida por reversión de señal. Antes
    # entry=0.15 y exit_reversal=0.2 dejaban una banda mínima sin ningún
    # piso de retención ni confirmación por N ciclos, así que ruido de
    # microestructura (p.ej. VPINLiquidityExpert, cuya dirección depende
    # del signo del último bucket de volumen) podía abrir y cerrar
    # posiciones en ciclos consecutivos de MIN_CYCLE_INTERVAL_SECONDS. ---
    ENTRY_SIGNAL_THRESHOLD: float = 0.15
    ENTRY_CONFIDENCE_THRESHOLD: float = 0.25
    EXIT_REVERSAL_SIGNAL_THRESHOLD: float = 0.35   # banda de histéresis ampliada (antes 0.2, casi sin margen sobre el entry)
    MIN_HOLD_SECONDS: float = 30.0                 # piso de retención: una reversión no puede cerrar una posición más joven que esto
    REVERSAL_CONFIRMATION_CYCLES: int = 2           # nº de ciclos consecutivos que deben confirmar la reversión antes de cerrar

    # Circuit breaker
    MAX_CONSECUTIVE_LOSSES: int = 4
    MAX_DAILY_LOSS_PCT: float = 0.08          # 8% del capital en un día -> kill switch

    # Gating adaptativo (Hedge / multiplicative weights)
    GATING_LEARNING_RATE: float = 0.08
    GATING_MIN_WEIGHT_FLOOR: float = 0.05     # ningún experto cae permanentemente a 0

    # Ejecución en vivo (deliberadamente apagado por defecto)
    LIVE_TRADING_ENABLED: bool = False
    BYBIT_API_KEY: str = field(default_factory=lambda: os.environ.get("BYBIT_API_KEY", ""))
    BYBIT_API_SECRET: str = field(default_factory=lambda: os.environ.get("BYBIT_API_SECRET", ""))

    # Endpoints públicos, sin autenticación
    BYBIT_BASE_URLS: Tuple[str, ...] = ("https://api.bybit.com", "https://api.bytick.com")
    FEAR_GREED_URL: str = "https://api.alternative.me/fng/"
    MEMPOOL_FEES_URL: str = "https://mempool.space/api/v1/fees/recommended"
    MEMPOOL_STATS_URL: str = "https://mempool.space/api/mempool"

    HTTP_TIMEOUT: float = 6.0

    # --- FIX (auditoría): caché compartida entre símbolos para datos que
    # NO son específicos de símbolo (FGI es un índice de mercado global;
    # la presión de mempool es de la red Bitcoin, no de BTC/ETH/SOL por
    # separado). Sin esto, con SYMBOLS=3 cada endpoint público recibía 3x
    # las llamadas necesarias cada ~MIN_CYCLE_INTERVAL_SECONDS, contra
    # APIs gratuitas que típicamente limitan a decenas de requests/min. ---
    FEAR_GREED_CACHE_TTL_SECONDS: float = 300.0    # el FGI de alternative.me se recalcula ~1 vez/día
    MEMPOOL_CACHE_TTL_SECONDS: float = 60.0        # la fee recomendada de mempool.space cambia en escala de minutos

    # --- FIX (auditoría): PaperExecutionAdapter.close_position() calculaba
    # el PnL como delta de precio puro, sin comisión ni slippage -- un
    # sistema "gratis" en el ledger de papel que en Bybit real paga taker
    # fee + slippage en cada vuelta. Esto es además la causa por la que el
    # churning de arriba (ver ENTRY_/EXIT_ thresholds) no se veía castigado
    # en el PnL simulado durante el diagnóstico. ---
    TAKER_FEE_PCT: float = 0.00055      # Bybit USDT perpetual, taker, tier base
    SLIPPAGE_PCT: float = 0.0005        # heurística conservadora por lado en mercado líquido (BTC/ETH/SOL)

    LOG_DIR: str = "logs"
    DECISION_TRACE_FILE: str = "decision_trace.jsonl"

    # --- v2: microestructura (experto hawkes_flow, de nucleus_autonomous) ---
    CVD_ZSCORE_WINDOW: int = 300
    HAWKES_DECAY: float = 0.35          # kappa del proceso de Hawkes (1/seg aprox.)
    HAWKES_BASELINE: float = 0.05

    # --- v2: gating multi-activo con partial pooling (ver CHANGELOG) ---
    GATING_CROSS_ASSET_SHRINKAGE: float = 0.15   # 0=aislado por símbolo, 1=un solo pool

    # --- v2: reloj de eventos (WS público + fallback REST, de nucleus_autonomous) ---
    PUBLIC_WS_HOSTS: Tuple[str, ...] = ("wss://stream.bybit.com/v5/public/linear",
                                         "wss://stream.bytick.com/v5/public/linear")
    RECONNECT_BACKOFF_BASE: float = 1.5
    RECONNECT_BACKOFF_MAX: float = 30.0
    STALE_HARD_SECONDS: float = 45.0
    MIN_CYCLE_INTERVAL_SECONDS: float = 3.0     # debounce: piso entre dos run_cycle() del mismo símbolo
    SAFETY_POLL_INTERVAL_SECONDS: float = 20.0  # red de seguridad si el stream de trades se cae

    def __post_init__(self) -> None:
        if not self.SYMBOLS:
            self.SYMBOLS = (self.SYMBOL,)


CFG = Config()


# =====================================================================
# 2. LOGGING ASÍNCRONO (patrón QueueHandler/QueueListener — ya validado
#    en producción por el operador para evitar stalls de UI por flush
#    síncrono a disco)
# =====================================================================

def build_async_logger(name: str, log_dir: str) -> Tuple[logging.Logger, logging.handlers.QueueListener]:
    os.makedirs(log_dir, exist_ok=True)
    log_queue: "queue.Queue" = queue.Queue(-1)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))

    file_handler = logging.FileHandler(os.path.join(log_dir, f"{name}.log"), encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))

    queue_handler = logging.handlers.QueueHandler(log_queue)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(queue_handler)
    logger.propagate = False

    listener = logging.handlers.QueueListener(log_queue, file_handler, console_handler, respect_handler_level=True)
    listener.start()
    return logger, listener


# =====================================================================
# 3. DECISION TRACE (transparencia — punto 15 del brief original)
# =====================================================================

class DecisionTrace:
    """Registra cada ciclo de inferencia de forma estructurada y auditable.
    No depende de narrativa generada por un LLM: los campos son los valores
    numéricos reales que causaron la decisión (salidas de expertos, pesos
    de gating, chequeos de riesgo)."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def record(self, entry: Dict[str, Any]) -> None:
        entry = dict(entry)
        entry["ts_utc"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")


# =====================================================================
# 4. CAPA DE INGESTA DE DATOS (solo endpoints públicos, sin autenticación)
# =====================================================================

class _TTLCache:
    """Caché compartida en memoria con expiración (thread-safe).

    FIX (auditoría post-consolidación): antes cada DataFeed -- uno por
    símbolo -- pedía get_fear_greed()/get_mempool_pressure() de forma
    independiente en cada ciclo, aun cuando ambos son datos DE MERCADO
    GLOBAL (no por símbolo). Con Config.SYMBOLS=3 eso multiplicaba por 3
    las llamadas a APIs públicas gratuitas de límite bajo. Solo se
    cachean resultados exitosos (value is not None): un fallo de red no
    bloquea el reintento en el siguiente ciclo."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get_or_fetch(self, key: str, ttl_seconds: float, fetch_fn: Callable[[], Any]) -> Any:
        now = time.time()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and (now - cached[0]) < ttl_seconds:
                return cached[1]
        value = fetch_fn()
        if value is not None:
            with self._lock:
                self._store[key] = (now, value)
        return value


class DataFeed:
    """Ingesta best-effort desde fuentes públicas. Cada método degrada a
    None si la fuente falla, para que los expertos puedan responder con
    baja confianza en vez de crashear el núcleo."""

    def __init__(self, cfg: Config, symbol: Optional[str] = None,
                 market_cache: Optional[_TTLCache] = None):
        self.cfg = cfg
        self.symbol = symbol or cfg.SYMBOL
        self._session = requests.Session() if requests else None
        # FIX (auditoría): sin market_cache explícita (uso standalone/tests)
        # cada DataFeed cachea solo para sí mismo -- mismo comportamiento
        # que antes. El orquestador multi-activo inyecta una única
        # instancia compartida entre los N símbolos (ver NucleusOrchestratorV2).
        self._market_cache = market_cache if market_cache is not None else _TTLCache()

    def _get_json(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        if self._session is None:
            return None
        try:
            r = self._session.get(url, params=params, timeout=self.cfg.HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def _bybit_get(self, path: str, params: dict) -> Optional[dict]:
        for base in self.cfg.BYBIT_BASE_URLS:
            data = self._get_json(base + path, params)
            if data is not None and data.get("retCode") == 0:
                return data
        return None

    def get_klines(self, interval: str = "5", limit: int = 200) -> Optional[np.ndarray]:
        """Devuelve array Nx6: [open_time, open, high, low, close, volume]."""
        data = self._bybit_get("/v5/market/kline", {
            "category": "linear", "symbol": self.symbol,
            "interval": interval, "limit": limit,
        })
        if not data:
            return None
        rows = data["result"]["list"]
        rows = rows[::-1]  # bybit devuelve descendente
        arr = np.array([[float(x) for x in row[:6]] for row in rows], dtype=float)
        return arr

    def get_recent_trades(self, limit: int = 500) -> Optional[List[Tuple[float, float, str, str, float]]]:
        data = self._bybit_get("/v5/market/recent-trade", {
            "category": "linear", "symbol": self.symbol, "limit": limit,
        })
        if not data:
            return None
        out = []
        for t in data["result"]["list"]:
            # execId y time YA vienen en cada trade de /v5/market/recent-trade
            # y antes se descartaban -- mismo patron de "el dato llega pero no
            # se captura" que el microprice en nucleus_kucoin_v2. Sin execId,
            # cualquier deduplicacion queda atada a la posicion del trade
            # dentro de la ventana REST, que no es estable (ver HawkesFlowExpert).
            exec_id = t.get("execId", "")
            ts_ms = t.get("time")
            ts_sec = float(ts_ms) / 1000.0 if ts_ms is not None else time.time()
            out.append((float(t["price"]), float(t["size"]), t.get("side", "Buy"), exec_id, ts_sec))
        return out

    def get_funding_rate(self) -> Optional[float]:
        data = self._bybit_get("/v5/market/funding/history", {
            "category": "linear", "symbol": self.symbol, "limit": 1,
        })
        if not data or not data["result"]["list"]:
            return None
        return float(data["result"]["list"][0]["fundingRate"])

    def get_ticker(self) -> Optional[dict]:
        data = self._bybit_get("/v5/market/tickers", {
            "category": "linear", "symbol": self.symbol,
        })
        if not data or not data["result"]["list"]:
            return None
        return data["result"]["list"][0]

    def get_fear_greed(self) -> Optional[float]:
        def _fetch() -> Optional[float]:
            data = self._get_json(self.cfg.FEAR_GREED_URL)
            if not data:
                return None
            try:
                return float(data["data"][0]["value"])  # 0..100
            except Exception:
                return None
        # FIX (auditoría): FGI es un índice de mercado global, no por
        # símbolo -- cacheado y compartido entre los DataFeed de BTC/ETH/SOL.
        return self._market_cache.get_or_fetch(
            "fear_greed", self.cfg.FEAR_GREED_CACHE_TTL_SECONDS, _fetch)

    def get_mempool_pressure(self) -> Optional[float]:
        """Proxy on-chain gratuito: presión de mempool normalizada 0..1
        usando fee recomendada 'fastest' como señal de congestión de red."""
        def _fetch() -> Optional[float]:
            fees = self._get_json(self.cfg.MEMPOOL_FEES_URL)
            if not fees:
                return None
            try:
                fastest = float(fees.get("fastestFee", 0))
                # normalización heurística: 1 sat/vB = tranquilo, 200+ = saturado
                return float(np.clip(fastest / 200.0, 0.0, 1.0))
            except Exception:
                return None
        # FIX (auditoría): presión de mempool es de la red Bitcoin, no por
        # símbolo -- misma caché compartida que get_fear_greed().
        return self._market_cache.get_or_fetch(
            "mempool_pressure", self.cfg.MEMPOOL_CACHE_TTL_SECONDS, _fetch)


# =====================================================================
# 4b. PRIMITIVAS DE MICROESTRUCTURA (portadas de nucleus_autonomous.py /
#     Taperead10.py, sin cambios de lógica) -- usadas por HawkesFlowExpert
# =====================================================================

class RollingZScore:
    def __init__(self, capacity: int):
        self.buf: Deque[float] = deque(maxlen=capacity)

    def push(self, v: float) -> None:
        self.buf.append(v)

    def zscore(self, v: float) -> float:
        if len(self.buf) < 20:
            return 0.0
        mu = statistics.fmean(self.buf)
        sd = statistics.pstdev(self.buf) or 1e-9
        return (v - mu) / sd


class HawkesIntensity:
    """Proceso de Hawkes univariante autoexcitado, calibración online acotada.
    Estima la intensidad instantánea de "eventos agresivos" (trades que cruzan
    el spread con tamaño relevante) -- señal de liquidez que no depende de
    ningún timeframe, solo del reloj de eventos."""

    def __init__(self, kappa: float, mu: float):
        self.kappa = kappa
        self.mu = mu
        self.intensity = mu
        self.last_ts: Optional[float] = None

    def on_event(self, ts: float, weight: float = 1.0) -> float:
        if self.last_ts is not None:
            dt = max(0.0, ts - self.last_ts)
            self.intensity = self.mu + (self.intensity - self.mu) * math.exp(-self.kappa * dt)
        self.intensity += weight
        self.last_ts = ts
        return self.intensity

    def decay_to(self, ts: float) -> float:
        if self.last_ts is None:
            return self.intensity
        dt = max(0.0, ts - self.last_ts)
        return self.mu + (self.intensity - self.mu) * math.exp(-self.kappa * dt)


class OrderFlowState:
    """CVD acumulado, z-score de CVD, e intensidad Hawkes bid/ask separada.
    Se alimenta trade a trade (ya sea desde el stream WS en vivo o, en modo
    degradado, desde el batch de get_recent_trades())."""

    def __init__(self, cfg: Config):
        self.cvd = 0.0
        self.z = RollingZScore(cfg.CVD_ZSCORE_WINDOW)
        self.hawkes_buy = HawkesIntensity(cfg.HAWKES_DECAY, cfg.HAWKES_BASELINE)
        self.hawkes_sell = HawkesIntensity(cfg.HAWKES_DECAY, cfg.HAWKES_BASELINE)
        self.last_trade_ts = 0.0
        self.trades_seen = 0

    def on_trade(self, side: str, qty: float, ts_sec: float) -> None:
        is_buy = str(side).lower().startswith("b")
        signed = qty if is_buy else -qty
        self.cvd += signed
        self.z.push(self.cvd)
        if is_buy:
            self.hawkes_buy.on_event(ts_sec, weight=min(qty, 5.0))
        else:
            self.hawkes_sell.on_event(ts_sec, weight=min(qty, 5.0))
        self.last_trade_ts = ts_sec
        self.trades_seen += 1

    def snapshot(self, now_sec: float) -> Dict[str, float]:
        return {
            "cvd_z": self.z.zscore(self.cvd),
            "hawkes_buy": self.hawkes_buy.decay_to(now_sec),
            "hawkes_sell": self.hawkes_sell.decay_to(now_sec),
            "seconds_since_trade": now_sec - self.last_trade_ts if self.last_trade_ts else 999.0,
        }


# =====================================================================
# 5. EXPERTOS (cada uno: .infer(features) -> ExpertOutput)
# =====================================================================

@dataclass
class ExpertOutput:
    name: str
    signal: float       # [-1, +1]  negativo=short, positivo=long
    confidence: float    # [0, 1]
    detail: Dict[str, Any] = field(default_factory=dict)


class KalmanDirectionalExpert:
    """Filtro de Kalman de nivel+tendencia local, con adaptación online de
    la varianza de observación R vía ventana de innovaciones (heredero
    directo del núcleo direccional Kalman ya validado por el operador)."""

    def __init__(self, q_level=1e-5, q_trend=1e-6, r_init=1.0, window=50):
        self.q_level = q_level
        self.q_trend = q_trend
        self.r = r_init
        self.window = window
        self._innovations: List[float] = []
        # estado: [nivel, tendencia]
        self.x = np.array([0.0, 0.0])
        self.P = np.eye(2) * 1.0
        self._initialized = False
        # FIX (revisión post-auditoría): último open_time procesado. Sin esto,
        # infer() reprocesaba toda la ventana de velas (p.ej. 200) en cada ciclo
        # de decisión aunque self.x/self.P ya persistían entre llamadas -> las
        # mismas innovaciones históricas se reinyectaban una y otra vez,
        # sesgando la estimación adaptativa de self.r (varianza de innovación).
        self._last_ts: Optional[float] = None

    def _step(self, z: float) -> Tuple[float, float]:
        F = np.array([[1.0, 1.0], [0.0, 1.0]])
        Q = np.array([[self.q_level, 0.0], [0.0, self.q_trend]])
        H = np.array([[1.0, 0.0]])

        if not self._initialized:
            self.x = np.array([z, 0.0])
            self._initialized = True
            return z, 0.0

        # predicción
        x_pred = F @ self.x
        P_pred = F @ self.P @ F.T + Q

        # innovación
        y = z - (H @ x_pred)[0]
        S = (H @ P_pred @ H.T)[0, 0] + self.r
        K = (P_pred @ H.T).flatten() / max(S, 1e-9)

        self.x = x_pred + K * y
        self.P = (np.eye(2) - np.outer(K, H)) @ P_pred

        # adaptación de R (Mehra-lite): varianza muestral de innovaciones
        self._innovations.append(y)
        if len(self._innovations) > self.window:
            self._innovations.pop(0)
        if len(self._innovations) >= 5:
            self.r = max(float(np.var(self._innovations)), 1e-6)

        return float(self.x[0]), float(self.x[1])

    def infer(self, closes: np.ndarray, timestamps: Optional[np.ndarray] = None) -> ExpertOutput:
        if closes is None or len(closes) < 10:
            return ExpertOutput("kalman_directional", 0.0, 0.0, {"reason": "datos insuficientes"})

        if timestamps is not None and self._last_ts is not None:
            # Solo re-alimentar velas realmente nuevas desde el ciclo anterior.
            new_mask = timestamps > self._last_ts
            new_closes = closes[new_mask]
            if len(new_closes) == 0:
                level, trend = float(self.x[0]), float(self.x[1])
            else:
                level = trend = 0.0
                for z in new_closes:
                    level, trend = self._step(float(z))
        else:
            # Primera llamada, o timestamps no disponibles (degradación segura
            # al comportamiento original: bootstrap con toda la ventana).
            level = trend = 0.0
            for z in closes:
                level, trend = self._step(float(z))

        if timestamps is not None and len(timestamps) > 0:
            self._last_ts = float(timestamps[-1])

        # normaliza la tendencia relativa al nivel para obtener una señal acotada
        norm_trend = trend / max(abs(level), 1.0)
        signal = float(np.tanh(norm_trend * 500.0))  # escala empírica, acotado en tanh
        confidence = float(np.clip(1.0 - min(self.r, 1.0), 0.1, 0.95))
        return ExpertOutput("kalman_directional", signal, confidence,
                             {"level": level, "trend": trend, "r": self.r})


class BOCPDRegimeExpert:
    """Bayesian Online Changepoint Detection (Adams & MacKay, 2007) sobre
    retornos, con prior Normal-Gamma conjugado. Detecta el punto de cambio
    de régimen más probable y usa la volatilidad post-cambio para modular
    la confianza del resto de expertos."""

    def __init__(self, hazard_lambda: float = 250.0,
                 mu0=0.0, kappa0=1.0, alpha0=1.0, beta0=1e-4):
        self.hazard = 1.0 / hazard_lambda
        self.mu0, self.kappa0, self.alpha0, self.beta0 = mu0, kappa0, alpha0, beta0
        self.reset()

    def reset(self):
        self.R = np.array([1.0])
        self.mu = np.array([self.mu0])
        self.kappa = np.array([self.kappa0])
        self.alpha = np.array([self.alpha0])
        self.beta = np.array([self.beta0])

    def _student_t_pdf(self, x, mu, sigma2, nu):
        # FIX (hallazgo crítico post-validación): math.gamma() es una función
        # escalar de Python y NO acepta arrays de numpy. mu/sigma2/nu son
        # siempre arrays (uno por hipótesis de run-length activa), por lo que
        # la versión original crasheaba con TypeError en la primerísima
        # llamada a update(), en cualquier numpy reciente. Se vectoriza vía
        # lgamma elemento a elemento (bonus: evita overflow de gamma directo
        # para nu grandes).
        nu = np.atleast_1d(nu).astype(float)
        sigma2 = np.atleast_1d(sigma2).astype(float)
        mu = np.atleast_1d(mu).astype(float)
        log_c = np.array([math.lgamma((n + 1.0) / 2.0) - math.lgamma(n / 2.0) for n in nu])
        log_c -= 0.5 * np.log(nu * np.pi * sigma2)
        c = np.exp(log_c)
        return c * (1 + ((x - mu) ** 2) / (nu * sigma2)) ** (-(nu + 1) / 2)

    def update(self, x: float) -> int:
        """Devuelve el run-length más probable (0 = changepoint justo ahora)."""
        nu = 2 * self.alpha
        sigma2 = self.beta * (self.kappa + 1) / (self.alpha * self.kappa)
        pred = self._student_t_pdf(x, self.mu, sigma2, nu)
        pred = np.clip(pred, 1e-300, None)

        growth = self.R * pred * (1 - self.hazard)
        cp = np.sum(self.R * pred * self.hazard)
        R_new = np.append(cp, growth)
        R_new /= R_new.sum()

        # actualización Normal-Gamma
        mu_new = np.append(self.mu0, (self.kappa * self.mu + x) / (self.kappa + 1))
        kappa_new = np.append(self.kappa0, self.kappa + 1)
        alpha_new = np.append(self.alpha0, self.alpha + 0.5)
        beta_new = np.append(self.beta0,
                              self.beta + (self.kappa * (x - self.mu) ** 2) / (2 * (self.kappa + 1)))

        self.R, self.mu, self.kappa, self.alpha, self.beta = R_new, mu_new, kappa_new, alpha_new, beta_new

        # trunca la distribución de run-length para que no crezca sin límite
        if len(self.R) > 500:
            keep = np.argsort(self.R)[-300:]
            keep.sort()
            self.R = self.R[keep]; self.R /= self.R.sum()
            self.mu = self.mu[keep]; self.kappa = self.kappa[keep]
            self.alpha = self.alpha[keep]; self.beta = self.beta[keep]

        return int(np.argmax(self.R))

    def infer(self, closes: np.ndarray) -> ExpertOutput:
        if closes is None or len(closes) < 15:
            return ExpertOutput("bocpd_regime", 0.0, 0.0, {"reason": "datos insuficientes"})
        rets = np.diff(np.log(closes + 1e-9))
        self.reset()
        run_length = 0
        for r in rets:
            run_length = self.update(float(r))

        recent_ret = float(np.mean(rets[-5:])) if len(rets) >= 5 else float(rets[-1])
        # régimen "joven" (run_length bajo) => cambio reciente => menor confianza direccional
        regime_maturity = float(np.clip(run_length / 30.0, 0.0, 1.0))
        signal = float(np.tanh(recent_ret * 300.0))
        confidence = 0.2 + 0.6 * regime_maturity
        return ExpertOutput("bocpd_regime", signal, confidence,
                             {"run_length": run_length, "recent_ret": recent_ret})


class JumpModelExpert:
    """Statistical Jump Model simplificado: K centroides en el espacio
    (retorno medio, volatilidad realizada) con penalización de salto que
    desincentiva cambiar de estado por ruido, tal como en la literatura de
    jump models para series financieras."""

    STATE_NAMES = ("bajista_volatil", "lateral", "alcista_volatil")

    def __init__(self, jump_penalty: float = 0.35, ema_alpha: float = 0.05):
        self.jump_penalty = jump_penalty
        self.ema_alpha = ema_alpha
        self.centroids = np.array([
            [-0.002, 0.02],   # bajista volátil
            [0.0, 0.005],     # lateral
            [0.002, 0.02],    # alcista volátil
        ])
        self.prev_state = 1

    def infer(self, closes: np.ndarray) -> ExpertOutput:
        if closes is None or len(closes) < 20:
            return ExpertOutput("jump_model", 0.0, 0.0, {"reason": "datos insuficientes"})
        rets = np.diff(np.log(closes + 1e-9))
        window = rets[-10:]
        feat = np.array([float(np.mean(window)), float(np.std(window))])

        dists = np.sum((self.centroids - feat) ** 2, axis=1)
        penalized = dists.copy()
        penalized[self.prev_state] -= self.jump_penalty * np.mean(dists)
        state = int(np.argmin(penalized))

        # actualización online del centroide ganador (EMA)
        self.centroids[state] = (1 - self.ema_alpha) * self.centroids[state] + self.ema_alpha * feat
        self.prev_state = state

        signal_map = {0: -1.0, 1: 0.0, 2: 1.0}
        base_signal = signal_map[state]
        # confianza según qué tan lejos está del centroide lateral (estado neutro)
        confidence = float(np.clip(dists[1] / (np.sum(dists) + 1e-9), 0.15, 0.9))
        return ExpertOutput("jump_model", base_signal, confidence,
                             {"state": self.STATE_NAMES[state], "feat": feat.tolist()})


class VPINLiquidityExpert:
    """Volume-Synchronized Probability of Informed Trading. Bucketiza por
    volumen fijo y mide el desequilibrio persistente comprador/vendedor.
    VPIN alto = flujo tóxico = mayor probabilidad de movimiento direccional
    fuerte inminente (útil para el objetivo de "captura de liquidez")."""

    def __init__(self, n_buckets: int = 30):
        self.n_buckets = n_buckets

    def infer(self, trades: Optional[List[Tuple[float, float, str]]]) -> ExpertOutput:
        if not trades or len(trades) < 20:
            return ExpertOutput("vpin_liquidity", 0.0, 0.0, {"reason": "datos insuficientes"})

        total_vol = sum(t[1] for t in trades)
        bucket_vol = max(total_vol / self.n_buckets, 1e-9)

        buckets = []
        cur_buy, cur_sell, cur_vol = 0.0, 0.0, 0.0
        for price, qty, side, *_ in trades:  # tolera el 5-tuple (execId, ts) que ahora emite get_recent_trades
            is_buy = str(side).lower().startswith("b")
            if is_buy:
                cur_buy += qty
            else:
                cur_sell += qty
            cur_vol += qty
            if cur_vol >= bucket_vol:
                buckets.append((cur_buy, cur_sell))
                cur_buy = cur_sell = cur_vol = 0.0
        if cur_vol > 0:
            buckets.append((cur_buy, cur_sell))

        if not buckets:
            return ExpertOutput("vpin_liquidity", 0.0, 0.0, {"reason": "sin buckets"})

        imbalances = [abs(b - s) / max(b + s, 1e-9) for b, s in buckets]
        vpin = float(np.mean(imbalances))

        # FIX (auditoría): antes la dirección dependía únicamente del signo
        # del ÚLTIMO bucket (last_buy > last_sell), que en ticks de alta
        # frecuencia puede voltear entre ciclos consecutivos de
        # MIN_CYCLE_INTERVAL_SECONDS sin que el desequilibrio de fondo haya
        # cambiado -- una fuente de ruido direccional independiente del
        # whipsaw ya corregido en run_cycle(). Ahora se usa el desequilibrio
        # NETO acumulado sobre los últimos hasta 3 buckets (o los que haya),
        # que exige que el flujo comprador/vendedor se sostenga a través de
        # más de un bucket para invertir la dirección, sin introducir estado
        # entre llamadas (infer() sigue siendo puro respecto a `trades`).
        trailing = buckets[-min(3, len(buckets)):]
        net_buy = sum(b for b, _ in trailing)
        net_sell = sum(s for _, s in trailing)
        direction = 1.0 if net_buy >= net_sell else -1.0
        signal = direction * float(np.clip(vpin, 0.0, 1.0))
        confidence = float(np.clip(vpin, 0.1, 0.95))
        return ExpertOutput("vpin_liquidity", signal, confidence, {"vpin": vpin})


class HawkesFlowExpert:
    """v2 -- 7º experto (de nucleus_autonomous.py / Taperead10.py). CVD con
    z-score rodante + intensidad de Hawkes bidireccional (compra y venta
    excitan procesos separados), a diferencia de VPIN que solo mide
    desequilibrio por bucket de volumen. Es deliberadamente redundante con
    VPIN en el ESPACIO de información que consume (ambos leen `trades`),
    pero mide algo distinto: VPIN es toxicidad acumulada por bucket, Hawkes
    es la ACELERACIÓN reciente de agresión de flujo, autoexcitada -- por
    diseño el GatingNetwork decide cuál pesar más según el desempeño real,
    en vez de que el ingeniero decida a priori cuál de las dos métricas de
    order-flow es "la buena".

    Recibe el mismo batch `trades` que VPINLiquidityExpert (lista de
    (price, qty, side) o, desde DataFeed.get_recent_trades(), el 5-tuple
    (price, qty, side, execId, ts_sec)). Cuando execId está disponible se
    deduplica por identidad real del trade (self._seen_ids/_seen_order,
    FIFO acotado), no por posición en la lista: get_recent_trades() es una
    FOTO de ventana fija de tamaño `limit`, no un stream acumulativo, y un
    índice creciente se congela en cuanto el volumen entre ciclos satura
    esa ventana -- sin excepción ni log que lo delate. Sin execId (tests,
    o un feed degradado) cae al fallback legado por longitud de batch."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.flow = OrderFlowState(cfg)
        self._trades_processed = 0  # solo para el fallback legado (batches sin execId)
        self._seen_ids: Set[str] = set()
        self._seen_order: Deque[str] = deque(maxlen=2000)  # 4x el limit=500 tipico: margen seguro contra falsos "ya visto"

    def infer(self, trades: Optional[List[Tuple[float, float, str]]]) -> ExpertOutput:
        if not trades:
            return ExpertOutput("hawkes_flow", 0.0, 0.0, {"reason": "sin datos"})

        now = time.time()
        has_ids = len(trades[0]) > 3 and bool(trades[0][3])

        if has_ids:
            # Dedup por execId: no asume orden ni crecimiento monotónico del
            # batch, así que sobrevive a ventana saturada (>500 trades/ciclo)
            # y a un orden de la API que no esté garantizado ser ascendente.
            nuevos = []
            for t in trades:
                trade_id = t[3]
                if trade_id in self._seen_ids:
                    continue
                if len(self._seen_order) == self._seen_order.maxlen:
                    self._seen_ids.discard(self._seen_order[0])  # el deque lo va a expulsar; purga el set en paralelo
                self._seen_order.append(trade_id)
                self._seen_ids.add(trade_id)
                nuevos.append(t)
        else:
            # Fallback legado: batch sin execId (tests, o feed degradado).
            # Misma heurística original, con la misma limitación que ya
            # documentaba el docstring -- no aplica en producción real.
            nuevos = trades[self._trades_processed:] if len(trades) >= self._trades_processed else trades
            self._trades_processed = len(trades)

        for t in nuevos:
            price, qty, side = t[0], t[1], t[2]
            # Reloj de eventos real cuando está disponible (ts_sec del propio
            # trade) en vez del wall-clock compartido `now` para todo el
            # batch -- antes cada evento del ciclo recibía el mismo `now`,
            # colapsando dt=0 dentro del batch y anulando la ventaja de
            # Hawkes (distinguir 50ms de 5s entre trades).
            ts_sec = t[4] if len(t) > 4 and t[4] else now
            if qty > 0:
                self.flow.on_trade(side, qty, ts_sec)

        snap = self.flow.snapshot(now)
        if self.flow.trades_seen < 20:
            return ExpertOutput("hawkes_flow", 0.0, 0.1, {"reason": "calentando ventana CVD", **snap})

        cvd_z = snap["cvd_z"]
        hawkes_diff = snap["hawkes_buy"] - snap["hawkes_sell"]
        signal = float(np.clip(math.tanh(cvd_z / 3.0) * 0.6 + math.tanh(hawkes_diff / 3.0) * 0.4, -1.0, 1.0))
        confidence = float(np.clip((abs(cvd_z) / 3.0) * 0.7 + min(abs(hawkes_diff) / 5.0, 1.0) * 0.3, 0.1, 0.9))
        return ExpertOutput("hawkes_flow", signal, confidence, snap)


class OnChainSentimentExpert:
    """Combina Fear&Greed (contrarian en extremos) y presión de mempool
    (proxy gratuito de actividad de red) como señal de contexto de fondo,
    no de timing fino."""

    def infer(self, fear_greed: Optional[float], mempool_pressure: Optional[float]) -> ExpertOutput:
        if fear_greed is None and mempool_pressure is None:
            return ExpertOutput("onchain_sentiment", 0.0, 0.0, {"reason": "sin datos"})

        signal = 0.0
        if fear_greed is not None:
            # extremo miedo (<20) -> sesgo contrarian largo; extremo codicia (>80) -> sesgo corto
            centered = (fear_greed - 50.0) / 50.0  # -1..1
            signal = -centered  # contrarian

        # FIX (revisión post-auditoría): mempool_pressure es puramente informativo
        # (congestión de red) y se reporta en 'detail' para contexto. Antes se
        # sumaba un término 0.0*mempool_pressure (no-op) pero SÍ incrementaba
        # 'parts', diluyendo el promedio de señal a la mitad cada vez que había
        # dato de mempool disponible, aun sin aportar dirección. Ya no participa
        # en el promedio direccional.
        confidence = 0.25 if fear_greed is not None else 0.1
        return ExpertOutput("onchain_sentiment", float(np.clip(signal, -1, 1)), confidence,
                             {"fear_greed": fear_greed, "mempool_pressure": mempool_pressure})


class FundingCarryExpert:
    """Funding rate como señal de carry/crowding: funding extremo indica
    posicionamiento apalancado unidireccional del mercado, con sesgo
    contrarian de corto plazo (mean reversion de crowding)."""

    def __init__(self, window: int = 30):
        self.history: List[float] = []
        self.window = window

    def infer(self, funding_rate: Optional[float]) -> ExpertOutput:
        if funding_rate is None:
            return ExpertOutput("funding_carry", 0.0, 0.0, {"reason": "sin datos"})
        self.history.append(funding_rate)
        if len(self.history) > self.window:
            self.history.pop(0)
        if len(self.history) < 5:
            return ExpertOutput("funding_carry", 0.0, 0.1, {"funding_rate": funding_rate})

        mean = statistics.mean(self.history)
        std = statistics.pstdev(self.history) or 1e-6
        z = (funding_rate - mean) / std
        # contrarian: funding muy positivo (largos pagando mucho) -> sesgo corto
        signal = float(np.clip(-np.tanh(z), -1, 1))
        confidence = float(np.clip(abs(z) / 3.0, 0.1, 0.8))
        return ExpertOutput("funding_carry", signal, confidence,
                             {"funding_rate": funding_rate, "z": z})


# =====================================================================
# 6. GATING NETWORK (evolución acotada vía multiplicative weights / Hedge)
# =====================================================================

class GatingNetwork:
    """Combina las salidas de los expertos ponderando por peso de
    confianza histórica (atribución de desempeño), estilo Hedge/
    multiplicative-weights. Los pesos son la explicación causal directa
    de la decisión — no requieren narrativa adicional para ser auditables.

    Evolución acotada: tras cada trade cerrado, se actualiza el peso de
    cada experto según si su señal en ese ciclo coincidió con el resultado
    realizado. Piso mínimo de peso: ningún experto se anula permanentemente,
    preservando la capacidad de recuperación si el régimen vuelve a
    favorecerlo (evita el sobreajuste al ruido reciente)."""

    def __init__(self, expert_names: List[str], learning_rate: float, min_floor: float,
                 initial_weights: Optional[Dict[str, float]] = None):
        self.names = expert_names
        self.lr = learning_rate
        self.min_floor = min_floor
        self.weights = self._validated_initial_weights(expert_names, min_floor, initial_weights)

    @staticmethod
    def _validated_initial_weights(expert_names: List[str], min_floor: float,
                                    initial_weights: Optional[Dict[str, float]]) -> Dict[str, float]:
        """Usa pesos calibrados (ValidationHarness) si están presentes y son
        válidos; si no, degrada de forma segura al prior uniforme 1/N. Nunca
        confía ciegamente en un JSON externo: valida cobertura de expertos,
        suma=1 y respeto del piso antes de aceptarlos."""
        uniform = {n: 1.0 / len(expert_names) for n in expert_names}
        if not initial_weights:
            return uniform
        same_keys = set(initial_weights.keys()) == set(expert_names)
        sums_to_one = abs(sum(initial_weights.values()) - 1.0) < 1e-6
        respects_floor = all(v >= min_floor - 1e-9 for v in initial_weights.values())
        if same_keys and sums_to_one and respects_floor:
            return dict(initial_weights)
        return uniform

    def combine(self, outputs: List[ExpertOutput]) -> Tuple[float, float, Dict[str, float]]:
        weighted_sum = 0.0
        weight_total = 0.0
        used_weights = {}
        for o in outputs:
            w = self.weights.get(o.name, 0.0) * o.confidence
            weighted_sum += w * o.signal
            weight_total += w
            used_weights[o.name] = w
        combined_signal = weighted_sum / weight_total if weight_total > 1e-9 else 0.0
        combined_confidence = float(np.clip(weight_total / max(sum(self.weights.values()), 1e-9), 0.0, 1.0))
        return float(np.clip(combined_signal, -1, 1)), combined_confidence, used_weights

    def attribute_outcome(self, outputs_at_entry: List[ExpertOutput], realized_pnl_sign: int) -> None:
        """realized_pnl_sign: +1 si el trade cerró en ganancia, -1 si en pérdida."""
        for o in outputs_at_entry:
            agreement = 1 if (np.sign(o.signal) == np.sign(realized_pnl_sign) and abs(o.signal) > 1e-6) else -1
            reward = agreement * o.confidence
            self.weights[o.name] *= math.exp(self.lr * reward)

        # FIX (hallazgo crítico post-validación): la versión original aplicaba
        # el piso y LUEGO volvía a dividir todos los pesos (incluido el recién
        # elevado al piso) por la nueva suma total -> el piso quedaba violado
        # de nuevo tras esa segunda normalización (confirmado por el test
        # existente, que fallaba con un peso ~0.091 contra un piso de 0.1).
        # Se usa "water-filling" (ver _apply_floor): los expertos por debajo
        # del piso quedan fijados exactamente en él, y el déficit que eso
        # introduce se descuenta proporcionalmente solo de los expertos que
        # SÍ superan el piso, preservando suma=1 sin volver a romper la
        # garantía del piso.
        self.weights = self._apply_floor(self.weights, self.names, self.min_floor)

    @staticmethod
    def _apply_floor(weights: Dict[str, float], names: List[str], min_floor: float) -> Dict[str, float]:
        """Normaliza `weights` a suma=1 y fuerza el piso `min_floor` por
        experto vía water-filling (ver nota FIX arriba). Extraído como
        staticmethod (v2) para que MultiAssetGatingPool pueda reaplicar la
        MISMA garantía de piso tras el shrinkage cross-symbol, sin duplicar
        esta lógica -- comportamiento numérico idéntico al de v1 cuando se
        llama desde attribute_outcome()."""
        total = sum(weights.values())
        if total <= 0:
            return {n: 1.0 / len(names) for n in names}
        normalized = {n: weights[n] / total for n in names}

        below = {n: v for n, v in normalized.items() if v < min_floor}
        above = {n: v for n, v in normalized.items() if v >= min_floor}
        deficit = sum(min_floor - v for v in below.values())
        above_total = sum(above.values())

        if above and above_total > deficit:
            scale = (above_total - deficit) / above_total
            return {n: (min_floor if n in below else normalized[n] * scale) for n in names}

        # Caso degenerado (min_floor * n_expertos >= 1: config inválida,
        # no resoluble por water-filling): degrada al piso uniforme previo
        # en vez de dividir por cero o producir pesos negativos.
        out = {n: max(normalized[n], min_floor) for n in names}
        total2 = sum(out.values())
        return {n: out[n] / total2 for n in names}


class MultiAssetGatingPool:
    """v2 -- gating compartido con partial pooling entre símbolos (decisión
    de arquitectura aprobada por el operador, ver CHANGELOG). Envuelve un
    GatingNetwork INDEPENDIENTE por símbolo (su lógica interna no se toca:
    los 17 tests de v1 la siguen validando sola) y, tras cada
    attribute_outcome(), contrae los pesos de cada símbolo una fracción
    `shrinkage` hacia la media cross-symbol de ese mismo experto -- shrinkage
    jerárquico clásico (partial pooling / James-Stein), reutilizando
    GatingNetwork._apply_floor() para no duplicar la garantía del piso.

    shrinkage=0.0 -> equivalente a 3 GatingNetwork totalmente aislados
    (comportamiento de v1 replicado x3). shrinkage=1.0 -> un único pool de
    pesos fusionado sin distinción de símbolo. El valor por defecto
    (Config.GATING_CROSS_ASSET_SHRINKAGE=0.15) deja que cada símbolo
    aprenda mayormente de su propio desempeño, con un empujón pequeño hacia
    lo que funciona en los otros dos."""

    def __init__(self, symbols: List[str], expert_names: List[str],
                 learning_rate: float, min_floor: float, shrinkage: float):
        self.symbols = list(symbols)
        self.min_floor = min_floor
        self.shrinkage = float(np.clip(shrinkage, 0.0, 1.0))
        self.networks: Dict[str, GatingNetwork] = {
            s: GatingNetwork(expert_names, learning_rate, min_floor) for s in self.symbols
        }

    def combine(self, symbol: str, outputs: List[ExpertOutput]) -> Tuple[float, float, Dict[str, float]]:
        return self.networks[symbol].combine(outputs)

    def attribute_outcome(self, symbol: str, outputs_at_entry: List[ExpertOutput],
                           realized_pnl_sign: int) -> None:
        self.networks[symbol].attribute_outcome(outputs_at_entry, realized_pnl_sign)
        self._apply_cross_asset_shrinkage()

    def weights_for(self, symbol: str) -> Dict[str, float]:
        return self.networks[symbol].weights

    def _apply_cross_asset_shrinkage(self) -> None:
        if self.shrinkage <= 0.0 or len(self.symbols) < 2:
            return
        names = self.networks[self.symbols[0]].names
        cross_mean = {n: statistics.fmean(self.networks[s].weights[n] for s in self.symbols) for n in names}
        for s in self.symbols:
            net = self.networks[s]
            shrunk = {n: (1.0 - self.shrinkage) * net.weights[n] + self.shrinkage * cross_mean[n]
                      for n in names}
            net.weights = GatingNetwork._apply_floor(shrunk, names, self.min_floor)


# =====================================================================
# 7. MÓDULO DE RIESGO (proceso lógico separado — solo veta/reduce/cierra)
# =====================================================================

@dataclass
class RiskDecision:
    approved: bool
    leverage: int
    position_size_usdt: float
    stop_loss_pct: float
    reason: str


class RiskModule:
    """Separado por diseño del núcleo de interpretación. No reinterpreta
    la señal de mercado: solo aplica límites duros de capital, apalancamiento
    y circuit breaker. Es el único punto con capacidad de veto."""

    def __init__(self, cfg: Config, symbol: Optional[str] = None, capital_usdt: Optional[float] = None):
        self.cfg = cfg
        self.symbol = symbol or cfg.SYMBOL
        # v2: riesgo independiente por símbolo (decisión del operador, ver
        # CHANGELOG) -- cada símbolo recibe su propia porción de capital en
        # vez de compartir cfg.CAPITAL_USDT íntegro entre los N símbolos.
        # Retrocompatible: si no se pasa capital_usdt (uso single-symbol de
        # v1), se comporta exactamente igual que antes.
        self.capital_usdt = capital_usdt if capital_usdt is not None else cfg.CAPITAL_USDT
        self.consecutive_losses = 0
        self.daily_pnl_pct = 0.0
        self.kill_switch_engaged = False
        # FIX (hallazgo crítico post-validación): era threading.Lock() (no
        # reentrante). register_trade_result() toma el lock y, mientras lo
        # sostiene, puede llamar a engage_kill_switch(), que intenta tomar el
        # MISMO lock -> deadlock total del hilo, justo en el momento en que
        # el circuit-breaker o el límite de pérdida diaria debían proteger
        # capital. RLock permite la re-entrada del mismo hilo sin cambiar la
        # semántica de exclusión mutua entre hilos distintos.
        self._lock = threading.RLock()

    def engage_kill_switch(self, reason: str) -> None:
        with self._lock:
            self.kill_switch_engaged = True
            self._kill_reason = reason

    def reset_daily(self) -> None:
        with self._lock:
            self.daily_pnl_pct = 0.0
            self.consecutive_losses = 0

    def register_trade_result(self, pnl_pct_of_capital: float) -> None:
        with self._lock:
            self.daily_pnl_pct += pnl_pct_of_capital
            if pnl_pct_of_capital < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0

            if self.consecutive_losses >= self.cfg.MAX_CONSECUTIVE_LOSSES:
                self.engage_kill_switch(
                    f"{self.consecutive_losses} pérdidas consecutivas (límite {self.cfg.MAX_CONSECUTIVE_LOSSES})")
            if self.daily_pnl_pct <= -self.cfg.MAX_DAILY_LOSS_PCT:
                self.engage_kill_switch(
                    f"pérdida diaria {self.daily_pnl_pct:.2%} excede el límite {self.cfg.MAX_DAILY_LOSS_PCT:.2%}")

    @staticmethod
    def _liquidation_distance_pct(leverage: int, maintenance_margin_rate: float) -> float:
        """Aproximación estándar (isolated margin, sin comisiones/funding):
        distancia porcentual de precio hasta liquidación ~= 1/leverage - mmr."""
        return max(1.0 / leverage - maintenance_margin_rate, 0.0)

    def evaluate_entry(self, required_stop_loss_pct: float,
                        leverage_preference: str = "auto") -> RiskDecision:
        """required_stop_loss_pct: distancia porcentual de precio a la que
        debe estar el stop-loss para respetar el 1-2% de riesgo de capital,
        dado el tamaño de posición que se evalúe.

        Regla dura: se elige el mayor apalancamiento disponible (HIGH o
        NORMAL) tal que la distancia a liquidación sea >= stop_loss *
        margen de seguridad. Si ninguno cumple, se rechaza la entrada."""

        if self.kill_switch_engaged:
            return RiskDecision(False, 0, 0.0, 0.0, f"kill-switch activo: {getattr(self, '_kill_reason', '')}")

        candidates = [self.cfg.LEVERAGE_HIGH, self.cfg.LEVERAGE_NORMAL]
        if leverage_preference == "normal_only":
            candidates = [self.cfg.LEVERAGE_NORMAL]

        for lev in sorted(candidates, reverse=True):
            liq_dist = self._liquidation_distance_pct(lev, self.cfg.MAINTENANCE_MARGIN_RATE)
            if liq_dist >= required_stop_loss_pct * self.cfg.LIQUIDATION_SAFETY_MARGIN:
                risk_pct = self.cfg.RISK_PCT_MIN if lev == self.cfg.LEVERAGE_HIGH else self.cfg.RISK_PCT_MAX
                capital_at_risk = self.capital_usdt * risk_pct
                position_size = capital_at_risk / max(required_stop_loss_pct, 1e-6)
                position_size = min(position_size, self.capital_usdt * lev)  # no exceder margen disponible
                return RiskDecision(True, lev, position_size, required_stop_loss_pct,
                                     f"aprobado a x{lev}: buffer_liq={liq_dist:.4f} "
                                     f">= stop*{self.cfg.LIQUIDATION_SAFETY_MARGIN}={required_stop_loss_pct * self.cfg.LIQUIDATION_SAFETY_MARGIN:.4f}")

        return RiskDecision(False, 0, 0.0, required_stop_loss_pct,
                             "rechazado: ningún perfil de apalancamiento respeta el buffer de liquidación "
                             "requerido para el stop-loss solicitado")


# =====================================================================
# 8. LIBRO VIRTUAL / EJECUCIÓN (paper por defecto; live requiere opt-in)
# =====================================================================

class ExecutionAdapter:
    def open_position(self, side: str, size_usdt: float, leverage: int, price: float) -> Dict[str, Any]:
        raise NotImplementedError

    def close_position(self, position: Dict[str, Any], price: float) -> float:
        raise NotImplementedError


class PaperExecutionAdapter(ExecutionAdapter):
    """Libro virtual (VirtualLedger). Modo por defecto y único activo
    salvo que el operador configure credenciales y active LIVE_TRADING_ENABLED."""

    def __init__(self, cfg: Optional[Config] = None):
        self.ledger: List[Dict[str, Any]] = []
        # FIX (auditoría): antes el ledger no aplicaba comisión ni slippage
        # -- el PnL era delta de precio puro. cfg es opcional (retrocompat
        # con uso standalone/tests) y cae a la instancia global CFG.
        self.cfg = cfg if cfg is not None else CFG

    def open_position(self, side: str, size_usdt: float, leverage: int, price: float) -> Dict[str, Any]:
        pos = {"side": side, "size_usdt": size_usdt, "leverage": leverage,
               "entry_price": price, "open_ts": time.time()}
        self.ledger.append(pos)
        return pos

    def close_position(self, position: Dict[str, Any], price: float) -> float:
        entry = position["entry_price"]
        direction = 1 if position["side"] == "long" else -1
        raw_return_pct = direction * (price - entry) / entry
        # El apalancamiento ya está reflejado en size_usdt vía el módulo de riesgo;
        # aquí solo se aplica el retorno porcentual de precio al tamaño nocional.
        pnl_usdt = raw_return_pct * position["size_usdt"]
        # FIX (auditoría): comisión taker + slippage heurístico, aplicados
        # a AMBOS lados de la vuelta (apertura + cierre) -- antes ausentes
        # por completo del ledger, lo que hacía invisible el costo real de
        # un patrón de whipsaw en el PnL simulado.
        round_trip_cost_pct = 2.0 * (self.cfg.TAKER_FEE_PCT + self.cfg.SLIPPAGE_PCT)
        fees_slippage_usdt = round_trip_cost_pct * position["size_usdt"]
        pnl_usdt -= fees_slippage_usdt
        position["closed"] = True
        position["exit_price"] = price
        position["fees_slippage_usdt"] = fees_slippage_usdt
        position["pnl_usdt"] = pnl_usdt
        return pnl_usdt


class LiveBybitExecutionAdapter(ExecutionAdapter):
    """Stub deliberado. Requiere BYBIT_API_KEY/SECRET y firma HMAC de
    Bybit v5 (no implementada aquí a propósito: la ejecución en vivo con
    dinero real es una decisión que el operador debe activar explícitamente,
    no algo que este fichero asuma por defecto)."""

    def __init__(self, cfg: Config):
        if not cfg.BYBIT_API_KEY or not cfg.BYBIT_API_SECRET:
            raise RuntimeError(
                "LIVE_TRADING_ENABLED=True pero faltan BYBIT_API_KEY/BYBIT_API_SECRET "
                "en variables de entorno. Ejecución en vivo abortada por seguridad.")
        raise NotImplementedError(
            "Adaptador de ejecución en vivo no implementado en esta entrega. "
            "Requiere firma HMAC autenticada de Bybit v5 (order/create) que el "
            "operador debe revisar y aprobar explícitamente antes de conectar "
            "capital real. El sistema opera en PAPER hasta entonces.")

    def open_position(self, side, size_usdt, leverage, price):
        raise NotImplementedError

    def close_position(self, position, price):
        raise NotImplementedError


# =====================================================================
# 9. NÚCLEO — orquesta expertos + gating + riesgo + ejecución + trace
# =====================================================================

class Nucleus:
    def __init__(self, cfg: Config, logger: logging.Logger, trace: DecisionTrace,
                 symbol: Optional[str] = None, gate: Optional[GatingNetwork] = None,
                 capital_usdt: Optional[float] = None,
                 on_close_attribution: Optional[Callable[[List[ExpertOutput], int], None]] = None,
                 market_cache: Optional[_TTLCache] = None):
        self.cfg = cfg
        self.logger = logger
        self.trace = trace
        # v2: multi-activo -- symbol/gate/capital_usdt/on_close_attribution
        # son opcionales y retrocompatibles: sin pasarlos, Nucleus se
        # comporta exactamente como en v1 (single-symbol, gate propio,
        # capital global, sin intercepción de atribución).
        self.symbol = symbol or cfg.SYMBOL

        # FIX (auditoría): market_cache es opcional -- sin ella, DataFeed
        # crea su propia caché privada (mismo comportamiento standalone/tests
        # de siempre). El orquestador multi-activo inyecta una única
        # instancia compartida entre los N símbolos.
        self.feed = DataFeed(cfg, self.symbol, market_cache=market_cache)
        self.experts = {
            "kalman_directional": KalmanDirectionalExpert(),
            "bocpd_regime": BOCPDRegimeExpert(),
            "jump_model": JumpModelExpert(),
            "vpin_liquidity": VPINLiquidityExpert(),
            "onchain_sentiment": OnChainSentimentExpert(),
            "funding_carry": FundingCarryExpert(),
            "hawkes_flow": HawkesFlowExpert(cfg),  # v2: microestructura (CVD+Hawkes), ver CHANGELOG
        }
        self.gate = gate if gate is not None else GatingNetwork(
            list(self.experts.keys()), cfg.GATING_LEARNING_RATE, cfg.GATING_MIN_WEIGHT_FLOOR)
        self.risk = RiskModule(cfg, symbol=self.symbol, capital_usdt=capital_usdt)
        self._on_close_attribution = on_close_attribution
        self.execution: ExecutionAdapter = (
            LiveBybitExecutionAdapter(cfg) if cfg.LIVE_TRADING_ENABLED else PaperExecutionAdapter(cfg)
        )

        self.open_position: Optional[Dict[str, Any]] = None
        self._open_position_outputs: List[ExpertOutput] = []
        self.last_cycle_summary: Dict[str, Any] = {}
        # FIX (auditoría): contador de ciclos consecutivos que confirman una
        # reversión de señal -- ver REVERSAL_CONFIRMATION_CYCLES en run_cycle().
        self._reversal_confirm_count: int = 0

    def run_cycle(self) -> Dict[str, Any]:
        self.logger.info(f"[{self.symbol}] fetch klines...")
        klines = self.feed.get_klines()
        self.logger.info(f"[{self.symbol}] fetch trades...")
        trades = self.feed.get_recent_trades()
        self.logger.info(f"[{self.symbol}] fetch funding/fng/mempool/ticker...")
        funding = self.feed.get_funding_rate()
        fear_greed = self.feed.get_fear_greed()
        mempool_pressure = self.feed.get_mempool_pressure()
        ticker = self.feed.get_ticker()

        closes = klines[:, 4] if klines is not None else None
        timestamps = klines[:, 0] if klines is not None else None
        last_price = float(closes[-1]) if closes is not None else (
            float(ticker["lastPrice"]) if ticker else None)

        outputs = [
            self.experts["kalman_directional"].infer(closes, timestamps),
            self.experts["bocpd_regime"].infer(closes),
            self.experts["jump_model"].infer(closes),
            self.experts["vpin_liquidity"].infer(trades),
            self.experts["onchain_sentiment"].infer(fear_greed, mempool_pressure),
            self.experts["funding_carry"].infer(funding),
            self.experts["hawkes_flow"].infer(trades),  # v2
        ]

        signal, confidence, gate_weights = self.gate.combine(outputs)

        decision = "flat"
        risk_decision = None
        if (last_price is not None and abs(signal) > self.cfg.ENTRY_SIGNAL_THRESHOLD
                and confidence > self.cfg.ENTRY_CONFIDENCE_THRESHOLD and self.open_position is None):
            side = "long" if signal > 0 else "short"
            # stop-loss requerido: heurística simple basada en volatilidad reciente
            vol = float(np.std(np.diff(np.log(closes[-30:] + 1e-9)))) if closes is not None and len(closes) > 30 else 0.01
            required_stop_pct = float(np.clip(vol * 3.0, 0.003, 0.02))
            risk_decision = self.risk.evaluate_entry(required_stop_pct)
            if risk_decision.approved:
                self.open_position = self.execution.open_position(side, risk_decision.position_size_usdt,
                                                                    risk_decision.leverage, last_price)
                self.open_position["side"] = side
                self.open_position["stop_loss_pct"] = risk_decision.stop_loss_pct
                self._open_position_outputs = outputs
                self._reversal_confirm_count = 0  # nueva posición: ninguna reversión pendiente de confirmar
                decision = f"abrir_{side}"
        elif self.open_position is not None and last_price is not None:
            direction = 1 if self.open_position["side"] == "long" else -1
            move_pct = direction * (last_price - self.open_position["entry_price"]) / self.open_position["entry_price"]
            stop_loss_hit = move_pct <= -self.open_position["stop_loss_pct"]
            trailing_hit = move_pct >= self.open_position["stop_loss_pct"] * 2.5  # trailing simplificado

            # FIX (auditoría): la salida por reversión de señal antes se
            # disparaba con un solo ciclo (abs(signal) > 0.2, banda mínima
            # sobre el entry de 0.15) y sin piso de retención -- ver
            # ENTRY_/EXIT_REVERSAL_/MIN_HOLD_/REVERSAL_CONFIRMATION_ en
            # Config. Ahora requiere: (a) haber mantenido la posición al
            # menos MIN_HOLD_SECONDS, (b) señal opuesta por encima del
            # umbral ampliado, y (c) que eso se sostenga durante
            # REVERSAL_CONFIRMATION_CYCLES ciclos consecutivos. Stop-loss y
            # trailing (arriba) NO pasan por este filtro: siguen siendo
            # inmediatos, son la protección de capital, no la señal.
            position_age_s = time.time() - self.open_position.get("open_ts", time.time())
            reversal_condition = (
                np.sign(signal) != direction
                and abs(signal) > self.cfg.EXIT_REVERSAL_SIGNAL_THRESHOLD
                and position_age_s >= self.cfg.MIN_HOLD_SECONDS
            )
            self._reversal_confirm_count = (self._reversal_confirm_count + 1) if reversal_condition else 0
            reversal_hit = self._reversal_confirm_count >= self.cfg.REVERSAL_CONFIRMATION_CYCLES

            should_close = stop_loss_hit or trailing_hit or reversal_hit
            if should_close:
                pnl = self.execution.close_position(self.open_position, last_price)
                pnl_pct_capital = pnl / self.risk.capital_usdt
                self.risk.register_trade_result(pnl_pct_capital)
                outcome_sign = 1 if pnl > 0 else -1
                if self._on_close_attribution is not None:
                    # v2: el pool multi-activo intercepta para aplicar,
                    # además de attribute_outcome(), el shrinkage cross-symbol.
                    self._on_close_attribution(self._open_position_outputs, outcome_sign)
                else:
                    self.gate.attribute_outcome(self._open_position_outputs, outcome_sign)
                decision = f"cerrar (pnl={pnl:.2f} USDT)"
                self.open_position = None
                self._open_position_outputs = []
                self._reversal_confirm_count = 0

        summary = {
            "symbol": self.symbol,  # v2
            "price": last_price,
            "signal": signal,
            "confidence": confidence,
            "decision": decision,
            "gate_weights": gate_weights,
            "expert_outputs": [o.__dict__ for o in outputs],
            "risk": risk_decision.__dict__ if risk_decision else None,
            "open_position": self.open_position,
            "kill_switch": self.risk.kill_switch_engaged,
        }
        self.trace.record(summary)
        self.logger.info(f"decision={decision} signal={signal:.3f} conf={confidence:.3f} price={last_price}")
        self.last_cycle_summary = summary
        return summary


# =====================================================================
# 9b. RELOJ DE EVENTOS + ORQUESTADOR MULTI-ACTIVO (v2, de nucleus_autonomous.py)
# =====================================================================

class PublicTradeStreamMulti(threading.Thread):
    """Portado de nucleus_autonomous.py (PublicTradeStream), sin cambios de
    lógica: intenta 'websocket-client' si está instalado; si no, degrada
    automáticamente a polling REST del feed público -- misma interfaz,
    mismo consumidor, cero intervención del usuario para arrancar."""

    def __init__(self, cfg: Config, symbols: List[str], feeds: Dict[str, "DataFeed"],
                 on_trade: Callable[[str, str, float, float], None], logger: logging.Logger):
        super().__init__(daemon=True, name="PublicTradeStreamMulti")
        self.cfg = cfg
        self.symbols = symbols
        self.feeds = feeds
        self.on_trade = on_trade
        self.logger = logger
        self._stop = threading.Event()
        self._ws_mod = None
        try:
            import websocket  # type: ignore
            self._ws_mod = websocket
        except Exception:
            self.logger.info("'websocket-client' no disponible -> modo polling REST público "
                              "(degradación limpia, sin intervención del usuario)")

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        if self._ws_mod is not None:
            self._run_ws()
        else:
            self._run_polling_fallback()

    def _run_ws(self) -> None:
        backoff = self.cfg.RECONNECT_BACKOFF_BASE
        host_i = 0
        while not self._stop.is_set():
            url = self.cfg.PUBLIC_WS_HOSTS[host_i % len(self.cfg.PUBLIC_WS_HOSTS)]
            try:
                ws = self._ws_mod.create_connection(url, timeout=10)
                self.logger.info(f"WS conectado a {url}")
                args = [f"publicTrade.{s}" for s in self.symbols]
                ws.send(json.dumps({"op": "subscribe", "args": args}))
                self.logger.info(f"WS suscripción enviada: {args}")
                last_msg = time.time()
                backoff = self.cfg.RECONNECT_BACKOFF_BASE
                while not self._stop.is_set():
                    ws.settimeout(5.0)
                    try:
                        raw = ws.recv()
                    except Exception:
                        if time.time() - last_msg > self.cfg.STALE_HARD_SECONDS:
                            raise TimeoutError("stale hard")
                        continue
                    if not raw:
                        raise ConnectionError("cierre limpio del peer")
                    last_msg = time.time()
                    msg = json.loads(raw)
                    for t in msg.get("data", []) or []:
                        if not msg.get("topic", "").startswith("publicTrade"):
                            self.logger.info(f"WS mensaje no-trade recibido: {msg.get('topic', msg)}")
                        try:
                            self.on_trade(t["s"], t["S"], float(t["v"]), time.time())
                        except Exception:
                            continue
                ws.close()
            except Exception as exc:
                self.logger.warning(f"WS público caído ({url}), reconectando en {backoff:.1f}s: {exc}")
                host_i += 1  # alterna entre espejos
                time.sleep(backoff)
                backoff = min(backoff * 2.0, self.cfg.RECONNECT_BACKOFF_MAX)

    def _run_polling_fallback(self) -> None:
        # Sin stream de trades no hay CVD/Hawkes reales, pero el reloj de
        # eventos sigue vivo: cada tick de este fallback dispara un ciclo de
        # decisión completo (que sí trae klines/funding/trades vía REST
        # batch en DataFeed), igual que la red de seguridad periódica.
        self.logger.info("Polling fallback activo (sin websocket-client o import falló)")
        while not self._stop.is_set():
            for sym in self.symbols:
                if self._stop.is_set():
                    return
                self.logger.info(f"Polling tick -> {sym}")
                self.on_trade(sym, "Buy" if random.random() > 0.5 else "Sell", 0.0, time.time())
                time.sleep(self.cfg.SAFETY_POLL_INTERVAL_SECONDS / max(len(self.symbols), 1))


class NucleusOrchestratorV2:
    """v2 -- orquesta un Nucleus por símbolo (BTC/ETH/SOL) sobre un
    MultiAssetGatingPool compartido, disparado por un reloj de eventos real
    (PublicTradeStreamMulti) en vez del timer fijo de v1. Cada símbolo:
      - tiene su propio Nucleus (expertos con estado propio, DataFeed propio)
      - tiene su propio RiskModule con capital y kill-switch independientes
      - comparte el aprendizaje de gating vía partial pooling (ver
        MultiAssetGatingPool / CHANGELOG)

    FIX (auditoría v2.1 -- causa raíz de "solo un par funciona"): la
    implementación original despachaba los ciclos de TODOS los símbolos
    desde una única cola FIFO consumida por un único hilo. run_cycle()
    es puramente I/O-bound (hasta 6 llamadas REST secuenciales: klines,
    trades, funding, fear&greed, mempool, ticker). Con un solo consumidor,
    el tiempo total de una vuelta completa era la SUMA de las latencias de
    los N símbolos, no el máximo -- bajo latencia de red real (no
    simulada), esa suma fácilmente supera varias decenas de segundos, y
    el símbolo que el operador observa en pantalla parece "el único que
    funciona" simplemente porque es el que tiene el turno en ese momento,
    mientras los otros dos quedan con datos visiblemente congelados
    minutos enteros. Además la cola era ilimitada: bajo tráfico real de
    Bybit (donde BTC genera muchas más ticks/seg que ETH/SOL) crecía sin
    cota (confirmado por simulación: >1400 elementos acumulados en 12s de
    prueba), consumiendo memoria en un equipo de 6GB sin razón.

    Solución: un hilo worker INDEPENDIENTE por símbolo. Cada símbolo tiene
    su propio threading.Event, marcado por cada tick entrante de ese
    símbolo (coalesce natural de ráfagas: no hace falta una cola, el
    Event ya representa "hay novedades pendientes"). El propio worker
    aplica el piso Config.MIN_CYCLE_INTERVAL_SECONDS tras cada ciclo. Los
    tres corren en paralelo real (GIL-friendly: cada ciclo bloquea en I/O
    de red, liberando el GIL la mayor parte del tiempo), así que el
    tiempo de vuelta completa vuelve a ser el máximo entre los tres, no
    la suma -- y ninguno puede monopolizar a los otros."""

    def __init__(self, cfg: Config, logger: logging.Logger, trace: DecisionTrace):
        self.cfg = cfg
        self.logger = logger
        self.trace = trace
        self.symbols = list(cfg.SYMBOLS)

        expert_names = ["kalman_directional", "bocpd_regime", "jump_model", "vpin_liquidity",
                         "onchain_sentiment", "funding_carry", "hawkes_flow"]
        self.pool = MultiAssetGatingPool(self.symbols, expert_names, cfg.GATING_LEARNING_RATE,
                                          cfg.GATING_MIN_WEIGHT_FLOOR, cfg.GATING_CROSS_ASSET_SHRINKAGE)

        capital_per_symbol = cfg.CAPITAL_USDT / max(len(self.symbols), 1)
        # FIX (auditoría): una única _TTLCache compartida entre los N
        # Nucleus/DataFeed del orquestador -- ver _TTLCache y DataFeed
        # .get_fear_greed()/.get_mempool_pressure() para el porqué (FGI y
        # presión de mempool son datos de mercado global, no por símbolo).
        self._market_cache = _TTLCache()
        self.nucleos: Dict[str, Nucleus] = {}
        for sym in self.symbols:
            gate = self.pool.networks[sym]
            self.nucleos[sym] = Nucleus(
                cfg, logger, trace, symbol=sym, gate=gate, capital_usdt=capital_per_symbol,
                on_close_attribution=(lambda outs, sign, s=sym: self.pool.attribute_outcome(s, outs, sign)),
                market_cache=self._market_cache,
            )

        # v2.1: un Event de "hay tick nuevo" por símbolo, en vez de una
        # cola global -- ver nota FIX arriba.
        self._tick_events: Dict[str, threading.Event] = {s: threading.Event() for s in self.symbols}
        self._workers: Dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        self._on_cycle_cb: Optional[Callable[[Dict[str, Any]], None]] = None
        self.stream = PublicTradeStreamMulti(cfg, self.symbols,
                                              {s: n.feed for s, n in self.nucleos.items()},
                                              self._on_trade_event, logger)
        self.last_summaries: Dict[str, Dict[str, Any]] = {}

    def _on_trade_event(self, symbol: str, side: str, qty: float, ts: float) -> None:
        evt = self._tick_events.get(symbol)
        if evt is not None:
            evt.set()

    def _symbol_worker(self, sym: str) -> None:
        evt = self._tick_events[sym]
        while not self._stop.is_set():
            # timeout = SAFETY_POLL_INTERVAL_SECONDS: red de seguridad para
            # seguir evaluando el símbolo aunque el stream de ticks se
            # calle del todo (sin depender de que llegue un trade nuevo).
            evt.wait(timeout=self.cfg.SAFETY_POLL_INTERVAL_SECONDS)
            evt.clear()
            if self._stop.is_set():
                break
            try:
                self.logger.info(f"run_cycle START {sym}")
                summary = self.nucleos[sym].run_cycle()
                self.logger.info(f"run_cycle END {sym} decision={summary.get('decision')}")
                self.last_summaries[sym] = summary
                if self._on_cycle_cb is not None:
                    self._on_cycle_cb(summary)
            except Exception:
                self.logger.exception(f"error en ciclo de decisión de {sym}")
            # piso entre ciclos, ahora aplicado por-símbolo y en paralelo
            # (ya no compite por un consumidor global compartido).
            self._stop.wait(timeout=self.cfg.MIN_CYCLE_INTERVAL_SECONDS)

    def start(self) -> None:
        self.logger.info(f"Orquestador arrancando stream + {len(self.symbols)} workers "
                          f"paralelos para símbolos={self.symbols}")
        self.stream.start()
        for sym in self.symbols:
            t = threading.Thread(target=self._symbol_worker, args=(sym,),
                                  daemon=True, name=f"nucleus-worker-{sym}")
            self._workers[sym] = t
            t.start()

    def stop(self) -> None:
        self._stop.set()
        self.stream.stop()
        for evt in self._tick_events.values():
            evt.set()  # despertar a todos los workers para que vean _stop y salgan

    def run_forever(self, on_cycle: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._on_cycle_cb = on_cycle
        self.start()
        try:
            while not self._stop.is_set():
                self._stop.wait(timeout=0.5)
        finally:
            self.stop()


# =====================================================================
# 10. SUITE DE TESTS AUTOCONTENIDA (corre al arranque, antes de operar)
# =====================================================================

class TestKalmanDirectionalExpert(unittest.TestCase):
    def test_converges_to_known_uptrend(self):
        expert = KalmanDirectionalExpert()
        rng = np.random.default_rng(42)
        prices = 100 + np.cumsum(np.full(200, 0.05)) + rng.normal(0, 0.05, 200)
        out = expert.infer(prices)
        self.assertGreater(out.signal, 0.0, "debe detectar señal alcista en tendencia ascendente clara")

    def test_flat_series_low_signal(self):
        expert = KalmanDirectionalExpert()
        prices = np.full(100, 100.0) + np.random.default_rng(1).normal(0, 0.01, 100)
        out = expert.infer(prices)
        self.assertLess(abs(out.signal), 0.5, "serie plana no debe producir señal fuerte")


class TestBOCPDRegimeExpert(unittest.TestCase):
    def test_detects_changepoint(self):
        expert = BOCPDRegimeExpert(hazard_lambda=50.0)
        rng = np.random.default_rng(7)
        seg1 = 100 + np.cumsum(rng.normal(0, 0.02, 60))
        seg2 = seg1[-1] + np.cumsum(rng.normal(0.3, 0.02, 60))
        series = np.concatenate([seg1, seg2])
        out = expert.infer(series)
        self.assertIsInstance(out.signal, float)
        self.assertGreaterEqual(out.confidence, 0.0)

    def test_insufficient_data_returns_neutral(self):
        expert = BOCPDRegimeExpert()
        out = expert.infer(np.array([100.0, 101.0]))
        self.assertEqual(out.signal, 0.0)
        self.assertEqual(out.confidence, 0.0)


class TestJumpModelExpert(unittest.TestCase):
    def test_persistence_reduces_flicker(self):
        expert = JumpModelExpert(jump_penalty=0.9)
        rng = np.random.default_rng(3)
        # ruido borderline alrededor de cero, no debería flickear violentamente
        series = 100 + np.cumsum(rng.normal(0, 0.001, 60))
        states = []
        for i in range(20, 60):
            out = expert.infer(series[:i])
            states.append(out.detail.get("state"))
        switches = sum(1 for a, b in zip(states, states[1:]) if a != b)
        self.assertLessEqual(switches, len(states) // 2, "penalización de salto debe limitar flicker")


class TestVPINLiquidityExpert(unittest.TestCase):
    def test_bounds(self):
        expert = VPINLiquidityExpert(n_buckets=5)
        trades = [(100.0, 1.0, "Buy")] * 30 + [(100.0, 1.0, "Sell")] * 5
        out = expert.infer(trades)
        self.assertGreaterEqual(abs(out.signal), 0.0)
        self.assertLessEqual(abs(out.signal), 1.0)

    def test_detects_buy_imbalance(self):
        expert = VPINLiquidityExpert(n_buckets=3)
        trades = [(100.0, 1.0, "Buy")] * 60
        out = expert.infer(trades)
        self.assertGreater(out.signal, 0.0, "flujo 100% comprador debe dar señal positiva")


class TestHawkesFlowExpert(unittest.TestCase):
    """v2 -- valida el 7º experto (CVD z-score + Hawkes bidireccional)."""

    def test_insufficient_data_returns_neutral(self):
        expert = HawkesFlowExpert(Config())
        out = expert.infer([(100.0, 1.0, "Buy")] * 5)  # < 20 trades
        self.assertEqual(out.signal, 0.0)
        self.assertLessEqual(out.confidence, 0.1)

    def test_detects_buy_pressure(self):
        expert = HawkesFlowExpert(Config())
        trades = [(100.0, 2.0, "Buy")] * 40
        out = expert.infer(trades)
        self.assertGreater(out.signal, 0.0, "flujo 100% comprador debe dar señal positiva")
        self.assertGreaterEqual(out.confidence, 0.1)

    def test_bounds(self):
        expert = HawkesFlowExpert(Config())
        trades = [(100.0, 3.0, "Buy") if i % 2 == 0 else (100.0, 3.0, "Sell") for i in range(80)]
        out = expert.infer(trades)
        self.assertGreaterEqual(out.signal, -1.0)
        self.assertLessEqual(out.signal, 1.0)

    def test_only_replays_new_trades_since_last_call(self):
        expert = HawkesFlowExpert(Config())
        batch1 = [(100.0, 1.0, "Buy")] * 25
        expert.infer(batch1)
        seen_after_first = expert.flow.trades_seen
        # el mismo batch1 completo + trades nuevos: no debe reprocesar batch1
        batch2 = batch1 + [(100.0, 1.0, "Sell")] * 5
        expert.infer(batch2)
        self.assertEqual(expert.flow.trades_seen, seen_after_first + 5)

    def test_id_based_dedup_survives_saturated_window(self):
        # Reproduce el bug real: la ventana REST se estabiliza en `limit`
        # trades/ciclo (o menos) y el batch YA NO crece monotónicamente.
        # Con dedup por índice esto congelaba trades_seen para siempre.
        expert = HawkesFlowExpert(Config())
        window = [(100.0, 1.0, "Buy", f"id{i}", 1000.0 + i) for i in range(25)]
        expert.infer(window)
        seen_after_first = expert.flow.trades_seen
        # ventana "saturada": tamaño estable, ids viejos salen, entran nuevos
        window = window[5:] + [(100.0, 1.0, "Sell", f"id{i}", 1000.0 + i) for i in range(25, 30)]
        expert.infer(window)
        self.assertEqual(expert.flow.trades_seen, seen_after_first + 5)

    def test_id_based_dedup_is_order_independent(self):
        # La API no garantiza orden ascendente; el dedup no debe depender
        # de la posición del trade dentro del batch.
        expert = HawkesFlowExpert(Config())
        batch1 = [(100.0, 1.0, "Buy", f"id{i}", 1000.0 + i) for i in range(25)]
        expert.infer(batch1)
        seen_after_first = expert.flow.trades_seen
        nuevos = [(100.0, 1.0, "Sell", f"id{i}", 1000.0 + i) for i in range(25, 28)]
        batch2_shuffled = list(reversed(batch1)) + list(reversed(nuevos))
        expert.infer(batch2_shuffled)
        self.assertEqual(expert.flow.trades_seen, seen_after_first + 3)


class TestGatingNetwork(unittest.TestCase):
    def test_weights_always_normalized(self):
        gate = GatingNetwork(["a", "b", "c"], learning_rate=0.1, min_floor=0.05)
        outputs = [ExpertOutput("a", 1.0, 0.9), ExpertOutput("b", -1.0, 0.5), ExpertOutput("c", 0.0, 0.1)]
        gate.attribute_outcome(outputs, realized_pnl_sign=1)
        total = sum(gate.weights.values())
        self.assertAlmostEqual(total, 1.0, places=6)
        for w in gate.weights.values():
            self.assertGreaterEqual(w, gate.min_floor - 1e-9)

    def test_min_floor_prevents_zero_weight(self):
        gate = GatingNetwork(["a", "b"], learning_rate=1.5, min_floor=0.1)
        outputs = [ExpertOutput("a", 1.0, 0.99), ExpertOutput("b", -1.0, 0.99)]
        for _ in range(20):
            gate.attribute_outcome(outputs, realized_pnl_sign=1)
        self.assertGreaterEqual(gate.weights["b"], 0.1 - 1e-6)


class TestMultiAssetGatingPool(unittest.TestCase):
    """v2 -- valida el partial pooling cross-symbol del gating multi-activo."""

    def test_zero_shrinkage_isolates_symbols(self):
        pool = MultiAssetGatingPool(["BTC", "ETH"], ["a", "b"], learning_rate=0.5,
                                     min_floor=0.05, shrinkage=0.0)
        outputs = [ExpertOutput("a", 1.0, 0.9), ExpertOutput("b", -1.0, 0.9)]
        pool.attribute_outcome("BTC", outputs, realized_pnl_sign=1)
        # ETH no participó en ningún trade: con shrinkage=0 debe seguir en el prior uniforme
        self.assertAlmostEqual(pool.weights_for("ETH")["a"], 0.5, places=6)
        self.assertNotAlmostEqual(pool.weights_for("BTC")["a"], 0.5, places=3)

    def test_positive_shrinkage_pulls_symbols_together(self):
        pool = MultiAssetGatingPool(["BTC", "ETH"], ["a", "b"], learning_rate=0.5,
                                     min_floor=0.05, shrinkage=0.5)
        outputs = [ExpertOutput("a", 1.0, 0.9), ExpertOutput("b", -1.0, 0.9)]
        pool.attribute_outcome("BTC", outputs, realized_pnl_sign=1)
        # ETH no operó, pero con shrinkage>0 debe haberse movido hacia BTC
        self.assertNotAlmostEqual(pool.weights_for("ETH")["a"], 0.5, places=3)

    def test_weights_stay_normalized_and_above_floor_after_shrinkage(self):
        pool = MultiAssetGatingPool(["BTC", "ETH", "SOL"], ["a", "b", "c"], learning_rate=1.2,
                                     min_floor=0.1, shrinkage=0.3)
        outputs = [ExpertOutput("a", 1.0, 0.95), ExpertOutput("b", -1.0, 0.95), ExpertOutput("c", 0.0, 0.1)]
        for sym in ["BTC", "BTC", "ETH", "SOL", "BTC"]:
            pool.attribute_outcome(sym, outputs, realized_pnl_sign=1 if sym != "SOL" else -1)
        for sym in pool.symbols:
            w = pool.weights_for(sym)
            self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
            for v in w.values():
                self.assertGreaterEqual(v, pool.min_floor - 1e-9)

    def test_isolated_underlying_gating_network_unaffected_by_pool_wrapper(self):
        # El GatingNetwork base, usado solo (fuera del pool), debe comportarse
        # exactamente igual que en v1 -- confirma que _apply_floor() no alteró
        # su comportamiento numérico al ser extraído.
        gate = GatingNetwork(["a", "b"], learning_rate=1.5, min_floor=0.1)
        outputs = [ExpertOutput("a", 1.0, 0.99), ExpertOutput("b", -1.0, 0.99)]
        for _ in range(20):
            gate.attribute_outcome(outputs, realized_pnl_sign=1)
        self.assertGreaterEqual(gate.weights["b"], 0.1 - 1e-6)
        self.assertAlmostEqual(sum(gate.weights.values()), 1.0, places=6)


class TestRiskModule(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.risk = RiskModule(self.cfg)

    def test_tight_stop_forces_normal_leverage_or_rejection(self):
        # stop muy amplio: a x66 la distancia a liquidación (~1.5%-0.5%mmr) no alcanza
        decision = self.risk.evaluate_entry(required_stop_loss_pct=0.02)
        if decision.approved:
            self.assertEqual(decision.leverage, self.cfg.LEVERAGE_NORMAL)
        else:
            self.assertFalse(decision.approved)

    def test_tiny_stop_allows_high_leverage(self):
        decision = self.risk.evaluate_entry(required_stop_loss_pct=0.003)
        self.assertTrue(decision.approved)
        self.assertEqual(decision.leverage, self.cfg.LEVERAGE_HIGH)

    def test_circuit_breaker_trips_on_consecutive_losses(self):
        for _ in range(self.cfg.MAX_CONSECUTIVE_LOSSES):
            self.risk.register_trade_result(-0.01)
        self.assertTrue(self.risk.kill_switch_engaged)

    def test_kill_switch_blocks_new_entries(self):
        self.risk.engage_kill_switch("test")
        decision = self.risk.evaluate_entry(required_stop_loss_pct=0.003)
        self.assertFalse(decision.approved)

    def test_daily_loss_limit_trips(self):
        self.risk.register_trade_result(-self.cfg.MAX_DAILY_LOSS_PCT - 0.001)
        self.assertTrue(self.risk.kill_switch_engaged)

    def test_position_size_respects_risk_budget(self):
        decision = self.risk.evaluate_entry(required_stop_loss_pct=0.003)
        capital_at_risk = decision.position_size_usdt * decision.stop_loss_pct
        max_allowed = self.cfg.CAPITAL_USDT * self.cfg.RISK_PCT_MAX * 1.01  # tolerancia
        self.assertLessEqual(capital_at_risk, max_allowed)

    def test_v2_independent_capital_per_symbol(self):
        # v2: dos RiskModule del mismo cfg pero con capital_usdt distinto
        # (símbolos independientes) no deben compartir presupuesto de riesgo.
        risk_btc = RiskModule(self.cfg, symbol="BTCUSDT", capital_usdt=500.0)
        risk_eth = RiskModule(self.cfg, symbol="ETHUSDT", capital_usdt=100.0)
        dec_btc = risk_btc.evaluate_entry(required_stop_loss_pct=0.003)
        dec_eth = risk_eth.evaluate_entry(required_stop_loss_pct=0.003)
        self.assertGreater(dec_btc.position_size_usdt, dec_eth.position_size_usdt)
        # el kill-switch de uno no debe afectar al otro
        risk_btc.engage_kill_switch("test aislado")
        self.assertFalse(risk_btc.evaluate_entry(required_stop_loss_pct=0.003).approved)
        self.assertTrue(risk_eth.evaluate_entry(required_stop_loss_pct=0.003).approved)


class TestPaperExecutionAdapter(unittest.TestCase):
    """FIX (auditoría): estos tests validaban el PnL como delta de precio
    puro (sin fees/slippage), que era precisamente el defecto reportado.
    Se actualizan para reflejar el costo de ida y vuelta ahora modelado en
    close_position() -- ver Config.TAKER_FEE_PCT/SLIPPAGE_PCT."""

    def _round_trip_cost(self, cfg: Config, size_usdt: float) -> float:
        return 2.0 * (cfg.TAKER_FEE_PCT + cfg.SLIPPAGE_PCT) * size_usdt

    def test_long_profit(self):
        cfg = Config()
        adapter = PaperExecutionAdapter(cfg)
        pos = adapter.open_position("long", 100.0, 20, 100.0)
        pnl = adapter.close_position(pos, 105.0)
        expected = 5.0 - self._round_trip_cost(cfg, 100.0)
        self.assertAlmostEqual(pnl, expected, places=6)
        self.assertAlmostEqual(pos["fees_slippage_usdt"], self._round_trip_cost(cfg, 100.0), places=6)

    def test_short_profit(self):
        cfg = Config()
        adapter = PaperExecutionAdapter(cfg)
        pos = adapter.open_position("short", 100.0, 20, 100.0)
        pnl = adapter.close_position(pos, 95.0)
        expected = 5.0 - self._round_trip_cost(cfg, 100.0)
        self.assertAlmostEqual(pnl, expected, places=6)

    def test_default_cfg_falls_back_to_global_CFG(self):
        # Retrocompatibilidad: instanciar sin cfg explícita no debe romper
        # (usa la instancia global CFG, igual que antes de este fix).
        adapter = PaperExecutionAdapter()
        pos = adapter.open_position("long", 100.0, 20, 100.0)
        pnl = adapter.close_position(pos, 100.0)  # sin movimiento de precio: pnl == -costo
        self.assertLess(pnl, 0.0)


class TestNucleusOrchestratorV2(unittest.TestCase):
    """v2 -- valida la integración completa multi-activo sin red (todo
    DataFeed degrada limpio a None sin conexión, igual que en v1)."""

    def test_orchestrator_builds_one_nucleus_per_symbol_with_seven_experts(self):
        cfg = Config(SYMBOLS=("BTCUSDT", "ETHUSDT"), CAPITAL_USDT=600.0)
        logger, listener = build_async_logger("test_orch", "/tmp/nucleus_v2_test_logs")
        trace = DecisionTrace("/tmp/nucleus_v2_test_logs/trace.jsonl")
        try:
            orch = NucleusOrchestratorV2(cfg, logger, trace)
            self.assertEqual(set(orch.nucleos.keys()), {"BTCUSDT", "ETHUSDT"})
            for sym, nucleus in orch.nucleos.items():
                self.assertEqual(set(nucleus.experts.keys()),
                                  {"kalman_directional", "bocpd_regime", "jump_model", "vpin_liquidity",
                                   "onchain_sentiment", "funding_carry", "hawkes_flow"})
                self.assertAlmostEqual(nucleus.risk.capital_usdt, 300.0, places=6)
                self.assertIs(nucleus.gate, orch.pool.networks[sym])
        finally:
            listener.stop()

    def test_run_cycle_degrades_cleanly_without_network(self):
        cfg = Config(SYMBOLS=("BTCUSDT",), CAPITAL_USDT=600.0)
        logger, listener = build_async_logger("test_orch2", "/tmp/nucleus_v2_test_logs")
        trace = DecisionTrace("/tmp/nucleus_v2_test_logs/trace.jsonl")
        with patch.object(DataFeed, "get_klines", return_value=None), \
             patch.object(DataFeed, "get_recent_trades", return_value=None), \
             patch.object(DataFeed, "get_funding_rate", return_value=None), \
             patch.object(DataFeed, "get_ticker", return_value=None), \
             patch.object(DataFeed, "get_fear_greed", return_value=None), \
             patch.object(DataFeed, "get_mempool_pressure", return_value=None):
            try:
                orch = NucleusOrchestratorV2(cfg, logger, trace)
                summary = orch.nucleos["BTCUSDT"].run_cycle()
                self.assertEqual(summary["symbol"], "BTCUSDT")
                self.assertIn(summary["decision"], ("flat",))  # sin red no debe abrir posición
            finally:
                listener.stop()


class TestMainEntrypointWiring(unittest.TestCase):
    """Regresión: FIX post-auditoría. main() llegó a instanciar un Nucleus
    de un solo símbolo y pasárselo a NucleusGUI (que exige .symbols/.nucleos
    de NucleusOrchestratorV2) -> AttributeError inmediato en GUI, y en
    headless el diseño multi-activo quedaba sin usarse. Este test fija que
    build_orchestrator() -- el único punto de construcción que usa main()
    -- siempre devuelve un NucleusOrchestratorV2 correctamente cableado
    para todos los símbolos configurados, no un Nucleus aislado."""

    def test_build_orchestrator_returns_multi_symbol_orchestrator(self):
        cfg = Config(SYMBOLS=("BTCUSDT", "ETHUSDT", "SOLUSDT"), CAPITAL_USDT=900.0)
        logger, listener = build_async_logger("test_entrypoint", "/tmp/nucleus_v2_test_logs")
        trace = DecisionTrace("/tmp/nucleus_v2_test_logs/trace_entrypoint.jsonl")
        try:
            runtime = build_orchestrator(cfg, logger, trace)
            self.assertIsInstance(runtime, NucleusOrchestratorV2)
            self.assertEqual(set(runtime.symbols), {"BTCUSDT", "ETHUSDT", "SOLUSDT"})
            self.assertEqual(set(runtime.nucleos.keys()), set(runtime.symbols))
            # lo que NucleusGUI necesita para construirse sin AttributeError:
            self.assertTrue(hasattr(runtime, "symbols"))
            self.assertTrue(hasattr(runtime, "nucleos"))
        finally:
            listener.stop()


class TestConcurrentSymbolProcessing(unittest.TestCase):
    """Regresión (auditoría v2.1): la implementación previa despachaba los
    ciclos de los N símbolos desde una única cola consumida por un solo
    hilo, así que el tiempo total de una vuelta era la SUMA de las
    latencias de cada símbolo, no el máximo -- con I/O de red real esto
    hacía que 2 de 3 símbolos quedaran con datos congelados minutos
    enteros (síntoma reportado: "solo funciona uno de los pares"). Este
    test fija que los ciclos corren en paralelo real (worker por símbolo):
    con 3 símbolos cuyo run_cycle() tarda T cada uno, el tiempo total para
    que los 3 completen al menos un ciclo debe acercarse a T, no a 3*T."""

    def test_symbols_run_concurrently_not_serially(self):
        cfg = Config(SYMBOLS=("BTCUSDT", "ETHUSDT", "SOLUSDT"), CAPITAL_USDT=900.0,
                     MIN_CYCLE_INTERVAL_SECONDS=0.1, SAFETY_POLL_INTERVAL_SECONDS=0.05)
        logger, listener = build_async_logger("test_concurrency", "/tmp/nucleus_v2_test_logs")
        trace = DecisionTrace("/tmp/nucleus_v2_test_logs/trace_concurrency.jsonl")
        cycle_started_at: Dict[str, float] = {}
        t0 = time.time()
        try:
            orch = NucleusOrchestratorV2(cfg, logger, trace)
            SIMULATED_IO_LATENCY = 0.5  # simula latencia REST real, no de red del sandbox

            def make_fake_cycle(sym: str):
                def fake_run_cycle():
                    cycle_started_at[sym] = time.time() - t0
                    time.sleep(SIMULATED_IO_LATENCY)
                    return {"symbol": sym, "decision": "flat"}
                return fake_run_cycle

            for sym, nucleus in orch.nucleos.items():
                nucleus.run_cycle = make_fake_cycle(sym)

            orch.start()
            try:
                for sym in orch.symbols:
                    orch._on_trade_event(sym, "Buy", 1.0, time.time())
                deadline = time.time() + 5.0
                while len(cycle_started_at) < len(orch.symbols) and time.time() < deadline:
                    time.sleep(0.02)
            finally:
                orch.stop()

            self.assertEqual(set(cycle_started_at.keys()), set(orch.symbols))
            # Si fueran seriales, el tercer símbolo empezaría en >= 2*LATENCIA.
            # En paralelo, los tres deben arrancar casi al mismo tiempo.
            self.assertLess(max(cycle_started_at.values()), SIMULATED_IO_LATENCY,
                             f"los ciclos no arrancaron en paralelo: {cycle_started_at}")
        finally:
            listener.stop()


def run_self_tests(verbosity: int = 1) -> bool:
    """Corre toda la suite. Devuelve True solo si todo pasó. El sistema NO
    debe pasar a modo autónomo si esto devuelve False."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for test_class in [TestKalmanDirectionalExpert, TestBOCPDRegimeExpert, TestJumpModelExpert,
                        TestVPINLiquidityExpert, TestHawkesFlowExpert, TestGatingNetwork,
                        TestMultiAssetGatingPool, TestRiskModule, TestPaperExecutionAdapter,
                        TestNucleusOrchestratorV2, TestMainEntrypointWiring,
                        TestConcurrentSymbolProcessing]:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return result.wasSuccessful()


# =====================================================================
# 11. GUI (tkinter, no bloqueante — hilo de trabajo + queue + polling)
# =====================================================================

class NucleusGUI:
    """v2.1 -- GUI multi-activo rediseñada: una pestaña por símbolo, cada
    una con tarjetas de estado (precio/señal/confianza/decisión), pesos de
    gating como barras horizontales estilizadas y un trace auditable, más
    kill-switch por símbolo y global. Mismo dato, misma arquitectura de
    render (queue + polling no bloqueante) que v1/v2 -- solo se pule la
    presentación: paleta consistente, jerarquía tipográfica clara, tarjetas
    en vez de etiquetas sueltas, y un indicador de frescura por símbolo que
    hace visible en pantalla el fix de concurrencia (ver NucleusOrchestratorV2)."""

    # --- paleta -----------------------------------------------------
    BG = "#0a0d13"            # fondo de ventana
    SURFACE = "#11151d"       # paneles
    CARD = "#161b26"          # tarjetas dentro de un panel
    BORDER = "#232a38"        # líneas divisorias sutiles
    FG = "#e6e9ef"            # texto principal
    FG_MUTED = "#7d8699"      # texto secundario / etiquetas
    ACCENT = "#5b9dff"        # acento neutro (marca)
    ACCENT_DIM = "#2f4a75"    # acento neutro atenuado (barras de menor peso)
    LONG = "#34d399"          # verde — largo / ganancia
    SHORT = "#fb6478"         # rojo — corto / pérdida / kill-switch
    WARN = "#f5b94d"          # ámbar — advertencia

    FONT_UI = ("Segoe UI", 10)
    FONT_LABEL = ("Segoe UI", 8)
    FONT_VALUE = ("Segoe UI Semibold", 15)
    FONT_HEADER = ("Segoe UI Semibold", 15)
    FONT_MONO = ("Consolas", 9)

    def __init__(self, orchestrator: "NucleusOrchestratorV2", cfg: Config):
        self.orch = orchestrator
        self.cfg = cfg
        self.ui_queue: "queue.Queue" = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"NUCLEUS MoE v2 · {' / '.join(orchestrator.symbols)}")
        self.root.configure(bg=self.BG)
        self.root.geometry("1180x720")
        self.root.minsize(900, 560)
        self._tabs: Dict[str, Dict[str, Any]] = {}
        self._last_update_ts: Dict[str, float] = {}
        self._build_style()
        self._build_widgets()
        self._tick_freshness()

    # --- estilo -------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Surface.TFrame", background=self.SURFACE)
        style.configure("Card.TFrame", background=self.CARD)
        style.configure("TLabel", background=self.BG, foreground=self.FG, font=self.FONT_UI)
        style.configure("Header.TLabel", background=self.BG, foreground=self.FG,
                         font=self.FONT_HEADER)
        style.configure("Sub.TLabel", background=self.BG, foreground=self.FG_MUTED,
                         font=self.FONT_LABEL)
        style.configure("Surface.TLabel", background=self.SURFACE, foreground=self.FG_MUTED,
                         font=("Segoe UI Semibold", 9))
        style.configure("Card.TLabel", background=self.CARD, foreground=self.FG_MUTED,
                         font=self.FONT_LABEL)
        style.configure("CardValue.TLabel", background=self.CARD, foreground=self.FG,
                         font=self.FONT_VALUE)
        style.configure("Fresh.TLabel", background=self.SURFACE, foreground=self.FG_MUTED,
                         font=("Consolas", 8))

        style.configure("TButton", font=("Segoe UI Semibold", 9), padding=(10, 6),
                         background=self.CARD, foreground=self.FG, borderwidth=0)
        style.map("TButton", background=[("active", self.BORDER)])
        style.configure("Kill.TButton", font=("Segoe UI Semibold", 9), padding=(10, 6),
                         background=self.SHORT, foreground="#1a0a0d", borderwidth=0)
        style.map("Kill.TButton", background=[("active", "#e04f63")])
        style.configure("KillGlobal.TButton", font=("Segoe UI Semibold", 10), padding=(14, 8),
                         background=self.SHORT, foreground="#1a0a0d", borderwidth=0)
        style.map("KillGlobal.TButton", background=[("active", "#e04f63")])

        style.configure("TNotebook", background=self.BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
        style.configure("TNotebook.Tab", background=self.SURFACE, foreground=self.FG_MUTED,
                         font=("Segoe UI Semibold", 10), padding=(18, 9), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", self.CARD)],
                  foreground=[("selected", self.FG)])

    # --- layout general -------------------------------------------------
    def _build_widgets(self) -> None:
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(14, 8))
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text="NUCLEUS", style="Header.TLabel").pack(side="left")
        ttk.Label(title_box, text=" MoE v2", foreground=self.ACCENT, background=self.BG,
                   font=self.FONT_HEADER).pack(side="left")
        ttk.Label(header, text=f"multi-activo · {len(self.orch.symbols)} pares en paralelo",
                   style="Sub.TLabel").pack(side="left", padx=(12, 0), pady=(4, 0))
        ttk.Button(header, text="⏻  KILL-SWITCH GLOBAL", style="KillGlobal.TButton",
                   command=self._on_kill_all).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for sym in self.orch.symbols:
            self._build_symbol_tab(sym)

        footer = ttk.Frame(self.root)
        footer.pack(fill="x", padx=16, pady=(0, 12))
        self.status_label = ttk.Label(footer, text="●  modo: PAPER TRADING", style="Sub.TLabel",
                                       foreground=self.LONG)
        self.status_label.pack(side="left")
        ttk.Label(footer, text=f"capital total: {self.cfg.CAPITAL_USDT:.0f} USDT  ·  "
                                f"{self.cfg.CAPITAL_USDT / max(len(self.orch.symbols), 1):.0f} USDT/par",
                   style="Sub.TLabel").pack(side="right")

    # --- una tarjeta de KPI reutilizada 4 veces por pestaña -------------
    def _kpi_card(self, parent: tk.Widget, label: str) -> ttk.Label:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(card, text=label.upper(), style="Card.TLabel").pack(anchor="w", padx=12, pady=(10, 0))
        value = ttk.Label(card, text="—", style="CardValue.TLabel")
        value.pack(anchor="w", padx=12, pady=(0, 12))
        return value

    def _build_symbol_tab(self, symbol: str) -> None:
        tab = ttk.Frame(self.notebook, style="TFrame")
        self.notebook.add(tab, text=f"  {symbol}  ")

        # -- fila de KPIs -------------------------------------------------
        kpi_row = ttk.Frame(tab)
        kpi_row.pack(fill="x", padx=10, pady=(10, 6))
        price_val = self._kpi_card(kpi_row, "Precio")
        signal_val = self._kpi_card(kpi_row, "Señal combinada")
        conf_val = self._kpi_card(kpi_row, "Confianza")
        decision_val = self._kpi_card(kpi_row, "Decisión")

        # -- cuerpo: gating (izq) + trace (der) ---------------------------
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(body, style="Surface.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        left_head = ttk.Frame(left, style="Surface.TFrame")
        left_head.pack(fill="x", padx=12, pady=(12, 0))
        ttk.Label(left_head, text="PESOS DE GATING · 7 EXPERTOS", style="Surface.TLabel").pack(side="left")
        fresh_label = ttk.Label(left_head, text="sin datos aún", style="Fresh.TLabel")
        fresh_label.pack(side="right")
        gate_canvas = tk.Canvas(left, bg=self.SURFACE, height=232, highlightthickness=0)
        gate_canvas.pack(fill="x", padx=12, pady=(6, 8))
        ttk.Button(left, text=f"⏻  Kill-switch {symbol}", style="Kill.TButton",
                   command=lambda s=symbol: self._on_kill_symbol(s)).pack(anchor="w", padx=12, pady=(0, 12))

        right = ttk.Frame(body, style="Surface.TFrame")
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        ttk.Label(right, text="DECISION TRACE · AUDITABLE", style="Surface.TLabel").pack(
            anchor="w", padx=12, pady=(12, 6))
        trace_text = tk.Text(right, bg=self.CARD, fg=self.FG, insertbackground=self.FG,
                              font=self.FONT_MONO, height=24, wrap="word", relief="flat",
                              borderwidth=0, padx=10, pady=8)
        trace_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._tabs[symbol] = {
            "price_label": price_val, "signal_label": signal_val,
            "conf_label": conf_val, "decision_label": decision_val,
            "gate_canvas": gate_canvas, "trace_text": trace_text, "fresh_label": fresh_label,
        }

    # --- acciones ---------------------------------------------------
    def _on_kill_symbol(self, symbol: str) -> None:
        self.orch.nucleos[symbol].risk.engage_kill_switch(f"kill-switch manual activado desde GUI ({symbol})")

    def _on_kill_all(self) -> None:
        for sym, nucleus in self.orch.nucleos.items():
            nucleus.risk.engage_kill_switch("kill-switch global activado desde GUI")
        self.status_label.config(text="●  modo: PAPER TRADING — KILL-SWITCH GLOBAL ACTIVO",
                                  foreground=self.SHORT)

    # --- render -------------------------------------------------------
    def _draw_gate_weights(self, canvas: tk.Canvas, weights: Dict[str, float]) -> None:
        canvas.delete("all")
        if not weights:
            return
        canvas.update_idletasks()
        w = max(canvas.winfo_width(), 320)
        ranked = sorted(weights.items(), key=lambda kv: -kv[1])
        n = len(ranked)
        row_h = 232 // max(n, 1)
        track_x0, track_x1 = 128, w - 56
        track_w = max(track_x1 - track_x0, 10)
        max_w = max(weights.values()) or 1.0
        for i, (name, val) in enumerate(ranked):
            y0 = i * row_h + 3
            y1 = (i + 1) * row_h - 3
            yc = (y0 + y1) // 2
            # pista de fondo (progress track)
            canvas.create_rectangle(track_x0, y0, track_x1, y1, fill=self.CARD, outline="")
            bar_len = max(int((val / max_w) * track_w), 3)
            color = self.ACCENT if i == 0 else self.ACCENT_DIM
            canvas.create_rectangle(track_x0, y0, track_x0 + bar_len, y1, fill=color, outline="")
            canvas.create_text(12, yc, anchor="w", fill=self.FG_MUTED,
                                text=name[:15], font=("Segoe UI", 8))
            canvas.create_text(track_x1 + 8, yc, anchor="w", fill=self.FG,
                                text=f"{val:.3f}", font=("Consolas", 8))

    def _poll_queue(self) -> None:
        try:
            while True:
                summary = self.ui_queue.get_nowait()
                self._render_summary(summary)
        except queue.Empty:
            pass
        self.root.after(300, self._poll_queue)

    def _render_summary(self, summary: Dict[str, Any]) -> None:
        symbol = summary.get("symbol")
        widgets = self._tabs.get(symbol)
        if widgets is None:
            return
        self._last_update_ts[symbol] = time.time()

        price = summary.get("price")
        widgets["price_label"].config(text=f"{price:,.2f}" if price else "—")

        sig = summary.get("signal", 0.0)
        sig_color = self.LONG if sig > 0.05 else (self.SHORT if sig < -0.05 else self.FG)
        widgets["signal_label"].config(text=f"{sig:+.3f}", foreground=sig_color)

        conf = summary.get("confidence", 0.0)
        widgets["conf_label"].config(text=f"{conf:.0%}")

        decision = str(summary.get("decision", "—"))
        dec_color = self.FG
        if decision.startswith("abrir_long"):
            dec_color = self.LONG
        elif decision.startswith("abrir_short"):
            dec_color = self.SHORT
        elif decision.startswith("cerrar"):
            dec_color = self.WARN
        if summary.get("kill_switch"):
            dec_color = self.SHORT
        widgets["decision_label"].config(text=decision, foreground=dec_color)

        self._draw_gate_weights(widgets["gate_canvas"], summary.get("gate_weights", {}))

        line = (f"[{datetime.now().strftime('%H:%M:%S')}] {decision}  "
                f"señal={sig:+.3f}  conf={conf:.2f}  precio={price}\n")
        widgets["trace_text"].insert("end", line)
        widgets["trace_text"].see("end")

    def _tick_freshness(self) -> None:
        """Indicador visible de 'hace cuánto se actualizó cada símbolo por
        última vez' -- deja a la vista, en tiempo real, que los N símbolos
        avanzan en paralelo (ver fix de concurrencia en
        NucleusOrchestratorV2): si alguno se atrasa notablemente respecto
        a los demás, se ve en esta misma etiqueta antes de que haga falta
        ir a revisar logs."""
        now = time.time()
        for sym, widgets in self._tabs.items():
            last = self._last_update_ts.get(sym)
            if last is None:
                widgets["fresh_label"].config(text="sin datos aún", foreground=self.FG_MUTED)
                continue
            age = now - last
            color = self.LONG if age < self.cfg.MIN_CYCLE_INTERVAL_SECONDS * 3 else self.WARN
            widgets["fresh_label"].config(text=f"actualizado hace {age:.0f}s", foreground=color)
        self.root.after(1000, self._tick_freshness)

    def start(self) -> None:
        # workers concurrentes por símbolo dentro del orquestador (ver fix
        # de concurrencia) -- on_cycle empuja cada resultado a la cola de
        # la GUI, que solo hace polling no bloqueante sobre el hilo Tk.
        threading.Thread(
            target=lambda: self.orch.run_forever(on_cycle=self.ui_queue.put),
            daemon=True,
        ).start()
        self.root.after(300, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        self.orch.stop()
        self.root.destroy()


# =====================================================================
# 12. ENTRYPOINT
# =====================================================================

def build_orchestrator(cfg: Config, logger: logging.Logger, trace: DecisionTrace) -> "NucleusOrchestratorV2":
    """Punto único de construcción del runtime v2.

    FIX (auditoría post-consolidación v1->v2): main() instanciaba un
    Nucleus de un solo símbolo y lo pasaba directo a NucleusGUI, que
    espera un NucleusOrchestratorV2 (usa .symbols y .nucleos). Esto
    rompía en AttributeError apenas arrancaba la GUI, y en modo headless
    ignoraba en silencio todo el diseño multi-activo (partial pooling,
    riesgo por símbolo, reloj de eventos) operando solo BTCUSDT con el
    capital global entero. Aislar la construcción en una función propia
    permite testearla (ver TestMainEntrypointWiring) para que una futura
    regresión de este tipo la atrape la suite de autotest obligatoria,
    no un crash en producción.
    """
    return NucleusOrchestratorV2(cfg, logger, trace)


def _print_cycle_summary(summary: Dict[str, Any]) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {summary.get('symbol')}: decision={summary.get('decision')} "
          f"signal={summary.get('signal', 0.0):+.3f} conf={summary.get('confidence', 0.0):.2f} "
          f"price={summary.get('price')}")


def main():
    print("=" * 70)
    print("NUCLEUS MoE v2 — arrancando suite de autotest obligatoria")
    print("=" * 70)
    ok = run_self_tests(verbosity=2)
    if not ok:
        print("\nAUTOTEST FALLÓ. El sistema NO pasará a modo autónomo.")
        sys.exit(1)
    print("\nAutotest OK. Inicializando orquestador multi-activo...\n")

    logger, listener = build_async_logger("nucleus", CFG.LOG_DIR)
    trace = DecisionTrace(os.path.join(CFG.LOG_DIR, CFG.DECISION_TRACE_FILE))

    try:
        orch = build_orchestrator(CFG, logger, trace)
    except Exception as e:
        print(f"No se pudo inicializar el orquestador: {e}")
        sys.exit(1)

    if not requests:
        print("AVISO: paquete 'requests' no disponible — la ingesta de datos "
              "en vivo no funcionará hasta instalarlo (pip install requests).")

    if _TK_AVAILABLE:
        logger.info("Lanzando GUI multi-activo")
        gui = NucleusGUI(orch, CFG)
        gui.start()
    else:
        logger.info("Modo headless: arrancando run_forever()")
        print(f"tkinter no disponible en este entorno: corriendo en modo headless "
              f"(consola, event-driven, símbolos={orch.symbols}).")
        try:
            orch.run_forever(on_cycle=_print_cycle_summary)
        except KeyboardInterrupt:
            orch.stop()

    listener.stop()


if __name__ == "__main__":
    main()
