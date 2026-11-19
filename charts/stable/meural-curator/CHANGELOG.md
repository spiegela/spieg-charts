# Changelog

## 0.1.0

- Renamed from `reddit-meural` (app 0.2.0, image `spiegela/meural-curator`). Museums on by default (AIC, The Met),
  Reddit off by default (needs an approved OAuth app), gallery `Curated Art`, database `/data/meural-curator.sqlite3`
  (an existing `reddit-meural.sqlite3` there is adopted).

## 0.0.2

- reddit-meural 0.1.1: Reddit via OAuth (`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`; anonymous reads are blocked),
  Metron API token, `museums` sources (AIC, The Met, Cleveland, any Wikidata collection), per-source metadata templates
  (`config.metadata.sources`) with comic and museum defaults.

## 0.0.1

- reddit-meural 0.1.0 as a CronJob (every 6 hours): config from values (configmap), credentials as env from an existing secret (`credentialsSecret`),
  state (sqlite, Meural token, image cache) on `/data`.
