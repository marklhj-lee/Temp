#!/usr/bin/env bash
set -euo pipefail

############################
# CONFIG — EDIT THESE
URL="https://your.internal.domain/health"   # full URL to test
HOST="your.internal.domain"                 # hostname (for DNS/SAN checks)
CA_BUNDLE="/etc/ssl/certs/corp-ca-bundle.pem"  # corp/enterprise CA chain (PEM). leave blank if unknown: ""
############################

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()  { printf "✅ %s\n" "$*"; }
warn(){ printf "⚠️  %s\n" "$*"; }
err() { printf "❌ %s\n" "$*" ; }

say "0) basic info"
echo "whoami: $(whoami)"
echo "python: $(command -v python || true)"
python -V || true
echo "pip:    $(command -v pip || true)"
echo "curl:   $(curl --version | head -n1)"
echo "openssl:$(openssl version)"
echo "URL:    $URL"
echo "HOST:   $HOST"
echo "CA_BUNDLE: ${CA_BUNDLE:-'(none)'}"

say "1) proxy environment"
: "${HTTP_PROXY:=}"; : "${HTTPS_PROXY:=}"; : "${NO_PROXY:=}"
echo "HTTP_PROXY=$HTTP_PROXY"
echo "HTTPS_PROXY=$HTTPS_PROXY"
echo "NO_PROXY=$NO_PROXY"
if [[ -n "${HTTPS_PROXY}${HTTP_PROXY}" ]]; then
  echo "Testing proxy reachability (HEAD to example.com):"
  if curl -sS -I https://example.com >/dev/null; then ok "proxy path OK (curl)"; else warn "proxy may be blocking or mis-set"; fi
else
  ok "no proxy configured in env (that’s fine if direct access works)"
fi

say "2) NO_PROXY sanity (should include your internal host/domain)"
if [[ -n "$NO_PROXY" ]] && echo "$NO_PROXY" | tr ',' '\n' | grep -xqF "$HOST"; then
  ok "NO_PROXY contains exact host"
elif [[ -n "$NO_PROXY" ]] && echo "$NO_PROXY" | tr ',' '\n' | grep -q "\.${HOST#*.}$"; then
  ok "NO_PROXY contains matching domain suffix"
else
  warn "NO_PROXY might not exclude $HOST — if you use a proxy, add: ,$HOST,.${HOST#*.}"
fi

say "3) DNS + connectivity"
echo "getent hosts:"
getent hosts "$HOST" || err "DNS lookup failed"
echo "ping (2x, may fail on blocked ICMP — ignore if so):"
ping -c2 -W1 "$HOST" || warn "ICMP blocked (not fatal)"
echo "curl -v (IPv4):"
curl -4 -sS -o /dev/null -w "HTTP %{http_code}\n" -v "$URL" || warn "curl -4 failed (note TLS lines above)"
echo "curl -v (IPv6):"
curl -6 -sS -o /dev/null -w "HTTP %{http_code}\n" -v "$URL" || warn "curl -6 failed (may be OK if no IPv6 route)"

say "4) TLS/cert chain (OpenSSL view)"
echo | openssl s_client -connect "${HOST}:443" -servername "$HOST" -showcerts >/tmp/s_client.txt 2>/dev/null || true
if grep -q "Verify return code: 0 (ok)" /tmp/s_client.txt; then
  ok "OpenSSL verification OK to $HOST"
else
  warn "OpenSSL verify not OK — likely missing corporate CA or hostname mismatch"
fi
echo "Subject of leaf cert:"
awk '/BEGIN CERTIFICATE/{flag=1;print>"/tmp/leaf.pem";next}/END CERTIFICATE/{print>>"/tmp/leaf.pem";flag=0}flag{print>>"/tmp/leaf.pem"}' </tmp/s_client.txt
openssl x509 -in /tmp/leaf.pem -noout -subject -issuer -ext subjectAltName 2>/dev/null || true

say "5) curl with/without custom CA"
if curl -sS -o /dev/null "$URL"; then
  ok "curl default trust OK"
else
  warn "curl default trust failed"
fi
if [[ -n "$CA_BUNDLE" && -f "$CA_BUNDLE" ]]; then
  if curl --cacert "$CA_BUNDLE" -sS -o /dev/null "$URL"; then
    ok "curl with CA_BUNDLE OK — CA file works"
  else
    warn "curl with CA_BUNDLE still failed — check chain/host"
  fi
else
  warn "no CA_BUNDLE provided — if Python fails with CERTIFICATE_VERIFY, you need your corp CA chain"
fi

say "6) python: where is certifi, and what’s the default CA?"
python - <<'PY'
import sys, ssl
print("Python:", sys.version)
try:
    import certifi
    print("certifi.where():", certifi.where())
except Exception as e:
    print("certifi not found:", e)
print("OpenSSL:", ssl.OPENSSL_VERSION)
PY

say "7) python requests test (default trust)"
python - <<PY || true
import requests, sys
url = "${URL}"
try:
    r = requests.get(url, timeout=10)
    print("requests default OK:", r.status_code)
except Exception as e:
    print("requests default FAIL:", repr(e))
    sys.exit(1)
PY

say "8) python requests test (with CA_BUNDLE if provided)"
if [[ -n "$CA_BUNDLE" && -f "$CA_BUNDLE" ]]; then
python - <<PY || true
import requests, sys
url = "${URL}"
try:
    r = requests.get(url, timeout=10, verify="${CA_BUNDLE}")
    print("requests verify=CA_BUNDLE OK:", r.status_code)
except Exception as e:
    print("requests verify=CA_BUNDLE FAIL:", repr(e))
    sys.exit(1)
PY
else
  warn "skip: CA_BUNDLE not set/file missing"
fi

say "9) python requests (insecure, diagnostic ONLY)"
python - <<'PY' || true
import requests, sys, urllib3
urllib3.disable_warnings()
url = """'"$URL"'"""
try:
    r = requests.get(url, timeout=10, verify=False)
    print("requests verify=False OK (diagnostic):", r.status_code)
except Exception as e:
    print("requests verify=False FAIL:", repr(e)); sys.exit(1)
PY
echo "If verify=False passes but default fails => CA/trust issue."

say "10) httpx tests (default & with CA; respects proxy env by default)"
python - <<PY || true
import httpx, sys, os
url = "${URL}"
print("trust_env:", httpx.Client()._transport._pool._proxy is not None if hasattr(httpx.Client()._transport, "_pool") else "n/a")
try:
    with httpx.Client(timeout=10) as c:
        r = c.get(url)
        print("httpx default OK:", r.status_code)
except Exception as e:
    print("httpx default FAIL:", repr(e))
    sys.exit(1)
PY

if [[ -n "$CA_BUNDLE" && -f "$CA_BUNDLE" ]]; then
python - <<PY || true
import httpx, sys
url = "${URL}"
try:
    with httpx.Client(timeout=10, verify="${CA_BUNDLE}") as c:
        r = c.get(url)
        print("httpx verify=CA_BUNDLE OK:", r.status_code)
except Exception as e:
    print("httpx verify=CA_BUNDLE FAIL:", repr(e)); sys.exit(1)
PY
fi

say "11) IPv4-forced Python request (helps catch IPv6 routing issues)"
python - <<'PY' || true
import socket, requests, sys, urllib3
urllib3.disable_warnings()
host = "'"$HOST"'"
url  = "'"$URL"'"
try:
    addr = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)[0][4][0]
    r = requests.get(f"https://{addr}" + url.split(host,1)[1], headers={"Host": host}, timeout=10, verify=False)
    print("IPv4 forced (verify=False) status:", r.status_code)
except Exception as e:
    print("IPv4 forced FAIL:", repr(e)); sys.exit(1)
PY

say "12) conclusions (common interpretations)"
echo "- If: curl OK, requests FAIL default, requests verify=CA_BUNDLE OK -> add corp CA via REQUESTS_CA_BUNDLE/SSL_CERT_FILE."
echo "- If: both requests/httpx fail, verify=False OK -> CA trust or hostname mismatch."
echo "- If: only via IPv4-forced works -> IPv6 DNS/route issue; adjust NO_PROXY or disable IPv6."
echo "- If: proxy needed for curl but Python fails -> set HTTPS_PROXY/HTTP_PROXY/NO_PROXY env before pytest."
