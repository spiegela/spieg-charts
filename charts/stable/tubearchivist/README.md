# Tube Archivist

This chart runs `bbilly1/tubearchivist:latest` with `image.pullPolicy` set to `Always`.

Dependencies:

- Redis through the TrueCharts Redis subchart.
- Elasticsearch through an ECK `Elasticsearch` custom resource rendered by this chart.

The ECK resource creates a single-node Elasticsearch instance named `<release>-elasticsearch`. HTTP TLS is disabled so Tube Archivist can use `http://<release>-elasticsearch-es-http:9200`. The chart reads `ELASTIC_PASSWORD` from ECK's generated `<release>-elasticsearch-es-elastic-user` secret.

Persistent paths:

- `/youtube` for archived media
- `/cache` for Tube Archivist cache data
- Elasticsearch data through the ECK volume claim template

Set `config.taPassword` and `config.taHost` before deploy.

