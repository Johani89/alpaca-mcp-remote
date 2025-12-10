FROM python:3.11-slim

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY .github/core .github/core

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

#Railway sets PORT env variable so we expose it
ENV PORT=8000

# Start Alpaca MCP server on the correct host/port
CMD ["alpaca-mcp-server", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
