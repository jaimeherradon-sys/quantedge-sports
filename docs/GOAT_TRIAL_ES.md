# GOAT NBA · prueba de 7 días (sin apuestas reales)

Actualizado: 2026-11-12. Este flujo solo obtiene datos autorizados con tu clave `BDL_API_KEY` almacenada en GitHub Actions Secrets.

## Antes de nada

En BALLDONTLIE comprueba que la suscripción indica **Cancel at trial end** y que muestra la fecha exacta de caducidad; guarda la confirmación de cancelación. No introduzcas tu tarjeta ni tus claves en GitHub, archivos o chats.

## 1. Comprobar que la clave ya tiene permisos GOAT

Abre `Actions > GOAT trial - verify access or backfill historical NBA stats > Run workflow` y selecciona **probe** en `main`. La prueba hace solo dos consultas, separadas por 18 segundos, a `/v1/stats` y `/nba/v2/stats/advanced`. Si falla, revisa la ejecución y no inicies el backfill. Un código 200 con datos vacíos verifica acceso técnico, no cobertura estadística.

## 2. Importar el histórico (solo si probe está verde)

Vuelve a ejecutar el mismo workflow, pero selecciona **backfill**. Por defecto recoge **2025-12-01 a 2026-02-28** (NBA 2025-26). Se hace por quincenas, con límite interno de 18 segundos entre peticiones para respetar la prueba de 5 req/min. La duración depende del número real de páginas y del tiempo de respuesta de la API.

El histórico se guarda en el archivo descargable `nba-goat-history-<run_id>` de la ejecución. Dentro hay `data/goat-trial.sqlite` y `reports/goat-trial-audit.json`. Los artefactos expiran a los **30 días**: **descarga y haz copia local del ZIP** antes de esa fecha. No subas el fichero SQLite al repositorio público sin revisar protección de datos, derechos de terceros y licencia. Github Actions no acumula automáticamente la base entre ejecuciones; cada una genera una base propia. Debemos desarrollar un almacenamiento persistente y la unión auditada de lotes antes de depender de los resultados.

## 3. Antes de modelar apuestas

Conseguir `player_games` permite calcular medias y entrenar un primer modelo experimental, **no** demuestra rentabilidad. Falta validar cobertura, sesgos, divisiones temporales, minutos esperados, lesiones y **cuotas históricas reales capturadas antes del evento**. Hasta entonces: **NO BET**.

## Fuentes

- https://docs.balldontlie.io/
- https://www.balldontlie.io/terms.html

Condiciones vigentes al revisar: 7 días de prueba GOAT, 5 solicitudes por minuto y cancelación al final. BALLDONTLIE declara que, sujeto a sus términos y derechos de terceros, se pueden conservar datos obtenidos legalmente tras la suscripción, pero no revenderlos como API sustitutiva.
