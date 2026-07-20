# Ignis

This chart packages the upstream `nobbe/ignis` image. Ignis listens on port
`8080` and persists three distinct paths:

- `/vaults` holds the Obsidian vaults. Each immediate subdirectory is a vault.
- `/app/data` holds Ignis state such as plugin management and sync settings.
- `/app/obsidian-app` caches the Obsidian application downloaded during first startup.

The first start downloads and extracts the configured Obsidian version, and
then installs the Obsidian Headless CLI. The startup probe allows 15 minutes
for that one-time work before Kubernetes declares the container unhealthy.

## Security and ownership

Ignis has no built-in authentication and serves plain HTTP. Put it behind an
authenticated TLS-enabled ingress or proxy before exposing it beyond a trusted
network. HTTPS is also functionally required for browser crypto and clipboard
features at non-localhost origins.

The image starts as root to create the configured `PUID` and `PGID` and chown
the three persisted paths, then runs the server as that user. The chart keeps
this upstream behavior and defaults both values to `1000`:

```yaml
securityContext:
  container:
    PUID: 1000
  pod:
    fsGroup: 1000
```

For NFS with `root_squash`, make the mounted storage writable by the chosen
UID/GID first. Ignis continues after an unsuccessful `chown`, but it can only
work when that user already has read/write access.

## Offline first start

For a restricted network, mount an Obsidian `.deb`, `.asar.gz`, or `.asar`
file at `/packages/obsidian.deb` and point `config.obsidianPackage` to it.
For example, add a persistence entry backed by an existing PVC:

```yaml
config:
  obsidianPackage: /packages/obsidian.deb

persistence:
  obsidian-package:
    enabled: true
    existingClaim: obsidian-package
    mountPath: /packages
    readOnly: true
```

`config.obsidianVersion` should match the supplied package whenever possible.
