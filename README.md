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
