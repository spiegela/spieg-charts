# Spotizerr

This chart runs `cooldockerizer93/spotizerr:latest` and sets `image.pullPolicy` to `Always`.

The upstream compose file includes Redis. This chart uses the TrueCharts Redis subchart and wires `REDIS_URL` and `REDIS_BACKEND` from the generated `rediscreds` secret.

Persistent paths:

- `/app/data` for app data and credentials
- `/app/downloads` for downloaded media
- `/app/logs` for logs
- `/app/cache/.cache` for cache data

