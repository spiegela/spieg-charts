# Changelog

## 0.0.1

- reddit-meural 0.1.0 as a CronJob (every 6 hours): config from values (configmap), credentials as env from an existing secret (`credentialsSecret`),
  state (sqlite, Meural token, image cache) on `/data`.
