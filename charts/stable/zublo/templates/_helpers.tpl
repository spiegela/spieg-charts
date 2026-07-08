{{- define "zublo.pbEncryptionKey" -}}
{{- $secretName := printf "%s-main" .Release.Name -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if .Values.config.pbEncryptionKey -}}
{{- .Values.config.pbEncryptionKey -}}
{{- else if and $existing (hasKey $existing.data "PB_ENCRYPTION_KEY") -}}
{{- index $existing.data "PB_ENCRYPTION_KEY" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
