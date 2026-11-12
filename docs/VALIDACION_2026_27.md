# Validación exploratoria NBA 2026-27 (12 de noviembre de 2026)

**Estado: NO BET.** Investigación retrospectiva, sin cuotas ni lesiones verificadas antes del partido.

## Fuentes y cobertura

Se auditaron dos exportaciones privadas BALLDONTLIE GOAT aportadas por el usuario. Los datos originales no se publican aquí.

| Temporada | Partidos finalizados | Registros jugador-partido |
|---|---:|---:|
| 2025-26 (dic-feb) | 597 | 12.849 |
| 2026-27 (oct-nov) | 170 | 3.843 |
| Total | **767** | **16.692** |

105 fechas con estadísticas, 608 jugadores distintos, 30 equipos. Los puntos individuales de ambos equipos cuadran con el marcador de cada partido. Sin IDs duplicados, sin estadísticas individuales vacías; SQLite `integrity_check = ok`. Los archivos no contienen cuotas ni snapshots de lesiones.

**Faltan marzo-junio de 2026**. Se han reiniciado los promedios móviles al comenzar la temporada 2026-27 para evitar que febrero se trate como el pasado inmediato de octubre.

## Prueba entre temporadas sin uso de resultados futuros para seleccionar modelos

Con 10.367 registros elegibles de 2025-26 se usaron 3 validaciones temporales expansivas para elegir entre media móvil de 5, Poisson y gradient boosting. Los modelos seleccionados se ajustaron exclusivamente con datos de 2025-26. Se evaluaron sin refinar sobre **1.725 registros** de 2026-27 (13 fechas elegibles, 29-oct a 11-nov), usando solo los cinco partidos *anteriores del mismo jugador en la misma temporada* y datos conocidos del calendario.

| Umbral ilustrativo (NO línea de casa) | Modelo elegido en 2025-26 | Brier 2026-27 | Brier media últimos 5 | Log Loss 2026-27 |
|---|---|---:|---:|---:|
| Puntos > 9,5 | Poisson | **0,1746** | 0,1778 | 0,5227 |
| Rebotes > 3,5 | Gradient Boosting | **0,1872** | 0,1878 | 0,5527 |
| Asistencias > 1,5 | Gradient Boosting | **0,1839** | 0,1953 | 0,5439 |

Los resultados son retrospectivos, condicionados a que el jugador haya participado. No incorporan lesiones, titularidad confirmada, rotaciones futuras, ni cuota de una casa. Los umbrales son experimentales. **No hay datos suficientes para afirmar EV positivo, ROI o ventaja de mercado.**

La base fusionada, los CSV de predicciones, el informe extenso y el evaluador reproducible se entregaron al propietario como archivo privado, no en este repositorio público. No se automatizan apuestas reales.
