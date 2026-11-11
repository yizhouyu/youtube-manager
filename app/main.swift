// 审片.app — a thin native window around the review pages. All logic lives in Python
// (src/editor/app_server.py): this file (main.swift) starts that server, shows its page in a WKWebView over the native
// sidebar vibrancy, wires ⌘1–⌘5 / the folder picker, and stops the server (and with it the episode servers) on quit.
import AppKit
import WebKit

/// Lets the window be dragged by the empty strip next to the traffic lights (web content swallows drags).
final class DragStrip: NSView {
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 { window?.zoom(nil) } else { window?.performDrag(with: event) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var background = false
    var shellReady = false
    var pendingURLs: [String] = []
    var web: WKWebView!
    var sideW: NSLayoutConstraint!, dragW: NSLayoutConstraint!   // sidebar + drag strip widths (0 when the sidebar is hidden)
    var server: Process?
    let portFile = NSTemporaryDirectory() + "shenpian-\(getpid()).port"
    let logDir = ProcessInfo.processInfo.environment["SHENPIAN_LOGS"] ?? NSHomeDirectory() + "/Library/Logs/审片"

    /// One line in app.log (agent URLs: received / queued / handed to the page).
    func note(_ s: String) {
        let line = "[app \(ISO8601DateFormatter().string(from: Date()))] \(s)\n"
        if let h = FileHandle(forWritingAtPath: logDir + "/app.log") { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile() }
    }

    /// Repo + python: $SHENPIAN_REPO, else Info.plist ShenpianRepo (set by build.sh), else ~/Desktop/youtube-manager.
    var repo: String {
        let env = ProcessInfo.processInfo.environment["SHENPIAN_REPO"]
        let plist = Bundle.main.object(forInfoDictionaryKey: "ShenpianRepo") as? String
        return (env ?? plist ?? "~/Desktop/youtube-manager" as String).replacingOccurrences(of: "~", with: NSHomeDirectory())
    }
    var python: String {
        let mine = repo + "/venv/bin/python"
        return FileManager.default.isExecutableFile(atPath: mine) ? mine : NSHomeDirectory() + "/Desktop/youtube-manager/venv/bin/python"
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        buildWindow()
        startServer()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    // Unsaved shot edits on the 成片 page: a browser tab would ask before closing; the app asks before quitting.
    var discardOK = false
    func confirmDiscard(_ done: @escaping (Bool) -> Void) {
        guard let web = web else { done(true); return }
        web.evaluateJavaScript("!!(window.shell&&shell.dirty&&shell.dirty())") { r, _ in
            guard (r as? Bool) == true else { done(true); return }
            let a = NSAlert()
            a.messageText = "成片里有修改还没保存"
            a.informativeText = "现在退出，这些修改会丢掉。"
            a.addButton(withTitle: "取消")
            a.addButton(withTitle: "不保存，退出")
            done(a.runModal() == .alertSecondButtonReturn)
        }
    }

    func windowShouldClose(_ w: NSWindow) -> Bool {
        if discardOK { return true }
        confirmDiscard { ok in if ok { self.discardOK = true; w.close() } }
        return false
    }

    func applicationShouldTerminate(_ app: NSApplication) -> NSApplication.TerminateReply {
        if discardOK { return .terminateNow }
        confirmDiscard { ok in self.discardOK = ok; app.reply(toApplicationShouldTerminate: ok) }
        return .terminateLater
    }

    func applicationWillTerminate(_ note: Notification) {
        guard let s = server, s.isRunning else { return }
        s.terminate()   // app_server stops the episode servers it started on SIGTERM
        let deadline = Date().addingTimeInterval(6)
        while s.isRunning && Date() < deadline { usleep(100_000) }
        try? FileManager.default.removeItem(atPath: portFile)
    }

    // MARK: window

    func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "审片"
        window.delegate = self
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbar = NSToolbar(identifier: "shenpian")
        window.toolbarStyle = .unified          // 52 pt bar, traffic lights centred in it
        window.minSize = NSSize(width: 980, height: 600)
        window.backgroundColor = Theme.bg
        // SHENPIAN_BACKGROUND=1 (agents / tests while he works on this Mac, scripts/shenpian --background): the window
        // sits under all his windows, never activates, never takes clicks or keys, doesn't touch the saved frame; it
        // keeps rendering while covered, so `screencapture -l` works. SHENPIAN_SIZE=WxH sets the size.
        let env = ProcessInfo.processInfo.environment
        background = env["SHENPIAN_BACKGROUND"] == "1"
        if !background { window.setFrameAutosaveName("ShenpianMain") }
        if let sz = env["SHENPIAN_SIZE"]?.split(separator: "x").compactMap({ Double($0) }), sz.count == 2 {
            window.setContentSize(NSSize(width: sz[0], height: sz[1]))
        }
        if window.frame.origin == .zero { window.center() }

        let root = NSView()
        window.contentView = root
        let side = NSVisualEffectView()
        side.material = .sidebar
        side.blendingMode = .behindWindow
        side.state = .followsWindowActiveState

        let cfg = WKWebViewConfiguration()
        cfg.preferences.isElementFullscreenEnabled = true
        cfg.mediaTypesRequiringUserActionForPlayback = []
        cfg.userContentController.add(self, name: "shell")
        cfg.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.classList.add('native')", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: cfg)
        web.setValue(false, forKey: "drawsBackground")   // transparent: the sidebar vibrancy shows through the page
        web.underPageBackgroundColor = Theme.bg
        web.uiDelegate = self
        web.navigationDelegate = self
        // keep rendering while covered / off screen (background mode, screenshots of a window he doesn't see)
        let occl = Selector(("_setWindowOcclusionDetectionEnabled:"))
        if background && web.responds(to: occl) { web.perform(occl, with: nil) }   // nil = NO
        web.allowsMagnification = false
        if #available(macOS 13.3, *) { web.isInspectable = true }

        let drag = DragStrip()
        sideW = side.widthAnchor.constraint(equalToConstant: Theme.sidebarWidth)
        dragW = drag.widthAnchor.constraint(equalToConstant: Theme.sidebarWidth - Theme.dragLeading)
        for v in [side, web!, drag] as [NSView] {
            v.translatesAutoresizingMaskIntoConstraints = false
            root.addSubview(v)
        }
        NSLayoutConstraint.activate([
            side.leadingAnchor.constraint(equalTo: root.leadingAnchor), side.topAnchor.constraint(equalTo: root.topAnchor),
            side.bottomAnchor.constraint(equalTo: root.bottomAnchor), sideW,
            web.leadingAnchor.constraint(equalTo: root.leadingAnchor), web.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            web.topAnchor.constraint(equalTo: root.topAnchor), web.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            drag.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: Theme.dragLeading),
            dragW,
            drag.topAnchor.constraint(equalTo: root.topAnchor), drag.heightAnchor.constraint(equalToConstant: Theme.toolbarHeight),
        ])
        web.loadHTMLString("<html style='font:13px -apple-system;color:#86868b'><body style='display:grid;place-items:center;height:90vh;background:transparent'>启动中…</body></html>", baseURL: nil)
        if background {   // below every normal window, on every Space, clicks pass through: he never sees or hits it
            window.ignoresMouseEvents = true
            window.level = NSWindow.Level(rawValue: NSWindow.Level.normal.rawValue - 1)
            window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
            window.orderFrontRegardless()
        } else {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    // MARK: python server

    func startServer() {
        try? FileManager.default.createDirectory(atPath: logDir, withIntermediateDirectories: true)
        let logPath = logDir + "/app.log"
        let fd = open(logPath, O_WRONLY | O_APPEND | O_CREAT, 0o644)   // append mode: the app's own notes interleave safely
        let log: FileHandle? = fd >= 0 ? FileHandle(fileDescriptor: fd, closeOnDealloc: true) : nil
        try? FileManager.default.removeItem(atPath: portFile)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["-m", "src.editor.app_server", "--port-file", portFile, "--parent-pid", "\(getpid())",
                       "--window-id", "\(window.windowNumber)"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        p.standardOutput = log
        p.standardError = log
        do { try p.run() } catch { fail("启动不了 Python：\(python)\n\(error.localizedDescription)"); return }
        server = p
        waitForPort(tries: 0)
    }

    func waitForPort(tries: Int) {
        if let s = try? String(contentsOfFile: portFile, encoding: .utf8), let port = Int(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            var u = URLComponents(string: "http://127.0.0.1:\(port)/")!
            let env = ProcessInfo.processInfo.environment   // SHENPIAN_OPEN=<project> [SHENPIAN_TAB=cut]: open straight into it
            if let open = env["SHENPIAN_OPEN"] {
                u.queryItems = [URLQueryItem(name: "open", value: open), URLQueryItem(name: "tab", value: env["SHENPIAN_TAB"] ?? ""),
                                URLQueryItem(name: "t", value: env["SHENPIAN_T"] ?? ""), URLQueryItem(name: "clip", value: env["SHENPIAN_CLIP"] ?? "")]
            }
            web.load(URLRequest(url: u.url!))
            return
        }
        if tries > 200 || !(server?.isRunning ?? false) { fail("后台没有启动起来，日志在 ~/Library/Logs/审片/app.log"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { self.waitForPort(tries: tries + 1) }
    }

    func fail(_ msg: String) {
        let a = NSAlert()
        a.messageText = "审片"
        a.informativeText = msg
        a.runModal()
    }

    // MARK: agent control (shenpian:// URLs, see scripts/shenpian): open / tab / seek / quit, nothing that writes

    /// The schemes this build answers to (Info.plist): shenpian, or a test copy's own.
    lazy var schemes: [String] = ((Bundle.main.object(forInfoDictionaryKey: "CFBundleURLTypes") as? [[String: Any]]) ?? [])
        .flatMap { ($0["CFBundleURLSchemes"] as? [String]) ?? [] }

    func application(_ application: NSApplication, open urls: [URL]) {
        for var url in urls where schemes.contains(url.scheme ?? "") || url.scheme == "shenpian" {
            note("agent url \(url.absoluteString) (window \(window == nil ? "not built yet" : "ready"), page \(shellReady ? "ready" : "loading"))")
            if url.scheme != "shenpian", var c = URLComponents(url: url, resolvingAgainstBaseURL: false) {
                c.scheme = "shenpian"; url = c.url ?? url   // a test copy's own scheme: same meaning
            }
            let q = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            if url.host == "quit" { agentQuit(); continue }
            if q.first(where: { $0.name == "bg" })?.value != "1" { comeForward() }
            pendingURLs.append(url.absoluteString)
        }
        flushURLs()
    }

    /// The shell page opens the episode (app_server.parse_agent_url decides what the URL may do). A URL that comes
    /// while the app is still starting waits until the page itself says it can take it (not only for didFinish).
    var flushTries = 0
    func flushURLs() {
        guard !pendingURLs.isEmpty, web != nil else { return }
        web.evaluateJavaScript("!!(window.shell&&shell.agent)") { r, _ in
            guard (r as? Bool) == true else {
                self.flushTries += 1
                if self.flushTries < 240 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.flushURLs() } }
                else { self.note("agent url dropped: the page never became ready") }
                return
            }
            self.flushTries = 0
            self.handURLs()
        }
    }

    func handURLs() {
        for u in pendingURLs {
            guard let d = try? JSONSerialization.data(withJSONObject: [u]), let arr = String(data: d, encoding: .utf8) else { continue }
            note("agent url handed to the page: \(u)")
            web.evaluateJavaScript("window.shell&&void shell.agent(\(arr)[0])") { _, e in if let e = e { self.note("agent url failed in the page: \(e)") } }
        }
        pendingURLs.removeAll()
    }

    func webView(_ w: WKWebView, didFinish nav: WKNavigation!) {
        if w.url?.scheme == "http" { shellReady = true; flushURLs() }
    }

    /// From background mode to a normal window he can use.
    func comeForward() {
        guard window != nil else { DispatchQueue.main.async { self.comeForward() }; return }   // URL before the window exists
        if background {
            background = false
            window.ignoresMouseEvents = false
            window.level = .normal
            window.collectionBehavior = []
            let occl = Selector(("_setWindowOcclusionDetectionEnabled:"))
            if web.responds(to: occl) { web.perform(occl, with: NSNumber(value: true)) }   // non-nil = YES
            window.setFrameAutosaveName("ShenpianMain")
            _ = window.setFrameUsingName("ShenpianMain")
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Quit only when nothing is unsaved (an agent never gets the 「不保存，退出」 dialog).
    func agentQuit() {
        guard let web = web else { NSApp.terminate(nil); return }
        web.evaluateJavaScript("!!(window.shell&&shell.dirty&&shell.dirty())") { r, _ in
            if (r as? Bool) == true { return }
            self.discardOK = true
            NSApp.terminate(nil)
        }
    }

    // MARK: page -> app

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        if body["cmd"] as? String == "sidebar" {   // the page hid / showed its sidebar: follow with the vibrancy view
            let shown = body["shown"] as? Bool ?? true
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.2
                sideW.animator().constant = shown ? Theme.sidebarWidth : 0
                dragW.animator().constant = shown ? Theme.sidebarWidth - Theme.dragLeading : 0
            }
            return
        }
        guard body["cmd"] as? String == "pickFolder" else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "打开（只读）"
        panel.message = "选一个项目文件夹（比如外接硬盘上的旧项目）。只读：不会写进去。"
        let drive = "/Volumes/YZY's drive/YouTube Channel"
        if FileManager.default.fileExists(atPath: drive) { panel.directoryURL = URL(fileURLWithPath: drive) }
        panel.beginSheetModal(for: window) { r in
            guard r == .OK, let url = panel.url,
                  let data = try? JSONSerialization.data(withJSONObject: [url.path]),
                  let arr = String(data: data, encoding: .utf8) else { return }
            self.web.evaluateJavaScript("shell.openPath(\(arr)[0])")
        }
    }

    @objc func toggleSidebar(_ sender: Any?) {
        web.evaluateJavaScript("window.shell&&shell.toggleSide&&shell.toggleSide()")
    }

    @objc func toggleRail(_ sender: Any?) {   // the chat rail lives in the episode pages (chat.py)
        web.evaluateJavaScript("window.shell&&shell.rail&&shell.rail()")
    }

    @objc func switchTab(_ sender: NSMenuItem) {
        web.evaluateJavaScript("window.shell&&shell.tab(\(sender.tag))")
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.runModal(); completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "好"); a.addButton(withTitle: "取消")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    // MARK: menu

    func buildMenu() {
        let main = NSMenu()
        func sub(_ title: String, _ items: [NSMenuItem]) {
            let m = NSMenu(title: title); items.forEach { m.addItem($0) }
            let it = NSMenuItem(); it.submenu = m; main.addItem(it)
        }
        func item(_ t: String, _ a: Selector?, _ k: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: a, keyEquivalent: k); i.keyEquivalentModifierMask = mods; return i
        }
        sub("审片", [item("隐藏审片", #selector(NSApplication.hide(_:)), "h"), .separator(),
                    item("退出审片", #selector(NSApplication.terminate(_:)), "q")])
        sub("编辑", [item("撤销", Selector(("undo:")), "z"), item("重做", Selector(("redo:")), "z", [.command, .shift]), .separator(),
                    item("剪切", #selector(NSText.cut(_:)), "x"), item("拷贝", #selector(NSText.copy(_:)), "c"),
                    item("粘贴", #selector(NSText.paste(_:)), "v"), item("全选", #selector(NSText.selectAll(_:)), "a")])
        let tabs = ["封面", "素材", "成片", "Shorts", "标题"].enumerated().map { (i, t) -> NSMenuItem in
            let it = item(t, #selector(switchTab(_:)), "\(i + 1)"); it.tag = i + 1; it.target = self; return it
        }
        let side = item("显示 / 隐藏边栏", #selector(toggleSidebar(_:)), "s", [.command, .control]); side.target = self
        let rail = item("显示 / 隐藏右边栏", #selector(toggleRail(_:)), "s", [.command, .option]); rail.target = self
        sub("显示", tabs + [.separator(), side, rail, item("进入全屏幕", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])])
        sub("窗口", [item("最小化", #selector(NSWindow.performMiniaturize(_:)), "m"), item("关闭", #selector(NSWindow.performClose(_:)), "w")])
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
