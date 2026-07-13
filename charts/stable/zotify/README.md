# Zotify

This chart packages Zotify as a TrueCharts CronJob workload.

The upstream project documents building a local Docker image, but does not publish an official image. The chart defaults to the community `bussnet/zotify:latest` image and sets `image.pullPolicy` to `Always`. Override `image.repository` when a preferred image or future Shipwright-built image is available.

The CronJob is suspended by default. Set `workload.main.suspend=false` and configure at least one target:

- `config.urls`
- `config.liked=true`
- `config.playlists=true`
- `config.followed=true`

Persistent paths:

- `/config` for Zotify config and archive files
- `/downloads/music` for music output
- `/downloads/podcasts` for podcast output

You can provide an existing `credentials.json` through `config.credentialsJson`, which mounts at `/config/credentials.json`.

