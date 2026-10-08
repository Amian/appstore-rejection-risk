# App Store rejection risk

An agent skill that reviews an iOS app's codebase for App Store Review Guideline
violations before you submit. It reports each likely problem with two numbers:

- **Reject %:** the chance it gets your next submission rejected.
- **Ban %:** the chance it leads to account-level action (a 5.6 warning, Extended Review or
  termination).

It works with Claude Code, Codex, or any coding agent that can run a shell command and read
a `SKILL.md`.

Works on **Swift / Objective-C, Flutter, React Native / Expo and Capacitor** apps.

## Why it is cheap

Asking an agent to "read my app and check it against Apple's guidelines" can burn hundreds
of thousands of tokens and still miss things. This skill splits the job:

1. **A script does the searching.** `scripts/scan.py` (Python standard library only, about
   2 seconds) greps the repo against a catalogue of 40+ rules, plus checks that need logic:
   - purpose strings
   - privacy manifest
   - background modes
   - paywall dark patterns
   - template-clone overlap
   - the App Store listing itself

   It prints only the hits: about 30–80 lines.
2. **The agent only judges the hits.** It opens the flagged lines (±8 lines, one batched
   command), marks each finding confirmed, likely, unclear or a false alarm, and scores the
   result.

A full audit usually costs 10–25k tokens.

## What you get

```
## MyApp · App Review risk · 2026-10-08
Rejection chance next submission: ~91% · Ban / account-action risk: ~3%

| # | Issue                                   | Guideline | Reject | Ban | Evidence                      | Fix                            |
|---|-----------------------------------------|-----------|--------|-----|-------------------------------|--------------------------------|
| 1 | UIWebView in the binary                 | 2.5.1     | 100%   | 0%  | OnboardingView.swift:20       | Replace with WKWebView         |
| 2 | Location used without a purpose string  | 5.1.1     | 95%    | 0%  | OnboardingView.swift:13       | Add NSLocationWhenInUse...     |
| 3 | Ad SDK without an ATT prompt            | 5.1.2     | 85%    | 2%  | OnboardingView.swift:5        | Request ATT before ads start   |
...
Dismissed: PAY-EQUIV-PRICE (savings maths, never shown)
Check by hand before submitting: privacy label, IAPs attached, demo account ...
```

## Install

Clone the repo into your agent's skills folder:

```bash
# Claude Code
git clone https://github.com/Amian/appstore-rejection-risk ~/.claude/skills/appstore-rejection-risk

# Codex
git clone https://github.com/Amian/appstore-rejection-risk ~/.codex/skills/appstore-rejection-risk
```

Other agents: point them at `SKILL.md`. Then ask, for example: *"Will this app get rejected
by App Review?"*

### Optional: check the live App Store listing

Several of the most common rejections are in the store listing, not the code: a missing
Terms of Use link in a subscription app's description, prices in the app name, in-app
purchases that were never submitted. With the [`asc`](https://github.com/rorkai/App-Store-Connect-CLI)
CLI installed (`brew install asc`) and signed in, the scanner pulls the live listing and
checks it as well. Without `asc`, it reads a fastlane `metadata/` folder if the repo has one.

## Run the scanner on its own

```bash
python3 scripts/scan.py path/to/your-app                       # code + listing
python3 scripts/scan.py path/to/your-app --no-store            # code only, offline
python3 scripts/scan.py path/to/your-app --bundle-id com.x.y   # repos with several apps
python3 scripts/scan.py path/to/your-app --portfolio ~/apps    # 4.3 template-clone check
```

## Rules

Reject % and ban % assume the finding is real. The agent lowers them for findings that are
only likely or unclear, and drops false alarms. Ban risk is non-zero only where Apple's
Developer Code of Conduct (5.6) treats the behaviour as dishonest.

| ID | Guideline | Checks for | Reject | Ban |
|----|-----------|------------|--------|-----|
| `PAY-TERMS` | 3.1.2 | Subscriptions sold but no Terms (EULA) / Privacy Policy links in the app | 75% | 0% |
| `PAY-RESTORE` | 3.1.1 | Purchases but no Restore Purchases | 70% | 0% |
| `PAY-HARDPRICE` | 3.1.2 | Hard-coded price on the paywall | 45% | 0% |
| `PAY-TRIAL` | 3.1.2 | Trial / 'free' offered without saying payment starts automatically | 50% | 0% |
| `PAY-EXTERNAL` | 3.1.1 / 3.1.3 | Payment outside In-App Purchase (web checkout, Stripe, licence keys) | 80% | 15% |
| `PAY-HIDDEN-UNLOCK` | 2.3.1 / 3.1.1 | Hidden premium unlock (reviewer/secret/promo code, forced premium) | 40% | 20% |
| `PAY-EQUIV-PRICE` | 3.1.2(c) | Per-week / per-day equivalent price on the paywall | 45% | 2% |
| `HONEST-REVIEWMODE` | 2.3.1 / 5.6 | Code that detects App Review and may change behaviour | 60% | 40% |
| `HONEST-SANDBOX` | 2.3.1 | Behaviour branches on sandbox / TestFlight (App Review uses sandbox) | 50% | 20% |
| `HONEST-REMOTEGATE` | 2.3.1 / 3.2(f) | Remote config / feature flags (check what they switch) | 15% | 35% |
| `HONEST-HOTCODE` | 2.5.2 / 3.3.1(b) | Downloads or runs code that changes the app after review | 60% | 25% |
| `HONEST-PRIVATEAPI` | 2.5.1 | Private or undocumented API use | 75% | 5% |
| `HONEST-RATING` | 5.6.1 / 3.2.2 | Rating gate, custom 'rate us' prompt or reward for reviews | 50% | 10% |
| `HONEST-RATING-CUSTOM` | 5.6.1 | Custom star-rating UI (instead of the system review prompt) | 30% | 2% |
| `HONEST-REVIEWTIMING` | 5.6.1 | Review prompt in onboarding / first-launch code | 45% | 0% |
| `HONEST-FAKE` | 2.3.1 / 5.6 | Fake system alerts, fake scans or fake functionality | 80% | 30% |
| `HONEST-MINING` | 3.1.5(b) | Crypto mining code | 95% | 50% |
| `PRIV-ATT-MISSING` | 5.1.2 | Advertising / attribution SDK or IDFA without an ATT prompt | 85% | 2% |
| `PRIV-ATT-NOTRACK` | 5.1.2 | ATT prompt shown but no tracking SDK found | 35% | 0% |
| `PRIV-ATT-KEY` | 5.1.2 | ATT requested but NSUserTrackingUsageDescription missing (crash) | 95% | 0% |
| `PRIV-ATT-PREPROMPT` | 5.1.1(iv) / 5.1.2 | Custom pre-prompt before ATT that pushes or rewards 'Allow' | 35% | 2% |
| `PRIV-LOCATION-ALWAYS` | 5.1.1 | Asks for 'Always' location | 30% | 0% |
| `PRIV-FACE-DATA` | 5.1.2(vi) / 2.1 | Processes face data (reviewers ask how it is handled) | 40% | 0% |
| `PRIV-ACCOUNT-DELETE` | 5.1.1(v) | Accounts can be created but not deleted in the app | 85% | 0% |
| `PRIV-SIWA` | 4.8 | Google / Facebook login without Sign in with Apple or an equal option | 75% | 0% |
| `PRIV-AI-CONSENT` | 5.1.1(i) / 5.1.2(i) | User content sent to a third-party AI without an in-app consent step | 60% | 0% |
| `PRIV-FORCED-DATA` | 5.1.1(ii) | Asks for personal data the core feature may not need | 35% | 0% |
| `PRIV-ATS` | 5.1.1 / 2.5 | App Transport Security disabled globally | 10% | 0% |
| `DONE-UIWEBVIEW` | 2.5.1 | UIWebView (deprecated, upload is refused) | 100% | 0% |
| `DONE-PLACEHOLDER` | 2.1 / 2.3.10 | Placeholder or unfinished text in the UI | 45% | 0% |
| `DONE-BETA` | 2.2 | Beta / demo / test-version wording in the UI | 35% | 0% |
| `DONE-DEVURL` | 2.1 | Localhost / staging / ngrok URL in code | 25% | 0% |
| `DONE-OTHERPLATFORM` | 2.3.10 | Mentions Android / Google Play in iOS UI text | 40% | 0% |
| `CONTENT-WEBWRAP` | 4.2 / 4.2.2 | Web view loads a remote site: check the app is more than a wrapped website | 55% | 0% |
| `CONTENT-MEDICAL` | 1.4.1 / 1.1.6 | Health, medical or financial claims that may mislead | 55% | 5% |
| `CONTENT-HEALTH-CITES` | 1.4.1 | Health / medication information with no source citations in the app | 50% | 5% |
| `CONTENT-IP` | 4.1 / 5.2 | Third-party brand or IP in app text | 50% | 5% |
| `CONTENT-KIDS` | 1.3 / 2.3 | Wording aimed at children | 40% | 0% |
| `CONTENT-UGC` | 1.2 | Users can share content with others but no report/block | 65% | 0% |
| `CONTENT-GAMBLING` | 5.3 / 3.1.1 | Gambling, loot boxes or real-money games | 50% | 5% |
| `CONTENT-CRYPTO` | 3.1.5 | Crypto wallet, trading or exchange features | 40% | 0% |
| `CONTENT-VPN` | 5.4 | VPN / Network Extension entitlement | 50% | 0% |

These checks are built into `scan.py`:
- **Purpose strings:** missing, vague, or missing in some localisations.
- **Privacy manifest:** missing, or missing required-reason categories.
- **Code that doesn't match settings:** unused background modes, and a tracking flag with no
  ATT prompt.
- **Device and toolchain:** iPad support, and a local Xcode older than 26.
- **Paywall:** a delayed close button, and a free-trial toggle.
- **4.3 template clones:** code overlap with sibling apps.
- **App Store listing:** Terms link per locale, privacy URL, product states, product IDs in
  code but not in the store, price words and brands in name, subtitle or keywords,
  undisclosed paid features, and the home-screen name differing from the store name.

## How the percentages were set

They are calibrated estimates, not measurements. They draw on three things:
- Apple's App Review Guidelines and its "Avoiding common issues" page
- the reasons Apple's App Store Transparency Reports cite most often
- how mechanically each rule is enforced

Automated upload checks (a missing purpose string, UIWebView) are near-certain. Judgement
calls (vague copy, review-prompt timing) are lower. If your rejections suggest a number is
off, please open an issue or PR with what happened.

## Contributing

Rule changes, new rules, false-alarm fixes and better percentages are all welcome.

- **Add or change a rule** in `scripts/checks.py`: one dict with a regex, guideline, reject %,
  ban % and a one-line hint for judging a hit. Checks that need logic go in `scripts/scan.py`.
- **Add a test case.** Put code that should trigger your rule in a fixture under
  `tests/fixtures/` and add the rule's ID to that fixture's `expected.txt`. A false-alarm fix
  goes in `clean-swift`, which must stay at zero findings. Fixtures for Flutter, React
  Native / Expo and Capacitor would be especially welcome.
- **Run the tests:** `python3 tests/run_tests.py`. CI runs them on every PR.
- Keep the scanner on the Python standard library, and keep its output short. Every line it
  prints costs the agent tokens.
- If you change a percentage, say why in the PR (a rejection you received, an Apple
  statement, a published report).

## Disclaimer

Not affiliated with or endorsed by Apple. App Review is done by people, and no tool can
promise approval. Use this to catch likely problems early, not as a guarantee. "App Store" is
a trademark of Apple Inc.

## Licence

[MIT](LICENSE)
