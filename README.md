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

## 🍎 Native macOS Swift App

You can launch the HUD directly as a standalone, native Mac app:

### 1. Launch App
```bash
open "NFL Fantasy HUD.app"
```

### 2. Swift App Features:
1. **Welcome / Setup Dialog**:
   - **Sleeper League ID** input (pre-filled with default)
   - **Target Display Selection** (instantly switch between MacBook screen, external monitors, or projectors)
   - **Matchup Layout Selection** (Automatic, Continuous Ticker, or Step-by-Step Shift for leagues of any size)
   - **Animation Speed** (Normal, Fast, Slow)
   - **Game Week Selection** (*Live / Auto* or specific *Week 1* to *Week 18*)
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

## 🛠️ Rebuilding the App (Optional)
If you make modifications to the Swift codebase:
```bash
./build_mac_app.sh
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
