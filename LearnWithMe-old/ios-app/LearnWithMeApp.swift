//
//  LearnWithMeApp.swift
//  安冉的学习助手 - iPad 原生壳
//
//  使用 SwiftUI + WKWebView 包装 Web 应用，便于在 Xcode 中调试。
//  将此文件直接替换 Xcode 默认生成的 LearnWithMeApp.swift。
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

/// 主视图：全屏承载 WKWebView，并叠加一个浮动设置按钮
struct ContentView: View {
    @State private var urlString: String = AppConfig.serverURL
    @State private var showSettings: Bool = false
    @State private var reloadToken: Int = 0

    var body: some View {
        ZStack(alignment: .topTrailing) {
            // WKWebView 容器：全屏并忽略安全区，让 PWA 自身的 safe-area 生效
            WebViewContainer(urlString: urlString, reloadToken: reloadToken)
                .ignoresSafeArea(.all, edges: [.top, .bottom])

            // 浮动按钮：换地址 / 重新加载（调试时方便切换电脑 IP）
            Button(action: { showSettings = true }) {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(10)
                    .background(Color.black.opacity(0.45), in: Circle())
                    .padding(.top, 56)
                    .padding(.trailing, 14)
            }
            .accessibilityLabel("服务器设置")
        }
        .sheet(isPresented: $showSettings) {
            SettingsSheet(
                urlString: $urlString,
                reloadToken: $reloadToken,
                onReload: { reloadToken &+= 1 }
            )
            .presentationDetents([.medium])
        }
    }
}

/// 集中配置：服务器地址，便于修改
enum AppConfig {
    /// 你的电脑局域网 IP，跑起 server.py 后填这里。
    /// 也可在 App 运行时点右上角齿轮按钮临时修改。
    static let defaultServerURL = "http://10.76.189.67:8080/"

    /// 读取上一次保存的地址，没有就用默认
    static var serverURL: String {
        let saved = UserDefaults.standard.string(forKey: "serverURL")
        return saved ?? defaultServerURL
    }
}

/// WKWebView 的 SwiftUI 包装
struct WebViewContainer: UIViewRepresentable {
    let urlString: String
    /// 改变此值会触发 reload
    let reloadToken: Int

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptEnabled = true
        config.allowsInlineMediaPlayback = true
        config.allowsAirPlayForMediaPlayback = true
        // 允许在 WKWebView 内部弹窗（alert/confirm）
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        // iPadOS 上默认禁止后退/前进手势，调试时打开更顺手
        webView.allowsBackForwardNavigationGestures = true
        // 在 Debug 下打开网页检查器
        #if DEBUG
        if #available(iOS 16.4, *) {
            webView.isInspectable = true
        }
        #endif

        load(into: webView)
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // 仅在 reloadToken 改变时重新加载，避免每次状态更新都刷新
        if context.coordinator.lastReloadToken != reloadToken {
            context.coordinator.lastReloadToken = reloadToken
            load(into: uiView)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    private func load(into webView: WKWebView) {
        guard let url = URL(string: urlString) else {
            print("[LearnWithMe] 无效 URL: \(urlString)")
            return
        }
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        webView.load(request)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var lastReloadToken: Int = -1

        func webView(_ webView: WKWebView,
                     didStartProvisionalNavigation navigation: WKNavigation!) {
            print("[LearnWithMe] 开始加载: \(webView.url?.absoluteString ?? "")")
        }

        func webView(_ webView: WKWebView,
                     didFinish navigation: WKNavigation!) {
            print("[LearnWithMe] 加载完成: \(webView.url?.absoluteString ?? "")")
        }

        func webView(_ webView: WKWebView,
                     didFail navigation: WKNavigation!,
                     withError error: Error) {
            print("[LearnWithMe] 加载失败: \(error.localizedDescription)")
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

/// 服务器地址设置面板
struct SettingsSheet: View {
    @Binding var urlString: String
    @Binding var reloadToken: Int
    let onReload: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("服务器地址") {
                    TextField("http://192.168.x.x:8080/", text: $urlString)
                        .keyboardType(.URL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                    Button("保存并重新加载") {
                        let trimmed = urlString.trimmingCharacters(in: .whitespaces)
                        urlString = trimmed
                        UserDefaults.standard.set(trimmed, forKey: "serverURL")
                        onReload()
                        dismiss()
                    }
                    .buttonStyle(.borderedProminent)
                }

                Section("说明") {
                    Text("· 电脑需运行 server.py\n· iPad/电脑同 Wi-Fi\n· 用 Mac Safari 开发菜单可调试 WKWebView")
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
