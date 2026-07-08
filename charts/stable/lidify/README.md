# Lidify

Lidify supports multiple discovery modes through the `mode` environment variable. This chart exposes it as `config.mode`.

## LastFM Mode

`LastFM` is the recommended default. Upstream notes that Spotify API changes in November 2024 prevent the old Spotify integration from working normally, so new deployments should generally use Last.fm.

```yaml
config:
  mode: LastFM
  lastFm:
    apiKey: ""
    apiSecret: ""
```

## Spotify Mode

`Spotify` remains exposed because the application still documents the setting, but expect it to be limited or broken unless upstream changes its integration.

```yaml
config:
  mode: Spotify
  spotify:
    clientId: ""
    clientSecret: ""
```

## Shared Lidarr Settings

Both modes use the Lidarr settings:

```yaml
config:
  lidarr:
    address: http://lidarr:8686
    apiKey: ""
  rootFolderPath: /data/media/music/
```
