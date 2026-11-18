# go2rtc

[go2rtc](https://github.com/AlexxIT/go2rtc) camera streaming server, packaged on the TrueCharts common library
(no TrueCharts chart exists). Built for Home Assistant's WebRTC Camera integration (AlexxIT/WebRTC): HA proxies the
signalling over its authenticated websocket; media flows browser <-> go2rtc on the `webrtc` LoadBalancer (8555
tcp/udp). The API/WebUI (1984) stays ClusterIP: it has no auth and shows sources that carry cloud tokens.

Values: `go2rtc.candidate` (LAN `ip:8555`, required), `go2rtc.streams` (name -> source; empty ones skipped),
`persistence.hass` (HA config dir, read-only, for the WebUI's Roborock tab to import the core integration's login).

Roborock cameras (S6/S7 MaxV, Qrevo MaxV): `kubectl -n home-assistant port-forward svc/go2rtc 1984`, open
http://localhost:1984 > Add > Roborock, copy the `roborock://...` source, append the app's pattern password as digits
(grid 123/456/789), and set it as a stream.
