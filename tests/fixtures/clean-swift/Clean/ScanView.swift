import SwiftUI
import AVFoundation

struct ScanView: View {
    @AppStorage("scans") private var scans = 0
    var body: some View {
        Text("Scans: \(scans)").onAppear { _ = AVCaptureDevice.default(for: .video) }
    }
}
