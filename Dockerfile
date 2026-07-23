FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

USER 65532:65532
EXPOSE 8080

CMD ["uvicorn", "alpaca_connector.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
