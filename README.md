# 🧠 NUCLEUS MoE v2.1 — Multi-Asset Liquidity Capture System

<p align="center">
  <img src="https://img.shields.io/badge/status-paper--trading-brightgreen" alt="status">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/deps-numpy%20%7C%20requests-lightgrey" alt="deps">
  <img src="https://img.shields.io/badge/tests-33%20passing-success" alt="tests">
  <img src="https://img.shields.io/badge/hardware-no%20AVX2%20%7C%20no%20GPU%20%7C%206GB%20RAM-orange" alt="hardware">
  <img src="https://img.shields.io/badge/live--trading-disabled%20by%20default-critical" alt="live-trading">
  <img src="https://img.shields.io/badge/license-private-lightgrey" alt="license">
</p>

> Sistema autónomo de captura de liquidez para **BTC/ETH/SOL USDT-M Perpetuals**, con un núcleo de 7 expertos estadísticos combinados mediante gating adaptativo, riesgo aislado por símbolo, y ejecución en **modo paper por defecto**. Diseñado y validado explícitamente para correr en hardware modesto (Compaq CQ45, 6GB RAM, sin GPU, sin AVX2).

---

## 📑 Tabla de contenidos

- [🎯 Qué es esto](#-qué-es-esto)
- [🏗️ Arquitectura](#️-arquitectura)
- [🧩 Los 7 expertos](#-los-7-expertos)
- [⚖️ Gating adaptativo multi-activo](#️-gating-adaptativo-multi-activo)
- [🛡️ Módulo de riesgo](#️-módulo-de-riesgo)
- [🔍 Auditoría cruzada v2 → v2.1](#-auditoría-cruzada-v2--v21)
- [⚙️ Configuración](#️-configuración)
- [🚀 Instalación y uso](#-instalación-y-uso)
- [🧪 Suite de autotest](#-suite-de-autotest)
- [🖥️ Requisitos de hardware](#️-requisitos-de-hardware)
- [🗺️ Roadmap / fuera de alcance](#️-roadmap--fuera-de-alcance)
- [⚠️ Aviso](#️-aviso)

---

## 🎯 Qué es esto

`nucleus_moe_v4.py` es un **prototipo de investigación en gating adaptativo multi-experto** para trading algorítmico de criptomonedas, no un sistema "listo para capital real" tal cual. Opera en **paper trading desde el primer arranque**; pasar a ejecución en vivo requiere que el operador configure credenciales explícitas y active un flag manual (ver [Ejecución en vivo](#ejecución-en-vivo)).

Fusiona dos linajes de trabajo previos en un solo fichero (monolito único, sin dependencias externas más allá de `numpy`/`requests`):

- **`nucleus_moe_v1`**: núcleo MoE (Mixture of Experts), gating adaptativo tipo Hedge/multiplicative-weights, módulo de riesgo, suite de autotests.
- **`nucleus_autonomous` / `Taperead10.py`**: microestructura Hawkes bidireccional + CVD, reloj de eventos (WebSocket con fallback a polling REST), GUI dark multi-símbolo.

### Principios de diseño (no negociables)

| # | Principio |
|---|---|
| 1 | Un único núcleo de interpretación por símbolo — no se instancia el mercado dos veces |
| 2 | El módulo de riesgo es un proceso lógico separado: solo veta / reduce / cierra, **nunca reinterpreta la señal** |
| 3 | Toda inferencia produce un `DecisionTrace` estructurado y auditable — los pesos de gating SON la explicación causal |
| 4 | El aprendizaje se limita a actualización acotada de pesos (Hedge), nunca gradiente opaco sobre el núcleo completo; piso mínimo de peso por experto |
| 5 | **Modo PAPER por defecto** — la ejecución en vivo exige credenciales + flag manual explícito |
| 6 | Ingesta de datos: solo endpoints públicos, sin autenticación |
| 7 | El apalancamiento es una regla dura del módulo de riesgo, no una preferencia del operador |

---

## 🏗️ Arquitectura

```
                         ┌─────────────────────────────────────────┐
                         │         NucleusOrchestratorV2            │
                         │  (reloj de eventos: WS + fallback REST)  │
                         └───────────────┬───────────────────────────┘
                                          │  1 worker concurrente por símbolo
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
      ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
      │  Nucleus BTC   │           │  Nucleus ETH   │           │  Nucleus SOL   │
      │  DataFeed  ─┐  │           │  DataFeed  ─┐  │           │  DataFeed  ─┐  │
      │  7 Expertos │  │           │  7 Expertos │  │           │  7 Expertos │  │
      │  GatingNet  │  │           │  GatingNet  │  │           │  GatingNet  │  │
      │  RiskModule │  │           │  RiskModule │  │           │  RiskModule │  │
      │  Execution  │  │           │  Execution  │  │           │  Execution  │  │
      └─────────────┼──┘           └─────────────┼──┘           └─────────────┼──┘
                     │                            │                            │
                     └──────────── _TTLCache compartida (FGI / mempool) ───────┘
                                          │
                          MultiAssetGatingPool (partial pooling / shrinkage)
```

- **Datos por símbolo**: klines, trades recientes, funding rate, ticker (Bybit público).
- **Datos globales compartidos**: Fear & Greed Index, presión de mempool BTC — cacheados una sola vez para los 3 símbolos, no por separado.
- **Riesgo aislado**: cada símbolo tiene su propio `RiskModule` con capital, circuit breaker y kill switch independientes — una racha de pérdidas en SOL no apaga BTC ni ETH.
- **Gating con partial pooling**: cada símbolo mantiene su propio vector de pesos, pero se contrae una fracción pequeña hacia la media cross-symbol tras cada resultado (shrinkage jerárquico estilo James-Stein).

---

## 🧩 Los 7 expertos

Cada experto implementa el mismo contrato `ExpertOutput(name, signal ∈ [-1, 1], confidence ∈ [0, 1], meta)`, para que el `GatingNetwork` los combine y evalúe de forma homogénea.

| Experto | Fuente de señal | Idea central |
|---|---|---|
| 🧭 `kalman_directional` | Precio de cierre | Filtro de Kalman sobre retornos para estimar dirección persistente |
| 📈 `bocpd_regime` | Precio de cierre | Bayesian Online Changepoint Detection (Adams & MacKay, 2007) — modula confianza según madurez del régimen |
| ⚡ `jump_model` | Precio de cierre | Detección de saltos con persistencia (reduce parpadeo de señal) |
| 💧 `vpin_liquidity` | Trades recientes | Volume-Synchronized PIN — flujo tóxico comprador/vendedor por bucket de volumen |
| ⛓️ `onchain_sentiment` | Fear & Greed + mempool | Sentimiento de mercado y congestión de red Bitcoin como proxy on-chain |
| 💰 `funding_carry` | Funding rate | Sesgo direccional derivado del costo de carry del perpetuo |
| 🌊 `hawkes_flow` | Trades recientes | CVD con z-score rodante + proceso de Hawkes bidireccional (microestructura) |

---

## ⚖️ Gating adaptativo multi-activo

- **Combinación**: ponderación por `peso_experto × confianza`, normalizada — estilo Hedge/multiplicative-weights.
- **Atribución de resultado**: tras cada trade cerrado, cada experto gana o pierde peso según si su señal en la apertura coincidió con el signo del PnL realizado.
- **Piso de peso (`GATING_MIN_WEIGHT_FLOOR`)**: ningún experto se anula permanentemente vía *water-filling* — el déficit de los expertos por debajo del piso se descuenta proporcionalmente solo de los que sí lo superan, preservando `Σpesos = 1` sin volver a romper la garantía del piso.
- **Shrinkage cross-symbol (`GATING_CROSS_ASSET_SHRINKAGE`)**: `0.0` = 3 redes de gating totalmente aisladas; `1.0` = un único pool fusionado sin distinción de símbolo. Por defecto `0.15`: cada símbolo aprende sobre todo de sí mismo, con un empujón pequeño hacia lo que funciona en los otros dos.

---

## 🛡️ Módulo de riesgo

- Apalancamiento **ALTO (x66)** vs **NORMAL (x20)** elegido según si la distancia a liquidación resultante respeta el stop-loss necesario para no exceder el 1–2% de riesgo de capital — regla dura, no heurística blanda.
- **Circuit breaker**: se activa tras `MAX_CONSECUTIVE_LOSSES` pérdidas seguidas.
- **Límite de pérdida diaria**: kill switch al superar `MAX_DAILY_LOSS_PCT` del capital en un día.
- **Capital independiente por símbolo**: `CAPITAL_USDT / nº símbolos` por defecto, configurable.

### Ejecución en vivo

`LiveBybitExecutionAdapter` es **un stub deliberadamente bloqueado**: exige `BYBIT_API_KEY` / `BYBIT_API_SECRET` por variable de entorno y `Config.LIVE_TRADING_ENABLED = True`, y aun así lanza `NotImplementedError` — la firma HMAC autenticada de Bybit v5 no está implementada a propósito, para que conectar capital real sea una decisión explícita y revisada del operador, nunca un valor por defecto de este fichero.

---

## 🔍 Auditoría cruzada v2 → v2.1

Esta versión incorpora una ronda de auditoría cruzada (verificación línea por línea contra el código, no solo contra un informe externo) sobre un hallazgo central: **en presencia de ruido de microestructura, el sistema entraba y salía de posiciones de forma repetitiva (whipsaw)**, sin fricción de mercado que lo penalizara en el PnL simulado. Los cuatro hallazgos se confirmaron y corrigieron quirúrgicamente:

| # | Hallazgo | Corrección aplicada |
|---|---|---|
| A | Banda mínima (0.15 → 0.2) entre umbral de entrada y salida por reversión, **sin histéresis, piso de retención ni confirmación por N ciclos** | Salida por reversión ahora exige `MIN_HOLD_SECONDS` de retención mínima + umbral ampliado (`EXIT_REVERSAL_SIGNAL_THRESHOLD`) + `REVERSAL_CONFIRMATION_CYCLES` ciclos consecutivos. Stop-loss y trailing siguen siendo inmediatos (protección de capital, no señal) |
| B | `PaperExecutionAdapter.close_position()` **no aplicaba comisión ni slippage** — PnL de delta de precio puro, invisibilizando el costo real del whipsaw | Se descuenta round-trip de `TAKER_FEE_PCT + SLIPPAGE_PCT` sobre ambos lados de la vuelta |
| C | `get_fear_greed()` / `get_mempool_pressure()` son datos **globales**, pero cada `DataFeed` (uno por símbolo) los pedía por separado → 3x llamadas redundantes a APIs públicas de límite bajo, riesgo real de HTTP 429 sostenido | `_TTLCache` compartida entre los `DataFeed` de los N símbolos; solo se cachean resultados exitosos |
| D | `VPINLiquidityExpert.infer()` fijaba la dirección por el **signo del último bucket de volumen únicamente**, que puede voltear entre ciclos consecutivos de `MIN_CYCLE_INTERVAL_SECONDS` sin cambio real de fondo | La dirección ahora usa el desequilibrio neto acumulado sobre los últimos hasta 3 buckets, no uno solo |

### Evaluado y descartado deliberadamente en esta ronda

`BOCPDRegimeExpert.reset()` se invoca en cada `infer()`, recalculando el changepoint desde cero sobre la ventana visible en vez de mantener estado online entre ciclos. Es una **inconsistencia de diseño real** (convierte un método "online" en uno "batch", perdiendo memoria de régimen fuera de la ventana visible) — pero el recálculo es computacionalmente trivial sobre ~200 velas incluso en el hardware objetivo, así que **no es un riesgo de estabilidad ni de CPU**. Queda documentado en el CHANGELOG del propio fichero para una futura versión con estado online, en vez de corregirse a ciegas fuera del alcance de esta auditoría.

> **Encuadre honesto**: presentado como "sistema listo para capital real", el whipsaw sin fricción era descalificante. Presentado como lo que efectivamente es — un prototipo de investigación en gating adaptativo multi-experto con paper trading, con `LIVE_TRADING_ENABLED = False` por defecto y el adaptador en vivo bloqueado deliberadamente — el churning era un hallazgo esperable de una versión en desarrollo, ya identificado y corregido en esta ronda.

---

## ⚙️ Configuración

Todos los parámetros viven en `Config` (dataclass, un solo lugar). Los más relevantes:

<details>
<summary><strong>Ver tabla completa de parámetros clave</strong></summary>

| Parámetro | Default | Descripción |
|---|---|---|
| `SYMBOLS` | `("BTCUSDT","ETHUSDT","SOLUSDT")` | Símbolos operados en paralelo |
| `CAPITAL_USDT` | `666.0` | Capital total, dividido entre símbolos |
| `RISK_PCT_MIN` / `MAX` | `0.01` / `0.02` | Rango de riesgo por trade sobre capital |
| `LEVERAGE_HIGH` / `NORMAL` | `66` / `20` | Perfiles de apalancamiento elegidos por el módulo de riesgo |
| `ENTRY_SIGNAL_THRESHOLD` | `0.15` | Umbral mínimo de señal combinada para entrar |
| `ENTRY_CONFIDENCE_THRESHOLD` | `0.25` | Confianza mínima combinada para entrar |
| `EXIT_REVERSAL_SIGNAL_THRESHOLD` | `0.35` | Umbral ampliado de reversión (post-auditoría) |
| `MIN_HOLD_SECONDS` | `30.0` | Piso de retención antes de permitir salida por reversión |
| `REVERSAL_CONFIRMATION_CYCLES` | `2` | Ciclos consecutivos requeridos para confirmar reversión |
| `MAX_CONSECUTIVE_LOSSES` | `4` | Pérdidas seguidas que activan el circuit breaker |
| `MAX_DAILY_LOSS_PCT` | `0.08` | Pérdida diaria que activa el kill switch |
| `GATING_LEARNING_RATE` | `0.08` | Tasa de aprendizaje del gating Hedge |
| `GATING_MIN_WEIGHT_FLOOR` | `0.05` | Piso mínimo de peso por experto |
| `GATING_CROSS_ASSET_SHRINKAGE` | `0.15` | Fuerza del partial pooling entre símbolos |
| `TAKER_FEE_PCT` / `SLIPPAGE_PCT` | `0.00055` / `0.0005` | Fricción aplicada al PnL simulado por lado |
| `FEAR_GREED_CACHE_TTL_SECONDS` | `300.0` | TTL de la caché compartida del FGI |
| `MEMPOOL_CACHE_TTL_SECONDS` | `60.0` | TTL de la caché compartida de presión de mempool |
| `DECISION_INTERVAL_SECONDS` | `15.0` | Cadencia objetivo del ciclo de decisión |
| `MIN_CYCLE_INTERVAL_SECONDS` | `3.0` | Debounce mínimo entre dos ciclos del mismo símbolo |
| `LIVE_TRADING_ENABLED` | `False` | Flag manual explícito para ejecución real (stub bloqueado) |

</details>

---

## 🚀 Instalación y uso

```bash
# Dependencias (solo dos, ambas opcionales con degradación limpia)
pip install numpy requests

# websocket-client es opcional: sin él, degrada limpiamente a polling REST
pip install websocket-client   # opcional

# Ejecutar (arranca autotest obligatorio antes de operar)
python nucleus_moe_v4.py
```

- Con `tkinter` disponible → lanza la **GUI dark** con una pestaña por símbolo (precio, señal, decisión, pesos de gating, log de razonamiento, kill switch por símbolo).
- Sin `tkinter` (p. ej. servidor headless) → corre en **modo consola event-driven**, imprimiendo cada decisión por símbolo.
- El sistema **rechaza arrancar en modo autónomo si la suite de autotest falla** — no hay bypass.

---

## 🧪 Suite de autotest

33 tests obligatorios (`unittest`), ejecutados automáticamente antes de cualquier operación autónoma:

```
Ran 33 tests in ~0.08s
OK
```

Cubren: cada uno de los 7 expertos (incluidos casos límite de datos insuficientes), water-filling del piso de gating, shrinkage cross-symbol (aislamiento en `shrinkage=0`, convergencia en `shrinkage>0`), circuit breaker / daily loss / kill switch, sizing de posición respetando presupuesto de riesgo, apalancamiento alto vs normal según distancia a liquidación, PnL de `PaperExecutionAdapter` (long/short), wiring del orquestador multi-símbolo con los 7 expertos, degradación limpia sin red, y concurrencia real (no serial) entre símbolos.

---

## 🖥️ Requisitos de hardware

Diseñado explícitamente para hardware modesto, no como optimización posterior:

- Windows 10 64-bit
- 6GB RAM
- Sin GPU
- **Sin AVX2** (Compaq CQ45) — nada de rutas numéricas que asuman instrucciones vectoriales modernas
- Solo `numpy` + `requests` como dependencias externas; el resto es stdlib (`tkinter`, `threading`, `queue`, `unittest`, `dataclasses`, `json`, `logging`)

---

## 🗺️ Roadmap / fuera de alcance

- [ ] `BOCPDRegimeExpert` con estado online real entre ciclos (eliminar el `reset()` por `infer()`), documentado como inconsistencia de diseño de bajo riesgo, no corregido en esta ronda
- [ ] Adaptador de ejecución en vivo para Bybit v5 (firma HMAC), deliberadamente no implementado hasta revisión explícita del operador
- [ ] Backtesting histórico formal sobre los cuatro fixes de esta ronda (por ahora validado por autotest unitario + ejecución headless en vivo contra datos reales, no por backtest de PnL)

---

## ⚠️ Aviso

Este software se entrega en **modo paper trading** y como **prototipo de investigación**. No constituye asesoría financiera. La activación de ejecución en vivo requiere pasos explícitos y deliberados del operador (credenciales + flag), y el adaptador correspondiente está bloqueado a propósito en esta entrega. Cualquier uso con capital real es responsabilidad exclusiva de quien lo active.
