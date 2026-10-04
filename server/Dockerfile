FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
# Normalize only source/build inputs, including files created with host umask 077.
RUN find app -type d -exec chmod 755 {} + \
    && find app -type f -exec chmod 644 {} + \
    && chmod 644 pyproject.toml
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir . && useradd --create-home appuser \
    && mkdir -p /var/lib/modbus-monitor/backups \
    && chown appuser:appuser /var/lib/modbus-monitor/backups \
    && chmod 700 /var/lib/modbus-monitor/backups
COPY alembic.ini ./
COPY alembic ./alembic
RUN find alembic -type d -exec chmod 755 {} + \
    && find alembic -type f -exec chmod 644 {} + \
    && chmod 644 alembic.ini
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
