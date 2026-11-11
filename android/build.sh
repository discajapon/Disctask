#!/usr/bin/env bash
# Builds the signed release APK into android/dist/ and writes dist/latest.json (version, date, size, sha256).
# Needs node, JDK 17+, Android SDK ($ANDROID_HOME). The signing key lives OUTSIDE the repo:
#   ~/.config/disctask/signing/{disctask.keystore,env}  (created on first run, back it up: losing it means
#   installed apps can no longer be updated by new APKs).
set -euo pipefail
cd "$(dirname "$0")"
# Capacitor 7 compiles with JDK 21 (a JRE is not enough). Use a user-local Temurin 21 so the system JDK stays untouched.
J=~/.local/share/jdk-21
if [ ! -x $J/bin/javac ]; then
  mkdir -p $J && curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse" | tar -xz -C $J --strip-components=1
fi
export JAVA_HOME=$J PATH=$J/bin:$PATH
K=~/.config/disctask/signing
if [ ! -f $K/disctask.keystore ]; then
  mkdir -p $K && chmod 700 $K && umask 077
  PW=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
  keytool -genkeypair -keystore $K/disctask.keystore -alias disctask -keyalg RSA -keysize 4096 -validity 36500 \
    -storepass "$PW" -keypass "$PW" -dname "CN=Disctask, O=discajapon" >/dev/null
  echo "export DISCTASK_KEYSTORE_PASSWORD='$PW'" > $K/env
fi
. $K/env
export DISCTASK_KEYSTORE=$K/disctask.keystore
VER=$(node -p "require('./package.json').version")
CODE=$(git rev-list --count HEAD)
[ -d node_modules ] || npm ci --no-audit --no-fund
mkdir -p www dist && cp ../index.html ../bg.jpg ../icon.png www/   # same UI as the desktop app (the proprietary font is not bundled)
npx cap sync android >/dev/null
(cd android && ./gradlew --no-daemon -q assembleRelease -PappVersionName="$VER" -PappVersionCode="$CODE")
OUT=dist/disctask-$VER.apk
cp android/app/build/outputs/apk/release/app-release.apk "$OUT"
"$ANDROID_HOME"/build-tools/36.0.0/apksigner verify --verbose "$OUT" | head -3
python3 - "$OUT" "$VER" <<'PY'
import hashlib, json, os, sys, datetime
f, v = sys.argv[1:]
json.dump({'version': v, 'date': datetime.date.today().isoformat(), 'file': os.path.basename(f), 'size': os.path.getsize(f),
           'sha256': hashlib.sha256(open(f, 'rb').read()).hexdigest()}, open('dist/latest.json', 'w'), indent=1)
PY
cat dist/latest.json
