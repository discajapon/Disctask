#!/usr/bin/env bash
# Idempotent deploy to the VPS: ./deploy/deploy.sh [host]   (ssh as root, key auth)
# First run also creates the service user, random tokens (/etc/disctask/env), systemd units and the nginx route.
# Tokens are never printed: read them on the VPS with `cat /etc/disctask/env`.
set -euo pipefail
HOST=${1:-discajapon.com}
cd "$(dirname "$0")/.."
ssh "$HOST" 'id disctask >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin disctask
mkdir -p /opt/disctask/app /etc/disctask'
rsync -a --delete --exclude tests --exclude __pycache__ server/ "$HOST:/opt/disctask/app/"
rsync -a deploy/disctask.service deploy/disctask-backup.service deploy/disctask-backup.timer "$HOST:/etc/systemd/system/"
rsync -a deploy/nginx-disctask.conf "$HOST:/etc/nginx/snippets/disctask.conf"
rsync -a deploy/nginx-disctask-limit.conf "$HOST:/etc/nginx/conf.d/disctask-limit.conf"
ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
[ -x /opt/disctask/venv/bin/pip ] || python3 -m venv /opt/disctask/venv
/opt/disctask/venv/bin/pip install -q -r /opt/disctask/app/requirements.txt
if [ ! -f /etc/disctask/env ]; then
  umask 077
  printf 'DISCTASK_DEVICE_TOKEN=%s\nDISCTASK_MCP_TOKEN=%s\nDISCTASK_TZ=America/Guayaquil\n' \
    "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > /etc/disctask/env
fi
chmod 600 /etc/disctask/env
systemctl daemon-reload
systemctl enable --now disctask-backup.timer >/dev/null 2>&1
systemctl enable disctask >/dev/null 2>&1
systemctl restart disctask
S=/etc/nginx/sites-enabled/discajapon.com
if ! grep -q 'snippets/disctask.conf' $S; then
  mkdir -p /root/nginx-backup && B=/root/nginx-backup/discajapon.com.$(date +%s) && cp $S $B  # outside sites-enabled: nginx would load it
  trap 'cp $B $S; echo "nginx config invalid, restored $S" >&2' ERR
  sed -i '0,/^    location \/api\/ {/s//    include snippets\/disctask.conf;\n\n    location \/api\/ {/' $S
  nginx -t
  trap - ERR
fi
nginx -t && systemctl reload nginx
sleep 1; systemctl is-active disctask
REMOTE
curl -fsS "https://$HOST/disctask/api/health" && echo
