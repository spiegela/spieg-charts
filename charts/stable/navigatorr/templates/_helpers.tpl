{{- define "navigatorr.authToken" -}}
{{- $secretName := printf "%s-main" .Release.Name -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if .Values.config.authToken -}}
{{- .Values.config.authToken -}}
{{- else if and $existing (hasKey $existing.data "MCP_STDIO_SERVE_TOKEN") -}}
{{- index $existing.data "MCP_STDIO_SERVE_TOKEN" | b64dec -}}
{{- else -}}
{{- randAlphaNum 64 -}}
{{- end -}}
{{- end -}}

{{- define "navigatorr.configYaml" -}}
{{- $enabledServices := dict -}}
{{- range $name, $service := .Values.config.services -}}
  {{- if $service.enabled -}}
    {{- $_ := set $enabledServices $name $service -}}
  {{- end -}}
{{- end -}}
max_response_size_kb: {{ .Values.config.maxResponseSizeKB }}
allow_destructive: {{ .Values.config.allowDestructive }}
{{- if $enabledServices }}
services:
  {{- range $name := keys $enabledServices | sortAlpha }}
    {{- $service := index $enabledServices $name }}
  {{ $name }}:
    url: {{ required (printf "config.services.%s.url is required when enabled" $name) $service.url | quote }}
    api_key: {{ required (printf "config.services.%s.apiKey is required when enabled" $name) $service.apiKey | quote }}
    {{- with $service.authMethod }}
    auth_method: {{ . | quote }}
    {{- end }}
    {{- with $service.authHeader }}
    auth_header: {{ . | quote }}
    {{- end }}
    {{- with $service.authPrefix }}
    auth_prefix: {{ . | quote }}
    {{- end }}
    {{- with $service.apiVersion }}
    api_version: {{ . | quote }}
    {{- end }}
    {{- with $service.openapiUrl }}
    openapi_url: {{ . | quote }}
    {{- end }}
  {{- end }}
{{- else }}
services: {}
{{- end }}
{{- with .Values.config.transmission }}
  {{- if .enabled }}
transmission:
  url: {{ required "config.transmission.url is required when enabled" .url | quote }}
  username: {{ .username | quote }}
  password: {{ .password | quote }}
  {{- end }}
{{- end }}
{{- with .Values.config.qbittorrent }}
  {{- if .enabled }}
qbittorrent:
  url: {{ required "config.qbittorrent.url is required when enabled" .url | quote }}
  username: {{ .username | quote }}
  password: {{ .password | quote }}
  {{- end }}
{{- end }}
{{- with .Values.config.sabnzbd }}
  {{- if .enabled }}
sabnzbd:
  url: {{ required "config.sabnzbd.url is required when enabled" .url | quote }}
  api_key: {{ required "config.sabnzbd.apiKey is required when enabled" .apiKey | quote }}
  url_base: {{ .urlBase | quote }}
  {{- end }}
{{- end }}
queue:
  path: {{ .Values.config.queuePath | quote }}
{{- end -}}
