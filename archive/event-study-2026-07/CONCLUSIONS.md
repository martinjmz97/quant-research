# Conclusión de la investigación (cerrada 2026-07-08)

## Pregunta original
¿Cuando líderes mundiales y grandes empresarios de EE.UU. hablan en redes sociales, mueve eso los mercados de forma capturable? Y más adelante: ¿un enfoque cualitativo de tesis de cadena de suministro, filtrado con métodos cuantitativos, encuentra ineficiencias que el arbitraje automatizado no llega a cubrir?

## Resultado: no se encontró señal capturable, en ningún nivel probado

| Nivel testeado | Método | Resultado |
|---|---|---|
| Índices (SPY/QQQ) vs. posts de Trump | Event study + placebo test, corto y multi-día | Nulo — el único resultado "significativo" no sobrevivió el placebo (p=0.024 con 27 tests sin corregir, exactamente lo esperado por azar) |
| Patrón recurrente semis→autos (Renesas, tormenta Texas, terremoto Taiwán) | Event study + test de permutación, n=3 eventos | Inconcluyente — n=3 es matemáticamente insuficiente, el patrón visible a ojo (proveedor plano, automotrices cayendo) no se distingue de tríos de fechas aleatorias |
| BTC ante tweets de Trump sobre crypto | Event study + placebo | El único caso donde el placebo NO replicó el resultado — pero se descartó por contaminación (4 de 19 "eventos" eran el mismo momento en una conferencia, inflando el n) |
| 22 tesis cualitativas de cadena de valor (chokepoints reales, documentados, con mecanismo y fecha exacta) a 90 días | Event study diario + test de permutación individual por evento | **48% de acierto direccional (11/23) — peor que cara o cruz. Solo 1/23 mostró un movimiento estadísticamente inusual respecto al historial propio de la acción** |
| Velocidad de reacción intradía (datos de minuto reales, 7 eventos 2023-2026) | Trayectoria minuto a minuto | Inconsistente: a veces el 70%+ del movimiento ya pasó antes de la apertura (ASML), a veces se revierte contra la tesis correcta el mismo día (MP Materials, +12.66% en la apertura → -6.59% al cierre), a veces tarda horas en desarrollarse (RTX, ERIC) |

## Por qué

Todo lo que se puede formular como tesis razonable a partir de información pública (aranceles, disrupciones de cadena de suministro, controles de exportación, declaraciones políticas) ya está siendo procesado por participantes más rápidos y sistemáticos (bancos, fondos cuant — ej. el índice "Volfefe" de JPMorgan para tweets de Trump). Lo que queda después de que el mercado absorbe esa información es indistinguible del ruido a 90 días para una sola empresa, incluso cuando el mecanismo causal es real y bien documentado. Es el resultado esperable bajo la hipótesis de mercados eficientes en su forma semi-fuerte.

## Lo que sí quedó de valor, más allá de la señal de trading

1. **El motor de testing (event study + placebo/permutación)** en `src/eventstudy/` — sirve para descartar rápido y barato cualquier tesis nueva antes de arriesgar capital en ella. Ese fue el verdadero producto de esta investigación, no una señal.
2. **La base de conocimiento de cadenas de valor** en `data/valuechain/*.md` y `src/valuechain/registry.py` (12 industrias, chokepoints, empresas expuestas directa/indirectamente) — útil para mapear exposición de una cartera existente, no para timing de entrada.
3. **El pipeline de ingesta** (`src/ingestion/`, `src/news/`) — Trump/Truth Social, crypto (Binance), equities (Databento), RSS de noticias — reutilizable si se retoma la investigación.

## Pregunta que quedó abierta, sin cerrar
¿Vender/comprar volatilidad (en vez de apostar dirección) alrededor de estos eventos tiene edge, dado que el salto de volatilidad SÍ es real y observable (todos los gaps medidos) aunque la dirección no sea predecible? No se testeó.

## Estado de la infraestructura
El dashboard que corría en el servidor remoto fue dado de baja el 2026-07-08 — los `LaunchAgents` se desinstalaron para no consumir recursos. El código y los datos quedan intactos por si se retoma.
