{{- define "grimoire.secretKey" -}}
{{- $secretName := printf "%s-main" .Release.Name -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if .Values.config.secretKey -}}
{{- .Values.config.secretKey -}}
{{- else if and $existing (hasKey $existing.data "SECRET_KEY") -}}
{{- index $existing.data "SECRET_KEY" | b64dec -}}
{{- else -}}
{{- randAlphaNum 64 -}}
{{- end -}}
{{- end -}}
