# Feishin

This chart defaults to the official `ghcr.io/jeffvli/feishin:latest` image.

## Server Types

The official Feishin image supports these locked server types through `config.server.type`:

- `jellyfin`
- `navidrome`
- `subsonic`

Set `config.server.name`, `config.server.type`, and `config.server.url`, then set `config.server.lock=true` to preconfigure the server for users.

## Plex

Official Feishin does not natively support Plex. The chart includes the Plex-capable fork in `Chart.yaml` sources and exposes `config.plex.enabled` as an operator note, but using Plex requires a Plex-capable Feishin image, such as a locally built image from `lux032/feishin`.

When using such an image, override:

```yaml
image:
  repository: your-registry/feishin-plex
  tag: latest
  pullPolicy: Always

config:
  server:
    name: plex
    type: plex
    url: https://plex.example.com
    lock: true
  plex:
    enabled: true
```
