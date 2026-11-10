#!/bin/zsh
# Build 审片.app (unsigned, local only):  app/build.sh [--install]
#   -> app/build/审片.app ; --install also copies it to ~/Applications/审片.app
# The app runs the Python code of $SHENPIAN_REPO (default ~/Desktop/youtube-manager) with its venv.
set -e
HERE=${0:A:h}
REPO=${SHENPIAN_REPO:-$HOME/Desktop/youtube-manager}
PY=$REPO/venv/bin/python; [ -x "$PY" ] || PY=$HOME/Desktop/youtube-manager/venv/bin/python
APP="$HERE/build/审片.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 -o "$APP/Contents/MacOS/Shenpian" "$HERE/main.swift" "$HERE/Theme.swift" -framework AppKit -framework WebKit

# icon: 1024 png -> iconset -> icns
T=$(mktemp -d); "$PY" "$HERE/make_icon.py" "$T/icon.png"; mkdir "$T/AppIcon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$T/icon.png" --out "$T/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$T/icon.png" --out "$T/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$T/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"; rm -rf "$T"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>审片</string>
  <key>CFBundleDisplayName</key><string>审片</string>
  <key>CFBundleIdentifier</key><string>dev.yizhouyu.shenpian</string>
  <key>CFBundleExecutable</key><string>Shenpian</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>ShenpianRepo</key><string>$REPO</string>
</dict></plist>
EOF
echo "built $APP (repo: $REPO)"
if [ "$1" = "--install" ]; then
  [ -d "$HOME/Applications" ] || { echo "~/Applications does not exist; not installing"; exit 1; }
  rm -rf "$HOME/Applications/审片.app"; cp -R "$APP" "$HOME/Applications/审片.app"
  echo "installed ~/Applications/审片.app"
fi
