# Aurral

Aurral is a Lidarr companion for self-hosted music discovery. The chart follows the upstream container layout, exposing the web interface on port `3001` and mounting persistent storage at `/config` and shared Lidarr media at `/data`.

The configuration directory uses the Lidarr namespace by default:

```yaml
persistence:
  config:
    type: hostPath
    hostPath: /var/mnt/Pool1/apps/static/lidarr/aurral
```

Configure `persistence.data` with the same host media path mounted into Lidarr so both applications see identical paths.
