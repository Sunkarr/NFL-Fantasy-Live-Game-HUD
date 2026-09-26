#!/bin/bash
set -e

# ==============================================================================
# NFL Fantasy Live Game HUD — DMG Installer Packaging Script
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

APP_NAME="NFL Fantasy HUD"
DMG_NAME="NFL-Fantasy-HUD.dmg"
DMG_TEMP_DIR="dmg_input"

# 1. Terminate any running instances of the app or backend before packaging
echo "🔍 Checking for running instances of ${APP_NAME}..."
pkill -f "${APP_NAME}" 2>/dev/null || true
pkill -f "NFL-Fantasy-Live-Game-HUD/main.py" 2>/dev/null || true
sleep 1

# 2. Unmount any lingering mounted volumes of this DMG
echo "🔍 Checking for mounted volumes of ${APP_NAME}..."
hdiutil info | grep -E "/Volumes/${APP_NAME}" | awk '{print $1}' | while read -r dev; do
    echo "Unmounting existing volume: $dev"
    hdiutil detach "$dev" -force 2>/dev/null || true
done

# 3. Read current version from version.txt
VERSION_FILE="${DIR}/version.txt"
if [ -f "$VERSION_FILE" ]; then
    VERSION_CONTENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')
else
    VERSION_CONTENT="1.0.0"
fi

IFS='.' read -r MAJOR MIDDLE MINOR <<< "$VERSION_CONTENT"
MAJOR=${MAJOR:-1}
MIDDLE=${MIDDLE:-0}
MINOR=${MINOR:-0}
CURRENT_VERSION="${MAJOR}.${MIDDLE}.${MINOR}"

echo "=== Starting DMG Build for version: v${CURRENT_VERSION} ==="

# 4. Compile fresh app bundle
echo "=== Building ${APP_NAME}.app ==="
chmod +x build_mac_app.sh
./build_mac_app.sh

# 5. Prepare staging directory
echo "=== Preparing Packaging Directory ==="
rm -rf "$DMG_TEMP_DIR"
mkdir -p "$DMG_TEMP_DIR"
cp -R "${APP_NAME}.app" "$DMG_TEMP_DIR/"

# 6. Include Gatekeeper (xattr) Instructions & One-Click Fixer
cat << 'TXT' > "$DMG_TEMP_DIR/Install & Gatekeeper Instructions.txt"
======================================================================
  NFL Fantasy Live Game HUD — Installation & Gatekeeper (xattr) Fix
======================================================================

1. Drag "NFL Fantasy HUD.app" into your "Applications" folder.

2. Because this is an open-source application not signed through Apple's
   paid developer program, macOS Gatekeeper may show:
   "NFL Fantasy HUD is damaged and can't be opened" or "Unidentified Developer".

3. To authorize the app, open Terminal and run this one-line command:

   xattr -cr "/Applications/NFL Fantasy HUD.app"

   (Alternatively, double-click "Fix_Gatekeeper.command" in this window)

4. Press Enter. You can now launch NFL Fantasy HUD directly from
   Spotlight or Applications!
======================================================================
TXT

cat << 'CMD' > "$DMG_TEMP_DIR/Fix_Gatekeeper.command"
#!/bin/bash
clear
echo "================================================================="
echo "  NFL Fantasy Live Game HUD — Gatekeeper Quarantine Removal"
echo "================================================================="
echo ""
APP_PATH="/Applications/NFL Fantasy HUD.app"

if [ ! -d "$APP_PATH" ]; then
    echo "⚠️  'NFL Fantasy HUD.app' was not found in /Applications."
    echo "Please drag the app to Applications first, then run this helper."
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Removing quarantine flag from: $APP_PATH"
xattr -cr "$APP_PATH"
echo ""
echo "✅ Gatekeeper quarantine cleared successfully!"
echo "You can now launch NFL Fantasy HUD directly from Applications or Spotlight."
echo ""
read -p "Press Enter to exit..."
CMD
chmod +x "$DMG_TEMP_DIR/Fix_Gatekeeper.command"

# 7. Package using create-dmg if available, fallback to hdiutil
echo "=== Creating DMG Package (v${CURRENT_VERSION}) ==="
rm -f "${DMG_NAME}"

if command -v create-dmg >/dev/null 2>&1; then
    create-dmg \
      --volname "${APP_NAME}" \
      --window-pos 200 120 \
      --window-size 650 380 \
      --icon-size 100 \
      --icon "${APP_NAME}.app" 160 140 \
      --app-drop-link 480 140 \
      --no-internet-enable \
      "${DMG_NAME}" \
      "$DMG_TEMP_DIR" || {
        echo "⚠️ create-dmg failed or exited with status, falling back to hdiutil..."
        hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_TEMP_DIR" -ov -format UDZO "${DMG_NAME}"
      }
else
    echo "ℹ️ create-dmg not found, creating DMG with native hdiutil..."
    hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_TEMP_DIR" -ov -format UDZO "${DMG_NAME}"
fi

# 8. Clean up staging directory
rm -rf "$DMG_TEMP_DIR"

echo "================================================================="
echo "✅ DMG Build Completed Successfully: ${DMG_NAME} (v${CURRENT_VERSION})"
echo "================================================================="
