# Cuotas y líneas NBA GOAT: importación auditable

> **NO BET:** este proceso recopila datos, no recomienda ni ejecuta apuestas.
> Verificado contra la documentación del proveedor el 12-11-2026. Las conexiones reales requieren tu clave GOAT: no se ejecutan en pruebas locales.

## Fuentes y limitaciones

| Objetivo | Endpoint documentado | Carácter |
|---|---|---|
| Ganador, spread, total actuales | `GET /v2/odds?game_ids[]=...` | Live, `updated_at` |
| Props actuales PTS, REB, AST, triples, PRA | `GET /v2/odds/player_props?game_id=...` | Live, `updated_at`; sin paginación |
| Aperturas históricas de partido | `GET /nba/v2/odds/opening?game_ids[]=...` | Histórica, `opened_at`; paginación |
| Aperturas históricas de props | `GET /nba/v2/odds/player_props/opening?game_id=...` | Histórica, `opened_at`; sin paginación |

Fuente oficial: https://docs.balldontlie.io/ . La cobertura de aperturas se limita a temporadas recientes. No existe un histórico completo de cambios de precio para los props, y **las aperturas no permiten calcular Closing Line Value por sí solas**. En algunos partidos el mercado de props puede estar vacío.

## Cómo ejecutar sin revelar las credenciales

1. Confirma que `BDL_API_KEY` está configurada en *GitHub Actions Secrets*.
2. Abre `Actions → GOAT NBA odds - collect real market snapshots (NO BET) → Run workflow`.
3. Selecciona `mode=live`, deja `game_date` vacía y `max_games=3` para consultar hasta tres encuentros aún no empezados en la fecha NBA de hoy (UTC). Si no hay partidos por iniciar, devolverá **NO BET**; puedes probar la fecha del día siguiente.
4. Para **cuotas de apertura históricas**, elige `mode=opening` y un día anterior a hoy, por ejemplo `2026-11-11`, con `max_games=3`. Usa únicamente fechas con partidos NBA.
5. Abre la ejecución y descarga `nba-goat-odds-<run_id>.zip` en **Artifacts**. Conserva una copia: los artefactos de GitHub caducan a los 30 días. Sube el ZIP en esta conversación si deseas analizar la cobertura y unirla al histórico NBA anterior.

## Qué se guarda

- `goat_games`: game ID, día NBA, inicio UTC, equipos, estado y fecha de consulta.
- `goat_odds_raw`: respuestas completas del proveedor, parámetros y hora local de consulta (sin secretos).
- `goat_odds_quotes`: `game_id`, `player_id` cuando procede, vendor, mercado, lado, línea, cuota original americana, cuota decimal, probabilidad implícita, `quote_at`, `observed_at`, tipo `opening` o `live`, fuente, y validación `pregame`.
- `reports/goat-odds-summary.json`: número de juegos y cuotas, mercados, casas y pares over/under.

**Importante:** `quote_at` es hora informada por el proveedor; `observed_at` es la hora en la que **nuestro** proceso recuperó esa cotización. Una cuota de apertura histórica puede tener `quote_at` antes del partido pero `observed_at` muchos meses después; debe etiquetarse **opening** y nunca hacerse pasar por una cotización que nuestro modelo observó en tiempo real.

## Cuotas americanas

Si la casa muestra `-110`, la cuota decimal es `1 + 100/110 = 1,9091`. Con `+150` resulta `1 + 150/100 = 2,50`. La probabilidad implícita es `1/cuota`. Para dos lados equivalentes, misma casa, línea y marca temporal, se puede calcular la probabilidad *sin margen* por normalización, pero **no** sustituye el precio ofertado en el cálculo de EV.

La API no garantiza disponibilidad de **Bet365 para props** aunque sí puede ofrecer Bet365 en cuotas de partido. Tampoco se garantiza acceso regional a las casas que aparecen.

## Precauciones

- Respetamos un espacio de al menos 18 segundos entre **solicitudes lógicas**. No deben ejecutarse otras operaciones con la misma API Key durante la importación; GitHub Actions comparte un grupo de concurrencia con nuestros otros flujos.
- La ejecución no solicita apuestas, ni envía órdenes, ni inventa líneas inexistentes.
- Sin minutos previstos verificables, lesiones, precios prepartido **y probabilidades calibradas para líneas reales**, el sistema mantiene **NO BET**.
- Los datos actuales se limitan a eventos futuros cuya hora de inicio es posterior a la captura. Los históricos se etiquetan como aperturas y solo aceptan `opened_at` anterior al inicio.
- Guardar el archivo localmente no publica datos licenciados en el repositorio. Respeta términos de uso, almacenamiento y difusión del proveedor.
