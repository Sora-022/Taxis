#!/usr/bin/env python3
"""taxis - a safe, reversible debloater for Fire TV and Android/Google TV (profile sets).

Inspired by Gathin23/cleanyourtv (credit where due). Different goals:
Fire TV only, tiered profiles, typed confirmation, auto-discovery,
and a restore path that works even without Python (restore.sh).
Standard library only. Needs `adb` on your PATH.
"""
import argparse, json, os, re, shutil, socket, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADB_EXE = ROOT / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
PROFILES_ROOT = ROOT / "profiles"
SET = "firetv"  # profile set; chosen by --set or auto-detected from the device
STATE = Path.home() / ".taxis" / "snapshots"
TIERS = ["safe", "medium", "aggressive"]  # each tier includes the ones before it
PKG_RE = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")
COMP_RE = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*/[A-Za-z0-9_.$]+")


# ---------- helpers ----------
def sh(*args, serial=None, timeout=30):
    """Run one ADB command using the bundled copy when it is available."""
    adb = str(ADB_EXE) if ADB_EXE.is_file() else "adb"
    cmd = [adb] + (["-s", serial] if serial else []) + list(args)
    try:
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}  # no console flash from the GUI
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timeout"


def shell(serial, cmd, timeout=30):
    return sh("shell", cmd, serial=serial, timeout=timeout)[1]


def valid_pkg(p):
    """True only for plain package names, so profile or snapshot text cannot smuggle shell commands to the TV."""
    return bool(PKG_RE.fullmatch(p or ""))


def valid_comp(c):
    """True only for package/activity component names; same injection guard as valid_pkg."""
    return bool(COMP_RE.fullmatch(c or ""))


def need_adb():
    """Stop with installation guidance when neither bundled nor system ADB exists."""
    if not ADB_EXE.is_file() and not shutil.which("adb"):
        sys.exit("adb not found. Install it first:\n"
                 "  macOS:   brew install android-platform-tools\n"
                 "  Ubuntu:  sudo apt install adb\n"
                 "  Windows: winget install Google.PlatformTools")


def sets():
    return sorted(d.name for d in PROFILES_ROOT.iterdir() if d.is_dir())


def resolve_set(serial, wanted=None):
    """Pick the profile set: --set wins, else detect from the device."""
    global SET
    if wanted:
        SET = wanted
    else:
        maker = shell(serial, "getprop ro.product.manufacturer").lower()
        dev = shell(serial, "getprop ro.product.device").strip()
        if "amazon" in maker:
            SET = "firetv"
        elif dev == "G13":
            SET = "tcl-g13"
        else:
            sys.exit(f"No profile set matches this device (maker={maker!r}, device={dev!r}).\n"
                     f"Available sets: {', '.join(sets())}. Pick one with --set NAME,\n"
                     f"or add profiles/<name>/ with safe.txt, medium.txt, aggressive.txt, never.txt.")
    if not (PROFILES_ROOT / SET).is_dir():
        sys.exit(f"Unknown set {SET!r}. Available: {', '.join(sets())}")
    print(f"Profile set: {SET}")


def read_profile(name):
    out = {}
    for line in (PROFILES_ROOT / SET / f"{name}.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg, _, desc = line.partition("#")
        out[pkg.strip()] = desc.strip()
    return out


def never():
    return set(read_profile("never"))


def plan_for(profile):
    names = TIERS[: TIERS.index(profile) + 1]
    plan = {}
    for n in names:
        for pkg, desc in read_profile(n).items():
            plan[pkg] = (n, desc)
    for pkg in never():
        plan.pop(pkg, None)
    return plan


def pkg_sets(serial):
    allp = {l.split(":", 1)[1].strip() for l in shell(serial, "pm list packages").splitlines() if l.startswith("package:")}
    dis = {l.split(":", 1)[1].strip() for l in shell(serial, "pm list packages -d").splitlines() if l.startswith("package:")}
    return allp, dis


def parse_choice(text, n):
    """'all' | 'none' | '1,3,5-7' -> sorted list of 0-based indexes, or None if invalid."""
    t = text.strip().lower().replace(" ", "")
    if t in ("all", "a"):
        return list(range(n))
    if t in ("", "none", "n", "0"):
        return []
    out = set()
    for part in t.split(","):
        lo, _, hi = part.partition("-")
        if not lo.isdigit() or (hi and not hi.isdigit()):
            return None
        lo, hi = int(lo), int(hi or lo)
        if lo < 1 or hi > n or lo > hi:
            return None
        out.update(range(lo - 1, hi))
    return sorted(out)


def show_after(done_count):
    f = PROFILES_ROOT / SET / "after.txt"
    if done_count and f.exists():
        print("\n" + "=" * 60)
        print(f.read_text().rstrip())
        print("=" * 60)


def confirm(msg, yes=False):
    if yes:
        return True
    return input(f"{msg} Type YES to continue: ").strip() == "YES"


# ---------- discovery ----------
def local_prefix():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return ".".join(s.getsockname()[0].split(".")[:3])
    finally:
        s.close()


def probe(ip, port=5555):
    try:
        with socket.create_connection((ip, port), timeout=0.5):
            return ip
    except OSError:
        return None


def scan():
    pre = local_prefix()
    print(f"Scanning {pre}.0/24 for ADB (port 5555)...")
    with ThreadPoolExecutor(128) as ex:
        hits = [h for h in ex.map(probe, [f"{pre}.{i}" for i in range(1, 255)]) if h]
    found = []
    for ip in hits:
        sh("connect", f"{ip}:5555")
        model = shell(f"{ip}:5555", "getprop ro.product.model")
        found.append((ip, model or "?"))
    return found


def connected():
    _, out = sh("devices")
    devs = []
    for l in out.splitlines()[1:]:
        p = l.split()
        if len(p) == 2:
            devs.append(tuple(p))
    return devs


UNSUPPORTED = (
    "taxis only works on Android-based TVs (Android TV, Google TV, Fire TV).\n"
    "Samsung (Tizen), LG (webOS), Roku and Apple TV are NOT supported: they do not\n"
    "accept ADB commands, so nothing was changed. See README section 1.")


def guard(serial):
    """Refuse to touch anything that is not an Android TV-class device."""
    sdk = shell(serial, "getprop ro.build.version.sdk").strip()
    if not sdk.isdigit():
        sys.exit(f"{serial} does not look like an Android device. Nothing was changed.\n{UNSUPPORTED}")
    feats = shell(serial, "pm list features")
    is_tv = "android.software.leanback" in feats or "android.hardware.type.television" in feats
    if not is_tv and os.environ.get("TAXIS_ALLOW_NON_TV") != "1":
        maker = shell(serial, "getprop ro.product.manufacturer").strip()
        model = shell(serial, "getprop ro.product.model").strip()
        sys.exit(f"{serial} ({maker} {model}) is Android but does not report TV features.\n"
                 "It may be a phone or tablet, so taxis refuses to continue. Nothing was changed.\n"
                 "(Advanced: set TAXIS_ALLOW_NON_TV=1 if you are sure it is a TV box.)")


def pick_device(args):
    serial = _pick_device(args)
    guard(serial)
    return serial


def _pick_device(args):
    need_adb()
    if args.device:
        d = args.device if ":" in args.device else args.device + ":5555"
        out = sh("connect", d)[1]
        print(out)
        if any(w in out.lower() for w in ("failed", "cannot", "unable", "refused", "timed out", "no route")):
            sys.exit("Could not connect. Check the IP, that debugging is on and the TV is awake.\n"
                     "If your TV is a Samsung (Tizen) or LG (webOS), this tool cannot be used on it.\n"
                     "Nothing was changed.")
        return d
    devs = [d for d, st in connected() if st == "device"]
    if any(st == "unauthorized" for _, st in connected()):
        print("A device is waiting for approval: accept 'Allow USB debugging?' on the TV (tick 'Always allow').")
    if len(devs) == 1:
        return devs[0]
    if not devs:
        found = scan()
        if not found:
            sys.exit("No Android-based TV found on port 5555. Is debugging on? See README section 4.\n"
                     "Samsung (Tizen), LG (webOS), Roku and Apple TV are not supported.")
        devs = [f"{ip}:5555" for ip, _ in found]
        if len(devs) == 1:
            return devs[0]
    for i, d in enumerate(devs):
        print(f"  [{i}] {d}  {shell(d, 'getprop ro.product.model')}")
    while True:
        try:
            return devs[int(input("Which one? ").strip())]
        except (ValueError, IndexError):
            print("  Enter the number of one device from the list.")


def doctor(serial):
    model = shell(serial, "getprop ro.product.model")
    sdk = shell(serial, "getprop ro.build.version.sdk")
    fos = shell(serial, "getprop ro.build.version.name")
    print(f"Device : {model} ({serial})\nAndroid SDK {sdk}  {fos}")
    if sdk.isdigit() and int(sdk) < 25:
        print("WARNING: very old Fire OS (5.x). Reports say `pm` is refused on these; expect failures.")
    return model


# ---------- snapshots ----------
def snap_path(serial, ts):
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / f"{serial.replace(':', '_')}_{ts}.json"


def latest(serial=None, suffix=".json"):
    STATE.mkdir(parents=True, exist_ok=True)
    pat = (serial.replace(":", "_") + "_") if serial else ""
    files = sorted([f for f in STATE.glob(f"{pat}*{suffix}") if suffix != ".json" or not f.name.endswith(".restore.txt")],
                   key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


def backup(serial, targets):
    ts = time.strftime("%Y%m%d-%H%M%S")
    allp, dis = pkg_sets(serial)
    before = {p: ("missing" if p not in allp else "disabled" if p in dis else "enabled") for p in targets}
    p = snap_path(serial, ts)
    p.write_text(json.dumps({"serial": serial, "time": ts, "before": before, "applied": []}, indent=2))
    (p.with_suffix(".packages.txt")).write_text(shell(serial, "pm list packages -f"))
    print(f"Backup saved: {p}")
    return p, before


# ---------- actions ----------
def apply_disable(serial, pkgs):
    done = []
    for pkg in pkgs:
        if not valid_pkg(pkg):
            print(f"  SKIP {pkg}  -> not a valid package name")
            continue
        out = shell(serial, f"pm disable-user --user 0 {pkg}")
        ok = "disabled-user" in out or "new state" in out
        print(f"  {'OK  ' if ok else 'FAIL'} {pkg}" + ("" if ok else f"  -> {out.splitlines()[0] if out else 'no output'}"))
        if ok:
            done.append(pkg)
    return done


def cmd_debloat(a):
    serial = pick_device(a)
    resolve_set(serial, a.set)
    doctor(serial)
    plan = plan_for(a.profile)
    allp, dis = pkg_sets(serial)
    todo = [p for p in plan if p in allp and p not in dis]
    if not todo:
        return print("Nothing to do: none of the profile's packages are active on this device.")
    print(f"\nProfile '{a.profile}': {len(todo)} installed package(s) found. Disabling does NOT uninstall them:\n")
    for i, p in enumerate(todo, 1):
        print(f"  {i:>2}) [{plan[p][0]:<10}] {p:<44} {plan[p][1]}")
    if a.dry_run:
        return print("\nDry run only. Nothing changed.")
    chosen = todo
    if not a.all and not a.yes:
        while True:
            raw = input("\nWhich apps do you want to disable?\n"
                        "  type numbers (e.g. 1,3,5-7), 'all', or 'none': ")
            idx = parse_choice(raw, len(todo))
            if idx is not None:
                break
            print("  Not understood. Example: 1,3,5-7")
        chosen = [todo[i] for i in idx]
    if not chosen:
        return print("Nothing selected. Nothing changed.")
    print(f"\nYou selected {len(chosen)} app(s):")
    for p in chosen:
        print(f"  - {p}  ({plan[p][1]})")
    if a.profile == "aggressive":
        print("\n!! 'aggressive' includes OTA/update services. You may stop receiving security updates.")
    if not confirm("\nDisable these apps?", a.yes):
        return print("Cancelled. Nothing changed.")
    path, _ = backup(serial, chosen)
    done = apply_disable(serial, chosen)
    data = json.loads(path.read_text())
    data["applied"] = done
    path.write_text(json.dumps(data, indent=2))
    path.with_suffix(".restore.txt").write_text("\n".join(done) + "\n")
    print(f"\nDisabled {len(done)}/{len(chosen)}. Undo anytime:  python taxis.py restore  (or restore.ps1 / restore.sh)")
    show_after(len(done))


def cmd_restore(a):
    serial = pick_device(a)
    if a.everything:
        _, dis = pkg_sets(serial)
        pkgs = sorted(dis)
        print(f"{len(pkgs)} disabled package(s) found (includes ones YOU disabled elsewhere):")
        print("  " + "\n  ".join(pkgs))
    else:
        f = Path(a.file) if a.file else latest(serial)
        if not f:
            sys.exit("No snapshot found. Use --everything to re-enable every disabled app.")
        pkgs = json.loads(f.read_text())["applied"]
        print(f"Using snapshot {f.name}: {len(pkgs)} package(s) to re-enable")
    pkgs = [p for p in pkgs if valid_pkg(p)]
    if not pkgs:
        return print("Nothing to restore.")
    if not confirm("Re-enable these?", a.yes):
        return print("Cancelled.")
    for p in pkgs:
        out = shell(serial, f"pm enable {p}")
        print(f"  {'OK  ' if 'enabled' in out else 'FAIL'} {p}")


def cmd_status(a):
    serial = pick_device(a)
    f = latest(serial)
    if not f:
        return print("No snapshot yet; nothing to compare.")
    applied = json.loads(f.read_text())["applied"]
    _, dis = pkg_sets(serial)
    back = [p for p in applied if p not in dis]
    print(f"{len(applied) - len(back)}/{len(applied)} still disabled.")
    if back:
        print("Came back (usually after a firmware update):\n  " + "\n  ".join(back))
        if a.fix and confirm("Disable them again?", a.yes):
            apply_disable(serial, back)


def cmd_audit(a):
    serial = pick_device(a)
    resolve_set(serial, a.set)
    known = set(plan_for("aggressive")) | never()
    allp, dis = pkg_sets(serial)
    skip = ("com.android.", "com.google.android.overlay", "android.auto_generated")
    unknown = sorted(p for p in allp if p not in known and not p.startswith(skip)
                     and "auto_generated" not in p and "overlay" not in p)
    print(f"{len(unknown)} packages not in any profile (review, then add to a profile if safe):")
    print("  " + "\n  ".join(unknown))


def cmd_scan(a):
    need_adb()
    for ip, model in scan():
        print(f"  {ip}:5555  {model}")


def cmd_go(a):
    """The easy route: scan -> connect -> doctor -> plan -> confirm -> apply."""
    a.dry_run = False
    a.all = False
    print("taxis wizard (safe profile). Nothing happens without your YES.\n")
    cmd_debloat(a)


def main():
    ap = argparse.ArgumentParser(prog="taxis", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("-d", "--device", help="IP[:port]; omit to auto-discover")
        p.add_argument("-y", "--yes", action="store_true", help="skip typed confirmation (not recommended)")
        p.add_argument("-s", "--set", help="profile set (e.g. firetv, tcl-g13); auto-detected if omitted")
        p.set_defaults(fn=fn)
        return p
    add("go", cmd_go, help="guided: find device, show plan, confirm, apply (safe)").set_defaults(profile="safe")
    p = add("debloat", cmd_debloat, help="disable apps from a profile")
    p.add_argument("-p", "--profile", choices=TIERS, default="safe")
    p.add_argument("--dry-run", action="store_true", help="list only, change nothing")
    p.add_argument("--all", action="store_true", help="skip picking and select every listed app")
    p = add("restore", cmd_restore, help="re-enable what we disabled")
    p.add_argument("-f", "--file")
    p.add_argument("--everything", action="store_true", help="re-enable ALL disabled apps")
    p = add("status", cmd_status, help="did an update undo my changes?")
    p.add_argument("--fix", action="store_true")
    add("audit", cmd_audit, help="list Amazon packages no profile knows about")
    add("scan", cmd_scan, help="find Fire TVs on your network")
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
