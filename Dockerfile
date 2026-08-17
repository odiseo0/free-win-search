ARG PYTHON_BASE=3.13-slim

FROM python:${PYTHON_BASE} AS builder

ARG PDM_VERSION=2.28.1
ENV PDM_CHECK_UPDATE=false \
    PDM_VENV_IN_PROJECT=1

WORKDIR /app

RUN pip install --no-cache-dir "pdm==${PDM_VERSION}"

COPY pyproject.toml pdm.lock README.md ./
COPY src ./src

RUN pdm install --check --prod --no-editable


FROM python:${PYTHON_BASE} AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
COPY --chown=app:app src ./src
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini README.md ./

RUN mkdir -p /app/var/scraper && chown -R app:app /app/var

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/', timeout=2)"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.service_supervisor"]
