# Configuración de APIs · QuantEdge Sports
**Revisado el 12-11-2026.** Las conexiones autenticadas todavía no han sido comprobadas; faltan claves API.

## 1. BALLDONTLIE sin pagar
1. Regístrate en https://app.balldontlie.io/
2. Elige el plan NBA **Free (0 USD/mes)** y localiza tu clave de API.
3. No compartas la clave en el chat, archivos del repositorio o incidencias de GitHub.

Free permite consultar jugadores, equipos y partidos, pero **no** datos individuales de partidos (PTS/REB/AST). Para entrenar el MVP con esas estadísticas se requiere, como mínimo, **ALL-STAR NBA (9,99 USD/mes)**; GOAT NBA cuesta **39,99 USD/mes** y ofrece datos avanzados y props, sujeto a cobertura. No hay que contratar nada para comprobar la conexión gratuita.

## 2. Configura GitHub Secrets
Entra en: https://github.com/jaimeherradon-sys/quantedge-sports/settings/secrets/actions

Pulsa **New repository secret** y guarda:
- **Name:** `BDL_API_KEY`
- **Secret:** tu clave de BALLDONTLIE.

Estos valores no deben quedar visibles en commits o registros.

## 3. Ejecuta la comprobación manual
Abre https://github.com/jaimeherradon-sys/quantedge-sports/actions/workflows/provider-check.yml y pulsa **Run workflow** sobre `main`. Revisa los registros o el resumen. El flujo comprueba `/v1/teams`, **no** verifica que el plan permita descargar estadísticas individuales. Un fallo de autenticación o red detiene la prueba; no se fabrican resultados.

## 4. Cuotas opcionales
En https://the-odds-api.com/ hay un plan Starter gratuito de **500 créditos/mes**. Guarda su clave como `ODDS_API_KEY` en los mismos GitHub Secrets; no la compartas por chat. El flujo comprobará que responde el catálogo de deportes. La cobertura efectiva de props depende de partido, región y casa. El histórico de cuotas requiere un plan de pago.

## 5. Estado del modelo
Hasta contar con estadísticas y cuotas históricas autorizadas, información prepartido y pruebas temporales fuera de muestra, el resultado conservador es **NO BET**. No se colocan apuestas automáticamente.

Fuentes y condiciones: https://nba.balldontlie.io/ · https://www.balldontlie.io/terms.html · https://the-odds-api.com/ · https://the-odds-api.com/liveapi/guides/v4/
