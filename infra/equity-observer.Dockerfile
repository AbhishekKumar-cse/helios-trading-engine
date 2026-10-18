FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY research/helios ./research/helios
RUN uv sync --frozen --no-dev --no-editable
RUN useradd --uid 10001 --create-home observer && mkdir /output && chown observer /output
USER observer
ENTRYPOINT ["python", "-m", "helios.equities.service"]
