# delete temp cert files we created (quiet if none exist)
shopt -s nullglob
for f in /tmp/cert*.pem /tmp/chain.pem /tmp/dev_cert*.pem /tmp/leaf.pem; do
  sudo shred -u "$f" 2>/dev/null || sudo rm -f "$f"
done
shopt -u nullglob

# optional: show what’s left (should be nothing)
ls -l /tmp/cert*.pem /tmp/chain.pem /tmp/dev_cert*.pem /tmp/leaf.pem 2>/dev/null || echo "temp cert files cleaned"
