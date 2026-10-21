# 🏈 NFL Fantasy Live Game HUD

A professional, transparent broadcast overlay for Sleeper Fantasy Football leagues inspired by modern sports broadcast graphics (RedZone / ESPN).

---

## 🎨 Manager Glow Color Palette

Each manager in the live ticker has a high-contrast, glowing neon accent color configured to ensure zero visual ambiguity on dark stream backgrounds:

| Roster Order | Accent Glow Color | Hex Code | Visual Profile |
| :--- | :--- | :--- | :--- |
| **Roster 1 (User Default)** | Electric Cyan | `#00f0ff` | Signature Cyan Glow |
| **Roster 2** | Neon Hot Pink / Fuchsia | `#ff00aa` | Radiant Fuchsia |
| **Roster 3** | Electric Ultraviolet | `#a855f7` | Vivid Purple |
| **Roster 4** | Electric Amber Gold | `#ffaa00` | Bright Warm Gold |
| **Roster 5** | Neon Spring Green | `#00e676` | Vibrant High-Energy Green |
| **Roster 6** | Cardinal Red | `#ef4444` | True Cardinals Red |
| **Free Agent / Unowned** | Slate Gray | `#94a3b8` | Neutral Slate |

> [!TIP]
> Manager colors and the 16-team extended fallback palette can be customized in [`src/config.py`](file:///Users/jonas/Documents/GitHub/NFL-Fantasy-Live-Game-HUD/src/config.py). All colors feature dynamic SVG/CSS glow borders and score bar drop shadows in the live ticker and highlight pills.

---

## 🍏 Native macOS Swift App & DMG Installer

You can launch the HUD directly as a standalone, native Mac app:

### 1. Launch App & DMG Installer
- **DMG Package**: Open [`NFL-Fantasy-HUD.dmg`](file:///Users/jonas/Documents/GitHub/NFL-Fantasy-Live-Game-HUD/NFL-Fantasy-HUD.dmg) and drag `NFL Fantasy HUD.app` into your Applications folder. Includes a one-click `Fix_Gatekeeper.command` helper.
- **Direct Launch**:
```bash
open "NFL Fantasy HUD.app"
```

### 2. Swift App Features:
1. **Welcome / Setup Dialog**:
   - **Sleeper League ID** input (pre-filled with default, dynamic live switching)
   - **Newest Avatar & Data Preload**: Prioritizes custom league team avatars (`metadata.avatar`) and high-resolution Sleeper profile avatars concurrently at engine boot and dynamic league switch, with browser-side image preloading to prevent pop-in delay or image flicker.
   - **Target Display Selection** (instantly switch between MacBook screen, external monitors, or projectors)
   - **Matchup Layout Selection** (Automatic, Continuous Ticker, or Step-by-Step Shift for leagues of any size)
   - **Animation Speed** (Normal, Fast, Slow)
   - **Game Week Selection** (*Live / Auto* or specific *Week 1* to *Week 18*)
   - **Highlight & Injury Toggles**: Checkboxes for Big Play Highlights, Highlight Audio FX, Live Injury Alerts, and Negative Injury Sound FX
   - **Audio Theme Selectors with ▶ Preview**: Audition Fox Horn / RedZone / TD Siren / Brass Fanfare, or Whistle / Buzzer / Flatline / Vinyl Scratch directly before launching
   - **Automatic dependency installation & self-healing backend launcher**
2. **Transparent Ghost Top Bar Overlay**:
   - Uses Apple's native hardware-accelerated **WebKit (`WKWebView`)**
   - Ultra-low CPU overhead, zero Chromium bloat, smooth 60fps animations
   - Stays on top of fullscreen video streams (YouTube, DAZN, GamePass, VLC)
   - Click-through enabled: clicks pass seamlessly through the overlay to underlying video controls
3. **Menu Bar Tray Icon (`🏈 HUD`)**:
   - Shortcuts: `Cmd+H` (Toggle HUD visibility), `Cmd+S` (Setup Dialog), `Cmd+Q` (Quit)
   - Target monitor switching submenu in real time.

---


---

## 🚑 Live In-Game Injury Alerts & Negative Sound FX

The HUD automatically monitors real-time injury feeds directly from the ESPN NFL API for every owned player across your fantasy league:

1. **Owned Player In-Game Injury Detection**:
   - Continuously cross-references active roster ownership with ESPN's live NFL injury reports.
   - When any rostered player changes status to **Out (`O`)**, **Questionable (`Q`)**, **Doubtful (`D`)**, or **Injured Reserve (`IR`)**, an urgent **Injury Alert Banner** is pushed to the HUD spotlight queue.
   - Displays player headshot, position, manager name with custom team glow, status badge, and injury diagnosis details.

2. **Configurable Negative Sound FX**:
   - **4 Negative Audio FX Themes**:
     - `whistle_blow`: Referee penalty / injury whistle trill *(Default)*
     - `buzzer_flat`: Low, heavy rejection / error buzzer
     - `flatline`: Hospital telemetry pulse beeps ending in a heart monitor flatline
     - `record_scratch`: DJ vinyl record scratch / abrupt halt
   - Hardware-accelerated Web Audio API fallback ensures audio plays reliably with zero latency even when autoplay policies are restrictive.

3. **Master Feature Toggles (App Menu, Status Tray & Setup Dialog)**:
   - **Toggle Highlights (`ON` / `OFF`)**: Turn big-play highlight banners on or off dynamically without stopping the matchup ticker.
   - **Toggle Injury Alerts (`ON` / `OFF`)**: Silence or enable injury notifications on demand.
   - **Independent Audio Muting**: Enable/disable highlight fanfare or injury audio effects separately via Menu Bar, Status Bar, Dock Menu, or the Setup Dialog.

---

## 🛠️ Rebuilding the App & Packaging DMG
If you make modifications to the Swift codebase or backend:
```bash
# Rebuild native app bundle and update /Applications
./build_mac_app.sh

# Build DMG installer with drag-and-drop Applications shortcut
./create_dmg.sh
```

---

## 🌐 Web & OBS Streaming Alternatives
- **Control Center & Test Dashboard**: [http://localhost:8080/admin](http://localhost:8080/admin)
- **OBS Browser Source**: `http://localhost:8080/overlay` (Width: `1920`, Height: `68`)

### 3. macOS Gatekeeper (First-Time Opening)
When downloading from GitHub Releases, macOS Gatekeeper may show a warning for unsigned open-source applications. To authorize the app, open Terminal and run:
```bash
xattr -cr "/Applications/NFL Fantasy HUD.app"
```
Or double-click `Fix_Gatekeeper.command` included on the DMG installer.
