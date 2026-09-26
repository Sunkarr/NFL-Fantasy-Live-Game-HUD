import Cocoa
import WebKit

// ==============================================================================
// NFL Fantasy Live Game HUD — Native macOS App Launcher & Multi-Monitor Manager
// ==============================================================================

func writeLogLine(_ message: String) {
    let timestamp = ISO8601DateFormatter().string(from: Date())
    let line = "[\(timestamp)] [HUD-App] \(message)\n"
    print(line, terminator: "")
    if let data = line.data(using: .utf8) {
        let logPath = "/tmp/hud_app.log"
        if FileManager.default.fileExists(atPath: logPath) {
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(data)
                fileHandle.closeFile()
            }
        } else {
            try? data.write(to: URL(fileURLWithPath: logPath))
        }
    }
}

// Dedicated non-activating overlay panel subclass for YouTube/browser fullscreen support
class HUDOverlayPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    var statusItem: NSStatusItem?
    var setupWindow: NSWindow?
    var hudWindow: HUDOverlayPanel?
    var webView: WKWebView?
    var pythonProcess: Process?
    var keepFrontTimer: Timer?

    let serverURL = "http://localhost:8080"
    let defaultLeagueID = "1390344846723543040"
    let githubRepo = "Sunkarr/NFL-Fantasy-Live-Game-HUD"

    var leagueIdField: NSTextField!
    var screenPopup: NSPopUpButton!
    var modePopup: NSPopUpButton!
    var speedPopup: NSPopUpButton!
    var weekPopup: NSPopUpButton!
    var statusLabel: NSTextField!
    var launchBtn: NSButton!

    var selectedScreenIndex: Int = 0
    var retryCount: Int = 0
    var isDebugMode: Bool = false
    var isSoundEnabled: Bool = true
    var soundCheckbox: NSButton?
    var soundThemePopup: NSPopUpButton?
    var previewSoundPlayer: NSSound?
    var selectedSoundTheme: String = "fox_horn" 

    func applicationDidFinishLaunching(_ notification: Notification) {
        writeLogLine("Application did finish launching.")
        // Enforce accessory policy: allows HUD to float over other apps' fullscreen spaces
        NSApp.setActivationPolicy(.regular)

        setupMenuBar()
        setupStatusBar()
        showSetupDialog()

        // Check for updates from GitHub silently after startup
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
            self?.checkForUpdates(silent: true)
        }

        // Global key shortcut monitor (Cmd+Q to exit, Cmd+H to toggle overlay, Cmd+D for debug)
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.modifierFlags.contains(.command) && event.charactersIgnoringModifiers == "q" {
                self.quitApp()
                return nil
            }
            if event.modifierFlags.contains(.command) && event.charactersIgnoringModifiers == "h" {
                self.toggleHUD()
                return nil
            }
            if event.modifierFlags.contains(.command) && event.charactersIgnoringModifiers == "m" {
                self.toggleSound()
                return nil
            }
            return event
        }

        // Listen for screen layout changes (connecting/disconnecting Projector / External Displays)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(screensDidChange),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )

        // Listen for space changes to keep HUD above all fullscreen spaces
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(spaceOrAppDidChange),
            name: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil
        )

        // Listen for app activation (e.g. Chrome/Safari becoming frontmost or entering fullscreen)
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(spaceOrAppDidChange),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
    }

    @objc func screensDidChange() {
        writeLogLine("Display layout changed.")
        refreshScreenList()
        repositionHUD()
    }

    @objc func spaceOrAppDidChange() {
        bringHUDToFront()
    }

    func bringHUDToFront() {
        guard let window = hudWindow, window.isVisible else { return }
        window.orderFrontRegardless()
        // Re-assert after full-screen transition animation completes
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            self?.hudWindow?.orderFrontRegardless()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { [weak self] in
            self?.hudWindow?.orderFrontRegardless()
        }
    }

    func startKeepFrontTimer() {
        keepFrontTimer?.invalidate()
        keepFrontTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            guard let window = self?.hudWindow, window.isVisible else { return }
            window.orderFrontRegardless()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        writeLogLine("Application will terminate.")
        keepFrontTimer?.invalidate()
        hudWindow?.close()
        pythonProcess?.terminate()
    }


    // ==========================================================================
    // Dock Integration (Keep App in Dock, Custom Dock Menu & Click-to-Reopen)
    // ==========================================================================
    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "⚙️ Setup & Settings", action: #selector(showSetupDialog), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(title: "🔄 Check for Updates...", action: #selector(manualCheckForUpdates), keyEquivalent: "u"))
        menu.addItem(NSMenuItem(title: "🏈 Toggle HUD Visibility", action: #selector(toggleHUD), keyEquivalent: "h"))
        menu.addItem(NSMenuItem(title: isDebugMode ? "🐞 Debug Mode: ON (Clickable)" : "🐞 Debug Mode: OFF (Click-Through)", action: #selector(toggleDebugMode), keyEquivalent: "d"))
        menu.addItem(NSMenuItem(title: "📋 View Logs (/tmp/hud_backend.log)", action: #selector(viewLogs), keyEquivalent: "l"))
        menu.addItem(NSMenuItem(title: "🔄 Restart Backend Engine", action: #selector(restartBackend), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit NFL Fantasy HUD", action: #selector(quitApp), keyEquivalent: "q"))
        return menu
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        writeLogLine("Reopening Setup Dialog from Dock click.")
        showSetupDialog()
        return true
    }

    // ==========================================================================
    // Native macOS Menu Bar (Cmd+Q, Cmd+W, Cmd+H)
    // ==========================================================================
    func setupMenuBar() {
        let mainMenu = NSMenu()
        
        // App Menu
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "About NFL Fantasy HUD", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: ""))
        appMenu.addItem(NSMenuItem(title: "Check for Updates...", action: #selector(manualCheckForUpdates), keyEquivalent: ""))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Preferences / Setup (Cmd+S)...", action: #selector(showSetupDialog), keyEquivalent: "s"))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Toggle HUD (Cmd+H)", action: #selector(toggleHUD), keyEquivalent: "h"))
        appMenu.addItem(NSMenuItem(title: "Toggle Highlight Sound (Cmd+M)", action: #selector(toggleSound), keyEquivalent: "m"))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(NSMenuItem(title: "Quit", action: #selector(quitApp), keyEquivalent: "q"))
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        // Window Menu
        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(NSMenuItem(title: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w"))
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)

        // Edit Menu (Allows Cmd+V paste in textfields)
        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(NSMenuItem(title: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x"))
        editMenu.addItem(NSMenuItem(title: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
        editMenu.addItem(NSMenuItem(title: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v"))
        editMenu.addItem(NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        NSApp.mainMenu = mainMenu
    }

    // ==========================================================================
    // Status Bar Item (Menu Bar Tray)
    // ==========================================================================
    func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem?.button {
            button.title = "🏈 HUD"
        }

        buildStatusBarMenu()
    }

    func buildStatusBarMenu() {
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "⚙️ Setup & Settings (Cmd+S)", action: #selector(showSetupDialog), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(title: "🔄 Check for Updates...", action: #selector(manualCheckForUpdates), keyEquivalent: "u"))
        menu.addItem(NSMenuItem(title: "🏈 Toggle HUD Visibility (Cmd+H)", action: #selector(toggleHUD), keyEquivalent: "h"))
        
        let debugItem = NSMenuItem(title: isDebugMode ? "🐞 Debug Mode: ON (Clickable)" : "🐞 Debug Mode: OFF (Click-Through)", action: #selector(toggleDebugMode), keyEquivalent: "d")
        menu.addItem(debugItem)
        let soundTitle = isSoundEnabled ? "🔊 Highlight Sound FX: ON (Cmd+M)" : "🔇 Highlight Sound FX: MUTED (Cmd+M)"
        menu.addItem(NSMenuItem(title: soundTitle, action: #selector(toggleSound), keyEquivalent: "m"))
        menu.addItem(NSMenuItem(title: "📋 View Logs (/tmp/hud_backend.log)", action: #selector(viewLogs), keyEquivalent: "l"))
        menu.addItem(NSMenuItem(title: "🔄 Restart Backend Engine", action: #selector(restartBackend), keyEquivalent: "r"))

        menu.addItem(NSMenuItem.separator())

        // Screen switch submenu in status bar
        let screenMenu = NSMenu()
        for (idx, screen) in NSScreen.screens.enumerated() {
            let name = screen.localizedName
            let res = "\(Int(screen.frame.width))×\(Int(screen.frame.height))"
            let item = NSMenuItem(title: "\(idx == 0 ? "💻" : "🖥️") \(name) (\(res))", action: #selector(onScreenSelectedFromMenu(_:)), keyEquivalent: "")
            item.tag = idx
            item.state = (idx == selectedScreenIndex) ? .on : .off
            screenMenu.addItem(item)
        }
        let screenMenuItem = NSMenuItem(title: "🖥️ Target Display", action: nil, keyEquivalent: "")
        screenMenuItem.submenu = screenMenu
        menu.addItem(screenMenuItem)

        menu.addItem(NSMenuItem(title: "🌐 Control Center (Browser)", action: #selector(openControlCenter), keyEquivalent: "c"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit NFL Fantasy HUD (Cmd+Q)", action: #selector(quitApp), keyEquivalent: "q"))

        statusItem?.menu = menu
    }

    @objc func onScreenSelectedFromMenu(_ sender: NSMenuItem) {
        selectedScreenIndex = sender.tag
        writeLogLine("Selected screen index changed to \(selectedScreenIndex)")
        repositionHUD()
        buildStatusBarMenu()
    }

    @objc func openControlCenter() {
        if let url = URL(string: "\(serverURL)/admin") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func viewLogs() {
        writeLogLine("Opening log files...")
        let backendLog = URL(fileURLWithPath: "/tmp/hud_backend.log")
        let appLog = URL(fileURLWithPath: "/tmp/hud_app.log")
        
        if !FileManager.default.fileExists(atPath: backendLog.path) {
            try? "NFL Fantasy HUD - Backend Log\n".write(to: backendLog, atomically: true, encoding: .utf8)
        }
        if !FileManager.default.fileExists(atPath: appLog.path) {
            try? "NFL Fantasy HUD - App Log\n".write(to: appLog, atomically: true, encoding: .utf8)
        }
        
        NSWorkspace.shared.open(backendLog)
        NSWorkspace.shared.open(appLog)
    }

    @objc func toggleDebugMode() {
        isDebugMode = !isDebugMode
        writeLogLine("Debug mode toggled: \(isDebugMode)")
        if let window = hudWindow {
            window.ignoresMouseEvents = !isDebugMode
        }
        buildStatusBarMenu()
    }

    @objc func restartBackend() {
        writeLogLine("User initiated backend restart.")
        pythonProcess?.terminate()
        pythonProcess = nil

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        p.arguments = ["-f", "uvicorn.*8080|main.py"]
        try? p.run()
        p.waitUntilExit()

        updateServerStatus()
        showSetupDialog()
    }

    @objc func quitApp() {
        writeLogLine("Quitting application...")
        keepFrontTimer?.invalidate()
        hudWindow?.close()
        pythonProcess?.terminate()
        NSApp.terminate(nil)
    }

    // ==========================================================================
    // GitHub Auto-Updater
    // ==========================================================================
    @objc func manualCheckForUpdates() {
        checkForUpdates(silent: false)
    }

    func checkForUpdates(silent: Bool) {
        writeLogLine("Checking for updates from GitHub (\(githubRepo))...")
        guard let url = URL(string: "https://api.github.com/repos/\(githubRepo)/releases/latest") else { return }

        var request = URLRequest(url: url)
        request.setValue("application/vnd.github.v3+json", forHTTPHeaderField: "Accept")
        request.setValue("NFL-Fantasy-HUD-App", forHTTPHeaderField: "User-Agent")
        request.timeoutInterval = 8.0

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }

            if let error = error {
                writeLogLine("Update check error: \(error.localizedDescription)")
                if !silent {
                    DispatchQueue.main.async {
                        let alert = NSAlert()
                        alert.messageText = "Update Check Failed"
                        alert.informativeText = "Unable to connect to GitHub to check for updates: \(error.localizedDescription)"
                        alert.alertStyle = .warning
                        alert.addButton(withTitle: "OK")
                        alert.runModal()
                    }
                }
                return
            }

            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let tagName = json["tag_name"] as? String else {
                if !silent {
                    DispatchQueue.main.async {
                        let alert = NSAlert()
                        alert.messageText = "No Releases Found"
                        alert.informativeText = "No release information was found for this repository."
                        alert.alertStyle = .informational
                        alert.addButton(withTitle: "OK")
                        alert.runModal()
                    }
                }
                return
            }

            let releaseHtmlUrl = (json["html_url"] as? String) ?? "https://github.com/\(self.githubRepo)/releases"
            let releaseNotes = (json["body"] as? String) ?? ""

            // Look for .dmg in release assets
            var dmgDownloadUrl: String? = nil
            if let assets = json["assets"] as? [[String: Any]] {
                for asset in assets {
                    if let name = asset["name"] as? String, name.hasSuffix(".dmg"),
                       let download = asset["browser_download_url"] as? String {
                        dmgDownloadUrl = download
                        break
                    }
                }
            }

            let remoteVersion = tagName.trimmingCharacters(in: CharacterSet(charactersIn: "vV "))
            let localVersion = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "1.0.0"

            writeLogLine("Current version: \(localVersion), Latest remote version: \(remoteVersion)")

            let hasUpdate = self.isVersionNewer(remoteVersion, than: localVersion)

            DispatchQueue.main.async {
                if hasUpdate {
                    let alert = NSAlert()
                    alert.messageText = "🎉 New Version Available: \(tagName)"
                    let noteSnippet = releaseNotes.isEmpty ? "" : "\n\nRelease Highlights:\n\(releaseNotes.prefix(300))"
                    alert.informativeText = "A new version of NFL Fantasy HUD is available!\n\nInstalled version: v\(localVersion)\nLatest version: \(tagName)\(noteSnippet)"
                    alert.alertStyle = .informational

                    alert.addButton(withTitle: "Download Update")
                    alert.addButton(withTitle: "Release Notes")
                    alert.addButton(withTitle: "Later")

                    let response = alert.runModal()
                    if response == .alertFirstButtonReturn {
                        let target = dmgDownloadUrl ?? releaseHtmlUrl
                        if let targetUrl = URL(string: target) {
                            NSWorkspace.shared.open(targetUrl)
                        }
                    } else if response == .alertSecondButtonReturn {
                        if let targetUrl = URL(string: releaseHtmlUrl) {
                            NSWorkspace.shared.open(targetUrl)
                        }
                    }
                } else if !silent {
                    let alert = NSAlert()
                    alert.messageText = "You're Up to Date! 🏈"
                    alert.informativeText = "NFL Fantasy HUD v\(localVersion) is currently the newest version."
                    alert.alertStyle = .informational
                    alert.addButton(withTitle: "OK")
                    alert.runModal()
                }
            }
        }.resume()
    }

    func isVersionNewer(_ remote: String, than local: String) -> Bool {
        let rParts = remote.split(separator: ".").compactMap { Int($0) }
        let lParts = local.split(separator: ".").compactMap { Int($0) }

        let maxCount = max(rParts.count, lParts.count)
        for i in 0..<maxCount {
            let r = i < rParts.count ? rParts[i] : 0
            let l = i < lParts.count ? lParts[i] : 0
            if r > l { return true }
            if r < l { return false }
        }
        return false
    }


    // ==========================================================================
    // Welcome & Configuration Setup Dialog
    // ==========================================================================
    @objc func showSetupDialog() {
        if setupWindow == nil {
            createSetupWindow()
        }
        updateServerStatus()
        setupWindow?.center()
        setupWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func createSetupWindow() {
        let width: CGFloat = 520
        let height: CGFloat = 505
        let rect = NSRect(x: 0, y: 0, width: width, height: height)

        setupWindow = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        setupWindow?.title = "NFL Fantasy Live HUD — Setup & Debug"
        setupWindow?.delegate = self
        setupWindow?.isReleasedWhenClosed = false

        let contentView = NSView(frame: rect)

        // App Icon
        let iconView = NSImageView(frame: NSRect(x: 24, y: height - 70, width: 48, height: 48))
        if let appIcon = NSApp.applicationIconImage {
            iconView.image = appIcon
        }
        contentView.addSubview(iconView)

        // Title & Subtitle
        let titleLabel = NSTextField(labelWithString: "NFL Fantasy Live HUD")
        titleLabel.font = NSFont.systemFont(ofSize: 17, weight: .bold)
        titleLabel.frame = NSRect(x: 84, y: height - 44, width: width - 100, height: 24)
        contentView.addSubview(titleLabel)

        let subtitleLabel = NSTextField(labelWithString: "Broadcast-Grade Live Stream Overlay for Any League Size.")
        subtitleLabel.font = NSFont.systemFont(ofSize: 12, weight: .regular)
        subtitleLabel.textColor = .secondaryLabelColor
        subtitleLabel.frame = NSRect(x: 84, y: height - 64, width: width - 100, height: 18)
        contentView.addSubview(subtitleLabel)

        // 1. League ID Input
        let leagueLabel = NSTextField(labelWithString: "Sleeper League ID:")
        leagueLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        leagueLabel.frame = NSRect(x: 24, y: height - 108, width: 140, height: 20)
        contentView.addSubview(leagueLabel)

        leagueIdField = NSTextField(frame: NSRect(x: 168, y: height - 110, width: width - 192, height: 24))
        leagueIdField.stringValue = defaultLeagueID
        contentView.addSubview(leagueIdField)

        // 2. Monitor / Screen Selection Dropdown
        let screenLabel = NSTextField(labelWithString: "Target Display:")
        screenLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        screenLabel.frame = NSRect(x: 24, y: height - 144, width: 140, height: 20)
        contentView.addSubview(screenLabel)

        screenPopup = NSPopUpButton(frame: NSRect(x: 166, y: height - 148, width: width - 190, height: 26))
        contentView.addSubview(screenPopup)
        refreshScreenList()

        // 3. Matchup Display Mode Dropdown (Any League Size)
        let modeLabel = NSTextField(labelWithString: "Matchup Layout:")
        modeLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        modeLabel.frame = NSRect(x: 24, y: height - 180, width: 140, height: 20)
        contentView.addSubview(modeLabel)

        modePopup = NSPopUpButton(frame: NSRect(x: 166, y: height - 184, width: width - 190, height: 26))
        modePopup.addItem(withTitle: "⚡ Automatic (≤ 3 static, > 3 step-shift)")
        modePopup.addItem(withTitle: "📈 Continuous Ticker (Rolling marquee)")
        modePopup.addItem(withTitle: "➡️ Step Shift (1 exits left, 1 enters right)")
        modePopup.selectItem(at: 0)
        contentView.addSubview(modePopup)

        // 4. Animation / Transition Speed
        let speedLabel = NSTextField(labelWithString: "Animation Speed:")
        speedLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        speedLabel.frame = NSRect(x: 24, y: height - 216, width: 140, height: 20)
        contentView.addSubview(speedLabel)

        speedPopup = NSPopUpButton(frame: NSRect(x: 166, y: height - 220, width: width - 190, height: 26))
        speedPopup.addItem(withTitle: "⏱️ Normal (10s cycle)")
        speedPopup.addItem(withTitle: "⚡ Fast (5s cycle)")
        speedPopup.addItem(withTitle: "🐢 Slow (20s cycle)")
        speedPopup.selectItem(at: 0)
        contentView.addSubview(speedPopup)

        // 5. Game Week Override
        let weekLabel = NSTextField(labelWithString: "NFL Game Week:")
        weekLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        weekLabel.frame = NSRect(x: 24, y: height - 252, width: 140, height: 20)
        contentView.addSubview(weekLabel)

        weekPopup = NSPopUpButton(frame: NSRect(x: 166, y: height - 256, width: width - 190, height: 26))
        weekPopup.addItem(withTitle: "🟢 Live / Auto (Current NFL Week)")
        for w in 1...18 {
            weekPopup.addItem(withTitle: "Week \(w)")
        }
        weekPopup.selectItem(at: 0)
        contentView.addSubview(weekPopup)

        // 6. Highlight Audio FX Toggle Checkbox (User setting in Welcome Dialogue)
        let soundBtn = NSButton(checkboxWithTitle: "Enable Highlight Audio FX on Big Plays (Cmd+M)", target: self, action: #selector(onSoundCheckboxToggled))
        soundBtn.frame = NSRect(x: 24, y: height - 290, width: width - 48, height: 22)
        soundBtn.state = isSoundEnabled ? .on : .off
        soundBtn.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        contentView.addSubview(soundBtn)
        self.soundCheckbox = soundBtn

        // 7. Highlight Sound Theme Selector & Preview
        let soundThemeLabel = NSTextField(labelWithString: "Highlight Sound:")
        soundThemeLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        soundThemeLabel.frame = NSRect(x: 24, y: height - 326, width: 140, height: 20)
        contentView.addSubview(soundThemeLabel)

        let soundTheme = NSPopUpButton(frame: NSRect(x: 166, y: height - 330, width: width - 292, height: 26))
        soundTheme.addItem(withTitle: "🏈 NFL on FOX / Stadium Horn")
        soundTheme.addItem(withTitle: "⚡ NFL RedZone Chime Alert")
        soundTheme.addItem(withTitle: "🚨 Touchdown Siren & Horn")
        soundTheme.addItem(withTitle: "🎺 Classic Arena Fanfare")
        soundTheme.selectItem(at: 0)
        contentView.addSubview(soundTheme)
        self.soundThemePopup = soundTheme

        let testSoundBtn = NSButton(frame: NSRect(x: width - 118, y: height - 331, width: 94, height: 28))
        testSoundBtn.title = "▶ Preview"
        testSoundBtn.bezelStyle = .rounded
        testSoundBtn.target = self
        testSoundBtn.action = #selector(onPreviewSoundClicked)
        contentView.addSubview(testSoundBtn)

        // Server Status Indicator
        statusLabel = NSTextField(labelWithString: "Checking backend...")
        statusLabel.font = NSFont.systemFont(ofSize: 11, weight: .regular)
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.frame = NSRect(x: 24, y: 56, width: width - 48, height: 20)
        contentView.addSubview(statusLabel)

        // Action Buttons
        let logsBtn = NSButton(frame: NSRect(x: 24, y: 16, width: 105, height: 32))
        logsBtn.title = "📋 View Logs"
        logsBtn.bezelStyle = .rounded
        logsBtn.target = self
        logsBtn.action = #selector(viewLogs)
        contentView.addSubview(logsBtn)

        let quitBtn = NSButton(frame: NSRect(x: width - 215, y: 16, width: 85, height: 32))
        quitBtn.title = "Quit"
        quitBtn.bezelStyle = .rounded
        quitBtn.target = self
        quitBtn.action = #selector(quitApp)
        contentView.addSubview(quitBtn)

        launchBtn = NSButton(frame: NSRect(x: width - 120, y: 16, width: 100, height: 32))
        launchBtn.title = "Launch HUD"
        launchBtn.bezelStyle = .rounded
        launchBtn.isHighlighted = true
        launchBtn.keyEquivalent = "\r"
        launchBtn.target = self
        launchBtn.action = #selector(onLaunchClicked)
        contentView.addSubview(launchBtn)

        setupWindow?.contentView = contentView
    }

    @objc func onSoundCheckboxToggled() {
        isSoundEnabled = (soundCheckbox?.state == .on)
        writeLogLine("Sound checkbox toggled in setup dialog: \(isSoundEnabled)")
        webView?.evaluateJavaScript("if (window.hud) window.hud.setSound(\(isSoundEnabled));", completionHandler: nil)
        buildStatusBarMenu()
    }

    @objc func onPreviewSoundClicked() {
        let idx = soundThemePopup?.indexOfSelectedItem ?? 0
        let filenames = ["nfl_fox_horn.wav", "nfl_redzone_alert.wav", "nfl_touchdown_siren.wav", "nfl_brass_fanfare.wav"]
        let fn = filenames[min(max(idx, 0), filenames.count - 1)]
        writeLogLine("Previewing sound: \(fn)")
        if let url = URL(string: "\(serverURL)/static/sounds/\(fn)") {
            previewSoundPlayer?.stop()
            previewSoundPlayer = NSSound(contentsOf: url, byReference: true)
            previewSoundPlayer?.volume = 0.95
            previewSoundPlayer?.play()
        }
    }

    func refreshScreenList() {
        guard let popup = screenPopup else { return }
        popup.removeAllItems()
        let screens = NSScreen.screens
        for (i, screen) in screens.enumerated() {
            let name = screen.localizedName
            let res = "\(Int(screen.frame.width))×\(Int(screen.frame.height))"
            let isMain = (screen == NSScreen.main) ? " (Main)" : ""
            popup.addItem(withTitle: "\(i == 0 ? "💻" : "🖥️") \(name)\(isMain) [\(res)]")
        }
        if selectedScreenIndex < screens.count {
            popup.selectItem(at: selectedScreenIndex)
        }
    }

    func updateServerStatus() {
        checkBackendHealth { isHealthy in
            DispatchQueue.main.async {
                if isHealthy {
                    self.statusLabel.stringValue = "🟢 Live Game Engine Connected (http://localhost:8080)"
                    self.statusLabel.textColor = .systemGreen
                } else {
                    self.statusLabel.stringValue = "🟡 Backend offline — click 'Launch HUD' to start."
                    self.statusLabel.textColor = .systemOrange
                }
            }
        }
    }

    func checkBackendHealth(completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "\(serverURL)/health") else {
            completion(false)
            return
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 1.0
        URLSession.shared.dataTask(with: req) { _, response, error in
            if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                completion(true)
            } else {
                completion(false)
            }
        }.resume()
    }

    @objc func onLaunchClicked() {
        let inputLeagueId = leagueIdField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        let leagueId = inputLeagueId.isEmpty ? defaultLeagueID : inputLeagueId
        selectedScreenIndex = screenPopup.indexOfSelectedItem

        let modeIndex = modePopup.indexOfSelectedItem
        let modeParam: String
        switch modeIndex {
        case 1: modeParam = "ticker"
        case 2: modeParam = "step"
        default: modeParam = "auto"
        }

        let speedIndex = speedPopup.indexOfSelectedItem
        let speedParam: String
        switch speedIndex {
        case 1: speedParam = "fast"
        case 2: speedParam = "slow"
        default: speedParam = "normal"
        }

        let weekIndex = weekPopup.indexOfSelectedItem
        let weekParam: Int? = (weekIndex > 0) ? weekIndex : nil

        let themeIndex = soundThemePopup?.indexOfSelectedItem ?? 0
        let themeKeys = ["fox_horn", "redzone", "td_siren", "brass_fanfare"]
        let soundThemeParam = themeKeys[min(max(themeIndex, 0), themeKeys.count - 1)]
        selectedSoundTheme = soundThemeParam
        isSoundEnabled = (soundCheckbox?.state == .on)

        launchBtn.isEnabled = false
        statusLabel.stringValue = "⏳ Verifying backend engine connection..."
        statusLabel.textColor = .systemBlue
        writeLogLine("Launch HUD clicked. Target league: \(leagueId), mode: \(modeParam), speed: \(speedParam), week: \(String(describing: weekParam))")

        checkBackendHealth { [weak self] isHealthy in
            guard let self = self else { return }

            if isHealthy {
                writeLogLine("Backend is already running and healthy.")
                self.pushSettingsToBackend(leagueId: leagueId, mode: modeParam, speed: speedParam, week: weekParam, soundEnabled: self.isSoundEnabled, soundTheme: self.selectedSoundTheme) {
                    DispatchQueue.main.async {
                        self.setupWindow?.orderOut(nil)
                        self.launchBtn.isEnabled = true
                        self.startHUD()
                    }
                }
            } else {
                DispatchQueue.main.async {
                    self.statusLabel.stringValue = "⏳ Spawning backend engine process..."
                }
                self.launchBackendProcess(leagueId: leagueId) { success, errorSnippet in
                    DispatchQueue.main.async {
                        self.launchBtn.isEnabled = true
                        if success {
                            writeLogLine("Backend launched successfully.")
                            self.pushSettingsToBackend(leagueId: leagueId, mode: modeParam, speed: speedParam, week: weekParam, soundEnabled: self.isSoundEnabled, soundTheme: self.selectedSoundTheme) {
                                DispatchQueue.main.async {
                                    self.setupWindow?.orderOut(nil)
                                    self.startHUD()
                                }
                            }
                        } else {
                            self.statusLabel.stringValue = "❌ Failed to start backend engine."
                            self.statusLabel.textColor = .systemRed
                            writeLogLine("Backend failed to start. Error: \(errorSnippet)")

                            let alert = NSAlert()
                            alert.messageText = "Failed to Start HUD Backend"
                            alert.informativeText = "The backend server at http://localhost:8080 could not be launched.\n\nError output:\n\(errorSnippet)\n\nCheck /tmp/hud_backend.log or try running `python3 main.py` in your terminal."
                            alert.alertStyle = .critical
                            alert.addButton(withTitle: "Open Log File")
                            alert.addButton(withTitle: "Dismiss")
                            let res = alert.runModal()
                            if res == .alertFirstButtonReturn {
                                self.viewLogs()
                            }
                        }
                    }
                }
            }
        }
    }

    func pushSettingsToBackend(leagueId: String, mode: String, speed: String, week: Int?, soundEnabled: Bool, soundTheme: String, completion: @escaping () -> Void) {
        let group = DispatchGroup()

        // 1. Post display & audio settings
        if let settingsUrl = URL(string: "\(serverURL)/api/settings") {
            var req = URLRequest(url: settingsUrl)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = [
                "mode": mode,
                "speed": speed,
                "sound_enabled": soundEnabled,
                "sound_theme": soundTheme
            ]
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            
            group.enter()
            URLSession.shared.dataTask(with: req) { _, _, _ in group.leave() }.resume()
        }

        // 2. Post week override if selected
        if let week = week, let weekUrl = URL(string: "\(serverURL)/api/week") {
            var req = URLRequest(url: weekUrl)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = ["week": week]
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            
            group.enter()
            URLSession.shared.dataTask(with: req) { _, _, _ in group.leave() }.resume()
        }

        group.notify(queue: .main) {
            completion()
        }
    }

    func launchBackendProcess(leagueId: String, completion: @escaping (Bool, String) -> Void) {
        writeLogLine("Locating backend directory...")
        let fileManager = FileManager.default
        var repoPath = fileManager.currentDirectoryPath

        if !fileManager.fileExists(atPath: "\(repoPath)/main.py") {
            let bundleDir = Bundle.main.bundleURL.deletingLastPathComponent().path
            let userHome = NSHomeDirectory()
            let commonPaths = [
                bundleDir,
                "\(userHome)/Documents/GitHub/NFL-Fantasy-Live-Game-HUD",
                Bundle.main.bundlePath + "/Contents/Resources"
            ]
            for p in commonPaths {
                if fileManager.fileExists(atPath: "\(p)/main.py") {
                    repoPath = p
                    break
                }
            }
        }
        writeLogLine("Target repo path: \(repoPath)")

        // Identify Python binary containing FastAPI & Uvicorn
        var pythonBin = "python3"
        if fileManager.fileExists(atPath: "\(repoPath)/.venv/bin/python3") {
            pythonBin = "\(repoPath)/.venv/bin/python3"
        } else if fileManager.fileExists(atPath: "\(repoPath)/venv/bin/python3") {
            pythonBin = "\(repoPath)/venv/bin/python3"
        } else if fileManager.fileExists(atPath: "/opt/homebrew/bin/python3") {
            pythonBin = "/opt/homebrew/bin/python3"
        }
        writeLogLine("Using Python binary: \(pythonBin)")

        let logPath = "/tmp/hud_backend.log"
        let script = """
        cd "\(repoPath)"
        export SLEEPER_LEAGUE_ID="\(leagueId)"
        export PYTHONUNBUFFERED=1
        "\(pythonBin)" main.py > "\(logPath)" 2>&1 &
        """

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-c", script]

        do {
            try process.run()
            self.pythonProcess = process

            // Poll until server is ready (max 25 attempts * 400ms = 10s)
            var attempts = 0
            func poll() {
                self.checkBackendHealth { ready in
                    if ready {
                        writeLogLine("Backend server confirmed ready on port 8080.")
                        completion(true, "")
                    } else if attempts >= 25 {
                        writeLogLine("Backend health check timed out after 25 attempts.")
                        var tail = "Timeout waiting for backend server."
                        if let logContent = try? String(contentsOfFile: logPath, encoding: .utf8) {
                            let lines = logContent.components(separatedBy: .newlines).filter { !$0.isEmpty }
                            if !lines.isEmpty {
                                tail = lines.suffix(6).joined(separator: "\n")
                            }
                        }
                        completion(false, tail)
                    } else {
                        attempts += 1
                        DispatchQueue.global().asyncAfter(deadline: .now() + 0.4) {
                            poll()
                        }
                    }
                }
            }
            poll()
        } catch {
            let err = "Process execution failed: \(error.localizedDescription)"
            writeLogLine(err)
            completion(false, err)
        }
    }

    // ==========================================================================
    // Fullscreen HUD Overlay Window & WebView
    // ==========================================================================
    func startHUD() {
        writeLogLine("Starting HUD overlay window...")
        if hudWindow == nil {
            createHUDWindow()
        } else {
            repositionHUD()
            loadOverlayURL()
            bringHUDToFront()
        }
        hudWindow?.makeKeyAndOrderFront(nil)
        hudWindow?.orderFrontRegardless()
        startKeepFrontTimer()
        writeLogLine("HUD overlay window displayed.")
    }

    func createHUDWindow() {
        let screens = NSScreen.screens
        let targetScreen = (selectedScreenIndex < screens.count) ? screens[selectedScreenIndex] : (NSScreen.main ?? screens[0])
        let screenRect = targetScreen.frame
        writeLogLine("Creating overlay on screen: \(targetScreen.localizedName), dimensions: \(screenRect)")

        // Use non-activating HUDOverlayPanel to prevent losing focus during fullscreen video
        let window = HUDOverlayPanel(
            contentRect: screenRect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false,
            screen: targetScreen
        )

        // Float above fullscreen video spaces
        window.isFloatingPanel = true
        window.level = .screenSaver
        window.collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
            .ignoresCycle
        ]
        
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.ignoresMouseEvents = !isDebugMode  // Click-through in normal mode, inspectable in debug mode
        window.isMovable = false
        window.hidesOnDeactivate = false

        // WKWebView Configuration
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "allowFileAccessFromFileURLs")
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.setValue(false, forKey: "drawsBackground")
        config.mediaTypesRequiringUserActionForPlayback = []

        let wv = WKWebView(frame: NSRect(x: 0, y: 0, width: screenRect.width, height: screenRect.height), configuration: config)
        wv.autoresizingMask = [.width, .height]
        wv.navigationDelegate = self
        wv.setValue(false, forKey: "drawsBackground")

        if #available(macOS 13.3, *) {
            wv.isInspectable = true
        }

        window.contentView = wv
        self.webView = wv
        self.hudWindow = window

        loadOverlayURL()
        bringHUDToFront()
    }

    func loadOverlayURL() {
        guard let wv = webView, let url = URL(string: "\(serverURL)/overlay") else { return }
        writeLogLine("Loading WebKit URL: \(url)")
        wv.load(URLRequest(url: url))
    }

    // WKNavigationDelegate: Automatically retry if backend was bootstrapping
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        writeLogLine("WebView provisional navigation failed: \(error.localizedDescription) (Retry: \(retryCount))")
        if retryCount < 15 {
            retryCount += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                self.loadOverlayURL()
            }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        writeLogLine("WebView navigation finished successfully.")
        retryCount = 0
        bringHUDToFront()
    }

    func repositionHUD() {
        guard let window = hudWindow else { return }
        let screens = NSScreen.screens
        guard !screens.isEmpty else { return }
        
        let targetScreen = (selectedScreenIndex < screens.count) ? screens[selectedScreenIndex] : screens[0]
        let rect = targetScreen.frame
        writeLogLine("Repositioning HUD to \(targetScreen.localizedName): \(rect)")
        
        window.setFrame(rect, display: true, animate: false)
        bringHUDToFront()
    }

    @objc func toggleSound() {
        isSoundEnabled = !isSoundEnabled
        soundCheckbox?.state = isSoundEnabled ? .on : .off
        writeLogLine("Highlight sound toggled: \(isSoundEnabled)")
        webView?.evaluateJavaScript("if (window.hud) window.hud.setSound(\(isSoundEnabled));", completionHandler: nil)
        buildStatusBarMenu()
    }

    @objc func toggleHUD() {
        guard let window = hudWindow else { return }
        if window.isVisible {
            writeLogLine("HUD toggled OFF.")
            window.orderOut(nil)
        } else {
            writeLogLine("HUD toggled ON.")
            repositionHUD()
            loadOverlayURL()
            bringHUDToFront()
        }
    }
}

// Main entry point
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
writeLogLine("Starting NSApplication main loop...")
app.run()
