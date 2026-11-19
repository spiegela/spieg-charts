# meural-curator

[meural-curator](https://github.com/spiegela/meural-curator) (formerly reddit-meural) as a Kubernetes CronJob on the
TrueCharts common library: pulls public-domain museum art (AIC, The Met, Cleveland, any Wikidata collection), comic
covers (Metron / ComicVine) and, with an approved Reddit app, subreddit posts; uploads new ones to
a Meural cloud gallery and syncs it to the frame. A SQLite database on `/data` keeps it from uploading duplicates.

Values:
- `workload.main.schedule` (cron, default every 6 hours at :17), `workload.main.suspend`.
- `config`: the tool's `config.yaml` (sources, filters, gallery, device). Paths point into `/data`. Credential
  fields stay `${VAR}` placeholders: the tool expands them from the environment.
- `credentialsSecret`: an existing Secret loaded as env: `MEURAL_USERNAME`, `MEURAL_PASSWORD` (required),
  `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (Reddit OAuth app), `METRON_API_TOKEN`, `COMICVINE_API_KEY`, `REDDIT_USERNAME` (user agent).
- `persistence.data`: where state lives (set a hostPath / PVC; keep it across upgrades or everything re-uploads).

Run once now: `kubectl -n <ns> create job --from=cronjob/<release> meural-curator-manual`.
