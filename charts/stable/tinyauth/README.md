# Tinyauth

This chart packages the upstream `ghcr.io/tinyauthapp/tinyauth` image as a
Traefik forward-auth login server. It listens on port `3000` and keeps its
SQLite session store in `/data`. Persist `/data` so restarts don't log users
out.

## Configuration

```yaml
config:
  appUrl: https://auth.example.com   # cookie is issued for .example.com
  sessionExpiry: 2592000             # 30-day sliding session
  credentialsSecret: tinyauth-credentials  # Secret with a `credentials` key
  trustedProxies: 10.42.0.0/16       # Traefik pod CIDR
```

The `credentials` key holds one plain-text `username:password` entry per line.
On every pod start, the `hash-users` init container bcrypt-hashes them into an
in-memory users file for Tinyauth, so a rebuilt cluster needs nothing beyond
the Secret. Restart the pod after changing it. The init container skips
entries whose password is `REPLACE_ME`, rejects passwords under 12
characters, and fails if no usable entry remains, so Tinyauth never starts
with a placeholder login. Keep the Secret encrypted (for example with SOPS).

Browsers get redirected to the login page and receive a session cookie.
Non-browser clients get `401` and can send `Authorization: Basic` credentials
on each request instead. Accounts with TOTP can't use Basic auth.

## Protecting an app

Point a Traefik `forwardAuth` middleware in the app's namespace at the
service:

```yaml
ingressMiddlewares:
  traefik:
    tinyauth:
      enabled: true
      type: forward-auth
      data:
        address: http://tinyauth.tinyauth.svc.cluster.local:3000/api/auth/traefik
        trustForwardHeader: false
        authResponseHeaders: [Remote-User, Remote-Name, Remote-Email]
ingress:
  main:
    integrations:
      traefik:
        enabled: true
        middlewares:
          - name: tinyauth
```

The app's hostname must be under the parent domain of `config.appUrl`.
