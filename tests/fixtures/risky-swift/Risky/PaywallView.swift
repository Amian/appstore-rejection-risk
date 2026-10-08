import SwiftUI
import StoreKit

struct PaywallView: View {
    @State private var showClose = false
    var body: some View {
        VStack {
            Text("Start your free trial")
            Text("Just $0.19 a day")
            Text("$69.99")
            Button("Continue") { Task { _ = try? await Product.products(for: ["com.example.risky.annual"]) } }
        }
        .onAppear {
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) { showClose = true } // close button fades in
        }
    }
}
