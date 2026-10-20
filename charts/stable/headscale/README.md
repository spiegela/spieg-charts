# headscale

[Headscale](https://headscale.net) is a self-hosted implementation of the
Tailscale control server. This chart runs it on TrueCharts common with the
embedded DERP relay and STUN server enabled.

## Values

- `headscale.config` is rendered to `/etc/headscale/config.yaml`.
  `headscale.config.server_url` is required: it must be the public HTTPS URL
  that clients use, normally the ingress hostname. Reference:
  [config-example.yaml](https://github.com/juanfont/headscale/blob/v0.29.5/config-example.yaml).
- `headscale.policy` is rendered to `/etc/headscale/policy.hujson`. By default
  every node can reach every other node. Reference:
  [policy docs](https://github.com/juanfont/headscale/blob/v0.29.5/docs/ref/policy.md).
- `service.stun` is the UDP STUN listener for the embedded DERP region. Keep
  `service.stun.ports.stun.port` equal to the port in
  `headscale.config.derp.server.stun_listen_addr`. When it's a LoadBalancer,
  set `externalTrafficPolicy: Local`: STUN has to see each client's real
  source address.
- `persistence.data` (`/var/lib/headscale`) holds the SQLite database and the
  noise and DERP private keys. Back it up: if it's lost, every device has to
  register again.

## Operating

Exposing the main port: put it behind an ingress at `server_url`. The
ingress has to support HTTP Upgrade.

Managing the server: use the bundled CLI over the unix socket.

```sh
kubectl -n <ns> exec deploy/<release> -- headscale users create <name>
kubectl -n <ns> exec deploy/<release> -- headscale preauthkeys create --tags tag:router --expiration 24h
kubectl -n <ns> exec deploy/<release> -- headscale nodes list
```

## Notes

- The ConfigMap data is rendered as single-line JSON, which is valid YAML.
  TrueCharts common runs `tpl` on ConfigMap data after serializing it to YAML,
  and that would fold multi-line template output onto one line.
- The container runs as 568:568 with a read-only root filesystem. Every port
  is above 1024.
