# sm²

[sm²](https://github.com/nware-lab/sm2) provides a single, read-only view of
multiple Syncthing instances. It reads the normal Syncthing REST API and does
not create, change, or delete Syncthing configuration or files.

## Device configuration

Add consecutive device entries to a Kubernetes Secret, then reference that
existing Secret from the HelmRelease. The chart does not create or own the
Secret, so API keys are never committed to the GitOps repository.

```yaml
stringData:
  DEV_NAME_1: mikado
  DEV_URL_1: http://syncthing.syncthing.svc.cluster.local:8384
  DEV_API_KEY_1: replace-with-the-mikado-api-key
  DEV_NAME_2: current-laptop
  DEV_URL_2: http://100.x.y.z:8384
  DEV_API_KEY_2: replace-with-the-laptop-api-key
```

```yaml
workload:
  main:
    podSpec:
      containers:
        main:
          envFrom:
            - secretRef:
                name: sm2-devices
                expandObjectName: false
```

The API URLs must be reachable from the sm² pod. Use private addresses (for
example, Tailscale) for remote computers; do not expose Syncthing's GUI or API
to the public internet. `DISABLE_REPORTING` is enabled by default.
