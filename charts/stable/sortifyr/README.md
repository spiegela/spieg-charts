# Sortifyr

This chart runs `ghcr.io/topvennie/sortifyr:latest` with `image.pullPolicy` set to `Always`.

Dependencies:

- Postgres through TrueCharts CNPG support.
- Redis through the TrueCharts Redis subchart.
- S3-compatible object storage through external endpoint values.

Sortifyr names its S3-compatible provider `minio` internally. The chart keeps that upstream naming in env vars (`MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_USERNAME`, `MINIO_PASSWORD`, and `MINIO_SECURE`) while leaving the endpoint configurable for any S3-compatible service.

Set these before deploy:

- `config.auth.redirectUrl`
- `config.auth.spotify.callbackUrl`
- `config.auth.spotify.clientId`
- `config.auth.spotify.clientSecret`
- `config.minio.endpoint`
- `config.minio.bucket`
- `config.minio.username`
- `config.minio.password`

