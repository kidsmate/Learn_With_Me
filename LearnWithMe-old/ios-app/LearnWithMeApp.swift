//
//  LearnWithMeApp.swift
//  LearnWithMe - iPad 原生壳
//
//  使用 SwiftUI + WKWebView 包装 Web 应用，便于在 Xcode 中调试。
//  默认从 App Bundle 加载 www/index.html（完全离线，无需 server.py）。
//  开发期可切到"远程模式"指向运行 server.py 的电脑，便于热更新调试。
//

import SwiftUI
import WebKit

@main
struct LearnWithMeApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

/// 加载模式：本地 Bundle（默认、离线） 或 远程 server.py（开发调试用）
enum LoadMode: String, CaseIterable {
    case local  = "local"   // 本地 Bundle 资源
    case remote = "remote"  // 远程 server.py

    var label: String {
        switch self {
        case .local:  return "本地（Bundle，离线）"
        case .remote: return "远程（server.py）"
        }
    }
}

/// 主视图：全屏承载 WKWebView，右上角浮动设置按钮
struct ContentView: View {
    // 默认本地模式：完全离线，无需任何服务器
    @State private var loadMode: LoadMode = LoadMode(rawValue:
        UserDefaults.standard.string(forKey: "loadMode") ?? "local") ?? .local
    @State private var remoteURLString: String = AppConfig.defaultServerURL
    @State private var showSettings: Bool = false
    @State private var reloadToken: Int = 0

    var body: some View {
        ZStack(alignment: .topTrailing) {
            WebViewContainer(
                loadMode: loadMode,
                remoteURLString: remoteURLString,
                reloadToken: reloadToken
            )
            .ignoresSafeArea(.all, edges: [.top, .bottom])

            // 浮动按钮：切换模式 / 远程地址 / 重载
            Button(action: { showSettings = true }) {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(10)
                    .background(Color.black.opacity(0.45), in: Circle())
                    .padding(.top, 56)
                    .padding(.trailing, 14)
            }
            .accessibilityLabel("设置")
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet(
                loadMode: $loadMode,
                remoteURLString: $remoteURLString,
                reloadToken: $reloadToken,
                onReload: { reloadToken &+= 1 }
            )
            .presentationDetents([.medium])
        }
    }
}

/// 集中配置
enum AppConfig {
    /// 远程模式下默认指向的 server.py 地址（你的电脑局域网 IP）。
    /// 跑起 server.py 后用 ifconfig 查 IP 替换。
    static let defaultServerURL = "http://10.76.189.67:8080/"

    /// 从 Bundle 找到 www 目录 URL
    /// 前提：在 Xcode 里以"Folder Reference"方式添加了 www 文件夹
    static var wwwDirectoryURL: URL? {
        // 方式1：用 subdirectory（推荐，需要 folder reference）
        if let url = Bundle.main.url(forResource: "www", withExtension: nil) {
            return url
        }
        // 方式2：直接找 index.html（兼容未作为子目录添加的情况）
        if let html = Bundle.main.url(forResource: "index", withExtension: "html") {
            return html.deletingLastPathComponent()
        }
        return nil
    }

    /// 本地 index.html 的 URL
    static var localIndexURL: URL? {
        Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "www")
            ?? Bundle.main.url(forResource: "index", withExtension: "html")
    }

    /// 读取上一次保存的远程地址
    static var serverURL: String {
        let saved = UserDefaults.standard.string(forKey: "serverURL")
        return saved ?? defaultServerURL
    }
}

/// WKWebView 的 SwiftUI 包装
struct WebViewContainer: UIViewRepresentable {
    let loadMode: LoadMode
    let remoteURLString: String
    /// 改变此值会触发 reload
    let reloadToken: Int

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptEnabled = true
        config.allowsInlineMediaPlayback = true
        config.allowsAirPlayForMediaPlayback = true
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        #if DEBUG
        if #available(iOS 16.4, *) {
            webView.isInspectable = true
        }
        #endif

        load(into: webView)
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // 仅在 reloadToken 或模式变更时刷新
        let sig = "\(reloadToken)|\(loadMode.rawValue)|\(remoteURLString)"
        if context.coordinator.lastSignature != sig {
            context.coordinator.lastSignature = sig
            load(into: uiView)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    private func load(into webView: WKWebView) {
        switch loadMode {
        case .local:
            // 从 App Bundle 加载本地 www/index.html
            guard let indexURL = AppConfig.localIndexURL,
                  let wwwDir = AppConfig.wwwDirectoryURL else {
                print("[LearnWithMe] ❌ Bundle 中未找到 www/index.html")
                print("[LearnWithMe] 请确认在 Xcode 里以 Folder Reference 添加了 www 目录")
                loadErrorPage(into: webView, message: "未找到本地资源 www/index.html")
                return
            }
            // allowingReadAccessTo: 让 www 内的相对路径（css/js/libs/icons）都能访问
            webView.loadFileURL(indexURL, allowingReadAccessTo: wwwDir)
            print("[LearnWithMe] 📦 本地模式加载: \(indexURL.path)")

        case .remote:
            guard let url = URL(string: remoteURLString) else {
                print("[LearnWithMe] ❌ 无效远程 URL: \(remoteURLString)")
                return
            }
            var request = URLRequest(url: url)
            request.cachePolicy = .reloadIgnoringLocalCacheData
            webView.load(request)
            print("[LearnWithMe] 🌐 远程模式加载: \(remoteURLString)")
        }
    }

    private func loadErrorPage(into webView: WKWebView, message: String) {
        let html = """
        <!doctype html><meta charset="utf-8">
        <style>body{font-family:-apple-system;padding:40px;color:#c0392b}
        h1{font-size:22px;margin-bottom:12px}
        p{font-size:15px;line-height:1.6;color:#555}</style>
        <h1>⚠️ 本地资源加载失败</h1>
        <p>\(message)</p>
        <p>请确认已按以下步骤操作：</p>
        <ol style="font-size:14px;line-height:1.8;color:#555">
        <li>把 www 文件夹拖入 Xcode 项目导航器</li>
        <li>勾选 "Copy items if needed"</li>
        <li>选择 "Create folder references"（蓝色文件夹，不是黄色组）</li>
        <li>勾选当前 Target</li>
        </ol>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var lastSignature: String = ""

        func webView(_ webView: WKWebView,
                     didStartProvisionalNavigation navigation: WKNavigation!) {
            print("[LearnWithMe] 开始加载: \(webView.url?.absoluteString ?? "")")
        }

        func webView(_ webView: WKWebView,
                     didFinish navigation: WKNavigation!) {
            print("[LearnWithMe] 加载完成")
        }

        func webView(_ webView: WKWebView,
                     didFail navigation: WKNavigation!,
                     withError error: Error) {
            print("[LearnWithMe] 加载失败: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView,
                     didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            print("[LearnWithMe] 预加载失败: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView,
                     createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction,
                     windowFeatures: WKWindowFeatures) -> WKWebView? {
            // target=_blank 链接在当前 WebView 打开，避免被系统 Safari 接管
            if let url = navigationAction.request.url {
                webView.load(URLRequest(url: url))
            }
            return nil
        }
    }
}

/// 设置面板：模式切换 + 远程地址
struct SettingsSheet: View {
    @Binding var loadMode: LoadMode
    @Binding var remoteURLString: String
    @Binding var reloadToken: Int
    let onReload: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("加载模式") {
                    Picker("模式", selection: $loadMode) {
                        ForEach(LoadMode.allCases, id: \.self) { m in
                            Text(m.label).tag(m)
                        }
                    }
                    .pickerStyle(.segmented)

                    Button("应用并重新加载") {
                        UserDefaults.standard.set(loadMode.rawValue, forKey: "loadMode")
                        if loadMode == .remote {
                            let trimmed = remoteURLString.trimmingCharacters(in: .whitespaces)
                            remoteURLString = trimmed
                            UserDefaults.standard.set(trimmed, forKey: "serverURL")
                        }
                        onReload()
                        dismiss()
                    }
                    .buttonStyle(.borderedProminent)
                }

                if loadMode == .remote {
                    Section("远程服务器地址（server.py）") {
                        TextField("http://192.168.x.x:8080/", text: $remoteURLString)
                            .keyboardType(.URL)
                            .autocapitalization(.none)
                            .disableAutocorrection(true)
                    }
                }

                Section("说明") {
                    if loadMode == .local {
                        Text("本地模式：所有资源已打包进 App Bundle，完全离线运行，无需任何服务器。\nPDF 提取由前端 PDF.js 完成。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("远程模式：需电脑运行 server.py（python3 server.py）。\niPad/电脑同 Wi-Fi。\n适合开发时热更新代码，无需重打 App。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text("· 用 Mac Safari 开发菜单可调试 WKWebView")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("设置")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
        }
    }
}
