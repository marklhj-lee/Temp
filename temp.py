# validate it’s a cert in PEM
openssl x509 -in /tmp/cert02.pem -noout -subject -issuer -text | grep -A1 "Basic Constraints"

# install it
sudo install -d -m 0755 /usr/local/share/ca-certificates
sudo cp /tmp/cert02.pem /usr/local/share/ca-certificates/corp-root.crt
sudo update-ca-certificates    # should report "1 added"
