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

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    let portFile = NSTemporaryDirectory() + "shenpian-\(getpid()).port"
    let logDir = NSHomeDirectory() + "/Library/Logs/审片"

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
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.toolbar = NSToolbar(identifier: "shenpian")
        window.toolbarStyle = .unified          // 52 pt bar, traffic lights centred in it
        window.minSize = NSSize(width: 980, height: 600)
        window.backgroundColor = Theme.bg
        window.setFrameAutosaveName("ShenpianMain")
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
        web.allowsMagnification = false
        if #available(macOS 13.3, *) { web.isInspectable = true }

        let drag = DragStrip()
        for v in [side, web!, drag] as [NSView] {
            v.translatesAutoresizingMaskIntoConstraints = false
            root.addSubview(v)
        }
        NSLayoutConstraint.activate([
            side.leadingAnchor.constraint(equalTo: root.leadingAnchor), side.topAnchor.constraint(equalTo: root.topAnchor),
            side.bottomAnchor.constraint(equalTo: root.bottomAnchor), side.widthAnchor.constraint(equalToConstant: Theme.sidebarWidth),
            web.leadingAnchor.constraint(equalTo: root.leadingAnchor), web.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            web.topAnchor.constraint(equalTo: root.topAnchor), web.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            drag.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 80),
            drag.widthAnchor.constraint(equalToConstant: Theme.sidebarWidth - 80),
            drag.topAnchor.constraint(equalTo: root.topAnchor), drag.heightAnchor.constraint(equalToConstant: Theme.toolbarHeight),
        ])
        web.loadHTMLString("<html style='font:13px -apple-system;color:#86868b'><body style='display:grid;place-items:center;height:90vh;background:transparent'>启动中…</body></html>", baseURL: nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: python server

    func startServer() {
        try? FileManager.default.createDirectory(atPath: logDir, withIntermediateDirectories: true)
        let logPath = logDir + "/app.log"
        if !FileManager.default.fileExists(atPath: logPath) { FileManager.default.createFile(atPath: logPath, contents: nil) }
        let log = FileHandle(forWritingAtPath: logPath)
        log?.seekToEndOfFile()
        try? FileManager.default.removeItem(atPath: portFile)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["-m", "src.editor.app_server", "--port-file", portFile, "--parent-pid", "\(getpid())"]
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
                u.queryItems = [URLQueryItem(name: "open", value: open), URLQueryItem(name: "tab", value: env["SHENPIAN_TAB"] ?? "")]
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

    // MARK: page -> app

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], body["cmd"] as? String == "pickFolder" else { return }
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
        sub("显示", tabs + [.separator(), item("进入全屏幕", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])])
        sub("窗口", [item("最小化", #selector(NSWindow.performMiniaturize(_:)), "m"), item("关闭", #selector(NSWindow.performClose(_:)), "w")])
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
