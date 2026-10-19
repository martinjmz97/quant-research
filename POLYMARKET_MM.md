# Market Making en Polymarket — proyecto de aprendizaje

Investigación abierta el 2026-07-15. Objetivo: implementar un market maker real
sobre el CLOB de Polymarket con ~$100 de capital, para probar en carne propia
matemática de microestructura (control estocástico, gestión de inventario,
selección adversa) y tenerlo como proyecto de portfolio. **No se espera PnL
estadísticamente significativo con ese capital** — el resultado en dólares es
ruido a esa escala; lo que vale como evidencia es el modelo matemático, su
calibración con datos reales, y el manejo de riesgo, no el signo del retorno.

Contexto: este mismo repo cerró en 2026-07-08 (ver `CONCLUSIONS.md`) una
investigación de event-study que no encontró señal capturable en información
pública (posts de figuras públicas vs. mercados). Ese resultado se mantiene
como referencia: si en algún punto este proyecto incorpora un componente de
señal/fair-value propio, debe traer su propio test de falsificación — no
asumirse por analogía con el modelo de spread-capture puro.

## Decisiones tomadas

- **Universo: deportes tradicionales de duración normal** — soccer, fútbol
  americano, MLB, hockey, basketball (NBA/WNBA). **Esports queda afuera**,
  decisión tomada 2026-07-17 después de ver en datos en vivo que el mercado
  de un partido de LoL (`hanwha_win`/`t1_win`) se mueve ~10-30x más rápido
  por minuto que uno de MLB (ver sección "El stop-quoting no basta..." /
  "estructuralmente diferente" más abajo) y que el timestamp de kickoff para
  esports es un estimado sin verificar que en ese caso resultó estar mal por
  horas — los parámetros de reacción (intervalo de re-quote, ventana de
  widening por reloj de partido) están calibrados para el ritmo de deportes
  tradicionales, no para esports. Reemplaza la decisión original de
  "todos los mercados de deportes" (mayor N para calibrar/comparar) tomada
  el 2026-07-15, antes de tener datos en vivo de ningún partido.
- **Cripto se trata aparte, no en esta fase.** Ver sección "Cripto es un
  problema distinto" más abajo — motivo estructural, no solo de prioridad.
- **Target de implementación: CLOB V2**, vía el SDK nuevo (`polymarket-client`,
  `pip install --pre`), no el `py-clob-client` legado (archivado ~mayo 2026).
- **Jurisdicción:** se opera sobre el CLOB principal; el camino alternativo "Polymarket US"
  queda descartado (ver más abajo).

## Investigación de infraestructura (CLOB, API, fees)

Fuente: docs.polymarket.com, github.com/Polymarket, help.polymarket.com.
Vigente al 2026-07-15.

### Mecánica del CLOB
Híbrido: matching **off-chain**, settlement **on-chain** en Polygon PoS
(chain 137) vía el contrato `CTFExchange` (no custodial, auditado por
ChainSecurity). Reportado ampliamente como price-time priority, pero esa
frase exacta no aparece en la documentación oficial — asumir cierto pero sin
confirmación textual. Tipos de orden: GTC, GTD (expira 1 min antes de lo
indicado), FOK, FAK, más flag post-only para GTC/GTD maker-only. La doc dice
explícitamente que todas las órdenes son técnicamente límite — no hay
"market order" real. Para mercados binarios existe modo MINT: compras
complementarias de YES/NO pueden matchear entre sí sin contraparte directa,
minteando tokens nuevos.

### Acceso a la API
**El SDK establecido está deprecado.** `py-clob-client` / `clob-client` (TS)
archivados ~25-may-2026 tras el upgrade a CLOB V2 (go-live 28-abr-2026).
Reemplazo: `py-sdk` (`polymarket-client`, beta) / `ts-sdk`.

Auth en dos capas:
- **L1**: firma de wallet EIP-712, usada para mintear credenciales L2
  (`POST /auth/api-key`) y para firmar cada orden individual.
- **L2**: API key/secret/passphrase, HMAC-SHA256 sobre cada request REST.

Rate limits: CLOB general 9.000 req/10s · `/book` 1.500/10s ·
`POST /order` 5.000/10s en ráfaga (120.000/10min sostenido) ·
`DELETE /cancel-all` 250/10s.

WebSocket: canal market (`wss://ws-subscriptions-clob.polymarket.com/ws/market`,
sin auth, push de book/price/trade) y canal user (autenticado, lifecycle de
órdenes/trades). Heartbeat cada ~5-10s recomendado — riesgo de auto-cancelación
de órdenes abiertas si se corta (no verificado de forma independiente).

### Fees
**Maker paga 0% en todos los mercados.** Taker es fee-rate por categoría vía
`fee = C × feeRate × p × (1−p)`: deportes 0.05 · política/finanzas/tech 0.04 ·
crypto 0.07 · geopolítica 0%. Cambio más reciente datado: 10-jul-2026
(deportes taker 0.03→0.05, rebate 25%→15%). Reestructuración mayor
"Fee Structure V2" el 30-mar-2026.

Programa de **Maker Rebates**: 15–25% de las fees de taker recolectadas se
reparten diario entre makers, pago mínimo $1/día.

Gas: colocar/cancelar orden es **gasless** (mensaje firmado off-chain); el
settlement on-chain lo paga el relayer de Polymarket, no el usuario.

Implicancia directa para el modelo de quoting: como el maker fee es 0%, el
spread óptimo δ* no tiene que cubrir costo de transacción propio — solo
compensa riesgo de inventario y selección adversa. Eso simplifica la
calibración pero también significa que un spread mal calibrado no tiene
ningún colchón de fee que lo salve.

### Mecánica de mercados binarios
Cada mercado = tokens condicionales YES/NO ERC-1155 (Gnosis/UMA CTF),
divididos desde $1 de colateral (1 YES + 1 NO por $1) y fusionables de vuelta.
Desde 28-abr-2026 el colateral es **pUSD** (respaldado 1:1 por USDC),
reemplazó a USDC.e. Tick size **no es fijo, varía por mercado** (valores
documentados: 0.1, 0.01, 0.001, 0.0001, 0.0025 para mundiales) — siempre
consultar `/tick-size` en vivo, no asumir. No hay mínimo de tamaño de orden
publicado a nivel plataforma (existe error `INVALID_ORDER_MIN_SIZE` pero sin
umbral revelado).

Resolución: oráculo optimista UMA — proponente deposita bond (docs dicen $750
pUSD, help center dice USDC.e — **conflicto sin resolver**), ventana de
disputa 2h si nadie objeta, si se disputa escala a votación DVM de UMA
(~4-6 días total). Mercados no resolubles liquidan 50/50.

### Programa de Liquidity Rewards
Activo, auto-enrollment por tener órdenes límite resting, pago diario 00:00
UTC. Scoring: `S(v,s) = ((v−s)/v)² × b`, cotizar ambos lados pesa ~3x más que
un solo lado. Pago mínimo $1/día.

### Acceso desde EE.UU. (no aplica al usuario, documentado por si cambia el contexto)
Dos páginas oficiales se contradicen (geobloqueo "close-only" vs. bloqueo
total), pero en ambas versiones abrir órdenes nuevas en el CLOB principal
está bloqueado para usuarios en EE.UU. Camino alternativo: "Polymarket US"
(entidad separada, KYC, USD, vía QCX LLC) — producto distinto, fees
distintas (maker fee negativo ~−1.25%). Para este proyecto no aplica — se documenta solo como referencia.

### Conflictos / puntos sin verificar directamente antes de implementar
- Moneda exacta del bond UMA (pUSD vs. USDC.e).
- Tamaño mínimo de orden exacto.
- Si `py-clob-client` es totalmente incompatible con CLOB V2 o solo
  no-mantenido.

## Modelo de quoting

Punto de partida: Avellaneda-Stoikov (2008) — control estocástico de un MM
con utilidad CARA sobre riqueza terminal, horizonte finito T. Precio de
reserva `r(s,q,t) = s − qγσ²(T−t)`, spread óptimo
`δ_a+δ_b = γσ²(T−t) + (2/γ)ln(1+γ/κ)`.

### Por qué no aplica directo

El precio es una probabilidad p∈[0,1], acotado — A-S asume incrementos
gaussianos de varianza constante, imposible cerca de los bordes (un
martingala acotado en [0,1] tiene que reducir varianza cerca de p=0/1, tipo
difusión de Wright-Fisher, σ_local ∝ √(p(1−p))).

**Corrección**: trabajar en espacio logit, `x_t = ln(p_t/(1−p_t))`. En ese
espacio x vive en ℝ y el aparato de A-S se aplica directo; se mapea de vuelta
con la logística. `r_x(t) = x_t − qγσ_x²(T−t)` → `r_p = logistic(r_x)`. El
spread simétrico en x da un spread **asimétrico en p** — correcto, porque
cerca de los bordes no tiene sentido un spread simétrico en probabilidad.

### La identidad que reestructura el manejo de jumps

Si p_t es martingala (mercado eficiente) y p_T∈{0,1}:

```
E[(p_T − p_t)² | F_t] = p_t(1−p_t)
```

Exacto, no estimado — es la varianza que queda "por resolver", calculable
directo del precio actual. En equities, σ²(T−t) es un parámetro libre que se
estima de la historia porque el activo no converge a nada. Acá es una cota
dura: toda la variación futura (difusiva + saltos) tiene que sumar
exactamente p_t(1−p_t) para cuando llegue T. Sirve como chequeo de cordura:
si el σ_x² implícito integrado hasta T excede p_t(1−p_t), el modelo está mal
calibrado.

Diferencia clave con jump-diffusion A-S estándar (Cartea-Jaimungal y
similares): en equities los jumps son ruido adicional sobre una difusión que
sigue después indefinidamente — no hay colapso terminal. Acá los jumps
(gol, tarjeta roja) **son** la variación que consume el presupuesto
p(1−p), no ruido extra.

### Estructura de jumps para deportes

En vez de σ_x² constante (mala idea, muy dependiente del reloj de juego) o
un jump-diffusion genérico mal calibrado con poca data, se puede construir
σ_x²(t) desde un modelo estructural externo de win-probability condicionado
en tiempo restante y marcador (literatura de sports analytics: arribo de
goles ~Poisson con tasa dependiente del minuto y deporte, impacto en
win-prob por diferencial de marcador). Esto da una calibración de intensidad
de salto **independiente del propio order book**, usable tanto para fijar
spread como para detectar mispricing del book en ventanas de alto riesgo
(tiro de esquina, power play, etc.) — ahí conviene ensanchar o parar de
cotizar por regla casi determinística (evento observable en vivo), no
puramente estadística.

### Dónde se rompe la aproximación gaussiana

La derivación de A-S asume utilidad CARA sobre riqueza terminal
aproximadamente normal. Lejos de T, con p_t(1−p_t) grande, razonable. Cerca
de T el payoff terminal es Bernoulli, no gaussiano — la fórmula cerrada deja
de ser confiable justo cuando más importa. El inventario que quede sin
cerrar antes de resolución tiene riesgo binario puro, no riesgo de varianza.
Ahí conviene un **límite duro de inventario / stop-quoting explícito**
según t→T, no confiar en que γσ_x²(T−t)→0 "resuelva" el problema solo.

### Cripto es un problema distinto, no la misma extensión

Si un mercado resuelve contra un umbral de precio spot (ej. "¿BTC > $X para
la fecha Y?"), hay un precio de referencia externo, líquido y casi continuo
— matemáticamente es una opción digital, con fórmula de precio replicable
desde la vol implícita/histórica del spot. Ahí sí cabe un p̂_t propio
comparado contra el book de Polymarket — no es spread-capture puro, es una
apuesta direccional con argumento de replicación (`src/ingestion/crypto_binance.py`
ya existe en este repo y sirve de insumo). Se trata como fase separada para
no mezclar "estoy probando mecánica de MM" con "estoy probando si hay edge
de pricing" en el mismo experimento.

## Infraestructura: dónde corre cada cosa

Los trabajos largos (ingesta, backtests, el shadow-quoter) corren en un servidor remoto siempre
encendido, no en la laptop de desarrollo, porque la laptop se suspende y corta los procesos en
background. Los procesos de larga duración se gestionan con `launchd` (`KeepAlive`) y los trabajos
puntuales dentro de una sesión `tmux`. El acceso al servidor es privado y no se documenta aquí.

## Entorno de desarrollo

`requirements.txt` en la raíz. Setup: `python3 -m venv .venv && .venv/bin/pip
install -r requirements.txt`.

- Dataframe único: **polars**, no pandas (`polymarket-client[polars]`) —
  volumen esperado de cintas de trades con "todos los deportes" corriendo en
  simultáneo justifica el paralelismo; correr pandas y polars a la vez sumaba
  superficie de bugs sin necesidad. `statsmodels`/`scipy` reciben
  `.to_numpy()` en el borde.
- `numba` incluido para el loop de backtest tick-a-tick (secuencial, no
  vectorizable) — usar `@njit` solo donde el profiling confirme cuello de
  botella, no por defecto.
- Se descartó `diffrax`/JAX: A-S da fórmulas cerradas, no hay EDO/EDP que
  resolver numéricamente; simular el proceso de jumps es Euler-Maruyama
  simple con numpy/scipy, y conviene que quede escrito a mano y auditable en
  vez de depender de un solver caja negra para algo central a la tesis.
- Sin `ruff`/`mypy` por ahora (decisión explícita, revisar si el proyecto
  crece).
- **Gotcha de entorno**: en este Mac, `python3` está aliaseado a
  `/opt/homebrew/bin/python3.12` a nivel de shell — ese alias sobrevive a
  `source .venv/bin/activate` y hace que `python3` siga apuntando al Python
  global, no al del venv (`sys.path` no incluye el site-packages del venv).
  Usar `.venv/bin/python3` explícito o `python` (sin el `3`) dentro del venv,
  no `python3`.
- El paquete se instala como `polymarket-client` pero **el import es
  `import polymarket`**, no `polymarket_client` — nombre de distribución y
  nombre de módulo no coinciden.

### Detección de toxic flow — la defensa real contra jumps sin ver el partido

Decisión: no se persigue latencia de feed deportivo para reaccionar a jumps
(ver sección de datos en tiempo real, próximos pasos). El mecanismo de
defensa es detectar cuándo el flujo de trades hacia nuestras propias
cotizaciones deja de parecerse al flujo normal, sin necesidad de saber la
causa — equivalente en espíritu a VPIN (Easley/López de Prado/O'Hara):
bucketear flujo y medir desbalance direccional como proxy de toxicidad,
usando solo datos del propio book, latencia cero porque es el mismo venue.

No es un mecanismo aparte: sale de los mismos κ, A calibrados para el spread
óptimo de A-S. El detector es monitorear cuándo la intensidad de fills
*realizada* se dispara por encima de la línea de base calibrada para ese
momento del partido (z-score de arribo de trades) — ahí se ensancha o se
retira cotización.

**Limitación explícita, no vender como "evitar" el toxic flow**: el detector
llega después del primer trade tóxico, nunca antes — sin ver el partido no
hay forma de anticipar, solo de reaccionar más rápido que sin medir nada. Por
eso la defensa tiene dos patas, no una:
- **Ancho de spread** — compensa que el precio ya se movió.
- **Tamaño máximo por nivel/orden** — acota la pérdida del trade que sí
  alcanza a pegarnos antes de que el detector reaccione. Un spread ancho no
  sirve si el tamaño resting en el touch es grande y el flujo tóxico llega
  como un barrido de una sola vez.

## Ingesta de datos históricos

Cliente usado: `polymarket.clients.public.PublicClient()` — **sin auth**,
apunta a la Gamma API (`gamma-api.polymarket.com`), no al CLOB directo. Sirve
para todo lo de descubrimiento/histórico; el CLOB con auth queda para cuando
se opere en vivo.

- **Tag id `1` = "Sports"**, tag maestro que cubre las ~400+ ligas
  devueltas por `client.get_sports()` — un solo filtro
  `list_events(tag_ids=1, closed=True)` trae todos los deportes sin loopear
  liga por liga.
- `get_price_history` **rechaza (error, no trunca) ventanas largas** — límite
  no documentado, confirmado empíricamente: 7 días con `fidelity=60`
  (puntos horarios) funciona, 30 días falla con `'startTs' and 'endTs'
  interval is too long`. Se implementó chunking a 5 días (margen) +
  dedupe por timestamp en `src/ingestion/polymarket/history.py`.
- **Dos de los tres puntos "sin verificar" del research de API quedaron
  resueltos** al explorar el modelo `Market`: `market.trading` trae
  `minimum_tick_size` y `minimum_order_size` **por mercado**, directo en el
  mismo listado — no hace falta un endpoint separado ni asumir un valor
  global.

### Hallazgo importante: no hace falta pagar feed deportivo externo

El modelo `EventSportsMetadata` (dentro de cada evento, gratis, mismo
request que trae el mercado) ya trae `score`, `period`, `elapsed`,
`game_status`, nombres de equipos — con referencia a
`sportsradar_match_id`/`sportradar_game_id` en el modelo de streams, o sea
Polymarket ya está pagando y sirviendo datos calidad-Sportradar. Además el
SDK expone un **websocket nativo de eventos deportivos**
(`sports_ws_url = wss://sports-api.polymarket.com/ws`, tipo de mensaje
`SportsResultEvent`/`SportsGameResult`, suscribible vía
`AsyncPublicClient.subscribe`).

Esto reemplaza la recomendación anterior de pagar API-Football ($19/mes) o
similar — el score/reloj estructural que necesita el modelo de win-probability
sale gratis de la misma fuente que ya vamos a consultar por otras razones,
sin latencia extra de un proveedor tercero. Sigue en pie el punto de fondo de
la sección de toxic flow: esto da estado estructural (en qué momento del
partido estamos), no anticipa el jump — para eso sigue siendo el book propio,
no este feed.

**Limitación**: esto da el estado en el momento de la consulta, no un
historial de trayectoria de marcador para mercados ya cerrados — para
calibrar con datos históricos de estado de juego habría que haber estado
suscritos en vivo durante el partido. Hacia adelante, si nos suscribimos ya
queda grabado; hacia atrás, solo tenemos el score final por evento cerrado.

### Kickoff real vs. campos del catálogo — verificado con 3 partidos

`start_date` del catálogo (Gamma API) **no es el kickoff** — es ~24-30h
antes (probablemente hora de creación/apertura del mercado). `end_date`
**sí coincide con el kickoff real**, verificado exacto (al minuto) contra
fuentes externas en 3 partidos de Champions League 2025-26: Barcelona-
Olympiacos (`end_date`=kickoff=2025-10-21 16:45 UTC), Bilbao-Arsenal
(2025-09-16 16:45 UTC), Real Madrid-Marseille (2025-09-16 19:00 UTC). No
verificado más allá de estos 3 — asumir con cautela para otros mercados
hasta confirmar el patrón se sostiene (podría ser específico de fixtures
de Champions League con horario fijo, no un campo garantizado en general).

**Corrección a una afirmación anterior**: con el kickoff ya anclado, la
cinta de trades de esos 3 partidos (~1.9-2.7k trades c/u, buen N) muestra
que la transición pre/in-game **no es un escalón limpio de ~10-20x** como
se dijo en un primer pase (esa cifra comparaba promedios de 30min sobre
ventanas de horas, no minutos, y mezclaba "el mismo día del partido" con
"el partido en sí"). El patrón real, a resolución de 5min alrededor del
kickoff: la actividad empieza a subir gradualmente ~1-2h antes del
kickoff (probable positioning pre-partido), sigue elevada pero con picos
bursty durante el juego (consistente con arribo tipo Poisson de goles/
tarjetas, no una intensidad constante) y decae después de
~aprox. 130min post-kickoff (entretiempo + descuento incluido, silbatazo
final no verificado de forma independiente). Implica que calibrar κ,A con
un corte binario pre/in-game es una simplificación cruda — hace falta o
bien una ventana de "pre-kickoff inmediato" separada del resto del
pre-game, o modelar la intensidad como función continua del tiempo
relativo al kickoff en vez de un régimen de dos estados.

### No hay histórico de order book/spread — solo trades

Confirmado contra el SDK: `get_order_book`/`get_spread`/`get_midpoint` no
aceptan `start_ts`/`end_ts` — son estado **actual** únicamente, no existe
endpoint de histórico de book en la API pública. Para un mercado cerrado
esa información está perdida salvo que se haya estado suscrito al
websocket en vivo cuando pasó (mismo problema ya documentado para el feed
deportivo). Proxy usado en su lugar: separar trades BUY/SELL del token Yes
en la cinta — precio de BUY aproxima el ask, precio de SELL aproxima el
bid. Es spread **efectivo realizado** (lo que pagó quien cruzó), no spread
**cotizado** — no dice si una orden nuestra hubiera estado al frente de la
cola para capturarlo.

**Hallazgo (3 partidos, N chico — no tratar la magnitud como calibrada)**:
lejos del kickoff (horas antes) el spread proxy es consistentemente
~0.01, con flujo fuertemente unidireccional (BUY:SELL ~30-40:1) — casi
sin margen para un maker, y el poco que hay implica absorber inventario
contra una corriente de un solo lado, no cerrar pares. Cerca/durante el
kickoff el spread se ensancha (~0.02-0.10, en ráfagas, no como escalón
limpio) — pero ojo: con buckets de 5min muchas estimaciones del lado bid
quedan con **una sola venta** de muestra (SELL es ~20-25% del volumen y
concentrado cerca de la resolución, no uniforme en el tiempo) — la
magnitud exacta de cuánto se ensancha no es confiable todavía, solo la
dirección. Implica: la ventana de oportunidad real para un MM está en
kickoff±ventana, que es la misma ventana de mayor riesgo de toxic flow —
no hay almuerzo gratis en las horas pre-partido lejanas.

### Cuidado con pseudo-replicación al estimar cuántos partidos hacen falta

Con 3 partidos y buckets de 5min (n_buy≥3, n_sell≥3) pooleados, salían 32
observaciones de spread proxy — tentador tratarlas como 32 muestras
independientes para un power analysis. **Error**: los buckets dentro de un
mismo partido están correlacionados (comparten el mismo régimen de
volatilidad/narrativa del partido), la unidad real de independencia es el
partido, no el bucket. Con las medias por partido (Barcelona 0.0093,
Bilbao 0.0139, Real Madrid 0.0289 — rango 3x con solo 3 puntos): media
entre partidos 0.0174, std entre partidos 0.0103, t≈2.9 con 2 grados de
libertad — no alcanza para rechazar que la media real sea 0 (t-crítico
df=2 dos colas ≈4.3). El sample-size formal con esa media/std da n≈3-4,
pero es un cálculo inestable (la std de 3 puntos tiene error enorme) — de
mínima hacen falta ~8-15 partidos para una estimación de varianza que no
se mueva mucho al agregar un partido más, no los 3 actuales.

Ojo además con **dos preguntas distintas que no requieren la misma N**:
(1) "¿existe un ensanchamiento real de spread cerca del kickoff?" — la de
arriba, alcanzable con ~8-15 partidos dado el tamaño de efecto que se ve
hasta ahora. (2) "¿nuestra estrategia de quoting específica captura ese
spread neto de selección adversa?" — mucho más dura: la distribución de
P&L por round-trip probablemente tiene cola pesada (pérdidas grandes y
poco frecuentes por goles/tarjetas, ganancias chicas y frecuentes el
resto del tiempo) — ese tipo de distribución necesita bastante más N para
caracterizar la cola de forma confiable, no alcanza con el promedio.

### Escalado a 15 partidos — el hallazgo de ensanchamiento de spread NO replica

Se escaló la colección a 15 partidos de Champions League/Club World Cup
(alto volumen, mismo filtro de duración<48h). 3 quedaron fuera del
análisis por liquidez marginal (<300 trades totales: OGC Nice-Nantes,
Marseille-Lorient, Rapid Wien-Fiorentina) y 2 más sin buckets utilizables
en la ventana de kickoff (Fluminense-Chelsea, Benfica-Bayern) — quedan 10
partidos usables.

**Comparación pareada correcta** (spread proxy en ventana kickoff-1h/+2h
vs. baseline pre-game lejano kickoff-24h/-2h, por partido, no pseudo-
replicado): diferencia media = +0.0038, std = 0.0082, **t=1.45 con 9
grados de libertad — no significativo** (t-crítico α=0.05 dos colas =
2.262). El n=3 original mostraba una señal limpia (los 3 casos con
ensanchamiento) que resultó ser suerte de muestra chica, no un efecto
estable — con n=10 la mitad de los partidos muestra spread IGUAL o MENOR
en la ventana de kickoff que en el pre-game lejano (ej. Barcelona-
Olympiacos, Leverkusen-PSG, Arsenal-Atlético), no solo ensanchamiento.

**N requerido reestimado con este tamaño de efecto más realista**: ~35-40
partidos para 80% de power (vs. el ~3-4 que salía del cálculo original,
inflado por varianza mal estimada con 3 puntos). Conclusión: **la
hipótesis de "el spread se ensancha en kickoff" sigue abierta, no
confirmada ni refutada** — hace falta más N antes de tratarla como base
para calibrar nada. Hipótesis a explorar más adelante sobre por qué varía
tanto entre partidos: partidos parejos (más incertidumbre de resultado
condicionada al marcador) podrían ensanchar más que partidos con
favorito claro — no verificado, anotado para no perderlo.

### Shadow-quoting backtest sin queue — primer resultado, y es feo (a propósito)

`scripts/shadow_quote_backtest.py`: cotiza simétrico ±1c alrededor del
precio de `price_history` (fair value proxy), sin modelar cola — asume
fill automático cuando la cinta real cruza nuestra cotización, tope de
$2 de notional por fill. **Sin límite de inventario total** (a propósito,
para ver qué pasa sin la protección). Sobre los 13 partidos con datos
utilizables: PnL negativo en 9/13, posiciones máximas de 84 a 974 tokens
(irreal para $100 de capital — eso ya invalida leer el número de PnL como
dólares reales, es un bug de escala, no una simulación de producción).

**El mecanismo sí es real y es la validación empírica del punto de
inventario**: el flujo de mercado es fuertemente unidireccional (BUY:SELL
~30-40:1 pre-game, ya documentado arriba) — una cotización simétrica sin
límite va acumulando posición contraria a ese flujo de forma
prácticamente garantizada, y cuando el precio se mueve en la dirección
"obvia" (la que todo el mundo venía comprando), el inventario acumulado
se marca en contra, fuerte. Esto es la selección adversa jugando en
tiempo real, no un evento raro de cola — le pasó a 9 de 13 partidos.

**Siguiente paso obligado**: repetir con un límite duro de inventario
(el que ya está descrito en la sección de modelo de quoting, "Dónde se
rompe la aproximación gaussiana") y ver si eso solo alcanza para dar
vuelta el resultado, o si hace falta además ensanchar/parar de cotizar
en la ventana de kickoff — sin eso, no se puede saber todavía si el
problema es "faltó límite de inventario" o "no hay edge neto de selección
adversa ni con límite".

### Dashboard shadow — montos y el hueco de las colas gordas

`scripts/dashboard_server.py` (stdlib puro, `launchd` en el servidor remoto,
puerto 8765 sobre la IP privada) monitorea `shadow_quote_live.py`.
Montos usados (arbitrarios, no vienen de un plan de asignación de capital
real): `HALF_SPREAD=0.01` (spread total 2c), `MAX_FILL_USD=2.0` por fill,
sin límite de capital total cruzando los 6 tokens en simultáneo — o sea
todavía no simula la restricción real de $100 repartidos entre mercados.

**Hueco encontrado y corregido**: el histograma de round-trips solo
registra un punto cuando la posición vuelve exactamente a flat. Una
posición que se queda abierta (nos agarra un gol, no volvemos a cero
antes de que resuelva el mercado — exactamente el escenario de cola que
importa) **no generaba ningún punto en la distribución** — quedaba
invisible, solo visible indirectamente en `mark_to_market` marcado contra
el fair value en vivo, no contra el payoff terminal real (0 o 1). Se
agregó `worst_case_resolution_pnl`/`best_case_resolution_pnl` por token
(marca la posición abierta contra 0 y contra 1, el bound real) y un tile
de "peor caso si todo resuelve ya" sumando todos los tokens abiertos —
ese número es el que hay que mirar para riesgo de cola, no el histograma
de round-trips cerrados ni el mark-to-market solo.

**Resuelto**: el websocket no manda ningún evento de "este mercado ya
resolvió" (confirmado observando el feed) — la única señal autoritativa
es REST, `PublicClient.get_market(id=...).state.closed` +
`.outcomes.yes.price` (que pasa a valer exactamente 0 o 1 al resolver).
`shadow_quote_live.py` ahora poll-ea eso cada 5 min por mercado trackeado
y, si encuentra `closed=True`, fuerza el cierre de cualquier posición
abierta al payout real — ese cierre se loguea como un fill más
(`resolution_forced_close: true`) y el dashboard lo levanta como
round-trip cerrado igual que cualquier otro. Probado contra un mercado
ya resuelto (Barcelona-Olympiacos, resolvió Yes=1) antes de desplegar.

**También corregido**: `MAX_FILL_USD` estaba en $2, por debajo del
mínimo real de Polymarket — verificado contra el catálogo,
`minimum_order_size` es **uniformemente $5** en las 10.837 filas. Subido
a $5.

**Por qué importa el escenario de cola**: cotizar spread apretado
(`HALF_SPREAD` chico) cerca del final del partido es exactamente donde
más plata se puede quedar pegada — si el precio se mueve fuerte (gol) y
la cotización no se ensancha/retira a tiempo, la posición que se acumula
ya no tiene margen para salir antes de la resolución. Es el mismo punto
de "límite duro de inventario / stop-quoting" ya documentado en la
sección de modelo de quoting, ahora con instrumentación real para
medirlo en vivo en vez de solo razonarlo.

### Neg-risk — mecánica de conversión cruzada entre outcomes mutuamente excluyentes

Mercados de 3+ outcomes mutuamente excluyentes (ej. gana A / gana B /
empate) están marcados `neg_risk: True` en el order book (verificado
contra el book real de `france_win`, campo real del protocolo, no
supuesto). Hay un contrato (`NegRiskAdapter`,
[github.com/Polymarket/neg-risk-ctf-adapter](https://github.com/Polymarket/neg-risk-ctf-adapter))
que permite convertir posiciones NO en posiciones YES sin pasar por el
book (sin spread ni fee de taker).

**Dos fuentes se contradijeron** (la doc oficial vs. el README del
contrato) — se resolvió haciendo la cuenta de payoffs a mano en vez de
confiar en cualquiera de las dos a ciegas. Mecánica confirmada (ejemplo
de 3 outcomes A/B/C): **1 NO-A + 1 NO-B → 1 YES-C + 1 USDC** — hace falta
tener NO en **todos** los N-1 outcomes restantes, no en uno solo.
Verificado por igualdad de payoff en los 3 estados (gana A: 1=1, gana B:
1=1, gana C: 2=2).

**Sin verificar todavía** (ninguna fuente lo tenía): costo de gas, fee
del protocolo en la conversión. **Limitación importante para el caso de
uso que motivó la pregunta** (desbalance de inventario): esta conversión
sirve para *construir* una posición YES más barata a partir de NOs, no
para *reducir* una posición YES ya abierta — para reducir inventario
existente sigue haciendo falta vender en el book (pagando spread) o armar
el set completo (1 YES de cada outcome) y hacer `merge` a $1 garantizado,
que es una salida total, no un ajuste parcial. No implementado en el
shadow-quoter — cada book sigue corriendo 100% independiente.

### Pregunta abierta: ¿cómo sobrevive el lado vendedor a un desbalance tan grande?

Con datos reales del book en vivo (Francia-Inglaterra, 6h grabadas): el
touch (0.49/0.50) **no se movió ni un tick** pese a 16.279 cambios de
tamaño — no es una orden estática, se repone activamente al mismo nivel.
Con datos históricos (Barcelona, Real Madrid, pre-game lejano): el
desbalance BUY/SELL pesado por **notional** es peor que por cantidad de
trades — 318x y 85x respectivamente (no 44x/57x). Alguien vendió
sistemáticamente contra flujo comprador dominante, durante horas, sin
mover el precio ni una vez.

**No resuelto, hipótesis sin confirmar**: (1) se cubren fuera de
Polymarket (otro sportsbook, o el mecanismo neg-risk); (2) el rebate de
Liquidity Rewards compensa una pérdida esperada neta; (3) su fair value
genuinamente coincide con el precio y el flujo sesgado no los mueve; (4)
no es una sola entidad, son muchos vendedores independientes reponiendo
de a poco. Ninguna verificable con datos públicos de un solo book. Se
sigue grabando en vivo (Francia-Inglaterra resuelve 18-jul) — si en algún
momento el precio salta de golpe close al kickoff, ahí se vería si a
alguien le pegó de verdad, o si sigue reponiendo indefinidamente.

### Shadow-quoter protegido — bug de fondo encontrado + 4 protecciones

**Bug encontrado antes de agregar las protecciones**: la versión anterior
de `shadow_quote_live.py` recomputaba `our_bid`/`our_ask` desde el mismo
`(best_bid, best_ask)` que después usaba para chequear si nos cruzaban —
matemáticamente imposible (`our_ask = midpoint + H` siempre es mayor que
`best_bid` mientras `ask ≥ bid`, que es siempre). **0 fills durante toda
la grabación no era "mercado tranquilo", era un bug** — ninguna condición
de mercado podía haber generado un fill jamás. Fix: la cotización ahora
es estado que persiste entre updates — cada mensaje nuevo se chequea
contra la cotización *anterior* antes de recentrar. Verificado con un
salto simulado (gol): con el fix, un salto de 0.49→0.55 sí genera un
fill; sin el fix, no generaba ninguno sin importar el tamaño del salto.

**Las 4 protecciones agregadas** (antes: spread fijo, sin ninguna):

1. **Skew de inventario** (el término de precio de reserva de A-S que
   faltaba): `reservation = fair_value - posición×fracción_de_tope×3×HALF_SPREAD`.
   Posición larga → reserva por debajo del fair value (más ganas de
   vender, menos de comprar más); corta → por arriba. Es el mecanismo
   central — no evita el desbalance, hace que sea cada vez menos
   atractivo seguir tomando el mismo lado.
2. **Tope duro de inventario**: `MAX_POSITION_USD=20` por token. Bloquea
   fills que agrandarían la posición más allá del tope; sigue permitiendo
   fills que la reducen.
3. **Detector de flujo tóxico (proxy tipo VPIN)**: como no hay forma
   limpia de bucketear desbalance de flujo real desde este feed, se usa
   la tasa de *nuestros propios fills* como señal — si los fills de los
   últimos 120s llegan a >3x la tasa de los últimos 30min, ensancha 4x
   por 120s. Reactivo por construcción (dispara después del primer fill
   tóxico, no antes) — misma limitación ya reconocida en la sección de
   detección de toxic flow.
4. **Ensanchamiento por reloj de partido**: 2.5x determinístico en la
   ventana kickoff-15min a kickoff+130min, sin esperar confirmación del
   detector.

### Política de re-quote — separar "cuándo recotizamos" de "cuándo nos cruzan"

Encontrado mirando MLB en vivo: aunque el precio real se movió (0.453→
0.459 en 1h), seguían 0 fills. Causa: recotizábamos en *cada mensaje*,
así que nuestra cotización perseguía el fair value sin nunca quedar
atrás — solo un salto de un tick más grande que el spread podía
cruzarnos, nunca una deriva lenta acumulada. Es una latencia de re-quote
implícita de cero, poco realista (en la vida real siempre hay demora
entre ver un precio nuevo y actualizar la orden).

**Fix**: la cotización ahora es estado que solo se actualiza cuando pasa
alguna de estas tres cosas — el fair value se movió más de
`REQUOTE_DRIFT_THRESHOLD` (medio spread) desde el último re-quote, pasaron
más de `REQUOTE_MAX_INTERVAL_S=30s`, o acabamos de tener un fill. Entre
re-quotes la cotización queda deliberadamente vieja — así una deriva que
se acumula más rápido que el ciclo de refresco sí nos puede cruzar.

**Verificado con tests**: la misma deriva real de MLB (0.6c en 1h, o
incluso comprimida a 5min) sigue sin cruzarnos — correcto, no es un bug:
0.6c es menos que nuestro spread de 2c, no importa el ritmo, salvo que se
concentre en una ráfaga de <30s. Un salto tipo gol (0.49→0.55 en un solo
tick) sí cruza correctamente con este mecanismo. Confirma que el sistema
reacciona a saltos discretos reales, no a deriva lenta benigna — que es
el comportamiento correcto, no una limitación a resolver.

### Stop-quoting real — no solo ensanchar

Faltaba lo que ya estaba escrito ("cerca de T conviene un límite duro /
stop-quoting explícito, no confiar en la fórmula") pero nunca se
implementó como retiro real de la cotización — solo existía
ensanchamiento. Agregado: `_should_stop_quoting()` retira la cotización
del todo (`our_bid`/`our_ask` en `None`, ningún fill posible hasta que se
levante) por dos motivos —

1. **Cercanía a resolución**: `fair_value` a menos de 0.03 de 0 o 1 — el
   presupuesto de varianza `p(1-p)` ya se gastó casi entero, casi no
   queda margen que compensar con spread, pero el riesgo de un vuelco de
   último momento sigue ahí.
2. **Escalada del detector tóxico**: si dispara una segunda vez mientras
   todavía está en cooldown de la primera, no es ruido — el régimen
   cambió de verdad. Un disparo ensancha (ya existía); dos seguidos paran
   del todo por 10 minutos.

Verificado con tests: `fv=0.975` retira la cotización correctamente; dos
disparos tóxicos consecutivos (el segundo dentro del cooldown del
primero) escalan a stop (`n_stops` sube, no solo `n_toxic_widenings`).

### Primeros fills en vivo — dos bugs de re-disparo, y qué explica la pérdida

Con el shadow-quoter corriendo desde 2026-07-16 17:53 (servidor remoto), a las
~19h de grabación 6 de los 22 tokens trackeados tuvieron fills (73-81,
creciendo). Análisis sobre `shadow_fills.jsonl` y `shadow_state.json`.

**Bug 1 — el detector de flujo tóxico se retroalimenta a sí mismo estando
parado.** `_should_requote` trataba `our_bid is None` como "nunca
cotizamos" — pero ese campo también queda `None` mientras el
stop-quoting está activo, así que *todo* mensaje entrante (no solo los
que ameritan una nueva cotización) volvía a evaluar y **extender** el
estado de stop/tóxico. Confirmado con los contadores reales: `mets_win`
acumuló 39.962 "toxic widenings" / 39.960 "stops" contra solo 18 fills
reales — el feed de ese token mandó ~56 mensajes/segundo (582.497
mensajes en sus ~2h53m de vida), suficiente para que un solo episodio
atascado de unos pocos cientos de segundos produjera ese conteo. Fix:
gatear `_should_requote` únicamente en `last_requote_ts is None` (se
setea en cada requote, incluida la transición a stop) — restaura el
throttle normal de drift/intervalo también mientras el libro está
parado.

**Bug 2 — ping-pong de fills sin latencia de re-quote.** El log muestra
ráfagas de 2-5 fills en <1s por token (`mets_win`/`phillies_win`
22:44:33.836→22:44:34.506 UTC, posición saltando +19.5→+9.7→-1.9
tokens) — un MM real no puede cancelar, reponer y volver a ejecutarse
tan rápido. Causa: el requote inmediato tras un fill (`just_filled=True`)
recentra con latencia cero, y el siguiente mensaje (a veces <200ms
después) puede cruzar la cotización nueva. Fix: `MIN_REQUOTE_LATENCY_S
= 1.0` — valor conservador puesto a mano, no medido contra la
infraestructura real de Polymarket, elegido solo por ser mayor que los
gaps observados (~180-490ms). Ninguna cotización es cruzable hasta que
pasó ese tiempo desde que se fijó.

Ambos fixes con tests de regresión en `tests/scripts/test_shadow_quote_live.py`
(6 tests) — verificados fallando contra el código viejo y pasando con
el fix, no son vacuos.

**Pendiente**: los fixes están en el repo de la laptop. El proceso en el
servidor remoto sigue con la versión vieja hasta resincronizar y reiniciar —
no hecho todavía porque cortaría la grabación en curso.

**Cuánto del resultado es el bug y cuánto es selección adversa real**:
separando cada fill en "ráfaga" (gap <1s con el fill anterior del mismo
token — lo que el fix de latencia habría bloqueado) vs "limpio":

| Par (mismo `market_id`) | Estado | PnL total | PnL ráfaga | PnL limpio |
|---|---|---|---|---|
| mets_win / phillies_win | resuelto 17-jul 01:14 UTC (ganó Mets) | −1.678 | +5.00 / −5.00 (se cancela entre piernas) | −1.678 / 0.00 |
| hanwha_win / t1_win | en vivo (esports) | −15.00 | +10.00 / −5.00 (no cancela, snapshot a mitad de partido) | −25.00 / +5.00 |
| liberty_win / wings_win | en vivo (WNBA), sin ráfagas | 0.00 | — | +5.00 / −5.00 |

Hallazgo: para el par ya resuelto, el bug **no cambió el resultado
económico neto** — las ganancias/pérdidas fantasma de la ráfaga se
cancelan casi exacto entre las dos piernas complementarias (comprar
mets ↔ vender phillies es la misma apuesta, y ambos tokens del mismo
book reciben el mensaje del feed casi al mismo tiempo). La pérdida real
de -$1.678 sale entera de los fills limpios — selección adversa
genuina, no artefacto de implementación. Para el par en vivo, la
cancelación es parcial en este corte: el bug está mostrando un
resultado *menos* malo que el que darían solo los fills limpios (-$20
vs -$15 booked).

**Limitación que hay que decir en voz alta**: esto es una sola
partida/juego por par, 3-22 fills por pierna — la misma advertencia de
tamaño de muestra que ya se documentó para el backtest sin cola (hicieron
falta ~35-40 partidos para confirmar el ensanchamiento de spread en
kickoff). Ni el signo ni la magnitud de estos PnL son evidencia de que
el modelo tenga o no edge — es consistente con la selección adversa ya
documentada, pero con N=1-2 partidos no se puede decir más que eso.

### El stop-quoting no basta — falta cerrar el inventario activamente

Con `hanwha_win`/`t1_win` en vivo, `n_fills` es bastante mayor que la
cantidad de veces que la posición vuelve a flat — el libro casi siempre
termina con inventario abierto en vez de rondas cerradas. Eso ya era lo
esperado (flujo direccional + skew no alcanza a cerrar todo, documentado
arriba), no es un hallazgo nuevo. Lo que sí faltaba: separando cash
realizado de marca del inventario abierto, `t1_win` cerró sus fills en
cash exactamente en $0 pero se quedó corto 10.497 tokens marcados contra
`fv=0.999` — toda la pérdida visible (−$10.49) es esa posición abierta,
no las rondas que sí cerró. `hanwha_win` al revés: la pérdida ya estaba
mayormente realizada en cash, con la posición abierta valiendo ~$0
(consistente, `fv≈0.001`). El stop-quoting (`_should_stop_quoting`)
solo retira nuestra cotización — no hace nada con el inventario que ya
está abierto cuando `fv` se acerca a un extremo. Ese inventario quedaba
sin protección hasta que el poll REST (`RESOLUTION_CHECK_INTERVAL_S=300`,
cada 5 min) confirmara la resolución y forzara el cierre.

**Punto importante que hay que dejar claro, no es gratis**: cerrar
activamente cerca de `fv=0.03`/`0.97` **no mejora el mark-to-market** —
a esa altura la posición ya vale casi lo que va a pagar al resolver
(por eso `hanwha_win`/`t1_win` mostraban casi la misma pérdida con o sin
cerrar). Lo que sí hace: convierte una posición abierta (expuesta a una
reversión de último momento durante los hasta 5 minutos que tarda el
poll REST en confirmar) en cash realizado ya mismo. Es reducción de
ventana de exposición a una reversión, no una mejora de PnL esperado —
y tampoco protege contra un salto discontinuo (gol, jugada decisiva)
que lleve `fv` de, digamos, 0.7 a 0.99 en un solo tick: ahí no hay
ningún umbral que hubiera dado aviso antes, es la misma limitación ya
reconocida del detector de toxic-flow (reactivo, no predictivo).

**Redeployado** al servidor remoto 2026-07-17 ~13:00 UTC (`com.example.polymarket-shadow`,
launchd con `KeepAlive` — se reinició solo al matar el proceso viejo, no
hacía falta tocar tmux). Datos previos al fix archivados en
`data/raw/polymarket/orderbook_live/pre_fix_2026-07-17T0900Z/`. El script
relee `worldcup_semifinals.jsonl` desde el principio en cada arranque (no
hace seek al final) — el restart reprocesó las ~1.9M líneas grabadas
hasta ese momento con el código corregido, así que los números post-fix
no son directamente comparables fill-a-fill contra los de la sección de
arriba (la secuencia de fills cambia: `MIN_REQUOTE_LATENCY_S` bloquea
entradas que antes sí pasaban). Confirmado funcionando: 4 `forced_flatten`
en el replay completo, incluidos `t1_win`/`hanwha_win` cerrados en vez de
quedar abiertos esperando el poll REST.

Implementado: `_flatten_at_market()` (`scripts/shadow_quote_live.py`) —
al entrar en la zona de `_near_resolution` (no en el stop por spread
ancho ni por escalada tóxica, solo por proximidad a resolución), si hay
posición abierta la cruza contra el `best_bid`/`best_ask` real como
taker, pagando `TAKER_FEE_RATE_SPORTS=0.05` (`fee = tokens × feeRate ×
p × (1−p)`, misma fórmula de la sección de Fees — valor al 2026-07-15,
Polymarket lo cambia seguido). Es la única operación del modelo que paga
fee — todo lo demás asume que somos el lado maker (0% fee). Mismo
supuesto de "sin impacto de mercado" que el resto del shadow-quoter:
asume que toda la posición llena al precio de touch, sin slippage por
caminar el book. 4 tests de regresión en
`tests/scripts/test_shadow_quote_live.py` (`TestActiveFlattenNearResolution`).

### Game-status en vivo — reemplaza el kickoff adivinado

El mismo día se confirmó que el problema de kickoff no era solo de
esports: `liberty_win`/`wings_win` (WNBA, kickoff asumido
`2026-07-17 01:00 UTC` desde `end_date`, sin verificar) siguieron
cotizando activo en 0.45-0.55 más de 12 horas después de ese kickoff.
Consultando la API en vivo (`client.get_event`) el partido real ya
estaba en `period="POST"` (terminado) — el precio nunca entró en la zona
de `_near_resolution`, así que esa protección sola no lo hubiera
agarrado.

**Verificado contra 4 eventos reales antes de escribir nada**: `period`
es `None` en los 2 partidos de soccer que todavía no arrancaron,
`"POST"` en la WNBA ya terminada, `"VFT"` en la MLB ya terminada. Un
mercado 3-way de soccer (yes/no/draw) tiene 3 `market_id` pero comparte
UN solo evento — `event_id` se saca recortando el sufijo de outcome del
slug del mercado (`fifwc-fra-eng-2026-07-18-fra` → evento
`fifwc-fra-eng-2026-07-18`); para MLB/WNBA (mercado binario) el slug del
mercado ya ES el del evento. Los 4 `event_id` (uno por partido/evento
trackeado) se resolvieron a mano una vez y quedaron hardcodeados en
`EVENT_IDS`, mismo patrón que `MARKET_IDS`/`KICKOFFS`.

**Implementado** (`scripts/shadow_quote_live.py`):
- `check_game_status()` — pollea `client.get_event(id=...)` una vez por
  evento único (no una vez por token) cada `GAME_STATUS_CHECK_INTERVAL_S=60s`,
  guarda `event.sports.period` en cada `ShadowBook.game_period` vía
  `update_game_period()`. Mismo patrón sync/REST que `check_resolutions`
  — no hace falta el websocket de sports (`AsyncPublicClient`-only, hubiera
  significado migrar todo el script a async solo para esto).
- `_game_confirmed_over()` — `game_period in GAME_OVER_PERIODS`, con
  `GAME_OVER_PERIODS = {"POST", "VFT"}` **explícitamente no exhaustivo**
  (`period` es un string libre de la Gamma API, no hay enum en el SDK) —
  solo lo confirmado en vivo hasta ahora. Un deporte con un código
  terminal todavía no visto sigue teniendo como respaldo
  `_near_resolution` (precio) y `market.state.closed` (REST).
- `_should_flatten()` reemplaza el uso directo de `_near_resolution` para
  disparar `_flatten_at_market` — ahora es `_near_resolution(fv) or
  _game_confirmed_over()`, con guarda explícita de spread ancho (a
  diferencia de `_near_resolution`, `_game_confirmed_over` no implica
  nada sobre el spread, así que perdía la garantía matemática que hacía
  innecesaria esa guarda antes).
- Ensanchamiento por reloj de partido: `_in_match_window(now) or
  self.game_period is not None` — **OR, no reemplazo**. El estimado
  estático de kickoff se mantiene como margen de seguridad pre-partido
  (por si acierta) pero la confirmación en vivo solo puede sumar
  ensanchamiento, nunca sacarlo — así una falla en el poll no apaga
  silenciosamente la protección.

7 tests de regresión nuevos (`TestLiveGameStatus`, `TestCheckGameStatus`
en `tests/scripts/test_shadow_quote_live.py`), verificados fallando
contra el código sin este cambio antes de confirmarlos.

### Descubrimiento automático de partidos activos — reemplaza el hardcodeo manual

Con 2 partidos (MLB, WNBA) ya quedó claro que calibrar el spread óptimo
necesita muchos más — y armar cada partido a mano en `KICKOFFS`/
`TOKEN_LABELS`/`MARKET_IDS`/`EVENT_IDS` no escala. Implementado
2026-07-17: `src/ingestion/polymarket/active_markets.py` escanea las 6
ligas en scope (soccer=100350, NFL=450, MLB=100381, NHL=899, NBA=745,
WNBA=100254 — tag ids verificados contra `client.get_sports()`, no
supuestos) vía `iter_sports_events(closed=False)` y arma la lista de
tokens a trackear.

**Dos hechos de la API verificados en vivo antes de confiar en ellos**:
- `event.sports.game_id is not None` distingue un partido real de un
  evento de futuros/props de temporada (Champion, MVP) — un evento de
  futuros trae 30-50 mercados y `game_id=None`; un partido real trae
  `game_id` poblado. Confirmado contra ambos tipos reales.
- Para mercados estilo "¿gana el equipo X?" (splits 3-way de soccer:
  yes/no/draw como 3 mercados separados), `outcome.label` es
  literalmente "Yes"/"No" — el nombre real del equipo está en
  `market.group_item_title`. Solo se trackea el lado "yes" de estos
  (mismo criterio que ya se usaba a mano: `france_win`/`england_win`/
  `france_english_draw` nunca tuvieron un lado "no" trackeado).

Ventana de actividad: `game_start_time` (el campo confiable, no
`end_date`) entre `now-8h` y `now+2h` — cubre un partido que ya arrancó
o está por arrancar, con margen para la demora de resolución de UMA.
`volume_min=5000` para no traer mercados muertos.

**Decisión de sizing**: con potencialmente 50-100+ tokens simultáneos,
`MAX_POSITION_USD=20` queda desacoplado del supuesto viejo de "repartir
$100 entre ~8 tokens" — es una unidad de riesgo fija por token para
calibración, no una simulación de cartera real (estamos en fase de
paper trading, no capital real). Revisar esto antes de operar en vivo.

**Arquitectura**: `scripts/discover_active_markets.py` corre cada 15 min
(`launchd`, `com.example.polymarket-discover`, `StartInterval` no
`KeepAlive` — es un script de un solo shot) y escribe
`data/raw/polymarket/orderbook_live/tracked_markets.json`.
`record_orderbook.py` y `shadow_quote_live.py` releen ese archivo
periódicamente (`CONFIG_REFRESH_INTERVAL_S=300` / `TOKEN_REFRESH_INTERVAL_S=300`)
en vez de tener diccionarios hardcodeados. `record_orderbook.py`
reconecta el websocket cuando cambia el set de tokens (el protocolo de
subscribe manda la lista completa una sola vez al conectar, no hay forma
conocida de agregar tokens a una conexión existente). Los diccionarios
de `shadow_quote_live.py` (`KICKOFFS`/`TOKEN_LABELS`/`TOKEN_SIDE`/
`MARKET_IDS`/`EVENT_IDS`) solo crecen con el refresh, nunca se les saca
un token — un partido que sale de la ventana de "activo ahora" del
discovery no puede perder su metadata mientras siga con posición
abierta (mismo tipo de bug ya encontrado una vez con el filtro de
`process_message`).

Archivo de grabación renombrado de `worldcup_semifinals.jsonl` a
`live_book.jsonl` (ya no es específico de un torneo) — el archivo viejo
queda como está, historia preservada, no se migra.

18 tests nuevos (`tests/ingestion/polymarket/test_active_markets.py`,
más `TestRefreshTrackedTokens` en `tests/scripts/test_shadow_quote_live.py`).

### Dos bugs más encontrados desplegando lo de arriba, y round-trips durables

**Bug 1 — `tracked_markets.json` se sobreescribía, no se fusionaba.**
Un reinicio de `shadow_quote_live.py` reconstruye `TOKEN_LABELS`/etc.
desde cero leyendo ese archivo — coincidió con un ciclo de discovery
que había bajado a 0 partidos (correcto, ya habían resuelto) y el
proceso quedó sin nada, aunque momentos antes sabía de 12 tokens. Fix:
`merge_tracked_tokens()` en `active_markets.py` — unión por `asset_id`,
nunca se pisa. Pendiente sin resolver a propósito: el archivo ahora
crece sin límite (inofensivo a esta escala, revisar si esto corre
semanas — podar mal podría reintroducir el mismo bug).

**Bug 2 — reconstruir el estado desde el tape rompe la continuidad al
renombrar el archivo.** Al pasar de `worldcup_semifinals.jsonl` a
`live_book.jsonl`, `mets_win`/`phillies_win`/`liberty_win`/`wings_win`
desaparecieron de `shadow_state.json` en vivo — no se borró el dato
(seguía en las carpetas archivadas), pero dejó de ser visible sin ir a
buscarlo a mano. Confirma un patrón: todo lo que solo vive en memoria,
reconstruido por replay del tape, es frágil ante cualquier cambio de
archivo o reinicio.

**Fix estructural — dos logs nuevos, durables, append-only, que nunca
se renombran ni se resetean** (mismo patrón que ya se venía usando para
`RESOLVED_GAMES_PATH`):
- `round_trips.jsonl` — una línea por round-trip cerrado, con su PnL
  realizado. Detectado con el mismo proxy de cruce de signo
  (`ROUND_TRIP_EPS=0.5` tokens) ya usado a mano en análisis anteriores
  de esta sesión, ahora corriendo en vivo dentro de `update()`,
  `_flatten_at_market` y `force_close_at_resolution` — las 3 formas en
  que la posición puede volver a flat. Antes había que reconstruir la
  distribución de RT a mano desde fills archivados cada vez que se
  quería mirar; ahora se acumula solo.
- Backfilleados 8 round-trips de MLB/WNBA (`"backfilled": true`,
  derivados de los fills reales archivados, no inventados): `mets_win`
  3 RT (−5, +5, 0 → neto 0), `phillies_win` 3 RT (−0, −5, +5.02 → neto
  ~+0.02), `liberty_win`/`wings_win` 1 RT cada uno (el cierre forzado).

**Limitación que sigue abierta, la misma de siempre**: estos dos logs
nuevos tienen el mismo problema de fondo que `shadow_fills.jsonl` — un
reinicio a mitad de partido puede volver a escribir las mismas líneas
si el replay reprocesa ticks ya vistos. La disciplina de archivar antes
de reiniciar (que se viene siguiendo a mano en cada deploy de esta
sesión) sigue siendo necesaria; no está automatizada todavía. El
arreglo de fondo (dejar de reconstruir todo por replay, persistir el
estado de cada `ShadowBook` directamente) no se hizo en este pase —
alcance mayor, anotado para más adelante si el tape sigue creciendo.

9 tests nuevos (`TestResolvedGamesLog`, `TestRoundTripTracking` en
`tests/scripts/test_shadow_quote_live.py`) — incluye
`tests/scripts/conftest.py` nuevo, un fixture `autouse` que aísla los 3
paths durables (`ROUND_TRIPS_PATH`/`RESOLVED_GAMES_PATH`/
`TRACKED_MARKETS_PATH`) en todos los tests del directorio: sin esto,
correr la suite escribía basura en el archivo real del proyecto
(confirmado — pasó una vez, 5 líneas de test contaminaron
`round_trips.jsonl` antes de este fix).

### El dashboard (`dashboard_server.py`) no leía nada de lo nuevo

Reportado por el usuario: "no se ve nada" en el dashboard web (puerto
8765, IP privada). Causa real: el dashboard tenía su
**propia reimplementación** de detección de round-trips, re-derivada de
`shadow_fills.jsonl` en cada request — y ese archivo se archiva a mano
antes de cada reinicio (misma disciplina que ya se viene aplicando), así
que el dashboard perdía el historial en cada redeploy, sin relación con
los logs durables nuevos (`round_trips.jsonl`/`resolved_games.jsonl`)
que ya existían pero el dashboard nunca leía.

**Reescrito**: ahora lee directamente `round_trips.jsonl` y
`resolved_games.jsonl` (durables, acumulativos) en vez de re-derivar
nada de fills — elimina además una implementación duplicada de la
misma lógica de detección que podía divergir de la real. El cálculo de
"peor/mejor caso si resuelve ya" también se simplificó: se computa
directo de `cash`/`position` del book en vivo, ya no hace falta
replayear fills para eso tampoco. Nueva sección en la página: tabla de
partidos resueltos, con un marcador 📦 para las 4 entradas backfilleadas
a mano (no generadas por el mecanismo automático).

**Nota operativa**: al reiniciar `dashboard_server.py` el socket tarda
unos ~10s en pasar a estado `LISTEN` (visible con `lsof -i :8765`) —
`curl` inmediatamente después de un restart puede dar timeout o
conexión rechazada, no es un bug, solo esperar.

Verificado end-to-end desde afuera del servidor remoto (IP privada): los 4
partidos resueltos y los 8 round-trips aparecen correctamente, y un
partido nuevo que encontró el discovery (Rumania, `fc_voluntari` vs
`fc_botoșani`) ya aparece en "Books en vivo".

### Partido de Rumania — resultado desastroso, y un bug de histéresis nuevo

Con el discovery ya corriendo solo, el primer partido que dio números
grandes: `fc_voluntari_win`/`draw`/`fc_botoșani_win` (evento
`rou1-vol-fcb-2026-07-17`) cerró en **−$155.99 combinado** entre los 4
eventos ya decididos de la sesión (80% concentrado en este solo
partido). Terminó empate — la pierna `draw` venía corta (~−57 tokens)
cuando resolvió, forzando recompra a precio 1.0 de golpe
(`cash_after: -59.38` en una sola línea).

**Segundo mecanismo, más interesante — encontrado leyendo los fills
fill a fill, no asumido**: `fc_voluntari_win` mostró este patrón 4 veces
en ~25 minutos:

```
17:02:47  BUY 82 tokens @ 0.061   (fv sube sobre 0.03, retoma cotización, nos cruzan)
17:09:53  forced_flatten SELL @ 0.0   (fv cae bajo 0.03, vendemos lo recién comprado casi en cero)
17:13:26  BUY 94 tokens @ 0.053
17:13:35  forced_flatten SELL @ 0.002   (9s después)
17:13:37  BUY 93 tokens @ 0.0535
17:13:37.8  forced_flatten SELL @ 0.002   (0.8s después)
```

El precio real rebotaba pegado al límite de `RESOLUTION_PROXIMITY_STOP`
(0.03) — un solo umbral sin margen hace que el sistema retome
cotización apenas cruza de vuelta, lo crucen, y lo vuelva a flatear
casi en cero segundos después. No es selección adversa genérica, es un
problema de histéresis en el propio mecanismo de protección.

**Fix**: reutiliza `stopped_until` (el mismo campo que ya usa la
escalada tóxica) — al tocar la zona de `_near_resolution`, en vez de
solo evaluar el umbral puntual, extiende `stopped_until` a
`now + RESOLUTION_STOP_COOLDOWN_S` (600s, mismo valor que
`STOP_QUOTING_DURATION_S`, constante separada porque son conceptualmente
independientes). Cada nuevo toque de la zona extiende el cooldown de
nuevo — la cotización queda retirada hasta 600s después del ÚLTIMO
toque, no hasta que el precio cruce de vuelta por casualidad.
`n_stops` cuenta episodios distintos, no cada renovación dentro del
mismo episodio. **Reduce pero no elimina del todo** el patrón para un
mercado que sigue tocando el límite genuinamente durante muchos
minutos (no solo segundos) — verificado contra la secuencia real: un
cooldown de 600s hubiera bloqueado el reingreso de 17:21:57 pero no
necesariamente uno más espaciado en el tiempo.

5 tests nuevos (`TestResolutionStopHysteresis`), verificados fallando
sin el fix antes de confirmarlos. 92 tests en total.

### Cap de riesgo por evento — el enfoque de fondo estaba mal, no solo la calibración

Después de ver Rumania y WNBA perder plata real por el mismo motivo (ver
secciones de arriba), quedó claro que el problema no era selección
adversa mal calibrada — era que **cada pierna cotiza su propio libro sin
saber que las otras piernas son el mismo evento real**. Corto en
`liberty_win` (yes) + largo en `wings_win` (no) del mismo mercado no es
un hedge, es la misma apuesta direccional dos veces — cada uno con su
propio tope de $20 independiente, así que dos piernas "independientes"
pueden acumular $40+ de exposición real correlacionada a un solo
resultado. En Rumania (split 3-way) fueron tres piernas a la vez.

**Implementado** (`scripts/shadow_quote_live.py`):
- `event_worst_case(cash_total, positions)` — función pura: el pago
  combinado si el evento resuelve adverso ahora mismo. Exactamente una
  pierna paga su posición completa (la que gana), todas las demás pagan
  0 — así que el peor caso es `cash_total + min(positions)`.
- `event_sibling_books(books, asset_id)` — las otras piernas del mismo
  evento que ya tienen un `ShadowBook` (vía `EVENT_IDS`), sin incluir a
  sí mismo.
- `MAX_EVENT_LOSS_USD = 20.0` (mismo valor que `MAX_POSITION_USD` — la
  idea es que el evento completo comparta el presupuesto que antes tenía
  una sola pierna sola, no agregar un tope nuevo más permisivo).
- `ShadowBook.update()` ahora acepta `siblings: list[ShadowBook] | None`
  — si se pasa, calcula el peor caso combinado exacto (no aproximado)
  que resultaría de la fill prospectiva y bloquea si cruza
  `-MAX_EVENT_LOSS_USD`, **además** del tope individual existente (no lo
  reemplaza). `siblings=None` (el default) preserva el comportamiento
  viejo exacto — así que un token sin hermanos conocidos todavía no
  cambia nada, backward-compatible con toda la suite existente.

**Backtest contra el tape grabado** (mismo método que los A/B anteriores
— código con vs. sin el cap, mismos datos reales):

| evento | sin cap (lo que pasó) | con cap (hipotético) | diferencia |
|---|---|---|---|
| Rumania (3 piernas) | −104.38 | **−18.04** | **+86.34 (83%)** |
| WNBA (Liberty/Wings) | — | — | sin datos en este tape (la actividad real quedó en el `worldcup_semifinals.jsonl` viejo, antes del rename) |

Confirmado en vivo tras el redeploy: los mismos 3 tokens de Rumania
cerraron en −$5.00/−$8.04/−$5.00 (−$18.04 total), calzando exacto con
el backtest, con 25/27/17 fills bloqueados por el cap respectivamente.

8 tests nuevos (`TestEventWorstCase`, `TestEventSiblingBooks`,
`TestEventLevelRiskCap`). 100 tests en total.

**Investigación abierta, no cerrada acá**: esto corrige la exposición
correlacionada entre piernas del mismo evento — no resuelve la
selección adversa de fondo (el flujo direccional sigue empujando en una
sola dirección, el cap solo evita que se acumule sin límite combinado).
Falta ver cómo se comporta con partidos nuevos en vivo (esta validación
es sobre datos ya ocurridos, replayeados con el código nuevo, no una
predicción fuera de muestra) y seguir con la calibración de spread ya
pendiente.

### "La mitad de los fills llegan a resolución" — afirmación no verificable con el log que había

Observación del usuario mirando el dashboard: aproximadamente la mitad de
los round-trips parecían estar cerrando porque el mercado resolvió, no
porque el mecanismo de flatten activo (`_flatten_at_market`) o un cruce
orgánico los cerró antes. **No se podía confirmar con lo que ya estaba
logueado**: `round_trips.jsonl` registra `pnl`/`ts`/`label` pero no *cómo*
se cerró cada trip — las 3 vías de cierre (`update()` cruzando cero,
`_flatten_at_market`, `force_close_at_resolution`) escriben al mismo log
sin distinguirse entre sí. La tabla de partidos resueltos del dashboard
tiene una columna `flattens forzados` pero cuenta episodios de flatten
activo, no dice si el cierre final de cada round-trip fue uno de esos o
un pago a resolución — no alcanza para responder la pregunta tal como
estaba.

**Instrumentado, no todavía confirmado ni refutado**: `_maybe_close_round_trip`
ahora recibe un `reason` (`"organic"` | `"forced_flatten"` |
`"resolution_forced_close"`) y lo escribe en cada línea de
`round_trips.jsonl` como `close_reason`. El dashboard (`dashboard_server.py`)
agrega una tabla nueva ("Round-trips por cómo se cerraron") con n/%/PnL
medio/PnL sumado por razón — es lo que hace falta mirar para confirmar o
refutar la hipótesis con números, no a ojo. Trips logueados antes de este
cambio (incluyendo los 8 backfilleados a mano de MLB/WNBA) quedan en un
bucket `"unknown"`, sin inventar una razón retroactiva.

**Por qué importa la distinción, no es solo curiosidad**: si el PnL medio
de `resolution_forced_close` es consistentemente negativo y es una
fracción alta del total, el problema no es la calibración del spread —
es que `_should_flatten`/`_near_resolution`/el poll de game-status
(`RESOLUTION_CHECK_INTERVAL_S=300`, `GAME_STATUS_CHECK_INTERVAL_S=60`) no
está cerrando el inventario a tiempo, y el arreglo es de timing/umbral,
no de pricing. Si en cambio el PnL negativo está repartido parejo entre
las tres razones, la hipótesis del usuario no explica la pérdida y hay
que seguir buscando en otro lado (selección adversa de fondo, ya anotada
como investigación abierta arriba).

10 tests nuevos (`close_reason` cubierto en `TestRoundTripTracking`,
`tests/scripts/test_dashboard_server.py` nuevo con `TestReasonStats`).
107 tests en total (55 en el servidor remoto tras el deploy, subset relevante).

**Desplegado y verificado 2026-07-18 ~13:11-13:15 UTC**: `launchctl
kickstart -k` sobre `com.example.polymarket-shadow` dispara el replay
completo del tape (`live_book.jsonl`, 22.27M líneas / 15.4GB en ese
momento) desde cero — tardó **~3m20s** en ponerse al día (100% CPU
sostenido, `shadow_state.json.updated_at` pasó de estar parado a
quedar a segundos de la hora real). Sin errores en
`logs/shadow-quote.log`. `com.example.polymarket-dashboard` reiniciado
aparte (no depende del tape, no necesita replay).

**Resultado, con los 182 round-trips reconstruidos del tape completo**:

| close_reason | n | % | PnL sumado | PnL medio | std | peor |
|---|---|---|---|---|---|---|
| forced_flatten | 92 | 50.5% | −156.12 | **−1.697** | 4.54 | −17.20 |
| organic | 82 | 45.1% | −15.00 | −0.183 | 4.19 | −5.00 |
| unknown (backfilled, previo al tag) | 8 | 4.4% | −1.43 | −0.178 | 3.80 | −5.00 |
| resolution_forced_close | **0** | 0% | — | — | — | — |

Total: 182 round-trips, PnL acumulado realizado **−172.55**, win rate 29.1%.

**La afirmación original ("la mitad llega a resolución") queda
refutada en el mecanismo específico, pero el instinto de "hay un
problema y es la mitad" era correcto** — con el número exacto en mano
en vez de a ojo: **cero** round-trips llegaron a `force_close_at_resolution`
(el flatten activo por proximidad a resolución/fin de partido está
disparando a tiempo, siempre, no hay posiciones rodando hasta el
payout terminal). Lo que sí es ~mitad (50.5% de los trips) es
`forced_flatten` — y ahí está concentrada la pérdida: 90.5% del PnL
negativo total (−156.12 de −172.55) sale de esa mitad, con PnL medio
~9x peor que un cierre orgánico (−1.70 vs. −0.18) y una cola
claramente más pesada (peor caso −17.20 vs. −5.00 en orgánico, que
está topeado cerca de `MAX_FILL_USD` por construcción de un solo
fill).

**Lectura, consistente con lo ya documentado en "El stop-quoting no
basta"**: esto no es un bug de timing del flatten — el mecanismo
funciona (0 resolution_forced_close lo confirma). Es selección adversa
materializándose exactamente como se esperaba: un trip solo llega a
necesitar un flatten activo porque `fv` ya se movió fuerte hacia un
extremo en contra de la posición (por eso entró en la zona de
`_near_resolution`/`_game_confirmed_over` en primer lugar) — el
flatten realiza esa pérdida en cash, no la causa. El "arreglo" no es
ajustar `RESOLUTION_CHECK_INTERVAL_S`/`GAME_STATUS_CHECK_INTERVAL_S`
(ya está funcionando), es reducir cuánto inventario se acumula *antes*
de llegar a esa zona — calibración de spread/skew/tope de inventario
más agresiva, no un fix de mecanismo. Sigue siendo la misma
investigación abierta de selección adversa de fondo, ahora con el
tamaño del efecto cuantificado en vez de sospechado.

**Límite de esta lectura**: 182 round-trips de un puñado de partidos
(no es una muestra grande, y no son independientes entre sí dentro de
un mismo partido — mismo cuidado de pseudo-replicación ya señalado
arriba con el spread proxy). No tratar −1.697 como el PnL medio real
de `forced_flatten` en general, es el promedio observado en esta
ventana de datos.

**Reanálisis agrupando por evento, no por token** (mismo cuidado de
pseudo-replicación: muchas de las 100 etiquetas son piernas del mismo
partido — `team_a_win`/`team_b_win`/`draw_...` comparten `event_id` en
`tracked_markets.json`, no son sorteos independientes). Con la unidad
correcta: **50 eventos, PnL medio por evento = −3.45, std=7.22,
SE=1.02, t=−3.38 (df=49)** — significativo (t-crítico α=0.05≈2.01), y
no es un solo evento arrastrando el promedio: el peor evento es 10.5%
de la pérdida total, los 3 peores juntos 30.9%. Esto es evidencia real
de PnL esperado negativo por evento con la configuración actual, no
ruido de un outlier.

### Barrido de `HALF_SPREAD` — ¿ensanchar el spread arregla el edge negativo?

Pregunta directa del usuario tras ver el −3.38 de arriba: si las
ganancias por trade deben ser chicas y hay pérdidas grandes de cola,
¿hay alguna forma de que esto valga la pena? En vez de responder a
ojo, se armó un barrido real.

**Instrumentado**: `HALF_SPREAD` en `scripts/shadow_quote_live.py` pasa
a leerse de la env var `SHADOW_HALF_SPREAD` (default `0.01` sin
cambios, no afecta producción) — necesario porque `SKEW_MAX_SHIFT`/
`REQUOTE_DRIFT_THRESHOLD` se derivan de `HALF_SPREAD` al importar el
módulo, así que un barrido necesita un subproceso por valor, no un
loop dentro de un mismo proceso. `scripts/spread_sweep_backtest.py`
reusa `process_message`/`ShadowBook` **directamente** (no reimplementa
nada — evita exactamente el tipo de duplicación que ya causó que el
dashboard viejo divergiera de la lógica real) para reproducir el tape
grabado (`live_book.jsonl`) bajo un spread fijo, escribiendo a un
directorio aislado por corrida (`sweep_{spread}/`) para no tocar los
logs de producción. Payouts terminales de mercados que sí resolvieron
salen del `resolved_games.jsonl` real (ground truth ya conocido, no
recalculado); mercados sin resolver al final del tape quedan afuera
de las estadísticas (no realizados). **Brecha de fidelidad conocida,
aplica por igual a todos los valores del barrido**: sin llamadas REST
durante el replay, el flatten por game-status (`_game_confirmed_over`,
el caso WNBA donde el precio no se movía pero el partido ya había
terminado) no dispara — solo el flatten por precio (`_near_resolution`)
y el cruce orgánico cierran posiciones durante el replay mismo.
`scripts/run_spread_sweep.sh` corre la lista de valores secuencialmente.

**Desplegado y corrido en el servidor remoto 2026-07-18**: 5 valores
(0.01/0.02/0.03/0.05/0.08), cada uno un replay completo del tape
(22.27M líneas, ~3.5-4min por corrida, ~20min total).

| HALF_SPREAD | round-trips | eventos | PnL medio/evento | t | organic (mean) | forced_flatten (mean) |
|---|---|---|---|---|---|---|
| 0.01 | 175 | 46 | −3.63 | −3.34 | −0.18 | −1.63 |
| 0.02 | 93 | 36 | −3.16 | −2.41 | +0.16 | −1.92 |
| 0.03 | 63 | 28 | −2.60 | −1.88 | 0.00 | −1.78 |
| 0.05 | 30 | 14 | −2.51 | −1.44 | +0.83 | −2.51 |
| 0.08 | 10 | 6 | −5.41 | −2.32 | −1.67 | −3.92 |

**Resultado: ensanchar el spread, por sí solo, no convierte esto en
edge positivo en ningún punto del rango probado.** El PnL medio por
evento se queda entre −2.5 y −5.4 en todo el barrido, nunca cerca de
cero. Mecanismo encontrado, no solo el número: el lado `organic` sí
mejora con spread más ancho (−0.18→+0.16→0.00→+0.83, consistente con
capturar más edge por fill limpio) pero `forced_flatten` empeora
monótonamente (−1.63→−1.92→−1.78→−2.51→−3.92) — un spread más ancho
deja que el fair value se aleje más antes de que alguien cruce la
cotización, así que el fill que sí llega está más informado/adverso, y
cuando hace falta flatear activamente cerca de la resolución el
inventario ya derivó más lejos. La mejora del lado bueno queda
compensada casi entera por el empeoramiento del lado malo. Además el
n de eventos con algún trade cae fuerte con el spread (46→36→28→14→6)
— parte de por qué el t pierde significancia en 0.03/0.05 es menos
muestra, no menos pérdida esperada; en 0.08 vuelve a ser significativo
pero con n=6 no es una lectura confiable, solo indicativa.

**Lo que esto sí y no prueba**: cierra la hipótesis específica de "el
1¢ actual es un valor arbitrario, calibrarlo mejor alcanza" — no
alcanza, en este rango. No prueba que ningún enfoque pueda tener edge
en Polymarket sports MM — quedan sin probar: quoting asimétrico
reflejando el desbalance BUY:SELL 30-40:1 ya documentado (en vez de
`SKEW_MAX_SHIFT` simétrico), evitar del todo la ventana de kickoff en
vez de solo ensanchar ahí, o parar de cotizar en mercados/deportes
específicos donde el desbalance es peor. Tampoco es una muestra grande
ni independiente del período específico grabado (mismo partido de
fondo que en todos los hallazgos de esta sesión) — un tape distinto
(otra semana, otra mezcla de deportes) podría mover estos números.

3 tests nuevos (`TestHalfSpreadOverride` en `test_shadow_quote_live.py`,
`TestSpreadSweepBacktest` con smoke test end-to-end sobre un tape
sintético en `test_spread_sweep_backtest.py`). 114 tests en total.

### VPIN real (trade-tape) — calibrado y probado, no mueve la aguja

Pregunta del usuario: en equities la selección adversa se mitiga
mirando Level 3 (posición de cola por orden); Polymarket no expone eso
(confirmado, ver docstring de `record_orderbook.py`: "L2 aggregate
depth only... does not expose individual order queue position") —
¿qué se puede hacer con lo que sí hay?

**Verificado contra la cinta real antes de asumir nada**: el feed
(`live_book.jsonl`) tiene más de lo que `process_message` usaba.
Confirmado con una muestra de 300k líneas: los snapshots de book traen
**hasta 60 niveles de profundidad** con tamaño por nivel (no solo
top-of-book), los mensajes `price_change` traen `side`+`size` por
cambio (no solo el precio resultante), y hay un canal
**`last_trade_price`** separado (trades ejecutados reales, con
`price`/`size`/`side`/`fee_rate_bps`) que `process_message` no
manejaba — ninguna rama para ese `event_type`, se tiraba sin usar.

**Calibración de la señal, antes de implementar el gate** (48.446
eventos `last_trade_price` reales sobre 143 tokens trackeados,
extraídos de la cinta completa):
- **VPIN genuino (imbalance direccional)** —
  `|buy_vol−sell_vol|/total_vol` sobre ventana rodante de N trades.
  **Rechazado como gate de toxicidad**: mediana del imbalance en
  ventana de 20 trades = **0.97** (de 45.852 observaciones) — el flujo
  real está casi siempre saturado cerca del desbalance máximo, no es
  intermitente. Confirma a nivel de tick el hallazgo histórico de
  BUY:SELL~30-40:1 ya documentado arriba. Un umbral de nivel no puede
  distinguir "tóxico ahora" de "normal para este mercado" cuando lo
  normal ya está pegado al techo casi siempre — esta señal serviría
  mejor para sesgar la cotización en la dirección del desbalance que
  como gate on/off. No implementado (fuera de alcance de este pase).
- **Anomalía de tasa de arribo** (mismo esquema que el detector
  self-fill ya existente — tasa corta vs. tasa larga — pero alimentado
  por TODOS los trades reales del mercado, no solo los nuestros): sí
  tiene distribución usable — p50=1.93, p90=7.05, p95=9.44, p99=13.12.
  Reusar `TOXIC_RATE_MULTIPLIER=3.0` (calibrado para nuestros fills,
  mucho más esparcidos) marcaría tóxico ~31% del tiempo — no transfiere
  directo. `MARKET_VPIN_RATE_THRESHOLD=7.0` (~p90) elegido como primer
  corte, número empírico de esta cinta, no derivado teóricamente.

**Implementado**: `ShadowBook.record_market_trade()` (nuevo, alimentado
por el branch `last_trade_price` agregado a `process_message`) y un
segundo trigger independiente dentro de `_check_toxic_flow` —
`MARKET_VPIN_ENABLED` (default apagado vía env var
`SHADOW_MARKET_VPIN_ENABLED`, no toca producción) hace que la anomalía
de tasa de mercado completo **también** pueda disparar el mismo
mecanismo de widen/escalate-a-stop que ya usa el detector self-fill —
mismos campos (`toxic_until`/`stopped_until`/`n_stops`), sin tocar
`_should_stop_quoting` ni el resto. 6 tests nuevos
(`TestMarketWideTradeRecording`, `TestMarketWideToxicFlow`), 118 tests
en total.

**A/B contra el mismo tape, `HALF_SPREAD=0.01`** (mismo baseline del
barrido de arriba, dos corridas de `spread_sweep_backtest.py`,
`SHADOW_MARKET_VPIN_ENABLED=0` vs. `=1`):

| | sin VPIN (baseline) | con VPIN market-wide |
|---|---|---|
| round-trips | 179 | 164 |
| eventos | 47 | 47 |
| PnL total | −172.00 | −170.32 |
| PnL medio/evento | −3.66 | −3.62 |
| std | 7.30 | 8.46 |
| t-stat | −3.44 | −2.94 |
| organic (mean) | −0.23 | −0.45 |
| forced_flatten (mean) | −1.63 | −1.56 |

**No mueve la aguja.** La mejora en PnL total ($1.68 sobre $172, ~1%)
no es distinguible de ruido — el PnL medio por evento prácticamente no
cambia (−3.66→−3.62) y la desviación estándar **sube** (7.30→8.46), así
que el t-stat en realidad empeora (−3.44→−2.94) pese al PnL total
levemente mejor. Lo que sí cambia: el detector nuevo retira cotización
en algunos momentos que el detector self-fill no hubiera tocado —
`organic` mean empeora (−0.23→−0.45, se pierden algunos trades buenos)
y `forced_flatten` mean mejora apenas (−1.63→−1.56) — un efecto casi
nulo en ambas direcciones, se cancela.

**Lectura**: el umbral p90 empírico no es el único punto sin explorar
(quedan p75/p95/ventanas por volumen en vez de por tiempo sin probar),
pero con la primera calibración razonable la hipótesis "un detector de
flujo real en vez de auto-referencial reduce la pérdida" **no se
sostiene** en este tape. Consistente con el hallazgo del imbalance
direccional de arriba: el problema de fondo no parece ser "detectar
mejor cuándo el flujo es tóxico" (el flujo es tóxico casi siempre, de
forma persistente, no en ráfagas raras que un mejor detector
atraparía) — es la asimetría estructural del flujo en sí. Un detector
más rápido no ayuda contra una condición casi-permanente.

### Flow-skew asimétrico — empeora, no mejora, y el mecanismo importa más que el número

Idea siguiente, directo del hallazgo de arriba: si el flujo no es
intermitentemente tóxico sino persistentemente direccional, quizás no
conviene tratar de esquivarlo (gate on/off) sino **sesgar la
cotización en su dirección** — literatura estándar de microestructura
(Cont/Kukanov/Stoikov: order-flow imbalance predice drift de precio de
corto plazo, así que ambas puntas deberían liderar ese drift en vez de
quedarse pegadas al mid stale).

**Implementado**: `ShadowBook.market_flow_skew()` — imbalance con
signo `(buy_vol−sell_vol)/total_vol` sobre los últimos
`MARKET_FLOW_SKEW_WINDOW_TRADES=20` trades reales (mismo buffer que
`record_market_trade` ya alimenta). A diferencia del skew de
inventario (que RESTA — posición larga empuja la reserva hacia abajo,
defensivo), este **SUMA**: `reservation += flow_frac *
FLOW_SKEW_MAX_SHIFT` — flujo BUY-heavy empuja la reserva hacia arriba,
anticipando el drift en vez de reaccionar después. Gateado por
`SHADOW_MARKET_FLOW_SKEW_ENABLED` (default apagado).
`FLOW_SKEW_MAX_SHIFT` default = `SKEW_MAX_SHIFT` (0.03 a
`HALF_SPREAD=0.01`) — mismo orden de magnitud que el skew de
inventario, sin tunear, primer corte. 12 tests nuevos
(`TestMarketFlowSkew`, `TestMarketFlowSkewInReservation`). 127 tests
en total.

**A/B contra el mismo tape, `HALF_SPREAD=0.01`**:

| | sin flow-skew (baseline) | con flow-skew |
|---|---|---|
| round-trips | 186 | 204 |
| eventos | 48 | 51 |
| PnL total | −175.08 | **−231.20** |
| PnL medio/evento | −3.65 | **−4.53** |
| std | 7.26 | **20.74** |
| t-stat | −3.48 | −1.56 |

**Empeora, no mejora — y no por poco.** PnL total 32% peor
(−175→−231), PnL medio por evento peor (−3.65→−4.53), y la desviación
estándar casi se **triplica** (7.26→20.74) — el t-stat baja de
magnitud pero eso es ruido/varianza disparada, no una señal de que el
resultado se volvió menos negativo. No es un efecto marginal que
podría deberse solo a la magnitud sin tunear de `FLOW_SKEW_MAX_SHIFT`
— el signo del efecto (peor, no solo más ruidoso) sugiere un problema
de mecanismo, no de calibración fina.

**Por qué, con hipótesis mecanicista, no solo el número**: la
intuición de Cont/Kukanov/Stoikov se calibró en mercados líquidos
donde el impacto de precio de corto plazo suele revertir o al menos
tiene incertidumbre de dirección — anticiparlo captura spread de las
dos puntas. Acá el flujo BUY-heavy no parece ser una señal transitoria
así: es casi con certeza el mismo mecanismo ya documentado (la
multitud comprando cada vez más convencida del ganador a medida que el
partido avanza, empujando el precio hacia 1 de forma monótona, no
oscilante). Sesgar la reserva hacia arriba en ese contexto no es
"anticipar un rebote capturable" — es acumular más posición larga
exactamente en la dirección que ya explica las pérdidas de
`forced_flatten` (el precio convergiendo hacia un extremo antes de que
podamos salir), aumentando la exposición al mismo riesgo de cola en
vez de compensarlo. La suba de n_round_trips/n_eventos (186→204,
48→51) es consistente con esto: el bid más agresivo generó más fills
de compra, más inventario acumulado en la dirección tóxica.

**Implicación para el diseño, no solo para este experimento**: la
intuición de microestructura de equities sobre OFI asume una dinámica
de precio con reversión/incertidumbre de dirección de corto plazo —
acá el "OFI" persistente parece reflejar convergencia monótona hacia
un payoff terminal conocido (0 o 1), no ruido de liquidez transitorio.
Es exactamente el tipo de lugar donde la analogía con equities se
rompe, ya anotado como motivo de fondo del proyecto en
`POLYMARKET_MM.md` (sección de jumps/binary payoff). La forma
correcta de usar esta señal, si la hay, probablemente sea la
**contraria** — tratarla como razón para ensanchar/retirarse
(defensivo, mismo signo que el skew de inventario) en vez de liderarla
— no probado todavía, es la hipótesis natural para el próximo pase si
se decide seguir por acá.

### Test de calibración de precio — ¿está sesgado el precio de la cinta, no solo el mecanismo de quoting?

Pregunta distinta a todo lo anterior: los tres experimentos previos
(spread, VPIN, flow-skew) probaron **mecanismo de cotización**, dando
el precio de la cinta por bueno. Esta pregunta es si el precio en sí
tiene sesgo explotable — apostar en cualquier dirección, sin
market-making. Prior explícito del usuario antes de mirar el dato:
"estamos apostando contra una casa que estima muy bien sus odds" — es
decir, esperar calibración buena, no sesgo. Se corrió el test para
confirmar o refutar con números, no para validar la intuición a ojo.

**Datos**: los 43 partidos históricos ya bajados en
`data/raw/polymarket/matches/` (sin pegarle a la red de nuevo).
**Verdad de terreno del outcome**: el último precio grabado de cada
archivo, redondeado — NO el join contra el catálogo (ambiguo para
partidos 3-way de fútbol: home/away/draw comparten `event_title`, un
label por slug matchea múltiples filas del catálogo y no queda
guardado qué token específico se bajó). Usar el último precio del
propio archivo evita esa ambigüedad, al costo de descartar partidos
que no habían convergido para kickoff+8h (fin de la ventana de
fetch): **29 de 43 decisivos** (último precio >0.9 o <0.1), 14
descartados por no concluyentes.

**Metodología, con el mismo cuidado de pseudo-replicación de siempre**:
`scripts/price_calibration.py` (13 tests en `test_price_calibration.py`,
140 tests en total) toma precio en 5 checkpoints por FRACCIÓN de la
ventana propia de cada archivo (0.1/0.5/0.75/0.85/0.95 — 0.75 cae en
el kickoff por construcción de la ventana kickoff-24h/+8h), no en
timestamps absolutos, para no depender del join ambiguo ni siquiera
para la hora de kickoff. Poolear los 5 checkpoints por partido
infla N artificialmente (mismos 29 partidos, no independientes entre
checkpoints) — la lectura seria usa **un punto por partido**,
promediando los 4 checkpoints pre-resolución (0.1/0.5/0.75/0.85) por
partido antes de binear por precio.

**Resultado, con test binomial de dos colas por bin** (n_bins=5):

| bin de precio | n partidos | precio medio | outcome medio | gap | p (dos colas) |
|---|---|---|---|---|---|
| [0.0,0.2) | 2 | 0.120 | 0.000 | −0.120 | 1.000 |
| [0.2,0.4) | 6 | 0.314 | 0.167 | −0.148 | 0.780 |
| [0.4,0.6) | 3 | 0.558 | 0.667 | +0.108 | 1.000 |
| [0.6,0.8) | 14 | 0.707 | 0.929 | +0.221 | 0.107 |
| [0.8,1.0) | 4 | 0.895 | 0.750 | −0.145 | 0.719 |

**Ningún bin es significativo — y hay que decirlo aunque el más
llamativo casi lo sea.** El bin [0.6,0.8) (favoritos moderados,
n=14) muestra el patrón más grande — precio medio 0.707 pero resolvió
YES el 92.9% de las veces, sugiriendo que la cinta **subvalúa**
favoritos moderados. Con test de una cola (la lectura más favorable a
encontrar algo) da p=0.053, al borde pero sin cruzar el umbral
convencional de 0.05. Con el test de dos colas correcto (no elegir la
dirección después de ver el dato) da **p=0.107**, claramente no
significativo. Y esto es **antes** de corregir por comparaciones
múltiples — se testearon 5 bins, no 1; con Bonferroni haría falta
p<0.01 en un bin individual para significancia global, muy lejos de
0.107.

**Conclusión, sin inflar el hallazgo**: no hay evidencia de mispricing
explotable en esta muestra. El prior del usuario ("odds bien
estimadas") queda sin refutar — que es exactamente lo que hay que
reportar cuando el resultado nulo es el que sobrevive, no forzar un
hallazgo de un p al borde en un bin elegido después de mirar los 5.
Mismo patrón que la advertencia de "cuidado con pseudo-replicación"
de la sección de spread proxy: n=29 partidos (ya achicado de 43 por
el filtro de decisivos) es chico para caracterizar un efecto de este
tamaño con confianza — no alcanza para decir "no hay sesgo en
absoluto", solo para decir que esta muestra no lo muestra con
significancia. Haría falta un N bastante mayor (mismo orden que el
~35-40 partidos estimado para el hallazgo de ensanchamiento de spread)
antes de tratar el bin [0.6,0.8) como algo más que una curiosidad a
vigilar.

### Código

`src/ingestion/polymarket/`:
- `discovery.py` — `iter_sports_events()`, pagina todos los eventos de
  deportes (todas las ligas) vía tag id 1.
- `history.py` — `fetch_price_history()` (chunked+deduped) y
  `fetch_all_trades()` por mercado.
- `catalog.py` — `build_catalog()`/`save_catalog()`, aplana eventos→mercados
  a un DataFrame polars, un row por mercado binario, incluye
  score/período/equipos al momento del snapshot, tick size, order size
  mínimo. Guarda en `data/raw/polymarket/sports_markets_catalog.parquet`.
- `active_markets.py` — `discover_tracked_tokens()`, descubrimiento
  automático de partidos activos en las 6 ligas en scope (ver sección de
  arriba).

38 tests en `tests/ingestion/polymarket/` (pura lógica de chunking/dedupe y
de aplanado, sin red — `conftest.py` tiene factories para construir
instancias mínimas válidas de los modelos pydantic de la Gamma API).

## Conclusión y cierre de la sesión (2026-07-18)

Proyecto pausado acá — decisión del usuario tras la cadena de resultados
de abajo, no un bloqueo técnico. Los servicios en vivo del servidor remoto se
apagaron (`com.example.polymarket-shadow`, `-dashboard`, `-orderbook`,
`-discover` — ver "Apagado de infraestructura" más abajo); los datos
grabados (tape completo, round-trips, partidos resueltos, price
histories históricos) **no se borraron**, quedan en
`data/raw/polymarket/` en ambas máquinas por si se retoma.

### Qué se encontró, en orden

1. **El shadow-quoter en vivo, con protecciones (stop-quoting, flatten
   activo, cap de riesgo por evento), pierde plata de forma
   estadísticamente significativa**: agrupando por evento (no por
   token — corrige pseudo-replicación), 50 eventos, PnL medio por
   evento −3.45 a −3.66 según la corrida, t≈−3.4 a −3.5 (df≈45-49,
   t-crítico α=0.05≈2.0). No es un outlier arrastrando el promedio: el
   peor evento individual es ~10% de la pérdida total.
2. **Ensanchar el spread (`HALF_SPREAD` 0.01→0.08) no lo arregla.** El
   PnL medio por evento se mantiene entre −2.5 y −5.4 en todo el
   rango — mejora marginal en el medio, no una cura. Mecanismo: el
   lado orgánico mejora con spread más ancho, pero el lado
   `forced_flatten` empeora al mismo ritmo (el fair value se aleja más
   antes de que alguien cruce una cotización más ancha), y se cancelan.
3. **Un detector de flujo tóxico real (market-wide, no auto-referencial)
   tampoco ayuda.** Calibrado contra 48.446 trades reales: el
   imbalance direccional está casi siempre saturado (mediana 0.97, no
   intermitente) — no hay "momentos tóxicos" que detectar mejor, el
   flujo es persistentemente unidireccional. El A/B (mismo tape, mismo
   spread) da un cambio de PnL de ~1%, no distinguible de ruido.
4. **Sesgar la cotización en la dirección de ese flujo persistente
   (flow-skew) empeora, no mejora** — PnL 32% peor, varianza casi
   triplicada. La intuición de microestructura de equities (OFI predice
   drift de corto plazo, liderarlo captura spread) no transfiere: acá
   el flujo persistente refleja convergencia monótona hacia un payoff
   terminal conocido, no ruido transitorio con reversión — liderarlo es
   acumular más exposición a la misma cola que ya explica las pérdidas,
   no cubrirse contra ella.
5. **No hay evidencia de que el precio de la cinta esté mal calibrado**
   (test de calibración sobre 29 partidos históricos decisivos, 5 bins
   de precio, ningún bin significativo con test de dos colas — el más
   sugestivo da p=0.107, no p=0.05). N chico, no alcanza para descartar
   sesgo del todo, pero no lo confirma tampoco.

**Lectura conjunta**: cuatro resultados nulos/negativos consistentes
entre sí, no uno aislado. Ninguna variante del mecanismo de cotización
probada (spread, detección de toxicidad, dirección del skew) convierte
esto en edge positivo, y no hay señal de mispricing explotable para
apostar direccional en su lugar. La causa de fondo, con hipótesis
mecanicista y no solo el número: en un mercado binario que converge
monótono hacia un resultado conocido (no un proceso con reversión como
en equities), cualquier inventario que no se cierra antes de la
convergencia paga el movimiento completo — y no hay ajuste de
spread/detección/skew que reduzca eso sin también eliminar la mayor
parte del volumen que hace la estrategia operable en primer lugar. Es
exactamente el punto que motivó el proyecto desde el principio (ver
"Por qué no aplica directo" / jumps sobre payoff binario) — la
analogía con equities se rompe acá, ahora medida y no solo razonada.

**Lo que queda genuinamente sin resolver, no cerrado por falta de
interés sino por alcance**:
- Quién sostiene el lado vendedor contra el desbalance de 30-40x sin
  mover el precio (ver "Pregunta abierta..." arriba) — nunca se
  confirmó ninguna de las 4 hipótesis.
- Si un modelo de win-probability estructural (información real más
  rápida que la multitud, no ajuste de mecanismo) tendría edge — nunca
  se construyó, es lo único de la lista original de "Próximos pasos"
  que apuntaba a una fuente de edge distinta de la calibración del
  quoting.
- El test de calibración de precio con N mayor (29 partidos es chico
  para el tamaño de efecto que se vería en el bin más sugestivo).

### Apagado de infraestructura (2026-07-18)

`launchctl bootout` sobre los 4 jobs del servidor remoto
(`com.example.polymarket-shadow`, `-dashboard`, `-orderbook`,
`-discover`) — parados de inmediato. Los `.plist` se movieron de
`~/Library/LaunchAgents/` a `~/projects/quant/launchd_disabled/` (no
se borraron) para que tampoco vuelvan a cargar solos en el próximo
reinicio/login del servidor remoto — `RunAtLoad: true` los relanzaría si
quedaban en su carpeta original. Para retomar: mover los `.plist` de
vuelta y `launchctl bootstrap gui/$(id -u) <plist>` por cada uno (o
simplemente hacer login de nuevo con los archivos en su lugar).

Dashboard (puerto 8765, IP privada) deja de responder al apagar
`com.example.polymarket-dashboard`. Ningún dato se borró: tape completo
(`live_book.jsonl`), `round_trips.jsonl`, `resolved_games.jsonl`,
`shadow_fills.jsonl`, `tracked_markets.json`, los directorios
`sweep_*/` de los backtests, y los 43 `matches/*.parquet` históricos
siguen en `data/raw/polymarket/` en ambas máquinas.
