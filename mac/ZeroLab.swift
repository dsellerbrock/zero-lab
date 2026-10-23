// Zero Lab.app: a window around the local web UI. It starts the bundled Python server,
// shows its page, and on quit closes the server's stdin so it shuts the VM down first.
import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    let server = Process()
    let toServer = Pipe()
    var quitting = false

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.navigationDelegate = self
        web.isInspectable = true
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Zero Lab"
        window.contentView = web
        window.setFrameAutosaveName("ZeroLabMain")
        window.center()
        window.makeKeyAndOrderFront(nil)
        web.loadHTMLString("<body style='font:15px -apple-system;color:#888;display:grid;place-items:center;height:90vh'>Starting Zero Lab…</body>", baseURL: nil)
        startServer()
    }

    func startServer() {
        let res = Bundle.main.resourceURL!
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Zero Lab")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)

        server.executableURL = res.appendingPathComponent("python/bin/python3")
        server.arguments = ["-E", "-s", res.appendingPathComponent("app/server.py").path, "--watch-stdin"]
        var env = ProcessInfo.processInfo.environment
        env["ZL_QEMU_DIR"] = res.appendingPathComponent("qemu").path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        server.environment = env
        server.standardInput = toServer
        server.standardError = FileHandle(forWritingAtPath: logURL.path)
        let out = Pipe()
        server.standardOutput = out
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            guard let text = String(data: h.availableData, encoding: .utf8) else { return }
            for line in text.split(separator: "\n") where line.hasPrefix("ZL_URL ") {
                let url = URL(string: String(line.dropFirst(7)))!
                DispatchQueue.main.async { self?.web.load(URLRequest(url: url)) }
            }
        }
        server.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting else { return }
                let a = NSAlert()
                a.messageText = "Zero Lab's engine stopped"
                a.informativeText = "Details are in ~/Library/Logs/Zero Lab/server.log"
                a.runModal()
                NSApp.terminate(nil)
            }
        }
        do { try server.run() } catch {
            let a = NSAlert(error: error); a.runModal(); NSApp.terminate(nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ app: NSApplication) -> NSApplication.TerminateReply {
        guard server.isRunning else { return .terminateNow }
        quitting = true
        try? toServer.fileHandleForWriting.close()  // server: stop the VM cleanly, then exit
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(75)
            while self.server.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.2) }
            if self.server.isRunning { self.server.terminate() }
            DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }

    // Open external links (docs, licences) in the user's browser, keep the app on its own page.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let host = url.host, host != "127.0.0.1", host != "localhost",
           action.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Zero Lab", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Zero Lab", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Zero Lab", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Reload", action: #selector(WKWebView.reload(_:)), keyEquivalent: "r")
        winItem.submenu = win
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
