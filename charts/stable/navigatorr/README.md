# Navigatorr

This TrueCharts-style chart runs [Navigatorr](https://github.com/JakeNesler/navigatorr) behind the authenticated Streamable HTTP reverse gateway provided by [mcp-stdio](https://github.com/shigechika/mcp-stdio). Navigatorr supports Sonarr, Radarr, Lidarr, Readarr, and the other services represented in `config.services`.

## Authentication and exposure

Bearer authentication is always enabled. Set `config.authToken` to a long random value, or leave it empty and Helm will generate one. On an in-cluster Helm upgrade, the generated value is read from the existing Secret and retained. GitOps users should set the token explicitly because offline template rendering cannot look up the live Secret.

Retrieve an automatically generated token after installation:

```sh
kubectl -n media get secret navigatorr-main \
  -o jsonpath='{.data.MCP_STDIO_SERVE_TOKEN}' | base64 -d
```

The public MCP URL is `https://navigatorr.example.com/mcp`, and clients send:

```text
Authorization: Bearer <token>
```

The ingress must route `/`, not only `/mcp`, so the RFC 9728 protected-resource metadata remains reachable. The chart refuses to render an enabled ingress unless TLS is configured through an explicit TLS entry, the cert-manager integration, or the TLS-enabled Traefik integration.

## Minimal values

```yaml
config:
  authToken: "replace-with-a-long-random-token"
  services:
    sonarr:
      enabled: true
      url: http://sonarr.media.svc.cluster.local:8989
      apiKey: replace-me
    radarr:
      enabled: true
      url: http://radarr.media.svc.cluster.local:7878
      apiKey: replace-me
    lidarr:
      enabled: true
      url: http://lidarr.media.svc.cluster.local:8686
      apiKey: replace-me
    readarr:
      enabled: true
      url: http://readarr.media.svc.cluster.local:8787
      apiKey: replace-me

ingress:
  main:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/proxy-buffering: "off"
      nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
      nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    hosts:
      - host: navigatorr.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: navigatorr-tls
        hosts:
          - navigatorr.example.com
```

Navigatorr downloads service OpenAPI documents at startup, so the pod needs outbound HTTPS access to `raw.githubusercontent.com` and network access to each configured service.

## Operational notes

- Destructive calls default to disabled through `config.allowDestructive`.
- The request-queue HTTP listener is deliberately not exposed.
- Navigatorr locks its queue file for the life of each process. The gateway is therefore fixed at one backend session and the workload at one replica.
- Changing the generated config Secret requires a pod restart; a Helm upgrade performs that rollout.
- Shipwright in `spieg-clusters` builds and publishes `docker.io/spiegela/navigatorr-mcp:1.0.0` from `images/navigatorr/Dockerfile`.
