# headplane

[Headplane](https://headplane.net) is a web UI for Headscale. It manages
machines, routes, tags, users, auth keys, ACLs and DNS, and it's modeled on
Tailscale's admin console. This chart runs it on TrueCharts common and
configures it entirely through `HEADPLANE_*` environment variables, so it needs
no config file.

## Values

- `headplane.headscaleUrl` (required): how Headplane reaches Headscale's API,
  e.g. `http://headscale.<ns>.svc.cluster.local:8080`.
- `headplane.baseUrl` (required): the public URL, without `/admin`. The UI is
  served under `/admin`.
- `headplane.cookieSecret` (required): exactly 32 characters. It's stored in
  a chart-managed Secret.
- `persistence.headscaleconfig` + `headplane.headscaleConfigPath`: mount
  Headscale's `config.yaml` so DNS settings show up. Mounted read-only (the
  default), they're shown read-only, which keeps Git as the source of truth.
  Headplane can only apply config changes itself through Docker, so a writable
  mount isn't useful on Kubernetes.
- `persistence.data` (`/var/lib/headplane`): Headplane's own SQLite database
  (accounts and roles).

## Policy

Headplane's ACL editor only works when Headscale uses `policy.mode: database`.
With `policy.mode: file`, the ACL page is read-only, which suits GitOps.

## Signing in

Sign in with a Headscale API key:

```sh
kubectl -n <ns> exec deploy/headscale -- headscale apikeys create --expiration 90d
```

Headplane has no protection of its own before that sign-in page, so put an
authenticating proxy in front of it, such as Traefik forward-auth.

## Notes

- Health check: `/admin/healthz`. `/` returns 404, so redirect `/` to
  `/admin/` at the ingress.
- Headplane starts even when Headscale is unreachable, and keeps retrying.
- The container runs as 568:568 with a read-only root filesystem.
