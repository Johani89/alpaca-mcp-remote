FROM python:3.11-slim

WORKDIR /app

# Copy project metadata
COPY pyproject.toml README.md ./
COPY requirements.txt ./requirements.txt

# Copy source code
COPY src/ ./src/

# Copy MCP manifest (THIS IS WHAT WAS MISSING)
COPY .well-known ./.well-known

# Install package & dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

ENV PORT=8000

# Start the MCP server
CMD ["alpaca-mcp-server", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
