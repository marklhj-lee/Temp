export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
python - <<PY
import requests; print(requests.get("https://${HOST}/health", timeout=10).status_code)
PY