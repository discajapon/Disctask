#!/usr/bin/env bash
# Uploads the built APK + latest.json to https://discajapon.com/disctask/ (served from /var/lib/disctask/dl). ./publish.sh [host]
set -euo pipefail
HOST=${1:-discajapon.com}
cd "$(dirname "$0")"
ssh "$HOST" 'mkdir -p /var/lib/disctask/dl && chmod 755 /var/lib/disctask/dl'
rsync -a dist/*.apk ../bg.jpg "$HOST:/var/lib/disctask/dl/"
rsync -a dist/latest.json "$HOST:/var/lib/disctask/dl/latest.json"  # last: the page only advertises an APK that is already there
