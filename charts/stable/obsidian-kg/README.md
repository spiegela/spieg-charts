# obsidian-kg

TrueCharts-style chart for the read-only Obsidian knowledge-graph MCP server
built from [`images/obsidian-kg`](../../../images/obsidian-kg). Agents get
graph-aware tools (`kg_overview`, `kg_search`, `kg_read`, `kg_neighbors`,
`kg_path`, `kg_similar`, `kg_list`, `kg_tags`) over streamable HTTP at `/mcp`.

The server has **no authentication**. Put the ingress behind an
authenticating middleware, such as Tinyauth forward-auth.

## Example (hostPath vault behind Tinyauth)

```yaml
persistence:
  vault:
    type: hostPath
    hostPath: /mnt/pool/Obsidian/My Vault
    readOnly: true
ingressMiddlewares:
  traefik:
    tinyauth:
      enabled: true
      type: forward-auth
      data:
        address: http://tinyauth.tinyauth.svc.cluster.local:3000/api/auth/traefik
        trustForwardHeader: false
ingress:
  main:
    enabled: true
    hosts:
      - host: kg.example.com
    integrations:
      certManager:
        enabled: true
        certificateIssuer: letsencrypt
      traefik:
        enabled: true
        middlewares:
          - name: tinyauth
```

Clients then send `Authorization: Basic base64(<user>:<token>)` to
`https://kg.example.com/mcp`.

## Values

| Key | Default | |
|---|---|---|
| `config.exclude` | `Private` | comma-separated folders hidden from agents |
| `config.refreshSeconds` | `60` | vault rescan interval |
| `config.threads` | `2` | ONNX threads for embedding |
| `persistence.vault` | pvc, read-only | the vault root |
| `persistence.cache` | emptyDir | locally computed embeddings |
