# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Install Python dependencies
RUN uv pip install --system -e .

# Copy application code
COPY src/ ./src/
COPY README.md LICENSE ./

# Create a non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV OBSIDIAN_HOST=host.docker.internal
ENV OBSIDIAN_PORT=27124
ENV OBSIDIAN_PROTOCOL=https

# Health check (optional - checks if python can import the module)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import mcp_obsidian" || exit 1

# Default command
CMD ["mcp-obsidian"]
