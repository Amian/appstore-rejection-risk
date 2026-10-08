import SwiftUI
import StoreKit
import AVFoundation
import CoreLocation
import GoogleMobileAds

struct OnboardingView: View {
    @Environment(\.requestReview) private var requestReview
    let location = CLLocationManager()
    var body: some View {
        Text("Welcome").onAppear {
            requestReview()
            location.requestWhenInUseAuthorization()
            _ = AVCaptureDevice.default(for: .video)
        }
    }
}

final class LegacyWeb {
    let view = UIWebView()
}
