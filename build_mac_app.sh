#!/bin/bash
# ==============================================================================
# NFL Fantasy Live Game HUD — Swift Native Mac App Compiler
# Builds "NFL Fantasy HUD.app" with native WebKit and Apple Silicon Optimization
# ==============================================================================

set -e

APP_NAME="NFL Fantasy HUD"
BUNDLE_DIR="${APP_NAME}.app"
CONTENTS_DIR="${BUNDLE_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

# 1. Terminate running instances before building
echo "🔍 Checking for running instances of ${APP_NAME}..."
pkill -f "${APP_NAME}" 2>/dev/null || true
sleep 0.5

# 2. Read version from version.txt
VERSION_FILE="$(dirname "$0")/version.txt"
if [ -f "$VERSION_FILE" ]; then
    APP_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
else
    APP_VERSION="1.0.0"
fi

echo "🔨 Building Native macOS Swift App: ${APP_NAME} (v${APP_VERSION})..."

# Clean old build
rm -rf "${BUNDLE_DIR}"
mkdir -p "${MACOS_DIR}" "${RESOURCES_DIR}"

# Copy App Icon if available
if [ -f "AppIcon.icns" ]; then
    cp "AppIcon.icns" "${RESOURCES_DIR}/AppIcon.icns"
fi

# Compile Swift code
swiftc macos-app/main.swift \
    -O \
    -target arm64-apple-macos11.0 \
    -framework Cocoa \
    -framework WebKit \
    -o "${MACOS_DIR}/${APP_NAME}"

# Create Info.plist (Regular macOS app with Dock icon and Dock menu)
cat << PLIST > "${CONTENTS_DIR}/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.nflfantasy.livehud</string>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${APP_VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${APP_VERSION}</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
    </dict>
</dict>
</plist>
PLIST

chmod +x "${MACOS_DIR}/${APP_NAME}"

# Ad-hoc sign app bundle for local execution
codesign -s - --force --deep "${BUNDLE_DIR}"

echo "✅ App bundle created successfully: ${BUNDLE_DIR} (v${APP_VERSION})"
echo "🚀 You can launch it with: open \"${BUNDLE_DIR}\""
