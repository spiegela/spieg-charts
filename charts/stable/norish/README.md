# Norish

This chart follows the upstream `norish-recipes/norish` Docker setup. The app is spelled `Norish` upstream and published as:

```yaml
image:
  repository: norishapp/norish
  tag: latest
```

Norish listens on port `3000`, stores uploads in `/app/uploads`, requires Postgres, requires Redis for real-time events, and uses a headless Chrome process for recipe scraping.

## Dependencies

The chart enables:

- CNPG through the common chart for `DATABASE_URL`
- TrueCharts Redis for `REDIS_URL`
- A `zenika/alpine-chrome` sidecar on remote-debugging port `3003`

The Chrome sidecar uses `3003` instead of upstream's `3000` compose example because the Norish app already listens on `3000` in the same Kubernetes pod.

## Configuration

`MASTER_KEY` is generated when `config.masterKey` is empty and reused from the existing secret on upgrades. Keep it stable; changing it can invalidate encrypted data.

Common local overrides:

```yaml
config:
  authUrl: https://norish.example.com
  trustedOrigins: https://norish.example.com
  passwordAuthEnabled: true
```

Optional OIDC, GitHub, and Google OAuth settings are exposed under `config.oidc`, `config.github`, and `config.google`.
