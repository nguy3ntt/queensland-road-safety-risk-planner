FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m venv /opt/qrs-venv && \
    /opt/qrs-venv/bin/python -m pip install --no-cache-dir '.[app]'

FROM python:3.12-slim-bookworm

ENV PATH="/opt/qrs-venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=build /opt/qrs-venv /opt/qrs-venv
COPY configs/base.yaml /app/configs/base.yaml
RUN groupadd --gid 10001 qrs && \
    useradd --uid 10001 --gid qrs --home-dir /nonexistent --no-create-home qrs && \
    mkdir -p /app/data/processed/milestone6 /app/reports/generated/milestone6 && \
    chown -R qrs:qrs /app
USER qrs
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "qld_road_safety.container:create_container_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
