---
name: appstore-rejection-risk
description: Pre-submission App Review audit for any iOS app (Swift, Objective-C, Flutter, React Native / Expo, Capacitor). A script checks the codebase, and the App Store listing when it can, against a checklist of App Store Review Guideline violations. It reports each likely violation with the chance it gets the next submission rejected and the chance it leads to account-level action (5.6 warning, Extended Review, termination). Built to be cheap on tokens: the agent reads only the flagged lines, never the whole codebase. Use whenever the user asks "will this get rejected", "check my app against the App Store guidelines", "pre-submission check", "App Review audit", "is my app ready to submit", "could Apple ban my account", or wants an iOS codebase reviewed for guideline violations.
---

# App Store rejection risk

The scanner does the searching, so the agent only judges the hits. A full run should cost
about 10–25k tokens. The token rules below are part of the skill, not suggestions.

## 1. Scan (one command)

```bash
python3 "<this skill's folder>/scripts/scan.py" "<repo>" [--bundle-id <id>] [--no-store] [--portfolio <dir>]
```

Python 3.9+ only, no packages to install.

- `<repo>` is the app's root folder. Native, Flutter (`lib/` + `ios/`), React Native / Expo
  and Capacitor projects are detected automatically. Android, web, backend, test and build
  folders are skipped. JS/TS is only scanned inside a React Native / Expo / Capacitor package.
- Repos with several apps need `--bundle-id`. The header lists the candidate bundle IDs.
- **Store listing.** The scanner checks it from one of these sources, in order:
  1. the [`asc`](https://github.com/rorkai/App-Store-Connect-CLI) App Store Connect CLI, if it
     is installed and signed in. This gives the live metadata, EULA and in-app product states.
  2. a fastlane `metadata/` folder in the repo.
  3. nothing. The listing checks then go into the manual list in the report.
  `--no-store` skips the live lookup (offline use, or the app is not in App Store Connect yet).
- `--portfolio <dir>` points at the folder holding the developer's other apps. The scanner
  measures how many source files are identical to each sibling app (4.3 spam / template
  risk). It adds a few seconds. Use it when the developer ships several apps, especially from
  one template.
- The output is 30–80 lines and has three parts:
  - **Header:** bundle, stack, SDKs, the paywall files, the local Xcode version, the store
    source, and `history:` lines (guidelines cited in the repo's own docs, any mention of
    Extended Review, release checklists with unticked boxes).
  - **Findings,** sorted by reject %.
  - **`Clean:`** checks that found nothing. Do not redo those by hand.

## 2. Judge the findings (cheap)

Each finding has a `reject %` and `ban %`, valid **if the finding is real**, plus a `judge:`
hint.

- **DEFINITIVE** findings are violations as they stand. Accept them without opening files.
- **Every other finding:** open only its evidence lines, ±8 lines, **all in one batched
  command**. For example:
  `sed -n '180,200p' a.dart; echo ---; sed -n '40,58p' b.swift`
  Never open a whole file. The one exception is the paywall, the most rejected screen. Read
  the paywall file once if any PAY-* finding fired (grep inside it if it is over 600 lines),
  and check all of these in that one read:
  - the billed amount is the most prominent price
  - a trial says what is charged afterwards and that it renews
  - the close button is visible straight away
  - Terms, Privacy and Restore are present
  - there is no fake urgency (countdowns, "offer ends" timers)
- `... +N more: file(n)` lines tell you where the remaining hits are. Open them only if the
  shown hits were inconclusive.
- **HONEST-REMOTEGATE:** read the `keys:` (flag names) and the one file that defines them.
  It is real only if a flag can turn on undisclosed features, web payments or different
  content after review.
- **Feature claims** (2.3.1, one of the most common rejections), only if the store listing
  was found: read the en-US description from the path in the header (about 1k tokens). Check
  that each feature it promises has code behind it, with one batched grep.
- Do not use subagents. Do not read files the scan did not point to.

Verdict for each finding:
- **Confirmed:** keep the base %.
- **Likely:** probably real, one thing unclear. Use base × 0.6.
- **Unclear:** cannot tell without running the app. Use base × 0.3.
- **Dismissed:** give the reason in a few words (e.g. "only in an Android branch", "debug build only").

## 3. Score

- **Rejection chance for the next submission** = 1 − Π(1 − pᵢ) over the confirmed and likely
  findings. Cap it at 97%: App Review is never certain.
- **Ban / account-action risk**: the same formula over ban %. Most rejections carry 0%. Ban
  risk comes only from what the Developer Code of Conduct (5.6) treats as dishonest: hidden
  or review-only behaviour, dodging in-app purchase, review manipulation, downloaded code
  that changes the app, fake functionality, spam or copycat apps.
- **Account history.** Double every ban % (cap 90%), and say why, if either of these is true:
  - the user says the account has had an Extended Review, a 5.6 warning or repeated
    rejections for one guideline
  - the header's `history:` lines show Extended Review, or one guideline cited 3 or more times

  If neither is true, do not ask. Add one line to the report saying that prior warnings would
  raise the ban figures.
- **Unticked release checklists** in the header: grep their `- [ ]` lines once. Use them to
  tick or flag the matching manual checks below.

The percentages are calibrated estimates from Apple's guidelines and how strictly each rule
is enforced, not measurements. Say so once in the report, not on every line.

## 4. Report (in chat; write a file only if asked)

```
## <App> · App Review risk · <date>
Rejection chance next submission: ~NN% · Ban / account-action risk: ~N%

| # | Issue | Guideline | Reject | Ban | Evidence | Fix |
|---|-------|-----------|--------|-----|----------|-----|
| 1 | ...   | 3.1.2     | 75%    | 0%  | PaywallView.swift:192 | ... |

Dismissed: ID (reason), ID (reason)
Check by hand before submitting: <only the items below that apply>
```

Sort by reject %, but put any finding with ban ≥ 20% first. Each Fix is one line saying what
to change.

**Check by hand.** Code cannot show these; list only the ones that apply:
- The App Privacy label ("nutrition label") matches what the app and its SDKs collect. It
  says "used to track you" only if ATT and a tracking SDK exist (5.1.2).
- Every in-app purchase is in "Ready to Submit" with a review screenshot, and attached to this
  version's submission (2.1).
- A sandbox purchase and restore work on a release build, on iPhone and iPad (2.1).
- App Review Notes explain anything non-obvious: demo account if there is sign-in, where ads
  appear, which third-party AI receives user data, hardware or region requirements (2.1).
- Screenshots show the app in use, not only marketing art, and paid features are labelled
  as paid (2.3.3, 2.3.2).
- If the listing was not checked: the description of a subscription app has a Terms of Use
  link, and the name, subtitle and keywords have no prices, "free" or other brands (3.1.2, 2.3.7).
- Working demo credentials are in the Review Notes if the app has sign-in (2.1).
- The app still works with every permission denied, and nothing forces consent to continue
  (5.1.1(iv)).
- The age-rating questionnaire is complete, including Apple's newer questions.
- Health apps: the regulated medical device status is declared in App Store Connect (1.4.1).
- The build uses Xcode 26 / the iOS 26 SDK (required since 28 Apr 2026). The header shows
  the local Xcode; CI may use a different one.
- **4.3 spam:** if the developer ships several apps from one template, each needs a clearly
  distinct concept, design and content. Run with `--portfolio` to measure code overlap.
  Repeated 4.3 rejections are a common route to account termination.

## Extending the checklist

- The rules are in `scripts/checks.py`, one dict per rule: regex, reject %, ban % and a hint
  for judging. Add a rule when a rejection teaches something a grep could have caught.
- A false alarm seen twice means the regex needs tightening. Fix it rather than dismissing it
  on every run.
- Checks that need logic rather than one regex live in `scripts/scan.py`: purpose strings,
  privacy manifest, background modes, iPad, paywall close-delay and trial toggle, Xcode
  version, portfolio similarity, repo history, store listing.
- Dated facts (Xcode 26 requirement) were last checked on 2026-10-08 against
  developer.apple.com/news/upcoming-requirements. Re-check them if that date is over six
  months old.
