FROM python:3.11-slim

WORKDIR /app

# Copy project metadata
COPY pyproject.toml README.md ./
COPY requirements.txt ./requirements.txt

# Copy source code
COPY src/ ./src/

# Copy MCP manifest directory so /.well-known/mcp/manifest.json is available
COPY .well-known ./.well-known

# (Optional) Only needed if you really use this at runtime; otherwise you can remove
COPY .github/core .github/core

# Install Python package & deps
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

# Railway sets PORT
ENV PORT=8000

# Start Alpaca MCP server with HTTP transport for ChatGPT MCP
CMD ["alpaca-mcp-server", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
