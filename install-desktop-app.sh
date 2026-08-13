#!/bin/bash
# Double-clickable macOS app launcher — installs JARVIS.app to Desktop
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Desktop/JARVIS.app"
ICON="$DIR/assets/jarvis-icon.png"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>JARVIS</string>
  <key>CFBundleDisplayName</key><string>J.A.R.V.I.S.</string>
  <key>CFBundleIdentifier</key><string>com.stark.jarvis</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>jarvis</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>JARVIS needs microphone access for voice commands.</string>
  <key>NSSpeechRecognitionUsageDescription</key>
  <string>JARVIS uses speech recognition to understand your commands.</string>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/jarvis" <<EOF
#!/bin/bash
cd "$DIR"
exec "$DIR/start.sh"
EOF
chmod +x "$APP/Contents/MacOS/jarvis"

if [ -f "$ICON" ]; then
  cp "$ICON" "$APP/Contents/Resources/AppIcon.png"
fi

echo "✅ JARVIS.app oluşturuldu: $APP"
echo "   Masaüstünden çift tıklayarak açabilirsiniz."
