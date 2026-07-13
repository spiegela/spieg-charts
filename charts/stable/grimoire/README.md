# Grimoire

This chart follows the upstream `hunter-read/grimoire` Docker image and compose layout for the TTRPG library manager.

```yaml
image:
  repository: hunterreadca/grimoire
  tag: latest
  pullPolicy: Always
```

The container listens on port `9481`, reads the library from `/library`, and stores its database, thumbnails, rendered page cache, users, and campaign uploads under `/data`.

## Required Storage

Grimoire can boot with an empty image-provided `/library`, but a useful local install should mount your RPG library read-only:

```yaml
persistence:
  library:
    enabled: true
    type: hostPath
    hostPath: /path/to/your/library
    mountPath: /library
    readOnly: true
  data:
    enabled: true
    mountPath: /data
```

The `data` persistence is enabled by default.

## Configuration

The chart generates `SECRET_KEY` when `config.secretKey` is empty and reuses the existing secret on upgrades.

Common values:

```yaml
config:
  workers: 2
  baseUrl: http://localhost:9481
  opdsEnabled: false
  logLevel: info
  valkeyUrl: ""
```

Set `config.baseUrl` to the public URL when using ingress or OPDS. Set `config.valkeyUrl` to a Redis-compatible URL if you run Valkey or Redis separately for the optional page cache.
