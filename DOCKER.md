# Docker Deployment Guide

This guide explains how to run the MCP Obsidian server using Docker and Docker Compose.

## Prerequisites

1. **Docker** and **Docker Compose** installed
2. **Obsidian** with the **Local REST API** plugin installed and configured
3. An **API key** from the Obsidian Local REST API plugin

## Quick Start

### 1. Configure Environment Variables

Copy the example environment file and fill in your Obsidian API key:

```bash
cp .env.example .env
```

Edit `.env` and set your `OBSIDIAN_API_KEY`:

```env
OBSIDIAN_API_KEY=your-api-key-here
```

### 2. Build and Run

```bash
docker-compose up --build
```

Or run in detached mode:

```bash
docker-compose up -d --build
```

### 3. View Logs

```bash
docker-compose logs -f mcp-obsidian
```

### 4. Stop the Service

```bash
docker-compose down
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSIDIAN_API_KEY` | **Required** | API key from Obsidian Local REST API plugin |
| `OBSIDIAN_HOST` | `host.docker.internal` | Host where Obsidian is running |
| `OBSIDIAN_PORT` | `27124` | Port for Obsidian REST API |
| `OBSIDIAN_PROTOCOL` | `https` | Protocol (http or https) |

### Network Modes

The docker-compose file uses `network_mode: host` by default, which allows the container to access services running on the host (like Obsidian).

**For Docker Desktop (Mac/Windows):**
- Use `OBSIDIAN_HOST=host.docker.internal`

**For Linux:**
- Keep `network_mode: host` OR
- Use `OBSIDIAN_HOST=172.17.0.1` (Docker bridge IP)

**For Remote Obsidian:**
- Set `OBSIDIAN_HOST` to the IP address of the machine running Obsidian

## Vault Mounting

The `./vault` directory is mounted to `/vault` inside the container (read-only). This is optional and can be used if:
- You want the container to have read access to vault files
- You're running additional services that need vault access
- You want to back up or process vault files

**Note:** The MCP server accesses vault files via the Obsidian REST API, not directly from the filesystem.

## Building the Image

### Build only:

```bash
docker-compose build
```

### Build with no cache:

```bash
docker-compose build --no-cache
```

### Tag and push to registry:

```bash
docker build -t your-registry/mcp-obsidian:latest .
docker push your-registry/mcp-obsidian:latest
```

## Troubleshooting

### Container can't connect to Obsidian

1. **Check Obsidian REST API is running:**
   - Open Obsidian
   - Go to Settings → Community Plugins → Local REST API
   - Ensure it's enabled and running

2. **Verify the API key:**
   - Check that `OBSIDIAN_API_KEY` in `.env` matches the key in Obsidian

3. **Network connectivity:**
   - Test connection from container:
     ```bash
     docker-compose exec mcp-obsidian curl -k https://host.docker.internal:27124/
     ```

4. **Check host firewall:**
   - Ensure port 27124 is not blocked by your firewall

### Container exits immediately

Check logs for errors:
```bash
docker-compose logs mcp-obsidian
```

Common issues:
- Missing `OBSIDIAN_API_KEY`
- Invalid environment variables
- Python dependency issues

### Debugging

Run container in interactive mode:

```bash
docker-compose run --rm mcp-obsidian /bin/bash
```

## Advanced Usage

### Custom Command

Override the default command in docker-compose.yml:

```yaml
services:
  mcp-obsidian:
    command: python -m mcp_obsidian.server
```

### Resource Limits

Add resource constraints:

```yaml
services:
  mcp-obsidian:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          memory: 256M
```

### Using Bridge Network

If you need custom networking:

```yaml
services:
  mcp-obsidian:
    # Remove: network_mode: host
    networks:
      - mcp-network
    extra_hosts:
      - "host.docker.internal:host-gateway"

networks:
  mcp-network:
    driver: bridge
```

## Health Checks

The container includes a health check that verifies Python can import the module:

```bash
docker-compose ps
```

Look for "(healthy)" status.

## Production Deployment

For production:

1. Use secrets management instead of `.env` files
2. Set up proper logging aggregation
3. Configure restart policies
4. Use specific version tags instead of `latest`
5. Set up monitoring and alerting
6. Consider using orchestration (Kubernetes, Docker Swarm)

## Security Notes

- The `.env` file contains sensitive API keys - never commit it to version control
- The vault is mounted read-only for security
- SSL verification for Obsidian API is handled by the plugin
- Container runs as non-root user (UID 1000)
