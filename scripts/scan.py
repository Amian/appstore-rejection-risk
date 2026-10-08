#!/usr/bin/env python3
"""Scan an iOS app repo against the App Review checklist in checks.py.

Supports native (Swift / Objective-C), Flutter, React Native / Expo and Capacitor / Ionic.
Prints a compact report: only findings, with a few evidence lines each, so the agent
reads hits instead of the codebase. Python 3 stdlib only.

  python3 scan.py <repo> [--bundle-id ID] [--no-store] [--max-evidence 4]

Store listing checks (Terms link in the description, price words in the name, product
states ...) use, in order: the `asc` App Store Connect CLI if it is installed and signed in,
otherwise a fastlane `metadata/` folder in the repo, otherwise they are skipped.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from checks import CHECKS, PURPOSE_KEYS, BG_MODES, REQUIRED_REASON, SDKS, IP_TERMS  # noqa: E402

SKIP_DIRS = {".git", "Pods", "Carthage", ".build", "build", "DerivedData", "node_modules",
             "SourcePackages", ".dart_tool", ".symlinks", "android", "macos", "windows", "linux",
             "web", "site", "docs", "backend", "server", "functions", "fastlane", ".swiftpm",
             "Frameworks", "vendor", "screenshots", "design-assets", "tools", "scripts",
             "marketing", "dist", "www", "public", "coverage", "__tests__", "e2e", "storybook"}
DEMO_RE = re.compile(r"Mock|Fake|Stub|Fixture|Seeder|Sample|Demo|debug_|Debug", re.I)
TEST_RE = re.compile(r"(^|/)(\w*Tests?|\w*UITests|test|integration_test|Preview Content)(/|$)|"
                     r"Tests?\.swift$|_test\.dart$|\.(test|spec|stories)\.[jt]sx?$")
NATIVE_EXT = {".swift", ".m", ".mm", ".h"}
CODE_EXT = NATIVE_EXT | {".dart", ".js", ".jsx", ".ts", ".tsx"}
STR_EXT = {".strings", ".xcstrings", ".arb", ".stringsdict"}
DEP_NAMES = {"Podfile", "Podfile.lock", "Package.resolved", "Package.swift", "pubspec.yaml",
             "pubspec.lock", "Cartfile", "package.json"}
CONFIG_NAMES = {"app.json", "app.config.js", "app.config.ts", "capacitor.config.json",
                "capacitor.config.ts", "Info.plist"}
GENERATED = re.compile(r"GeneratedPluginRegistrant|\.g\.dart$|\.freezed\.dart$|firebase_options\.dart$|"
                       r"\.pb\.swift$|\.min\.js$|\.d\.ts$|\.bundle\.js$")
LIT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`\n]*`')
PAYWALL_RE = re.compile(r"paywall|subscri|purchas|premium|upgrade|pricing|(^|/)iap[_/.]|"
                        r"(Pro|Plus)(View|Screen|Sheet)\.|unlock", re.I)
COMMENT_RE = re.compile(r"^\s*(//|\*|/\*|#(?!if|else|endif|Preview))")


JS_EXT = {".js", ".jsx", ".ts", ".tsx"}
MOBILE_JS = re.compile(r"\"(react-native|expo|@capacitor/core|cordova-ios|@ionic/)")


def is_app_js(p: Path, root: Path, cache={}):
    """JS/TS counts only if its nearest package.json is a React Native / Expo / Capacitor app
    (skips backends, workers and websites that live in the same repo)."""
    d = p.parent
    while True:
        if d not in cache:
            pj = d / "package.json"
            cache[d] = bool(MOBILE_JS.search(pj.read_text(errors="ignore"))) if pj.exists() else None
        if cache[d] is not None:
            return cache[d]
        if d == root or d.parent == d:
            return False
        d = d.parent


def collect(root: Path):
    groups = {k: [] for k in ("code", "native", "paywall", "strings", "plist", "deps", "privacy")}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith((".", "build"))
                  and not d.endswith((".xcassets", ".framework", ".xcframework", ".bundle"))]
        for fn in fns:
            p = Path(dp) / fn
            rel = str(p.relative_to(root))
            if TEST_RE.search(rel) or GENERATED.search(fn):
                continue
            ext = p.suffix
            if fn in CONFIG_NAMES or ext in (".plist", ".entitlements", ".xcconfig") or fn == "project.pbxproj":
                if fn != "GoogleService-Info.plist":
                    groups["plist"].append(p)
            elif ext in CODE_EXT:
                if ext in JS_EXT and not is_app_js(p, root):
                    continue
                groups["code"].append(p)
                if PAYWALL_RE.search(rel):
                    groups["paywall"].append(p)
                if ext in NATIVE_EXT:
                    groups["native"].append(p)
            elif ext in STR_EXT or (ext == ".json" and re.search(r"i18n|l10n|locali|locales|lang|translations", rel, re.I)):
                groups["strings"].append(p)
            elif ext == ".xcprivacy":
                groups["privacy"].append(p)
            if fn in DEP_NAMES:
                groups["deps"].append(p)
    return groups


class Repo:
    def __init__(self, root):
        self.root = root
        self.groups = collect(root)
        self._lines = {}

    def lines(self, p):
        if p not in self._lines:
            try:
                self._lines[p] = [] if p.stat().st_size > 2_000_000 else p.read_text(errors="ignore").splitlines()
            except OSError:
                self._lines[p] = []
        return self._lines[p]

    def files(self, spec):
        seen, out = set(), []
        for g in spec.split():
            for p in self.groups[g]:
                if p not in seen:
                    seen.add(p); out.append(p)
        return out

    def grep(self, pattern, spec, literal=False, case=False, limit=None, ui=False):
        rx = re.compile(pattern, 0 if case else re.I)
        hits = []
        for p in self.files(spec):
            is_code = p.suffix in CODE_EXT
            if literal and is_code and DEMO_RE.search(p.name):
                continue  # demo / debug fixtures are not user-facing UI
            for i, ln in enumerate(self.lines(p), 1):
                if is_code and COMMENT_RE.match(ln):
                    continue
                if literal and is_code:
                    text = " ".join(l for l in LIT_RE.findall(ln) if not ui or " " in l)
                else:
                    text = ln
                if text and rx.search(text):
                    hits.append((p, i, ln))
                    if limit and len(hits) >= limit:
                        return hits
        return hits

    def text(self, spec):
        return "\n".join("\n".join(self.lines(p)) for p in self.files(spec))

    def rel(self, p):
        return str(p.relative_to(self.root))


def fmt_hits(repo, hits, n):
    out = [f"  {repo.rel(p)}:{i}: {ln.strip()[:150]}" for p, i, ln in hits[:n]]
    if len(hits) > n:
        per = Counter(repo.rel(p) for p, _, _ in hits[n:])
        out.append(f"  ... +{len(hits) - n} more: " + ", ".join(f"{f.split('/')[-1]}({c})" for f, c in per.most_common(6)))
    return out


# ---------------------------------------------------------------- app facts
def app_facts(repo, want_bundle):
    cfg = repo.text("plist")
    deps = repo.text("deps")
    ids = [b.strip().strip('"') for b in re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([^;]+);", cfg)]
    ids += re.findall(r"bundleIdentifier[\"']?\s*:\s*[\"']([\w.-]+)", cfg)      # Expo
    ids += re.findall(r"appId[\"']?\s*:\s*[\"']([\w.-]+)", cfg)                 # Capacitor
    ids = [b for b in ids if "$" not in b and not re.search(
        r"test|widget|extension|notification|share|intent|clip|watch|keyboard|\.stickers", b, re.I)]
    cands = [b for b, _ in Counter(ids).most_common()]
    names = set(re.findall(r"<key>CFBundleDisplayName</key>\s*<string>([^<]+)</string>", cfg))
    names |= {n.strip().strip('"') for n in re.findall(r"INFOPLIST_KEY_CFBundleDisplayName = ([^;]+);", cfg)}
    for p in repo.groups["plist"]:
        if p.name in ("app.json", "capacitor.config.json"):
            m = re.search(r"\"(?:name|appName)\"\s*:\s*\"([^\"]+)\"", "\n".join(repo.lines(p)))
            if m:
                names.add(m.group(1))
    names = {n for n in names if "$" not in n}
    ipad = bool(re.search(r'TARGETED_DEVICE_FAMILY = "?[^;]*2', cfg) or
                re.search(r"supportsTablet[\"']?\s*:\s*true", cfg))
    if any(p.suffix == ".dart" for p in repo.groups["code"]):
        stack = "Flutter"
    elif re.search(r"\"expo\"\s*:", deps):
        stack = "Expo / React Native"
    elif "react-native" in deps:
        stack = "React Native"
    elif "@capacitor/" in deps or "cordova" in deps:
        stack = "Capacitor / Cordova"
    else:
        stack = "Swift / Objective-C"
    return dict(bundle=want_bundle or (cands[0] if cands else None), candidates=cands,
                names=sorted(names), ipad=ipad, stack=stack, nsrc=len(repo.groups["code"]))


# ---------------------------------------------------------------- generic checks
def run_check(repo, c, nev):
    case = c.get("case", False)
    if c["kind"] == "present":
        hits = repo.grep(c["pat"], c["files"], c.get("literal", False), case, ui=c.get("ui", False))
        if c.get("path"):
            hits = [h for h in hits if re.search(c["path"], repo.rel(h[0]), re.I)]
        if not hits:
            return None
        ev = fmt_hits(repo, hits, nev)
        if c.get("extract"):
            names = set()
            for p in {h[0] for h in hits}:
                names |= set(re.findall(c["extract"], "\n".join(repo.lines(p))))
            if names:
                ev.append("  keys: " + ", ".join(sorted(names)[:40]))
        if c.get("counter"):
            ch = repo.grep(c["counter"], "code strings", True, False, 1)
            ev.append("  counter: " + (f"found {repo.rel(ch[0][0])}:{ch[0][1]}" if ch else "NOT FOUND"))
        return ev
    when = repo.grep(c["when"], c["when_files"], False, case)
    if not when or repo.grep(c["need"], c["need_files"], False, case, 1):
        return None
    return [f"  trigger found, needed /{c['need'][:70]}/ found nowhere"] + fmt_hits(repo, when, min(nev, 3))


# ---------------------------------------------------------------- special checks
def plist_value_pairs(repo):
    pairs = set()
    rxs = [r"<key>(\w+UsageDescription)</key>\s*<string>([^<]*)</string>",       # Info.plist
           r"(\w+UsageDescription) = \"?([^;\"]*)\"?;",                            # pbxproj / .strings
           r"[\"'](\w+UsageDescription)[\"']\s*=\s*\"([^\"]*)\";",                 # .strings
           r"[\"']?(\w+UsageDescription)[\"']?\s*:\s*\"((?:[^\"\\\n]|\\.)*)\"",    # app.json / JSON
           r"(\w+UsageDescription)\s*:\s*'((?:[^'\\\n]|\\.)*)'"]                  # app.config.js
    for p in repo.files("plist strings"):
        t = "\n".join(repo.lines(p))
        for rx in rxs:
            for k, v in re.findall(rx, t):
                pairs.add((repo.rel(p), k.replace("INFOPLIST_KEY_", ""), v))
    return sorted(pairs)


def check_purpose(repo, nev):
    found = []
    keys_text = repo.text("plist strings")
    for api, keys in PURPOSE_KEYS:
        hits = repo.grep(api, "code deps")
        if hits and not any(k in keys_text for k in keys):
            found.append((f"PURPOSE-MISSING:{keys[0]}", "5.1.1 / 2.5", 95, 0, True,
                          f"API used but {keys[0]} missing: crash on first use, refused at upload",
                          fmt_hits(repo, hits, 2),
                          "Dismiss only if the package is installed but its API is never called."))
    pairs = plist_value_pairs(repo)
    vague, seen = [], set()
    for f, k, v in pairs:
        if (k, v) in seen:
            continue
        seen.add((k, v))
        latin = all(ord(ch) < 0x250 for ch in v)
        if re.search(r"(needs?|requires?) (access|permission)|this app (uses|needs)|^\$\(|^\s*$|"
                     r"allow access to (your )?(camera|photos|location)", v, re.I) or (latin and len(v) < 25):
            vague.append(f"  {f}: {k} = \"{v[:110]}\"")
    if vague:
        found.append(("PURPOSE-VAGUE", "5.1.1(iii)", 40, 0, False,
                      "Permission text generic or too short", vague[:nev + 2],
                      "Each must say why the app needs it, with an example "
                      "('Take a photo of a plant so we can identify it'), in every language shipped."))
    # each target's lproj/InfoPlist.strings vs that target's own Info.plist
    plist_keys, pbx_keys, lproj = {}, set(), {}
    for f, k, _ in pairs:
        if f.endswith("Info.plist"):
            plist_keys.setdefault(str(Path(f).parent), set()).add(k)
        elif f.endswith(".pbxproj"):
            pbx_keys.add(k)
        elif f.endswith("InfoPlist.strings"):
            lproj.setdefault(f, set()).add(k)
    for p in repo.files("strings"):
        if p.name == "InfoPlist.strings":
            lproj.setdefault(repo.rel(p), set())
    gaps = []
    for f, ks in sorted(lproj.items()):
        base = plist_keys.get(str(Path(f).parent.parent)) if plist_keys else pbx_keys
        if base and base - ks:
            gaps.append(f"  {'/'.join(f.split('/')[-3:-1])}: missing {', '.join(sorted(base - ks))}")
    if gaps:
        found.append(("PURPOSE-LOCALE-GAP", "5.1.1", 25, 0, True,
                      "Some localisations lack permission strings (English shows instead)", gaps[:nev + 2], ""))
    return found


def check_privacy_manifest(repo, nev):
    out = []
    pm = repo.text("privacy")
    if "privacyManifests" in repo.text("plist"):  # Expo config plugin writes the manifest
        return out
    if not repo.groups["privacy"]:
        used = [cat for cat, rx in REQUIRED_REASON.items() if repo.grep(rx, "native", limit=1)]
        if used:
            out.append(("PRIVACY-MANIFEST", "5.1.1 (ITMS-91053)", 30, 0, False,
                        "No app-level PrivacyInfo.xcprivacy, but the app's own code uses required-reason APIs",
                        ["  uses: " + ", ".join(u.replace("NSPrivacyAccessedAPICategory", "") for u in used)],
                        "Apple flags this at upload with an ITMS-91053 email. If a recent build uploaded "
                        "without one, lower to 10%. Fix: add a manifest declaring each category and reason."))
    else:
        miss = [cat for cat, rx in REQUIRED_REASON.items() if cat not in pm and repo.grep(rx, "native", limit=1)]
        if miss:
            out.append(("PRIVACY-MANIFEST-REASONS", "5.1.1 (ITMS-91053)", 30, 0, False,
                        "Privacy manifest lacks categories the code uses",
                        ["  missing: " + ", ".join(m.replace("NSPrivacyAccessedAPICategory", "") for m in miss)], ""))
        if re.search(r"NSPrivacyTracking</key>\s*<true", pm) and not repo.grep(
                r"requestTrackingAuthorization|app_tracking_transparency|expo-tracking-transparency", "code deps", limit=1):
            out.append(("PRIVACY-TRACKING-FLAG", "5.1.2", 70, 0, True,
                        "Manifest says NSPrivacyTracking=true but there is no ATT prompt", [], ""))
    return out


def check_bg_modes(repo, nev):
    t = repo.text("plist")
    modes = set()
    for block in re.findall(r"<key>UIBackgroundModes</key>\s*<array>(.*?)</array>", t, re.S):
        modes |= set(re.findall(r"<string>([^<]+)</string>", block))
    for block in re.findall(r"UIBackgroundModes[\"']?\s*:\s*\[(.*?)\]", t, re.S):
        modes |= set(re.findall(r"[\"']([\w-]+)[\"']", block))
    unused = [m for m in modes if m in BG_MODES and not repo.grep(BG_MODES[m], "code deps", limit=1)]
    if unused:
        return [("BG-MODES", "2.5.4", 60, 0, False, "Background modes declared without matching code",
                 ["  unused: " + ", ".join(sorted(unused))], "Remove modes the app does not use.")]
    return []


def check_ipad(facts):
    if facts["ipad"]:
        return [("IPAD", "2.1 / 4.0", 20, 0, False, "iPad is a supported device: Apple will test the app on iPad",
                 [], "iPad crashes and broken layouts are a common 2.1 rejection. Test on iPad, or ship "
                     "iPhone-only. Apple may still test an iPhone-only app on iPad in compatibility mode.")]
    return []


def check_paywall_ui(repo, nev):
    """Multi-line paywall checks: delayed close button, free-trial toggle."""
    out, delay, toggle = [], [], []
    close = re.compile(r"close|dismiss|xmark|canClose|showClose", re.I)
    tog = re.compile(r"(\bToggle\(|\bSwitch\(|Switch\.adaptive|CupertinoSwitch|SwitchListTile|<Switch)"
                     r"[\s\S]{0,300}[Tt]rial|[Tt]rial[\s\S]{0,300}(\bToggle\(|\bSwitch\(|Switch\.adaptive|"
                     r"CupertinoSwitch|SwitchListTile|<Switch)")
    for p in repo.files("paywall"):
        t = "\n".join(repo.lines(p))
        for m in re.finditer(r"asyncAfter|Future\.delayed|Timer\(|\.delay\(|setTimeout|withDelay|AnimatedOpacity", t):
            if close.search(t[max(0, m.start() - 600): m.end() + 600]):
                delay.append(f"  {repo.rel(p)}:{t.count(chr(10), 0, m.start()) + 1}: {m.group(0)} near close/dismiss")
                break
        m = tog.search(t)
        if m and not re.search(r"remind", m.group(0), re.I):
            toggle.append(f"  {repo.rel(p)}:{t.count(chr(10), 0, m.start()) + 1}: trial toggle")
    if delay:
        out.append(("PAY-CLOSE-DELAY", "3.1.2 / 5.6", 30, 3, False,
                    "Paywall close button may appear late or be hidden", delay[:nev],
                    "Reviewers flag paywalls with no visible way out. A close button that fades in "
                    "after a few seconds is a common rejection; show it straight away."))
    if toggle:
        out.append(("PAY-TRIAL-TOGGLE", "3.1.2(c)", 20, 1, False, "Free-trial on/off toggle on the paywall",
                    toggle[:nev], "No explicit rule, but reviewers have rejected toggles that make "
                                  "the trial terms or billed price unclear."))
    return out


def check_toolchain():
    try:
        v = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return [], "Xcode: not found (not on a Mac?)"
    m = re.search(r"Xcode (\d+)", v)
    line = v.split("\n")[0] if v else "Xcode: unknown"
    if m and int(m.group(1)) < 26:
        return [("XCODE-OLD", "Upload requirement", 100, 0, True,
                 f"{line} is too old: uploads need Xcode 26 / iOS 26 SDK since 28 Apr 2026",
                 [], "Re-check developer.apple.com/news/upcoming-requirements each spring.")], line
    return [], line


def fingerprints(root):
    hs = set()
    for p in Repo(root).groups["code"]:
        try:
            t = p.read_text(errors="ignore")
        except OSError:
            continue
        if len(t) > 400:
            hs.add(hashlib.md5(re.sub(r"\s+", "", t).encode()).hexdigest())
    return hs


def check_portfolio(repo, portfolio):
    """4.3 spam: share of this app's source files that are byte-identical in sibling apps."""
    mine = fingerprints(repo.root)
    sims = []
    for d in sorted(Path(portfolio).expanduser().iterdir()):
        if not d.is_dir() or d.resolve() == repo.root or d.name.startswith((".", "_")):
            continue
        if not ((d / "pubspec.yaml").exists() or any(d.glob("*.xcodeproj")) or any(d.glob("*/*.xcodeproj"))
                or (d / "package.json").exists()):
            continue
        other = fingerprints(d)
        if mine and other:
            sims.append((len(mine & other) / len(mine), d.name))
    sims.sort(reverse=True)
    info = "portfolio: most similar " + (", ".join(f"{n} {s:.0%}" for s, n in sims[:3]) or "none")
    if sims and sims[0][0] >= 0.6:
        return [("TEMPLATE-CLONE", "4.3(a)/(b)", 20, 8, False,
                 "Most source files are identical to another app by the same developer",
                 [f"  {s:.0%} identical to {n}" for s, n in sims[:3] if s >= 0.6],
                 "Shared plumbing is fine. A violation if the concept, screens and content are also "
                 "near-duplicates. Repeated 4.3 rejections can end in account termination.")], info
    return [], info


def repo_history(repo):
    """Past rejections and unticked release checklists recorded in the repo's own docs."""
    docs = [p for pat in ("*.md", "docs/*.md", "*/*.md") for p in repo.root.glob(pat)
            if "node_modules" not in str(p)][:60]
    prior, ext, open_boxes = Counter(), [], []
    for p in docs:
        try:
            t = p.read_text(errors="ignore")
        except OSError:
            continue
        prior.update(re.findall(r"Guideline (\d\.\d+(?:\.\d+)?)", t))
        if re.search(r"extended review", t, re.I):
            ext.append(repo.rel(p))
        if re.search(r"checklist", p.name, re.I):
            n = len(re.findall(r"^\s*[-*] \[ \]", t, re.M))
            if n:
                open_boxes.append(f"{repo.rel(p)} ({n} unticked)")
    lines = []
    if prior:
        lines.append("history: guidelines cited in repo docs: " + ", ".join(f"{g}×{n}" for g, n in prior.most_common(8)))
    if ext:
        lines.append("history: EXTENDED REVIEW mentioned in " + ", ".join(ext[:3]) + " -> apply the account-history rule")
    if open_boxes:
        lines.append("history: release checklists with open items: " + ", ".join(open_boxes[:3]))
    return lines


# ---------------------------------------------------------------- store listing
def asc(*args):
    try:
        r = subprocess.run(["asc", *args, "--output", "json"], capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            return None
        out = r.stdout.strip()
        try:
            return json.loads(out)
        except ValueError:  # some asc commands print a second JSON line
            return json.loads(out.splitlines()[0])
    except Exception:
        return None


def load_store_asc(facts):
    """Live listing via the asc CLI. Returns a store dict, or (None, reason)."""
    if not shutil.which("asc"):
        return None, "asc CLI not installed"
    if not facts["bundle"]:
        return None, "no bundle ID found (pass --bundle-id)"
    apps = asc("apps", "list", "--bundle-id", facts["bundle"])
    if not apps or not apps.get("data"):
        return None, f"asc could not find {facts['bundle']} (not signed in, or app not created yet)"
    app = apps["data"][0]
    aid, attrs = app["id"], app["attributes"]
    vers = asc("versions", "list", "--app", aid, "--platform", "IOS", "--limit", "1")
    if not vers or not vers.get("data"):
        return None, f"app {aid} has no iOS version yet"
    v = vers["data"][0]["attributes"]
    vstr = v["versionString"]
    tmp = Path(tempfile.mkdtemp(prefix="asr-"))
    subprocess.run(["asc", "metadata", "pull", "--app", aid, "--version", vstr, "--platform", "IOS",
                    "--dir", str(tmp)], capture_output=True, timeout=120)
    eula = asc("eula", "view", "--app", aid)
    subs = (asc("subscriptions", "list", "--app", aid) or {}).get("data", [])
    iaps = (asc("iap", "list", "--app", aid) or {}).get("data", [])
    return dict(
        source=f"asc: {attrs.get('name')} (app {aid}), newest iOS version {vstr} "
               f"[{v.get('appVersionState') or v.get('appStoreState')}]",
        info={f.stem: json.loads(f.read_text()) for f in (tmp / "app-info").glob("*.json")},
        ver={f.stem: json.loads(f.read_text()) for f in (tmp / "version").glob("*/*.json")},
        desc_dir=str(tmp / "version" / vstr),
        custom_eula=bool(eula and eula.get("data", {}).get("id")),
        products=[(s["attributes"].get("productId"), s["attributes"].get("state")) for s in subs + iaps],
        kids=attrs.get("isOrEverWasMadeForKids"), name=attrs.get("name"), live=True), None


def load_store_fastlane(repo):
    """fastlane deliver layout: fastlane/metadata/<locale>/{name,subtitle,description,...}.txt"""
    for md in list(repo.root.glob("fastlane/metadata")) + list(repo.root.glob("*/fastlane/metadata")):
        info, ver = {}, {}
        for loc in md.iterdir():
            if not loc.is_dir() or loc.name in ("review_information", "trade_representative_contact_information"):
                continue
            rd = lambda n: (loc / f"{n}.txt").read_text(errors="ignore").strip() if (loc / f"{n}.txt").exists() else ""
            info[loc.name] = dict(name=rd("name"), subtitle=rd("subtitle"), privacyPolicyUrl=rd("privacy_url"))
            ver[loc.name] = dict(description=rd("description"), keywords=rd("keywords"),
                                 promotionalText=rd("promotional_text"))
        if ver:
            return dict(source=f"fastlane: {repo.rel(md)} (local files, may differ from the live listing)",
                        info=info, ver=ver, desc_dir=str(md), custom_eula=None, products=[],
                        kids=None, name=None, live=False)
    return None


def store_checks(repo, facts, nev, allow_asc):
    st, why = load_store_asc(facts) if allow_asc else (None, "--no-store")
    if not st:
        st = load_store_fastlane(repo)
        if not st:
            return [], [f"store: not checked ({why}; no fastlane/metadata either). Listing checks go to the manual list."]
    out = []
    info_md, ver_md, products = st["info"], st["ver"], st["products"]
    en_first = lambda kv: (kv[0] not in ("en-US", "default"), kv[0])
    sells = bool(products) or bool(repo.grep(CHECKS[0]["when"], "code deps", limit=1))

    # Terms of Use link in every locale's description (3.1.2, apps with auto-renewing subscriptions)
    if sells and not st["custom_eula"]:
        missing = [loc for loc, d in ver_md.items()
                   if d.get("description") and not re.search(r"stdeula|terms|eula|/legal", d["description"], re.I)]
        if missing:
            out.append(("STORE-EULA", "3.1.2", 85 if st["live"] else 70, 0, st["live"],
                        "Terms of Use (EULA) link missing from the App Store description",
                        [f"  locales without it ({len(missing)}/{len(ver_md)}): " + ", ".join(sorted(missing)[:20])],
                        "Subscription apps need a Terms link in the description (Apple's standard EULA "
                        "URL is fine) or a custom EULA in App Store Connect. Dismiss if the app sells "
                        "only one-off purchases, or (fastlane source) a custom EULA is set."))
    if st["live"]:
        nopriv = [loc for loc, d in info_md.items() if not d.get("privacyPolicyUrl")]
        if nopriv:
            out.append(("STORE-PRIVACY-URL", "5.1.1(i)", 95, 0, True, "Privacy Policy URL not set",
                        ["  locales: " + ", ".join(nopriv[:20])], ""))
    code_blob = repo.text("code")
    bad = [f"{pid} [{s}]{' (in code)' if pid and pid in code_blob else ''}" for pid, s in products
           if s not in ("APPROVED", "READY_TO_SUBMIT", "WAITING_FOR_REVIEW", "IN_REVIEW",
                        "REMOVED_FROM_SALE", "DEVELOPER_REMOVED_FROM_SALE")]
    if bad:
        out.append(("STORE-IAP-STATE", "2.1", 80, 0, False,
                    "In-app products not ready (missing metadata/screenshot), so they cannot be submitted",
                    ["  " + ", ".join(bad[:10])],
                    "Reviewers reject apps whose paywall offers products that were not submitted. Real "
                    "only if the app shows this product; unused leftovers can be dismissed."))
    if products:
        asc_ids = {pid for pid, _ in products}
        i18n_keys = set(re.findall(r'"([\w.-]+)"\s*:', repo.text("strings")))
        code_ids = set()
        for p, i, ln in repo.grep(r"[\"'][\w-]+(\.[\w-]+)+[\"']", "code", literal=True):
            for lit in LIT_RE.findall(ln):
                s = lit.strip("\"'`")
                if re.search(r"week|month|annual|year|lifetime", s, re.I) and "." in s and s not in i18n_keys \
                        and not re.search(r"/|\s|^com\.apple|\.(png|jpg|json|mp3|ttf|swift)$", s):
                    code_ids.add(s)
        bundle = (facts["bundle"] or "~").lower()
        heads = {i.split(".")[0].lower() for i in asc_ids} | {bundle}
        ghost = sorted(i for i in code_ids - asc_ids if i.split(".")[0].lower() in heads or i.lower().startswith(bundle))
        if ghost:
            out.append(("STORE-IAP-GHOST", "2.1", 60, 0, False,
                        "Product-ID-like strings in code that do not exist in App Store Connect",
                        ["  " + ", ".join(ghost[:8]), "  store has: " + ", ".join(sorted(asc_ids)[:8])],
                        "A paywall asking for a missing product fails in review. Dismiss if not product IDs."))
    en_ver = next((d for loc, d in sorted(ver_md.items(), key=en_first)), {})
    if sells and en_ver.get("description") and not re.search(
            r"premium|subscri|pro version|unlock|in-app purchase|\bpro\b|plus", en_ver["description"], re.I):
        out.append(("STORE-PAID-UNLABELLED", "2.3.2", 40, 0, False,
                    "Description never says that features need a purchase or subscription", [],
                    "2.3.2: the description must make clear which features require extra purchases."))
    price_rx = r"\b(free|gratis|kostenlos|gratuit|gratuito|grátis|darmowy|ücretsiz)\b|[$£€]\s?\d|\d+\s?% off|\bsale\b|discount"
    for loc, d in sorted(info_md.items(), key=en_first):
        for field in ("name", "subtitle"):
            val = d.get(field) or ""
            if re.search(price_rx, val, re.I):
                out.append((f"STORE-PRICE-WORD:{loc}", "2.3.7", 55, 0, True,
                            f"Price / 'free' wording in the app {field}", [f"  {loc} {field}: {val}"], ""))
            if re.search(IP_TERMS, val, re.I):
                out.append((f"STORE-IP:{loc}", "2.3.7 / 5.2", 60, 5, True,
                            f"Third-party brand in the app {field}", [f"  {loc} {field}: {val}"], ""))
    for loc, d in sorted(ver_md.items(), key=en_first):
        promo, kw, desc = d.get("promotionalText") or "", d.get("keywords") or "", d.get("description") or ""
        if re.search(r"[$£€]\s?\d|\d+\s?% off|discount", promo, re.I):
            out.append((f"STORE-PROMO-PRICE:{loc}", "2.3.7", 20, 0, False, "Price or discount in promotional text",
                        [f"  {loc}: {promo[:120]}"], "Low risk in promo text; never in name, subtitle or keywords."))
        if re.search(IP_TERMS, kw, re.I):
            out.append((f"STORE-IP-KW:{loc}", "2.3.7", 50, 0, True, "Third-party brand or competitor in keywords",
                        [f"  {loc}: {kw[:120]}"], "Keywords may not contain other apps' or companies' names."))
        if re.search(r"\bandroid\b|google play", desc, re.I):
            out.append((f"STORE-OTHERPLATFORM:{loc}", "2.3.10", 40, 0, True,
                        "Description mentions Android / Google Play", [], ""))
        if st["kids"] is False and re.search(r"for kids|for children|toddler|preschool", desc, re.I):
            out.append((f"STORE-KIDS:{loc}", "1.3 / 2.3", 40, 0, False, "Kids wording outside the Kids category", [], ""))
    en = next((d for loc, d in sorted(info_md.items(), key=en_first)), {})
    store_name = en.get("name") or st["name"] or ""
    for dn in facts["names"] if store_name else []:
        toks = [t for t in re.findall(r"\w+", dn.lower()) if len(t) > 2]
        if toks and not any(t in store_name.lower() for t in toks):
            out.append(("STORE-NAME-MISMATCH", "2.3.8", 45, 0, False,
                        "Home-screen name does not resemble the App Store name",
                        [f"  display '{dn}' vs store '{store_name}'"],
                        "2.3.8: the name under the icon should be similar to the store name."))
    # collapse per-locale duplicates into one finding each
    merged, locales = {}, {}
    for f in out:
        key, _, loc = f[0].partition(":")
        locales.setdefault(key, []).append(loc)
        merged.setdefault(key, [key, *f[1:]])
    for key, locs in locales.items():
        if len(locs) > 1:
            merged[key][6] = list(merged[key][6]) + [f"  also in {len(locs) - 1} more locale(s): " + ", ".join(locs[1:12])]
    info = [f"store: {st['source']} · {len(ver_md)} locales",
            f"store: descriptions in {st['desc_dir']} (read en-US for the feature-claim check)"]
    return [tuple(m) for m in merged.values()], info


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--bundle-id")
    ap.add_argument("--no-store", "--no-asc", dest="no_store", action="store_true",
                    help="skip the live App Store Connect lookup (fastlane metadata is still read)")
    ap.add_argument("--portfolio", help="folder holding the developer's other apps (4.3 template-clone check)")
    ap.add_argument("--max-evidence", type=int, default=4)
    a = ap.parse_args()
    root = Path(a.repo).expanduser().resolve()
    repo = Repo(root)
    facts = app_facts(repo, a.bundle_id)
    nev = a.max_evidence

    findings = []  # (id, g, reject, ban, definitive, title, evidence, hint)
    for c in CHECKS:
        ev = run_check(repo, c, nev)
        if ev:
            findings.append((c["id"], c["g"], c["reject"], c["ban"], c.get("definitive", False),
                             c["title"], ev, c.get("hint", "")))
    findings += check_purpose(repo, nev) + check_privacy_manifest(repo, nev) + check_bg_modes(repo, nev) \
        + check_ipad(facts) + check_paywall_ui(repo, nev)
    tc, xcode = check_toolchain()
    findings += tc
    extra = [xcode]
    if a.portfolio:
        pf, pinfo = check_portfolio(repo, a.portfolio)
        findings += pf
        extra.append(pinfo)
    sf, store_info = store_checks(repo, facts, nev, not a.no_store)
    findings += sf

    sdks = [n for n, rx in SDKS.items() if repo.grep(rx, "code deps", limit=1)]
    print(f"# App Store rejection-risk scan: {root.name}")
    print(f"bundle {facts['bundle']} (candidates: {', '.join(facts['candidates'][:4]) or 'none'}) · "
          f"display name {facts['names'] or '?'} · {facts['stack']}, {facts['nsrc']} source files · "
          f"iPad: {'yes' if facts['ipad'] else 'no'}")
    print("SDKs: " + (", ".join(sdks) or "none detected"))
    pw = [repo.rel(p) for p in repo.groups["paywall"]]
    print("paywall files: " + (", ".join(pw[:6]) if pw else "none matched by name (grep for the purchase screen if the app sells)"))
    for s in extra + store_info + repo_history(repo):
        print(s)
    if facts["nsrc"] == 0:
        print("WARNING: no source files found. Wrong folder? Pass the app's repo root.")
    findings.sort(key=lambda f: (-f[2], -f[3]))
    print(f"\n## {len(findings)} findings (reject% / ban% assume the finding is real)")
    for fid, g, rj, bn, de, title, ev, hint in findings:
        print(f"\n### {fid} · {g} · reject {rj}% · ban {bn}%{' · DEFINITIVE' if de else ''}")
        print(title)
        for e in ev:
            print(e)
        if hint:
            print("judge: " + hint)
    hit_ids = {f[0].split(":")[0] for f in findings}
    print("\n## Clean: " + " ".join(c["id"] for c in CHECKS if c["id"] not in hit_ids))


if __name__ == "__main__":
    main()
