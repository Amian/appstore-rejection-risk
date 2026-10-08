"""The checklist. One entry per App Review risk that can be spotted in an iOS codebase.

Works for native (Swift / Objective-C), Flutter, React Native / Expo and Capacitor / Ionic.
Fields:
  id       short stable id (shown in the report)
  g        App Review Guideline number
  title    what is wrong, in plain words
  reject   % chance the next submission is rejected IF the finding is real
  ban      % chance it leads to account-level action (5.6 warning, Extended Review,
           termination) IF real. Most rejections carry no ban risk at all.
  kind     "present"  pattern found = finding
           "missing"  `when` found but `need` found nowhere = finding
  files    file groups to search: code, native, paywall, strings, plist, deps, privacy
           ("paywall" = code files whose path looks like a paywall / store / subscription screen)
  path     only keep hits whose file path matches this regex
  literal  only match inside string literals in code files (cuts comment/identifier noise)
  ui       (literal only) only literals containing a space, i.e. user-facing text, not IDs
  counter  (present only) regex reported as found / NOT FOUND, e.g. a disclaimer
  extract  regex whose group 1 is listed as "keys:" (e.g. remote-config flag names)
  case     match case-sensitively (for SDK names that are also common words)
  definitive  True = a hit is a violation as-is, no need to open the file
  hint     how to judge a hit in one read

How the percentages were set: Apple's App Review Guidelines and "Avoiding common issues"
page, Apple's App Store Transparency Reports (2.1 completeness, 5.1 privacy, 4.x design and
2.3 metadata are the most-cited reasons every year), and how mechanically each rule is
enforced. Automated upload checks (missing purpose string, UIWebView) are near-certain;
judgement calls (vague copy, review-prompt timing) are lower. Ban % is non-zero only where
Apple's Developer Code of Conduct (5.6) treats the behaviour as dishonest.
"""

# Reusable patterns (native | Flutter | React Native / Expo | Capacitor) ----------
PURCHASE = (r"Product\.products\(|SKProductsRequest|SKPaymentQueue|Purchases\.shared|"
            r"purchasePackage|purchaseProduct|purchases_flutter|in_app_purchase|InAppPurchase|"
            r"RevenueCatUI|PaywallView|\.purchase\(|react-native-iap|requestSubscription|"
            r"requestPurchase|react-native-purchases|expo-in-app-purchases|"
            r"cordova-plugin-purchase|@capacitor-community/in-app-purchases|Adapty|Qonversion|"
            r"Superwall")
AD_SDK = (r"ASIdentifierManager|advertisingIdentifier|GoogleMobileAds|google_mobile_ads|"
          r"react-native-google-mobile-ads|@capacitor-community/admob|FBAudienceNetwork|"
          r"AppLovinSDK|applovin_max|react-native-applovin|AppsFlyerLib|appsflyer_sdk|"
          r"react-native-appsflyer|AdjustSdk|adjust_sdk|ADJConfig|react-native-adjust|"
          r"BranchSDK|flutter_branch_sdk|react-native-branch|KochavaTracker|IronSource|"
          r"UnityAds|VungleSDK|Chartboost|FBSDKCoreKit|facebook_app_events|react-native-fbsdk|"
          r"TikTokBusinessSDK|SingularSDK|MetaAudienceNetwork|TenjinSDK|tenjin|Mintegral|"
          r"PAGSdk|Pangle|InMobiSDK|Liftoff")
ATT_CALL = (r"requestTrackingAuthorization|app_tracking_transparency|AppTrackingTransparency|"
            r"expo-tracking-transparency|requestTrackingPermissions|react-native-tracking-transparency")
THIRD_AI = (r"api\.openai\.com|OpenAI\(|new OpenAI|generativelanguage\.googleapis|"
            r"GenerativeModel\(|google_generative_ai|@google/generative-ai|@google/genai|"
            r"firebase_vertexai|FirebaseVertexAI|FirebaseAI|firebase_ai|api\.anthropic\.com|"
            r"@anthropic-ai/sdk|api\.replicate\.com|fal\.run|queue\.fal|fal_client|@fal-ai|"
            r"api\.stability\.ai|api\.together|api\.groq\.com|openrouter\.ai|api\.deepseek|"
            r"api\.mistral\.ai|api\.elevenlabs\.io")
# Well-known brands and Apple trademarks that reviewers flag in names and app text.
IP_TERMS = (r"\b(disney|pixar|marvel|star wars|ghibli|pok[eé]mon|nintendo|minecraft|fortnite|"
            r"roblox|chatgpt|spotify|netflix|tiktok|instagram|whatsapp|snapchat|youtube|"
            r"beats by|apple watch|airpods|facetime|imessage)\b")

CHECKS = [
    # ---- Payments and subscriptions (3.1) --------------------------------------
    dict(id="PAY-TERMS", g="3.1.2", reject=75, ban=0, kind="missing",
         title="Subscriptions sold but no Terms (EULA) / Privacy Policy links in the app",
         when=PURCHASE, when_files="code deps",
         need=r"stdeula|terms[-_ ]?of[-_ ]?(use|service)|/terms|/eula|termsUrl|termsURL|eula",
         need_files="code strings plist",
         hint="3.1.2 requires functional Terms and Privacy links in the purchase flow."),
    dict(id="PAY-RESTORE", g="3.1.1", reject=70, ban=0, kind="missing",
         title="Purchases but no Restore Purchases",
         when=PURCHASE, when_files="code deps",
         need=r"restorePurchases|restoreCompletedTransactions|AppStore\.sync|restore",
         need_files="code strings",
         definitive=True, hint="Restorable purchases need a visible Restore control."),
    dict(id="PAY-HARDPRICE", g="3.1.2", reject=45, ban=0, kind="present",
         title="Hard-coded price on the paywall", files="paywall", literal=True,
         pat=r"\$\s?\d+[.,]\d{2}\b|[£€¥₹]\s?\d+|\d+[.,]\d{2}\s?(?:USD|EUR|GBP|[$£€])",
         hint="Fine only as a never-shown fallback. Shown prices must come from the store "
              "(StoreKit displayPrice / localizedPriceString), or they are wrong in other "
              "storefronts."),
    dict(id="PAY-TRIAL", g="3.1.2", reject=50, ban=0, kind="missing",
         title="Trial / 'free' offered without saying payment starts automatically",
         when=r"free trial|days? free|introductoryOffer|introductoryPrice|introPrice|start (my |your )?trial",
         when_files="code strings",
         need=r"auto-?renew|renews automatically|automatically (renew|charge|bill)|"
              r"then [^\"\n]{0,30}(per|/|a) ?(week|month|year)|cancel any ?time",
         need_files="code strings",
         hint="Must say e.g. '3 days free, then $4.99 per week'. ALSO open the paywall view once: "
              "the billed amount must be the most prominent price; per-week equivalents and "
              "'FREE' must be smaller. Misleading price emphasis is a very common 3.1.2 rejection."),
    dict(id="PAY-EXTERNAL", g="3.1.1 / 3.1.3", reject=80, ban=15, kind="present",
         title="Payment outside In-App Purchase (web checkout, Stripe, licence keys)",
         files="code deps", literal=False,
         pat=r"\bstripe\b|StripePaymentSheet|flutter_stripe|@stripe/stripe-react-native|paypal|"
             r"braintree|paddle\.com|lemonsqueezy|gumroad\.com|ko-fi\.com|buymeacoffee|patreon\.com|"
             r"/checkout|/pricing|buy on (our )?(web|site)|license key|licence key|activation code",
         hint="Digital content must use IAP. Physical goods and real-world services are fine, as "
              "are reader apps and storefronts with Apple's link-out entitlement. If a remote "
              "flag shows this only after review, ban risk is high."),
    dict(id="PAY-HIDDEN-UNLOCK", g="2.3.1 / 3.1.1", reject=40, ban=20, kind="present",
         title="Hidden premium unlock (reviewer/secret/promo code, forced premium)",
         files="code", literal=False,
         pat=r"reviewer ?code|secret ?code|unlock ?code|cheat ?code|debugUnlock|forcePremium|"
             r"grantPremium|godMode|backdoor",
         hint="Apple Offer Codes (presentCodeRedemptionSheet / offerCodeRedemption) are fine. "
              "Any other way to unlock paid content without IAP is a hidden feature unless it "
              "is debug-only or disclosed in App Review Notes."),

    dict(id="PAY-EQUIV-PRICE", g="3.1.2(c)", reject=45, ban=2, kind="present",
         title="Per-week / per-day equivalent price on the paywall", files="paywall", literal=False,
         pat=r"pricePer(Week|Day|Month)|per(Week|Day|Month)Price|weekly_?equivalent|equivalent|"
             r"/\s*(52|30|365|12)(\.0)?\b|\bper day\b|a day\b|/day|/wk|/mo\b",
         hint="Allowed only if the amount actually billed is clearly the largest, most prominent "
              "price. 'Just $0.19/day' in big type over a small annual price is rejected."),
    # PAY-CLOSE-DELAY and PAY-TRIAL-TOGGLE are multi-line checks in scan.py.

    # ---- Dishonest behaviour: the ban-level items (2.3.1, 2.5.2, 3.2(f), 5.6) --
    dict(id="HONEST-REVIEWMODE", g="2.3.1 / 5.6", reject=60, ban=40, kind="present",
         title="Code that detects App Review and may change behaviour",
         files="code", literal=False,
         pat=r"isInReview|inReview\b|isReviewMode|review_?mode|isAppReview|appReviewMode|"
             r"iPhone99|isUnderReview|under_review|hide_?(for|from|during)_?review|reviewer_?(mode|device|ip)|"
             r"\baudit_?mode\b|\bisAuditing\b|\bshenhe\b|show_?(real|hidden|full)_?(app|content|feature)|"
             r"enable_?(external|web)_?(pay|purchase|checkout)",
         hint="Any branch that shows Apple a different app than users get is grounds for "
              "termination (5.6). Analytics-only filtering of review devices is fine."),
    dict(id="HONEST-SANDBOX", g="2.3.1", reject=50, ban=20, kind="present",
         title="Behaviour branches on sandbox / TestFlight (App Review uses sandbox)",
         files="code", literal=False,
         pat=r"sandboxReceipt|appStoreReceiptURL[^\n]{0,80}sandbox|isTestFlight|"
             r"environment\s*==\s*\.?(sandbox|xcode)|AppTransaction[^\n]{0,80}sandbox",
         hint="Fine when it only picks the receipt-validation URL or hides debug menus. A violation "
              "if features, prices or content differ in sandbox, because reviewers then see a "
              "different app."),
    dict(id="HONEST-REMOTEGATE", g="2.3.1 / 3.2(f)", reject=15, ban=35, kind="present",
         title="Remote config / feature flags (check what they switch)",
         files="code", literal=False,
         pat=r"RemoteConfig\.remoteConfig|FirebaseRemoteConfig|firebase_remote_config|"
             r"@react-native-firebase/remote-config|Statsig|LaunchDarkly|ConfigCat|"
             r"FeatureFlag|featureFlag",
         extract=r"(?:getBool|getString|getInt|getDouble|getValue|getJson|getBoolean|"
                 r"configValue\(forKey:|remoteConfig\[|checkGate|getFeatureFlag)\(?\s*"
                 r"[\"']([\w.-]+)[\"']",
         hint="Fine for copy, price tests and kill switches. A violation only if a flag turns on "
              "undisclosed features, web payments, gambling or different content after review. "
              "Read the flag names and their definition file; do not read every caller."),
    dict(id="HONEST-HOTCODE", g="2.5.2 / 3.3.1(b)", reject=60, ban=25, kind="present",
         title="Downloads or runs code that changes the app after review",
         files="code deps", literal=False,
         pat=r"JSPatch|Rollout\.io|dlopen\(|NSClassFromString\(.*download|CodePush|code-push|"
             r"code_push|evaluateScript\(.*(http|download|remote)|hot ?update|hotfix ?bundle",
         hint="Executable code from a server is not allowed. Exception: JS/web updates (Expo "
              "Updates, CodePush, Capacitor live updates) that do not change the app's primary "
              "purpose or add features beyond what was reviewed. Shorebird claims compliance."),
    dict(id="HONEST-PRIVATEAPI", g="2.5.1", reject=75, ban=5, kind="present",
         title="Private or undocumented API use", files="native", literal=False,
         pat=r"LSApplicationWorkspace|_UIStatusBar|UIStatusBar_Modern|MobileGestalt|MGCopyAnswer|"
             r"NSSelectorFromString\(\s*@?\"_|valueForKey:\s*@\"_|forKey:\s*\"_|"
             r"\bSpringBoard\b|IOKit/|prefs:root|App-Prefs:|UIGetScreenImage|_setBackgroundStyle",
         definitive=True, hint="Usually caught automatically at upload or review."),
    dict(id="HONEST-RATING", g="5.6.1 / 3.2.2", reject=50, ban=10, kind="present",
         title="Rating gate, custom 'rate us' prompt or reward for reviews",
         files="code strings", literal=True, ui=True,
         pat=r"rate (us|the app|this app)? ?(5|five)\b|\b(5|five)[- ]stars?\b|"
             r"(enjoying|like|love|happy with) (the |this |our )?app\?|"
             r"unlock[^\"\n]{0,30}(rate|review)|(rate|review)[^\"\n]{0,30}(unlock|reward|bonus)",
         hint="Only the system review prompt is allowed: no custom star sheet, no pre-question "
              "that sends only happy users to the store, no reward. Incentivised or filtered "
              "reviews are manipulation under 5.6."),
    dict(id="HONEST-RATING-CUSTOM", g="5.6.1", reject=30, ban=2, kind="present",
         title="Custom star-rating UI (instead of the system review prompt)",
         files="code deps", literal=False,
         pat=r"RatingBar|StarRating|rating_bar|flutter_rating|smooth_star_rating|RatingView\(|"
             r"StarsView\(|react-native-ratings|react-native-rating",
         hint="Fine for rating content inside the app (a recipe, a scan result). A violation if it "
              "asks the user to rate the app itself or decides who gets the system prompt."),
    dict(id="HONEST-REVIEWTIMING", g="5.6.1", reject=45, ban=0, kind="present",
         title="Review prompt in onboarding / first-launch code",
         files="code", literal=False,
         path=r"onboard|splash|launch|AppDelegate|main\.dart$|App\.swift$|App\.tsx?$|welcome|intro|"
              r"_layout\.tsx?$|first_?run|getting_?started",
         pat=r"requestReview|SKStoreReviewController|RequestReviewAction|InAppReview\.instance|"
             r"in_app_review|expo-store-review|react-native-in-app-review|"
             r"@capacitor-community/in-app-review",
         hint="Open the call site once. Reviewers reject prompts fired at launch, in onboarding "
              "or before the user got any value. An import alone, or a call reached only later "
              "in the app, is fine."),
    dict(id="HONEST-FAKE", g="2.3.1 / 5.6", reject=80, ban=30, kind="present",
         title="Fake system alerts, fake scans or fake functionality",
         files="code strings", literal=True,
         pat=r"virus (detected|found)|(device|iphone|phone) is (infected|slow|at risk)|"
             r"battery (is )?damaged|ram boost|junk files? (found|detected)",
         definitive=True, hint=""),
    dict(id="HONEST-MINING", g="3.1.5(b)", reject=95, ban=50, kind="present",
         title="Crypto mining code", files="code deps", literal=False,
         pat=r"coinhive|xmrig|cryptonight|monero ?miner|webminer",
         definitive=True, hint=""),

    # ---- Privacy (5.1) ----------------------------------------------------------
    dict(id="PRIV-ATT-MISSING", g="5.1.2", reject=85, ban=2, kind="missing",
         title="Advertising / attribution SDK or IDFA without an ATT prompt",
         when=AD_SDK, when_files="code deps", need=ATT_CALL, need_files="code deps", case=True,
         hint="Either request ATT before any tracking SDK collects data, or remove the SDK. "
              "The App Privacy label must match."),
    dict(id="PRIV-ATT-NOTRACK", g="5.1.2", reject=35, ban=0, kind="missing",
         title="ATT prompt shown but no tracking SDK found",
         when=ATT_CALL, when_files="code deps", need=AD_SDK, need_files="code deps", case=True,
         hint="Dismiss if a tracking SDK exists that this list does not know. Otherwise the ATT "
              "prompt and an App Privacy label saying 'used to track you' look unjustified."),
    dict(id="PRIV-ATT-KEY", g="5.1.2", reject=95, ban=0, kind="missing",
         title="ATT requested but NSUserTrackingUsageDescription missing (crash)",
         when=r"requestTrackingAuthorization|requestTrackingPermissions", when_files="code",
         need=r"NSUserTrackingUsageDescription|userTrackingPermission", need_files="plist strings",
         definitive=True, hint=""),
    dict(id="PRIV-ATT-PREPROMPT", g="5.1.1(iv) / 5.1.2", reject=35, ban=2, kind="present",
         title="Custom pre-prompt before ATT that pushes or rewards 'Allow'",
         files="code strings", literal=True, ui=True,
         pat=r"(allow|enable)[^\n]{0,30}(track|personali[sz]ed ads)|"
             r"(track|personali[sz]ed)[^\n]{0,40}(reward|free|unlock|bonus)",
         hint="An explainer screen is fine. Offering a reward for allowing tracking, or a fake "
              "'Allow' button that mimics the system alert, is rejected."),
    dict(id="PRIV-LOCATION-ALWAYS", g="5.1.1", reject=30, ban=0, kind="present",
         title="Asks for 'Always' location", files="code plist", literal=False,
         pat=r"requestAlwaysAuthorization|NSLocationAlwaysAndWhenInUseUsageDescription|"
             r"requestBackgroundPermissionsAsync",
         hint="Only justified if a core feature works in the background (navigation, geofencing). "
              "Otherwise ask for When In Use."),
    dict(id="PRIV-FACE-DATA", g="5.1.2(vi) / 2.1", reject=40, ban=0, kind="present",
         title="Processes face data (reviewers ask how it is handled)",
         files="code deps", literal=False,
         pat=r"VNDetectFace|ARFaceTrackingConfiguration|FaceDetector|faceLandmarks|"
             r"google_mlkit_face|CIDetectorTypeFace|expo-face-detector|face-api",
         hint="The privacy policy needs a face-data section (what, why, third parties, retention) "
              "and App Review Notes should say it. Missing that commonly triggers a 2.1 "
              "information request or a 5.1.2(vi) rejection."),
    dict(id="PRIV-ACCOUNT-DELETE", g="5.1.1(v)", reject=85, ban=0, kind="missing",
         title="Accounts can be created but not deleted in the app",
         when=r"createUser\(|createUserWithEmailAndPassword|signUp\(|SignInWithAppleButton|"
              r"ASAuthorizationAppleIDProvider|GIDSignIn|google_sign_in|signInWithCredential|"
              r"sign_in_with_apple|auth\.signUp|Auth0|@clerk/|@react-native-google-signin",
         when_files="code deps",
         need=r"delete ?account|deleteAccount|deleteUser|\.delete\(\)|account deletion|remove account",
         need_files="code strings",
         hint="Anonymous auth only is not an account: dismiss. Deletion must start in the app, "
              "not only via a website or email."),
    dict(id="PRIV-SIWA", g="4.8", reject=75, ban=0, kind="missing",
         title="Google / Facebook login without Sign in with Apple or an equal option",
         when=r"GIDSignIn|google_sign_in|signInWithGoogle|FBSDKLoginKit|flutter_facebook_auth|"
              r"@react-native-google-signin|react-native-fbsdk",
         when_files="code deps",
         need=r"ASAuthorizationAppleIDProvider|SignInWithAppleButton|sign_in_with_apple|"
              r"AppleAuthProvider|expo-apple-authentication|apple-authentication",
         need_files="code deps",
         hint="4.8 wants a login option that limits data to name and email and lets users hide "
              "their email. Exempt: your own account system only, education/enterprise logins."),
    dict(id="PRIV-AI-CONSENT", g="5.1.1(i) / 5.1.2(i)", reject=60, ban=0, kind="missing",
         title="User content sent to a third-party AI without an in-app consent step",
         when=THIRD_AI, when_files="code deps",
         need=r"aiConsent|AIConsent|ai_consent|consent(Sheet|View|Screen|Given|Accepted|Key)|"
              r"hasConsented|didConsent|dataSharingConsent|"
              r"(send|share)s? (your )?(photos?|images?|data|text|content)[^\"\n]{0,40}"
              r"(OpenAI|Google|Gemini|Anthropic|third)",
         need_files="code strings",
         hint="Since Nov 2025, 5.1.2(i) requires clearly disclosing that personal data goes to "
              "third-party AI and getting permission first. A privacy policy alone is not enough. "
              "If the app calls its own backend that forwards to an AI, the same applies."),
    dict(id="PRIV-FORCED-DATA", g="5.1.1(ii)", reject=35, ban=0, kind="present",
         title="Asks for personal data the core feature may not need",
         files="strings code", literal=True, ui=True,
         pat=r"date of birth|your birthday|enter your (age|email|phone|name)|phone number",
         hint="Optional fields are fine. Rejected if the app blocks its core feature behind data "
              "it does not need."),
    dict(id="PRIV-ATS", g="5.1.1 / 2.5", reject=10, ban=0, kind="present",
         title="App Transport Security disabled globally", files="plist", literal=False,
         pat=r"NSAllowsArbitraryLoads</key>\s*<true|NSAllowsArbitraryLoads\s*=\s*(YES|true)|"
             r"\"NSAllowsArbitraryLoads\"\s*:\s*true",
         hint="Low risk; narrow it to specific domains if you can."),

    # ---- Completeness and content (2.1, 2.3, 1.x, 4.x) --------------------------
    dict(id="DONE-UIWEBVIEW", g="2.5.1", reject=100, ban=0, kind="present",
         title="UIWebView (deprecated, upload is refused)", files="native", literal=False,
         pat=r"\bUIWebView\b", definitive=True, hint=""),
    dict(id="DONE-PLACEHOLDER", g="2.1 / 2.3.10", reject=45, ban=0, kind="present",
         title="Placeholder or unfinished text in the UI", files="code strings", literal=True, ui=True,
         pat=r"lorem ipsum|coming soon|placeholder text|\bTBD\b|dummy (data|text)|test ?user|"
             r"Flutter Demo|Welcome to React Native|YourAppName|\bMyApp\b",
         hint="Ignore if only in previews, tests or debug builds."),
    dict(id="DONE-BETA", g="2.2", reject=35, ban=0, kind="present",
         title="Beta / demo / test-version wording in the UI", files="code strings", literal=True, ui=True,
         pat=r"\b(beta version|demo version|trial version|test version|test build)\b",
         hint="Betas belong in TestFlight. Dismiss if it is about a trial subscription."),
    dict(id="DONE-DEVURL", g="2.1", reject=25, ban=0, kind="present",
         title="Localhost / staging / ngrok URL in code", files="code plist", literal=True,
         pat=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+|192\.168\.|[^\"' ]*(staging|ngrok|\.local\b))",
         hint="Fine if only used in debug builds."),
    dict(id="DONE-OTHERPLATFORM", g="2.3.10", reject=40, ban=0, kind="present",
         title="Mentions Android / Google Play in iOS UI text", files="code strings", literal=True, ui=True,
         pat=r"\bandroid\b|google play|play store",
         hint="Fine if only shown on Android (Platform.isAndroid / Platform.OS === 'android') "
              "or never shown. Cross-platform apps often leak this."),
    dict(id="CONTENT-WEBWRAP", g="4.2 / 4.2.2", reject=55, ban=0, kind="present",
         title="Web view loads a remote site: check the app is more than a wrapped website",
         files="code", literal=False,
         pat=r"load\(URLRequest\(url:\s*URL\(string:\s*\"https?://|WebView\(.*https?://|"
             r"initialUrlRequest|loadRequest\(Uri\.parse\(['\"]https?://|"
             r"source=\{\{\s*uri:\s*['\"]https?://|server:\s*\{\s*url:",
         hint="Rejected if the main experience is a website in a frame. Fine for help pages, "
              "legal pages or a single embedded feature. Compare with the source-file count."),
    dict(id="CONTENT-MEDICAL", g="1.4.1 / 1.1.6", reject=55, ban=5, kind="present",
         title="Health, medical or financial claims that may mislead",
         files="strings code", literal=True, ui=True,
         pat=r"diagnos|\bcures?\b|safe to (take|eat)|\d{2}(\.\d)?% accura|"
             r"clinically|guaranteed (profit|returns|results)|buy signal|sell signal",
         counter=r"not (a |intended as )?(medical|financial|investment) advice|consult (a|your) "
                 r"(doctor|physician|pharmacist|professional|advisor)|informational purposes|"
                 r"sources?:|citations?|references?:",
         hint="Claims that could harm users if wrong need disclaimers, sources and evidence. "
              "Unbackable accuracy claims are rejected under 1.4.1 and 2.3.1."),
    dict(id="CONTENT-HEALTH-CITES", g="1.4.1", reject=50, ban=5, kind="missing",
         title="Health / medication information with no source citations in the app",
         when=r"\b(pills?|medications?|medicines?|drugs?|dosage|symptoms?|side effects|"
              r"supplements?|blood (pressure|sugar))\b",
         when_files="strings",
         need=r"dailymed|medlineplus|nlm\.nih|fda\.gov|nhs\.uk|who\.int|pubmed|drugs\.com|"
              r"\b(sources|citations|references)\b|data from",
         need_files="code strings",
         hint="Apps giving health or medical information should link the sources it comes "
              "from, inside the app. Dismiss if the app is not about health."),
    dict(id="CONTENT-IP", g="4.1 / 5.2", reject=50, ban=5, kind="present",
         title="Third-party brand or IP in app text", files="strings code plist", literal=True,
         pat=IP_TERMS,
         hint="Using another company's brand, characters or style name without permission is "
              "rejected under 5.2. Generic words ('anime', 'cartoon') are fine; a factual "
              "mention ('share to Instagram') usually is too. Repeat IP strikes can escalate."),
    dict(id="CONTENT-KIDS", g="1.3 / 2.3", reject=40, ban=0, kind="present",
         title="Wording aimed at children", files="strings code", literal=True, ui=True,
         pat=r"for kids|for children|kids app|toddlers?|preschool|ages? [2-9]\b",
         hint="Only fine if the app is in the Kids category, which then bans most third-party "
              "analytics and ads and needs a parental gate."),
    dict(id="CONTENT-UGC", g="1.2", reject=65, ban=0, kind="missing",
         title="Users can share content with others but no report/block",
         when=r"createPost|uploadPost|addComment|postComment|collection\([\"'](posts|comments|feed)|"
              r"publicGallery|shareToCommunity|communityFeed",
         when_files="code",
         need=r"report|blockUser|block user|flag ?content|moderat", need_files="code strings",
         hint="A private AI chat is not UGC. Content other users can see needs filtering, "
              "reporting, blocking and a published contact."),
    dict(id="CONTENT-GAMBLING", g="5.3 / 3.1.1", reject=50, ban=5, kind="present",
         title="Gambling, loot boxes or real-money games", files="strings code", literal=True, ui=True,
         pat=r"loot ?box|gacha|spin to win|real money|casino|place (a |your )?bet",
         hint="Loot boxes must disclose odds; real-money gambling needs licences, geo limits and "
              "an organisation account."),
    dict(id="CONTENT-CRYPTO", g="3.1.5", reject=40, ban=0, kind="present",
         title="Crypto wallet, trading or exchange features", files="code deps strings", literal=False,
         pat=r"walletconnect|web3dart|web3swift|ethers\b|buy (bitcoin|crypto)|crypto exchange",
         hint="Exchanges and wallets need an organisation account and licences where required. "
              "Price charts alone are fine."),
    dict(id="CONTENT-VPN", g="5.4", reject=50, ban=0, kind="present",
         title="VPN / Network Extension entitlement", files="plist", literal=False,
         pat=r"com\.apple\.developer\.networking\.networkextension|NEVPNManager",
         hint="Needs an organisation account and a clear data-use description."),
]

# Purpose strings: API pattern -> any of these Info.plist keys must exist.
# (Expo apps declare them in app.json under ios.infoPlist, which is scanned as "plist".)
PURPOSE_KEYS = [
    (r"AVCaptureDevice|AVCaptureSession|sourceType\s*=\s*\.camera|ImageSource\.camera|"
     r"package:camera/|CameraController\(|expo-camera|react-native-vision-camera|"
     r"launchCamera|@capacitor/camera", ["NSCameraUsageDescription"]),
    (r"PHPhotoLibrary\.requestAuthorization|PHAsset\.fetch|UIImagePickerController|"
     r"ImageSource\.gallery|package:image_picker|expo-image-picker|launchImageLibrary|"
     r"expo-media-library|@react-native-camera-roll", ["NSPhotoLibraryUsageDescription"]),
    (r"UIImageWriteToSavedPhotosAlbum|PHAssetChangeRequest|PHAssetCreationRequest|"
     r"image_gallery_saver|package:gal/|saveImageToGallery|saveToLibraryAsync|CameraRoll\.save",
     ["NSPhotoLibraryAddUsageDescription", "NSPhotoLibraryUsageDescription"]),
    (r"AVAudioRecorder|requestRecordPermission|installTap\(onBus|package:record/|"
     r"flutter_sound|speech_to_text|expo-av.*Recording|Audio\.Recording|react-native-audio-recorder",
     ["NSMicrophoneUsageDescription"]),
    (r"SFSpeechRecognizer|speech_to_text|@react-native-voice", ["NSSpeechRecognitionUsageDescription"]),
    (r"CLLocationManager|requestWhenInUseAuthorization|package:geolocator|package:location/|"
     r"expo-location|react-native-geolocation|@capacitor/geolocation",
     ["NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription"]),
    (r"requestAlwaysAuthorization|requestBackgroundPermissionsAsync",
     ["NSLocationAlwaysAndWhenInUseUsageDescription"]),
    (r"CNContactStore|flutter_contacts|contacts_service|expo-contacts|react-native-contacts",
     ["NSContactsUsageDescription"]),
    (r"EKEventStore|device_calendar|expo-calendar",
     ["NSCalendarsUsageDescription", "NSCalendarsFullAccessUsageDescription",
      "NSCalendarsWriteOnlyAccessUsageDescription"]),
    (r"CMMotionActivityManager|CMPedometer|expo-sensors.*Pedometer", ["NSMotionUsageDescription"]),
    (r"LAContext|evaluatePolicy|package:local_auth|expo-local-authentication|react-native-biometrics",
     ["NSFaceIDUsageDescription"]),
    (r"CBCentralManager|CBPeripheralManager|flutter_blue|flutter_reactive_ble|react-native-ble",
     ["NSBluetoothAlwaysUsageDescription"]),
    (r"HKHealthStore|package:health/|react-native-health", ["NSHealthShareUsageDescription", "NSHealthUpdateUsageDescription"]),
    (r"NFCNDEFReaderSession|NFCTagReaderSession|nfc_manager|react-native-nfc-manager", ["NFCReaderUsageDescription"]),
    (r"NWBrowser|NetServiceBrowser", ["NSLocalNetworkUsageDescription"]),
]

# Background modes: declared mode -> code that justifies it (2.5.4).
BG_MODES = {
    "audio": r"AVAudioSession|AVAudioPlayer|AVPlayer|just_audio|audioplayers|audio_service|"
             r"AVAudioEngine|expo-av|react-native-track-player|expo-audio",
    "location": r"startUpdatingLocation|allowsBackgroundLocationUpdates|startMonitoringSignificant|"
                r"geolocator|startLocationUpdatesAsync|react-native-background-geolocation",
    "voip": r"PKPushRegistry|CallKit|CXProvider|react-native-callkeep",
    "bluetooth-central": r"CBCentralManager|flutter_blue|flutter_reactive_ble|react-native-ble",
    "bluetooth-peripheral": r"CBPeripheralManager",
    "fetch": r"BGTaskScheduler|BGAppRefreshTask|setMinimumBackgroundFetchInterval|workmanager|"
             r"background_fetch|expo-background-fetch|expo-background-task",
    "processing": r"BGTaskScheduler|BGProcessingTask|workmanager|expo-background-task",
    "remote-notification": r"registerForRemoteNotifications|FirebaseMessaging|firebase_messaging|"
                           r"didReceiveRemoteNotification|OneSignal|expo-notifications|"
                           r"@react-native-firebase/messaging|@capacitor/push-notifications",
}

# Privacy manifest: required-reason API category -> the app's OWN native code that uses it.
# (Flutter plugins, pods and npm packages ship their own manifests.)
REQUIRED_REASON = {
    "NSPrivacyAccessedAPICategoryUserDefaults": r"UserDefaults|NSUserDefaults|@AppStorage",
    "NSPrivacyAccessedAPICategoryFileTimestamp": r"creationDate|modificationDate|contentModificationDate|"
                                                  r"fileModificationDate|attributesOfItem|\bstat\(",
    "NSPrivacyAccessedAPICategorySystemBootTime": r"systemUptime|mach_absolute_time",
    "NSPrivacyAccessedAPICategoryDiskSpace": r"volumeAvailableCapacity|systemFreeSize|statfs",
    "NSPrivacyAccessedAPICategoryActiveKeyboards": r"activeInputModes",
}

# SDKs worth naming in the header (they decide which rules apply).
SDKS = {
    "In-app purchases": PURCHASE,
    "Firebase": r"FirebaseCore|firebase_core|FirebaseApp\.configure|@react-native-firebase/app",
    "Analytics": r"FirebaseAnalytics|firebase_analytics|Mixpanel|Amplitude|PostHog|posthog|Segment",
    "Ads/attribution": AD_SDK,
    "Third-party AI": THIRD_AI,
    "Social login": r"GIDSignIn|google_sign_in|FBSDKLoginKit|flutter_facebook_auth|@react-native-google-signin",
    "WebView": r"WKWebView|webview_flutter|flutter_inappwebview|react-native-webview|@capacitor/core",
    "Remote config": r"RemoteConfig|firebase_remote_config|Statsig|LaunchDarkly",
    "OTA updates": r"expo-updates|CodePush|code-push|@capacitor/live-updates|shorebird",
}
