# Docker Deployment Guide

This guide explains how to run the MCP Obsidian server using Docker and Docker Compose.

## Overview

The MCP Obsidian server provides direct filesystem access to your Obsidian vault, enabling fast and efficient operations without requiring Obsidian to be running.

## Prerequisites

1. **Docker** and **Docker Compose** installed
2. An **Obsidian vault** directory accessible from your Docker host

## Quick Start

### 1. Configure Environment Variables

Copy the example environment file and set your vault path:

```bash
cp .env.example .env
```

Edit `.env` and set your `VAULT_PATH`:

```env
VAULT_PATH=./vault
```

Or use an absolute path:

```env
VAULT_PATH=/absolute/path/to/your/obsidian/vault
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
| `VAULT_PATH` | **Required** | Path to your Obsidian vault directory on the host |

### Vault Mounting

The vault is mounted read-only (`ro`) by default for safety. The container accesses the vault at `/vault` internally.

**For local development:**
```env
VAULT_PATH=./vault
```

**For absolute paths:**
```env
VAULT_PATH=/Users/yourname/Documents/ObsidianVault
```

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

### Container can't access vault

1. **Check vault path:**
   - Ensure `VAULT_PATH` in `.env` points to a valid directory
   - For relative paths, ensure they're relative to the docker-compose.yml location

2. **Check permissions:**
   - Ensure the vault directory is readable by the Docker user (UID 1000)
   - On Linux, you may need to adjust permissions:
     ```bash
     chmod -R +r /path/to/vault
     ```

3. **Verify mount:**
   - Check that the vault is mounted correctly:
     ```bash
     docker-compose exec mcp-obsidian ls -la /vault
     ```

### Container exits immediately

Check logs for errors:
```bash
docker-compose logs mcp-obsidian
```

Common issues:
- Missing or invalid `VAULT_PATH`
- Vault directory doesn't exist
- Permission denied accessing vault
- Python dependency issues

### Debugging

Run container in interactive mode:

```bash
docker-compose run --rm mcp-obsidian /bin/bash
```

Inside the container, check vault access:
```bash
ls -la /vault
cat /vault/some-note.md
```

## Advanced Usage

### Read-Write Access

If you need write access to the vault (for creating/editing files), remove the `:ro` flag:

Edit `docker-compose.yml`:
```yaml
volumes:
  - ${VAULT_PATH:-./vault}:/vault  # Remove :ro for read-write
```

**Warning:** Write access allows the container to modify your vault. Use with caution.

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

### Multiple Vaults

To work with multiple vaults, create multiple service instances:

```yaml
services:
  mcp-obsidian-personal:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: mcp-obsidian-personal
    environment:
      - VAULT_PATH=/vault
    volumes:
      - /path/to/personal/vault:/vault:ro

  mcp-obsidian-work:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: mcp-obsidian-work
    environment:
      - VAULT_PATH=/vault
    volumes:
      - /path/to/work/vault:/vault:ro
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
7. Enable read-only filesystem where possible
8. Run regular backups of your vault

## Security Notes

- The vault is mounted read-only by default for security
- Container runs as non-root user (UID 1000)
- No network exposure required (MCP uses stdio)
- Path traversal protection built into the server
- Consider running in a restricted Docker network

## Performance Tips

1. **Use SSD storage** for the vault for better I/O performance
2. **Limit vault size** - large vaults (>10GB) may have slower search times
3. **Exclude large binary files** from vault directory if possible
4. **Use fuzzy search sparingly** on large vaults with `search_content=true`

## Differences from REST API Version

This version uses **direct filesystem access** instead of the Obsidian REST API plugin:

**Advantages:**
- ✅ **Much faster** - no HTTP overhead
- ✅ **No Obsidian required** - works without Obsidian running
- ✅ **Simpler setup** - just point to vault directory
- ✅ **Better for Docker** - clean containerization

**Limitations:**
- ❌ **No real-time sync** - doesn't see changes made while running
- ❌ **No plugin integration** - can't use Dataview/Templater features
- ❌ **Basic periodic notes** - simplified implementation

## Migration from REST API Version

If migrating from the REST API version:

1. Remove old environment variables:
   - `OBSIDIAN_API_KEY`
   - `OBSIDIAN_HOST`
   - `OBSIDIAN_PORT`
   - `OBSIDIAN_PROTOCOL`

2. Add new environment variable:
   - `VAULT_PATH=/path/to/vault`

3. Rebuild the container:
   ```bash
   docker-compose down
   docker-compose build --no-cache
   docker-compose up -d
   ```

## Backup Recommendations

Since the server has read-only access by default, your vault is safe from accidental modifications. However, always maintain backups:

1. Use git for version control
2. Set up automated backups
3. Use cloud sync (Dropbox, iCloud, etc.)
4. Test your backups regularly
