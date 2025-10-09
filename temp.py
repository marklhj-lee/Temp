HOST="api.dev.mycorp.local"

# Dump the chain to individual files: /tmp/cert1.pem, cert2.pem, ...
openssl s_client -connect "${HOST}:443" -servername "${HOST}" -showcerts </dev/null 2>/dev/null \
| awk '/-----BEGIN CERTIFICATE-----/{i++;f=sprintf("/tmp/cert%d.pem",i)} f{print>$f} /-----END CERTIFICATE-----/{f=""} END{print "wrote",i,"certs" > "/dev/stderr"}'

# Find the leaf (CA:FALSE) and show SANs
leaf=""
for f in /tmp/cert*.pem; do
  if openssl x509 -in "$f" -noout -text 2>/dev/null | grep -q "CA:FALSE"; then leaf="$f"; break; fi
done
[ -n "$leaf" ] && openssl x509 -in "$leaf" -noout -subject -issuer -ext subjectAltName








# Identify which certs are CA=TRUE (those are the ones you trust)
for f in /tmp/cert*.pem; do
  echo "== $f =="; openssl x509 -in "$f" -noout -text 2>/dev/null | grep -A1 "Basic Constraints"
done

# Build a chain file from the CA=TRUE certs (adjust which files as needed)
sudo install -d -m 0755 /usr/local/share/ca-certificates
sudo bash -c 'cat /tmp/cert2.pem /tmp/cert3.pem > /usr/local/share/ca-certificates/corp-chain.crt'  # pick your CA files
sudo update-ca-certificates   # should report "1 added"

# Re-test
curl -v "https://${HOST}/health" -o /dev/null
