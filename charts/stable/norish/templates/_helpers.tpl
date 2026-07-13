{{- define "norish.masterKey" -}}
{{- $secretName := printf "%s-main" .Release.Name -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if .Values.config.masterKey -}}
{{- .Values.config.masterKey -}}
{{- else if and $existing (hasKey $existing.data "MASTER_KEY") -}}
{{- index $existing.data "MASTER_KEY" | b64dec -}}
{{- else -}}
{{- randBytes 32 -}}
{{- end -}}
{{- end -}}
