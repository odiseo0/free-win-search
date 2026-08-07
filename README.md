# Free Win Search

Microservicio de catálogo y publicaciones de cartas con API FastAPI, caché
Valkey y un pipeline ETL durable sobre PostgreSQL.

## Procesos

Primero aplica el esquema:

```shell
pdm run alembic upgrade head
```

La revisión base crea las tablas en instalaciones nuevas. Si encuentra tablas
legacy, verifica sus columnas antes de adoptarlas; un esquema parcial aborta la
migración.

Este servicio mantiene su historial en
`free_win_search_alembic_version`. La tabla predeterminada `alembic_version`
continúa siendo propiedad de Free Win Orders y no debe borrarse, editarse ni
marcarse con revisiones de Search. Por ello ambos servicios pueden usar la misma
base PostgreSQL conservando grafos de migración independientes.

En el primer despliegue sobre la base compartida:

```shell
# Muestra exclusivamente el historial de Free Win Search.
pdm run alembic current

# Crea/adopta las tablas de Search y su tabla de versión independiente.
pdm run alembic upgrade head
```

Si un intento anterior escribió una revisión de Search en `alembic_version`,
restaura esa tabla al revision ID vigente de Free Win Orders antes de continuar.
No uses `stamp` sobre la tabla compartida. La autogeneración de Search está
restringida a `cards`, `card_listings`, `scrape_targets` y `scrape_jobs`, de modo
que no propondrá eliminar tablas pertenecientes a Orders.

Ejecuta el API y el worker como procesos separados del mismo artefacto:

```shell
pdm run uvicorn src.application:app
pdm run python -m src.core.services.scraper worker
```

La busqueda canonica usa PostgreSQL de forma predeterminada. Para consumir un
servidor MeiliSearch externo configura `SEARCH_BACKEND=meilisearch`,
`SEARCH_MEILISEARCH_URL`, la API key si aplica y `SEARCH_INDEX_UID`. El API cae
a PostgreSQL si la busqueda remota falla; PostgreSQL sigue siendo la autoridad.

La sincronizacion del indice se ejecuta como otro proceso del mismo artefacto:

```shell
pdm run python -m src.core.services.search_index worker
pdm run python -m src.core.services.search_index once
pdm run python -m src.core.services.search_index reindex --batch-size 100
```

`reindex` no elimina documentos desconocidos. La activacion de lecturas en
MeiliSearch debe hacerse solamente despues de aprobar y aplicar sus settings y
de completar la reindexacion.

Para reclamar como máximo un trabajo (bootstrap o prueba manual):

```shell
pdm run python -m src.core.services.scraper once
```

En producción configura `CACHE_BACKEND=valkey`; la caché en memoria solo está
destinada a desarrollo local y pruebas. Los valores del worker se ajustan con
variables `SCRAPER_*`, incluidos polling, lease, intentos, concurrencia y timeout.

## Flujo de búsqueda

`GET /card-listings/search` consulta caché y PostgreSQL. Una coincidencia canónica
con datos frescos devuelve `200`; si están vencidos devuelve los datos actuales y
encola el refresco. Un cold miss devuelve `202` con `job_id` y el estado se consulta
en `GET /card-listings/jobs/{job_id}`. Una consulta ambigua puede leer listings
existentes, pero nunca crea objetivos arbitrarios ni acepta URLs externas.

## Backfill de cartas sin publicaciones

Despues de aplicar las migraciones, inspecciona primero cuantos trabajos se
programarian. Este modo no modifica PostgreSQL ni crea un checkpoint:

```shell
pdm run python -m src.core.services.scraper backfill-missing --dry-run
```

Para programarlos, ejecuta:

```shell
pdm run python -m src.core.services.scraper backfill-missing
```

El comando crea lotes de hasta 50 cartas. Todos los trabajos de un lote comparten
el mismo `available_at`, de modo que el worker puede procesarlos con concurrencia.
El primer lote queda disponible inmediatamente y cada lote siguiente toma el
horario del anterior y le suma un intervalo aleatorio de 5 a 30 minutos. Los
trabajos de backfill
usan prioridad `-10`, por lo que una busqueda interactiva con prioridad `0` se
atiende antes. El worker debe ejecutarse como un proceso separado.

El progreso durable se escribe atomicamente en
`var/scraper/missing-listings-backfill.json`. Si el proceso falla, la siguiente
ejecucion reanuda desde `last_card_id`. Una ejecucion terminada inicia un nuevo
recorrido completo. Para descartar deliberadamente un recorrido incompleto y
archivar su checkpoint usa:

```shell
pdm run python -m src.core.services.scraper backfill-missing --restart
```

El path y los valores predeterminados se pueden configurar con
`SCRAPER_BACKFILL_STATE_PATH`, `SCRAPER_BACKFILL_BATCH_SIZE`,
`SCRAPER_BACKFILL_MIN_INTERVAL_MINUTES`,
`SCRAPER_BACKFILL_MAX_INTERVAL_MINUTES` y `SCRAPER_BACKFILL_PRIORITY`. Tambien
existen flags equivalentes en el comando.

Un 404 es terminal: el target queda deshabilitado y no se vuelve a programar
automaticamente. Tras corregir el nombre o verificar la carta, se habilita de
nuevo sin crear un trabajo con uno de estos comandos:

```shell
pdm run python -m src.core.services.scraper reset-target --ygo-id 46986414
pdm run python -m src.core.services.scraper reset-target --card-id 2854
```

Las respuestas validas con al menos una publicacion en stock se refrescan una
hora despues. Si todas tienen stock cero, o la pagina confirma que no hay
publicaciones, el siguiente refresco queda disponible seis horas despues. Las
publicaciones con stock cero se conservan en `card_listings`.
