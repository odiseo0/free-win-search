# Free Win Search — guía para agentes

## Propósito y alcance
- Microservicio Python 3.13 para catálogo, búsqueda y pipeline de cartas de Free Win.
- Es propietario de `Card`, `CardListing`, caché y etapas de extracción, transformación y carga.
- No incorpora Usuarios, Pedidos, Órdenes, autenticación ni reglas del backend principal.
- Prioriza una solución comunitaria sencilla, segura, observable y mantenible.

## Arquitectura
- `src/api/cards/domain/`: contratos y errores; sin FastAPI ni SQLAlchemy.
- `src/api/cards/application/`: casos de uso y coordinación de puertos.
- `src/api/cards/infrastructure/`: routers delgados y traducción HTTP.
- `src/api/cards/repository/`: modelos, DAOs y consultas PostgreSQL.
- `src/core/services/scraper/`: extracción, transformación, búsqueda y carga ETL.
- `src/core/services/cache/`: puerto y adaptadores de memoria/Valkey.
- Mantén I/O asíncrono; mueve trabajo intensivo de CPU fuera del event loop.

## Reglas del pipeline
- Conserva separadas extracción, transformación y carga; no persistas desde una búsqueda implícitamente.
- Toda llamada externa necesita timeout, concurrencia limitada y manejo explícito de fallos.
- No ocultes errores de scraping: registra contexto seguro sin guardar HTML excesivo ni secretos.
- Normaliza y valida datos antes de persistir; usa `Decimal` para importes.
- Las cargas deben ser idempotentes, transaccionales y seguras ante reintentos.
- Revisa explícitamente la identidad de una publicación antes de cambiar el upsert.
- Cierra clientes, pools y executors durante el lifecycle del proceso.
- No pruebes contra CoolStuffInc, YGOPRODeck, Valkey o PostgreSQL reales por defecto.

## Convenciones de trabajo
- Usa tipos modernos, nombres en inglés y términos de dominio consistentes.
- Los errores recuperables usan `Result`, `Ok`, `Err` y tipos concretos.
- OpenAPI es el contrato público; documenta endpoints y valida sus respuestas.
- Declara directamente toda dependencia importada y nunca incluyas secretos.
- Preserva cambios ajenos y evita refactorizaciones fuera del alcance solicitado.

## Validación
- Prueba cada etapa con HTML, clientes, relojes y stores controlados.
- Cubre éxito, timeout, HTTP inválido, HTML cambiante, deduplicación, reintento y lote vacío.
- Usa PostgreSQL desechable para comportamiento específico de `ON CONFLICT`; no lo simules con SQLite.
- Ejecuta `pdm run pytest` y el type checker relevante; comunica cualquier validación omitida.
- Una corrección debe incluir una prueba de regresión cuando sea razonable.
