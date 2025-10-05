{{- define "secret-key" -}}
{{- $secretKey := randAlphaNum 20 }}
{{- if .Release.IsUpgrade }}
{{- $secretKey := print .Release.Name "-main"}}
{{- $secretKey = (lookup "v1" "Secret" .Release.Namespace $secretKey).data.secretKey }}
{{- end }}
{{- $secretKey }}
{{- end }}