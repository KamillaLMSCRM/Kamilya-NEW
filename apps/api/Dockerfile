FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 kamilya \
    && useradd --system --uid 10001 --gid kamilya --create-home \
        --home-dir /home/kamilya --shell /usr/sbin/nologin kamilya

RUN pip install --no-cache-dir poetry && poetry config virtualenvs.in-project true

COPY apps/api/pyproject.toml apps/api/poetry.lock* ./
COPY packages /packages
RUN poetry install --no-interaction --no-ansi --without dev --no-root --with observability

COPY apps/api/ .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
ENV HOME=/home/kamilya
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Application source and the in-project virtualenv remain root-owned/read-only.
# The runtime identity can write only to explicitly mounted storage and /tmp.
USER 10001:10001

# Run migrations before starting uvicorn. Uses sh -c so `&&` works in CMD.
# If migrations fail, the container exits and won't start with old code against a half-migrated DB.
# Acceptable on single-instance Render (numInstances=1). For multi-instance, switch to a preDeploy hook
# to avoid two containers racing on DDL.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
