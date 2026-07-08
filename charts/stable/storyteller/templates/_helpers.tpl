{{- define "storyteller.secretKey" -}}
{{- $secretName := printf "%s-main" .Release.Name -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if .Values.config.secretKey -}}
{{- .Values.config.secretKey -}}
{{- else if and $existing (hasKey $existing.data "secret_key") -}}
{{- index $existing.data "secret_key" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
