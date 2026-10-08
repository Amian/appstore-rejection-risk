import SwiftUI
import StoreKit

struct PaywallView: View {
    let product: Product
    var body: some View {
        VStack {
            Text(product.displayPrice).font(.largeTitle)
            Text("3 days free, then \(product.displayPrice) per year. Renews automatically, cancel any time.")
            Button("Subscribe") { Task { _ = try? await product.purchase() } }
            Button("Restore Purchases") { Task { try? await AppStore.sync() } }
            Link("Terms of Use", destination: URL(string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")!)
            Link("Privacy Policy", destination: URL(string: "https://example.com/privacy")!)
        }
    }
}
