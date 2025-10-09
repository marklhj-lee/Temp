echo | openssl s_client -connect "${HOST}:443" -servername "$HOST" -showcerts 2>/dev/null \
| awk 'BEGIN{n=0}/BEGIN CERTIFICATE/{n++;f="/tmp/leaf.pem";exit}'; openssl x509 -in /tmp/leaf.pem -noout -ext subjectAltName

getent hosts "$HOST"

IP="1.1.1.1"   # the IP you think is correct
curl --resolve "${HOST}:443:${IP}" -sS -o /dev/null "https://${HOST}/health" && echo "works with correct IP"
