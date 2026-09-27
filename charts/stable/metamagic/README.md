# MetaMagic

MetaMagic provides a web UI for managing Plex metadata, collections, artwork,
overlays, and related automations without hand-editing Kometa YAML.

The web interface is exposed on port `3800`. Persistent storage mounted at
`/config` contains the SQLite database, encryption key, saved credentials, and
original artwork, so it must be included in backups.

The upstream entrypoint starts as root to create and chown the configured
`PUID`/`PGID`, then runs the application processes as that user.
