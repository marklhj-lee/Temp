openssl s_client -connect "${HOST}:443" -servername "${HOST}" -showcerts </dev/null 2>/dev/null \
| awk '
/-----BEGIN CERTIFICATE-----/ {i++; fn=sprintf("/tmp/cert%02d.pem", i)}
fn {print > fn}
/-----END CERTIFICATE-----/   {fn=""}
END {printf("wrote %d certs\n", i) > "/dev/stderr"}'


ls -l /tmp/cert*.pem


leaf=""
for f in /tmp/cert*.pem; do
  if openssl x509 -in "$f" -noout -text 2>/dev/null | grep -q "CA:FALSE"; then leaf="$f"; break; fi
done
echo "Leaf cert: ${leaf:-'(not found)'}"
[ -n "$leaf" ] && openssl x509 -in "$leaf" -noout -subject -issuer -ext subjectAltName


for f in /tmp/cert*.pem; do
  echo "== $f =="; openssl x509 -in "$f" -noout -text 2>/dev/null | grep -A1 "Basic Constraints"
done


sudo install -d -m 0755 /usr/local/share/ca-certificates
sudo bash -c 'cat /tmp/cert02.pem /tmp/cert03.pem > /usr/local/share/ca-certificates/corp-chain.crt'  # adjust files as needed
sudo update-ca-certificates


curl -v "https://${HOST}/health" -o /dev/null

# make Python use the same trust
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
python - <<PY
import requests; print(requests.get("https://${HOST}/health", timeout=10).status_code)
PY
