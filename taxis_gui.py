#!/usr/bin/env python3
"""Taxis GUI: connect to a TV with ADB, then choose
   1) Quick clean / Debloat only   2) Built-in launcher + Debloat   3) Undo.
Every TV gets its own folder, every run is a revertible session.
Standard library only (tkinter). Needs `adb` on PATH."""
import json, os, queue, re, shutil, subprocess, sys, threading, time, urllib.request, webbrowser
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import taxis as tx

HOME_DIR = Path.home() / ".taxis"
TV_DIR = HOME_DIR / "tvs"
DL_DIR = HOME_DIR / "downloads"
PREFS = HOME_DIR / "gui.json"
LAUNCHERS_FILE = tx.PROFILES_ROOT / "launchers.json"
BUNDLED_APK = tx.ROOT / "launcher" / "taxis-launcher.apk"
GUI_ICON = tx.ROOT / "launcher" / "res" / "drawable" / "ic_launcher.png"
BUNDLED_COMP = "com.taxis.launcher/.MainActivity"
HOME_REDIRECT_COMP = "com.taxis.launcher/com.taxis.launcher.HomeRedirectService"
FONT_CHOICES = ["Segoe UI", "Inter", "Roboto", "Noto Sans", "Open Sans", "Ubuntu", "SF Pro Text", "Helvetica Neue",
                "Cantarell", "Lato", "Poppins", "Source Sans Pro", "Fira Sans", "Calibri", "Verdana", "Trebuchet MS",
                "Arial", "DejaVu Sans"]
PRESETS = ["Auto", "Midnight", "Ocean", "Forest", "Dusk", "Graphite"]
DIMS = {"Light": 25, "Medium": 45, "Strong": 65}
COFFEE_URL = "https://buymeacoffee.com/soranagi"
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
BG_DIR = "/sdcard/Android/media/com.taxis.launcher"
DREAM_COMP = "com.taxis.launcher/com.taxis.launcher.ClockDream"
AUTO_FONT = "Auto (best available)"
MORE_FONTS = "More fonts..."
NEVER_HIDE = ("com.google.android.apps.tv.launcherx", "com.google.android.tvlauncher")
PROTECTED = re.compile(r"^(android$|com\.android\.)|settings|setup|provision|factory|systemui|recovery|gms|gsf|tungsten|"
                       r"inputmethod|keyboard|tvstartup|bluetooth|nfc|telephony|dialer", re.I)
FAIL_WORDS = ("failed", "cannot", "unable", "refused", "timed out", "no route")
MODE_NAMES = {"1": "launcher+debloat", "2": "debloat-only"}
OK, FAIL, INFO = True, False, None
APP_NAME = "Taxis"

THEMES = {
    "Dark":          dict(bg="#0f1115", panel="#1a1e24", field="#232831", sel="#2d333d", fg="#f4f1ea",
                          muted="#a6abb4", accent="#f5bd3c", accent_fg="#16181c", ok="#55d879", bad="#ff6b6b", border="#3a414d"),
    "Light":         dict(bg="#f5f6f8", panel="#ffffff", field="#ffffff", sel="#dbe7ff", fg="#1d2129",
                          muted="#5f6673", accent="#e8590c", accent_fg="#ffffff", ok="#1b7f2b", bad="#c62828", border="#c9ced6"),
    "Ocean":         dict(bg="#0d1b2a", panel="#13293d", field="#1b3a57", sel="#2a5a85", fg="#e6f1fa",
                          muted="#8fb0c9", accent="#3ec1d3", accent_fg="#06202b", ok="#5be3a0", bad="#ff7a7a", border="#27506f"),
    "Forest":        dict(bg="#121a14", panel="#1a251d", field="#223027", sel="#35523f", fg="#e7f0e9",
                          muted="#93ab99", accent="#8bd450", accent_fg="#11200a", ok="#7ee08f", bad="#ff8a80", border="#2f4636"),
    "High contrast": dict(bg="#000000", panel="#000000", field="#000000", sel="#1a1a8c", fg="#ffffff",
                          muted="#d0d0d0", accent="#ffff00", accent_fg="#000000", ok="#00ff66", bad="#ff4d4d", border="#ffffff"),
}
TEXT_SIZES = {"Small": 9, "Normal": 10, "Large": 12, "Extra large": 14}


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "tv"


def tv_dir_for(model, serialno, ip):
    """Return the stable storage folder for one TV, using its serial or IP fallback."""
    model = (model or "TV").strip() or "TV"
    serialno = (serialno or "").strip()
    ident = serialno if serialno not in ("", "unknown") else ip
    return TV_DIR / safe_name(f"{model}_{ident}")


def guard_call(fn, *a):
    """taxis's CLI helpers call sys.exit(message); turn that into an error the GUI can show."""
    try:
        return fn(*a)
    except SystemExit as e:
        raise RuntimeError(str(e.code))


def load_prefs():
    try:
        return json.loads(PREFS.read_text())
    except Exception:
        return {}


def save_prefs(p):
    try:
        HOME_DIR.mkdir(exist_ok=True)
        PREFS.write_text(json.dumps(p, indent=2))
    except OSError:
        pass


def load_catalog():
    try:
        data = json.loads(LAUNCHERS_FILE.read_text())
        return [e for e in data.get("launchers", []) if e.get("name") and e.get("github")]
    except Exception:
        return []


def download_latest_apk(entry):
    """Download the newest .apk from a GitHub release. Returns (path, tag). Cached per release."""
    repo = entry["github"]
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"User-Agent": APP_NAME, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
    except Exception as e:
        raise RuntimeError(f"Could not reach github.com/{repo}: {e}. Check your internet, "
                           "or use 'Already on the TV' / 'My own APK file' instead.")
    apks = [a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".apk")]
    if not apks:
        raise RuntimeError(f"The latest release of {repo} has no .apk file. "
                           "Use 'My own APK file' or pick another built-in launcher.")
    apks.sort(key=lambda a: ("universal" not in a["name"].lower(), "tv" not in a["name"].lower(), a["name"]))
    a = apks[0]
    DL_DIR.mkdir(parents=True, exist_ok=True)
    dest = DL_DIR / f"{safe_name(repo)}_{safe_name(rel.get('tag_name', 'latest'))}_{safe_name(a['name'])}"
    if not (dest.exists() and dest.stat().st_size == a.get("size", -1)):
        tmp = dest.with_suffix(".part")
        try:
            dreq = urllib.request.Request(a["browser_download_url"], headers={"User-Agent": APP_NAME})
            with urllib.request.urlopen(dreq, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 16)
            with open(tmp, "rb") as f:
                magic = f.read(2)
            if magic != b"PK" or tmp.stat().st_size < 100_000:
                raise RuntimeError("The downloaded file is not a valid APK.")
            tmp.replace(dest)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Download failed: {e}")
    return str(dest), rel.get("tag_name", "latest")


# ----------------------------------------------------------------------------
# Engine: all ADB logic, no UI. emit(step, target, ok, detail) reports results.
# ----------------------------------------------------------------------------
class Engine:
    def __init__(self):
        self.serial = None
        self.info = {}
        self.set = None
        self.dir = None
        self.is_fire = False
        self.home_failed = None   # set when the TV accepted a new home but kept its own

    # ---- connection ----
    # Connects to one TV and initializes its device-specific working state.
    def connect(self, ip, port="5555"):
        guard_call(tx.need_adb)
        ip = ip.strip()
        port = (port or "5555").strip()
        target = f"{ip}:{port}"
        out = tx.sh("connect", target, timeout=20)[1]
        if any(w in out.lower() for w in FAIL_WORDS):
            raise RuntimeError(f"{out}\n\nCheck the IP, that debugging is ON and the TV is awake.\n"
                               "Samsung (Tizen) and LG (webOS) TVs are not supported.")
        state = self._state(target)
        if state == "unauthorized":
            raise RuntimeError("The TV is waiting for approval.\nAccept 'Allow USB debugging?' on the TV "
                               "(tick Always allow), then press Connect again.")
        if state != "device":
            raise RuntimeError(f"Device state: {state or 'not listed'}. Try 'adb kill-server' and connect again.")
        guard_call(tx.guard, target)
        self.serial = target
        # one round-trip per property is slow over Wi-Fi: fetch them all in parallel
        keys = {"manufacturer": "ro.product.manufacturer", "model": "ro.product.model", "device": "ro.product.device",
                "android": "ro.build.version.release", "sdk": "ro.build.version.sdk",
                "fingerprint": "ro.build.fingerprint", "serialno": "ro.serialno"}
        with ThreadPoolExecutor(len(keys)) as ex:
            vals = dict(zip(keys, ex.map(lambda k: tx.shell(target, f"getprop {keys[k]}").strip(), keys)))
        self.info = {"ip": ip, "port": port, **vals}
        maker, dev = vals["manufacturer"], vals["device"]
        self.is_fire = "amazon" in maker.lower()
        self.set = "firetv" if self.is_fire else ("tcl-g13" if dev == "G13" else None)
        if self.set:
            tx.SET = self.set
        self.dir = tv_dir_for(vals["model"], vals["serialno"], ip)
        (self.dir / "sessions").mkdir(parents=True, exist_ok=True)
        meta = self.dir / "device.json"
        try:
            first = json.loads(meta.read_text()).get("first_seen")
        except Exception:
            first = None
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        meta.write_text(json.dumps({**self.info, "first_seen": first or now, "last_seen": now}, indent=2))
        return self.info

    def _state(self, serial):
        for line in tx.sh("devices")[1].splitlines()[1:]:
            p = line.split()
            if len(p) == 2 and p[0] == serial:
                return p[1]
        return None

    def use_set(self, name):
        self.set = name or None
        if name:
            tx.SET = name

    # ---- apps ----
    def plan(self, tier):
        if not self.set:
            return []
        plan = tx.plan_for(tier)
        allp, dis = tx.pkg_sets(self.serial)
        return [(p, plan[p][0], plan[p][1]) for p in plan if p in allp and p not in dis]

    # ---- home launcher ----
    @staticmethod
    def _components(text):
        return [l.strip() for l in text.splitlines() if "/" in l and " " not in l.strip() and not l.startswith("#")]

    def _query(self, verb, extra=""):
        base = f"{verb} --brief -a android.intent.action.MAIN -c android.intent.category.HOME"
        comps = self._components(tx.shell(self.serial, "cmd package " + base))
        return comps or self._components(tx.shell(self.serial, "pm " + base))

    def current_home(self):
        comps = self._query("resolve-activity")
        return comps[-1] if comps else None

    def list_homes(self):
        return sorted({c for c in self._query("query-activities") if not c.startswith("android/")})

    def role_holder(self):
        """Android 10+ keeps the default home in the HOME role. Returns the package holding it."""
        out = tx.shell(self.serial, "cmd role get-role-holders --user 0 android.app.role.HOME").strip()
        m = re.search(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", out.splitlines()[0]) if out else None
        return m.group(0) if m else None

    def _is_home(self, comp):
        """True only if the TV really resolves HOME to this launcher. (The HOME role alone is not enough:
        Google TV can hold the role for us and still open its own launcher.)"""
        cur = self.current_home()
        if cur:
            return cur == comp
        return self.role_holder() == comp.split("/")[0]

    def _set_home(self, comp):
        tx.shell(self.serial, f"cmd package set-home-activity --user 0 {comp}")
        if self._is_home(comp):
            return True, "the TV now uses it as the home screen"
        tx.shell(self.serial, f"cmd role add-role-holder --user 0 android.app.role.HOME {comp.split('/')[0]}")
        if self._is_home(comp):
            return True, "the TV now uses it as the home screen (through the HOME role)"
        cur = self.current_home() or self.role_holder() or "its own launcher"
        return False, f"The TV accepted the command but still uses {cur} as its home screen."

    # ---- sessions ----
    def _new_session(self, mode):
        sid = time.strftime("%Y%m%d-%H%M%S") + "_" + mode
        d = self.dir / "sessions" / sid
        d.mkdir(parents=True, exist_ok=True)
        allp, dis = tx.pkg_sets(self.serial)
        (d / "packages-before.txt").write_text("\n".join(sorted(allp)))
        sess = {"id": sid, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode, "status": "running",
                "before": {"home": self.current_home(), "disabled": sorted(dis), "homes": self.list_homes()},
                "actions": {"disabled": [], "installed_apk": None, "home_set": None, "stock_hidden": None},
                "reverted": False}
        return d, sess

    @staticmethod
    def _save(d, sess):
        (d / "session.json").write_text(json.dumps(sess, indent=2))

    def sessions(self):
        out = []
        for f in sorted((self.dir / "sessions").glob("*/session.json"), reverse=True):
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                pass
        return out

    def _load(self, sid):
        f = self.dir / "sessions" / sid / "session.json"
        return f.parent, json.loads(f.read_text())

    # ---- actions ----
    def _disable(self, pkgs, emit):
        done = []
        for p in pkgs:
            out = tx.shell(self.serial, f"pm disable-user --user 0 {p}")
            ok = "disabled-user" in out or "new state" in out
            emit("Disable app", p, ok, (out.splitlines()[0] if out else "no output"))
            if ok:
                done.append(p)
        _, dis = tx.pkg_sets(self.serial)  # verify against the real state
        return [p for p in done if p in dis]

    def run(self, mode, pkgs, launcher, emit):
        """mode '1' = launcher+debloat, '2' = debloat only."""
        self.home_failed = None
        d, sess = self._new_session(MODE_NAMES[mode])
        self._save(d, sess)
        emit("Session", sess["id"], INFO, f"saved in {d}")
        if mode == "1":
            self._launcher_step(sess, launcher, emit)
        if pkgs:
            sess["actions"]["disabled"] = self._disable(pkgs, emit)
        sess["status"] = "done"
        self._save(d, sess)
        emit("Home now", self.current_home() or "unknown", INFO, "current default home app")
        return sess

    def _launcher_step(self, sess, launcher, emit):
        """Install or select a launcher, configure Taxis, and use the safest Home behavior for this TV."""
        src, comp, apk = launcher.get("source"), launcher.get("component"), launcher.get("apk")
        redirect_wanted = bool(launcher.get("home_redirect")) or self._home_redirect_active(self.serial)
        if src == "bundled":
            if not BUNDLED_APK.is_file():
                emit("Taxis Launcher", str(BUNDLED_APK), FAIL, "the included launcher APK is missing")
                return
            apk, comp = str(BUNDLED_APK), None
        elif src == "builtin":
            entry = launcher["entry"]
            try:
                apk, tag = download_latest_apk(entry)
                emit("Download launcher", entry["name"], OK, f"release {tag}, saved in {DL_DIR}")
            except RuntimeError as e:
                emit("Download launcher", entry["name"], FAIL, str(e))
                return
            comp = None
        elif src == "installed":
            apk = None
        else:
            comp = None
        if apk:
            out = tx.sh("install", "-r", apk, serial=self.serial, timeout=240)[1]
            ok = "Success" in out
            emit("Install launcher APK", os.path.basename(apk), ok, out.splitlines()[-1] if out else "no output")
            if not ok:
                return
            bgc = launcher.get("bg")
            if src == "bundled" and bgc:
                self.set_background(bgc.get("path"), bgc.get("dim", "Medium"), bgc.get("preset", "Auto"), emit)
            new = sorted(set(self.list_homes()) - set(sess["before"]["homes"]))
            sess["actions"]["installed_apk"] = {"file": os.path.basename(apk), "new_homes": new}
            if new:
                comp = new[0]
                emit("Detect launcher", comp, INFO, "new home app found after install")
            elif src == "bundled":
                comp = BUNDLED_COMP  # known component: no need to guess
                emit("Detect launcher", comp, INFO, "Taxis Launcher installed or updated")
            else:
                emit("Detect launcher", os.path.basename(apk), FAIL,
                     "no new home app detected; pick it in 'Already on the TV' and press 'Set as default home'")
        if not comp:
            if src == "installed":
                emit("Launcher", "-", FAIL, "no installed home app selected")
            return
        if src == "bundled":
            self.configure_launcher(launcher.get("city", ""), launcher.get("units", "C"), emit)
            if redirect_wanted:
                active = self._set_home_redirect(self.serial, True)
                emit("Keep Home redirect", "enabled" if active else "not enabled", active,
                     "restored after the launcher update" if active else "use Enable Home redirect on the Taxis Home page")
        if src == "bundled" and self.info.get("device") == "G13":
            emit("Safe system Home", "Google TV", OK,
                 "kept enabled for reliable startup; Taxis Home redirect handles the remote Home button")
            out = tx.shell(self.serial, f"am start -n {BUNDLED_COMP}")
            emit("Open Taxis", BUNDLED_COMP, "error" not in out.lower() and "exception" not in out.lower(), "opened on the TV")
            return
        prev = sess["before"]["home"]
        ok, detail = self._set_home(comp)
        emit("Set default home", comp, ok, detail)
        if not ok:
            if not self.is_fire:
                self.home_failed = comp
            return
        sess["actions"]["home_set"] = {"from": prev, "to": comp}
        self.go_home()
        emit("Show home screen", comp, INFO, "sent the Home key so you can see it on the TV now")
        if (launcher.get("hide_stock") and prev and prev.split("/")[0] != comp.split("/")[0] and not self.is_fire
                and prev.split("/")[0] not in NEVER_HIDE and not PROTECTED.search(prev.split("/")[0])):
            pkg = prev.split("/")[0]
            out = tx.shell(self.serial, f"pm disable-user --user 0 {pkg}")
            ok2 = "disabled-user" in out or "new state" in out
            emit("Hide stock launcher", pkg, ok2, out.splitlines()[0] if out else "no output")
            if ok2:
                sess["actions"]["stock_hidden"] = pkg

    def configure_launcher(self, city, units, emit):
        """Apply weather units and either a chosen city or the TV's network location."""
        city = re.sub(r"[^\w .,-]", "", city or "").strip()
        units = "f" if units == "F" else "c"
        pkg = BUNDLED_COMP.split("/")[0]
        grant = tx.shell(self.serial, f"pm grant {pkg} android.permission.ACCESS_COARSE_LOCATION")
        granted = "exception" not in grant.lower() and "error" not in grant.lower()
        emit("TV location access", "approximate location", granted,
             "used only for local weather; IP location is the fallback" if granted else self._first(grant))
        mode = f"--es city '{city}'" if city else "--ez auto_location true"
        cmd = f"am start -n {BUNDLED_COMP} --es units {units} {mode}"
        out = tx.shell(self.serial, cmd)
        ok = "error" not in out.lower() and "exception" not in out.lower()
        emit("Taxis weather", city or "automatic TV location", ok,
             f"units {units.upper()}" if ok else (out.splitlines()[-1] if out else "no output"))

    @staticmethod
    def _first(out):
        out = (out or "").strip()
        return out.splitlines()[0] if out else "no output"

    def _disable_home_app(self, h, emit):
        """Hide one competing home app. Tries the whole package first, then just its home activity."""
        pkg = h.split("/")[0]
        out = tx.shell(self.serial, f"pm disable-user --user 0 {pkg}")
        if "disabled-user" in out or "new state" in out:
            emit("Hide original home", pkg, OK, self._first(out))
            return "pkg", pkg
        emit("Hide original home", pkg, INFO, "the TV refused to turn off the whole app: " + self._first(out))
        out2 = tx.shell(self.serial, f"pm disable --user 0 {h}")
        if "disabled" in out2 and "exception" not in out2.lower() and "error" not in out2.lower():
            emit("Hide its home screen only", h, OK, self._first(out2))
            return "comp", h
        emit("Hide its home screen only", h, FAIL, self._first(out2))
        return None, None

    def make_default(self, comp, emit, city="", units="C", hide=False):
        """Try everything, safest first, and say exactly what the TV answered:
           1) ask the TV  2) HOME role  3) hide the competing home apps (undoable)."""
        pkg = comp.split("/")[0]
        allp, _dis = tx.pkg_sets(self.serial)
        if pkg not in allp:
            emit("Launcher installed", pkg, FAIL, "It is not on the TV. Press 'Install and set as default' first.")
            return False
        homes = self.list_homes()
        if comp not in homes:
            emit("Offered as a home screen", comp, FAIL,
                 "The TV does not list the launcher as a home app, so it cannot be the default. Reinstall it, then try again.")
            return False
        d, sess = self._new_session("make-default")
        prev = self.current_home()
        ok, detail = self._set_home(comp)
        emit("Ask the TV to use it", comp, ok, detail)
        hidden_pkgs, hidden_comps = [], []
        if not ok and hide:
            winner = self.current_home()
            if not winner:
                emit("Home app the TV uses", "unknown", FAIL, "could not read which home app the TV uses, so nothing was turned off")
            elif winner.split("/")[0] == pkg:
                emit("Home app the TV uses", winner, INFO, "already ours")
            elif winner.split("/")[0] in NEVER_HIDE:
                emit("Home app the TV uses", winner, FAIL,
                     "This is Google TV's own launcher. Taxis will not turn it off: this TCL model needs it to start safely. "
                     "doing so left the TV stuck on its loading screen after a restart.")
            elif re.search(r"setupwraith|recovery", winner, re.I):
                emit("Home app the TV uses", winner, FAIL,
                     "This is Google TV's own recovery screen. The TV switches to it when its normal launcher is off, "
                     "so it is protected and Taxis will not turn it off. If Home shows a setup or recovery screen, "
                     "open Undo and undo the 'make-default' session, then run 'Full home check' and send me the report.")
            elif PROTECTED.search(winner.split("/")[0]):
                emit("Home app the TV uses", winner, FAIL,
                     "this is a protected system app. Taxis will not turn it off, to keep your TV safe.")
            else:
                emit("Home app the TV uses", winner, INFO, "this one wins over your launcher, so it is the one to turn off (undoable)")
                kind, what = self._disable_home_app(winner, emit)
                if kind == "pkg":
                    hidden_pkgs.append(what)
                elif kind == "comp":
                    hidden_comps.append(what)
            if hidden_pkgs or hidden_comps:
                ok, detail = self._set_home(comp)
                emit("Ask the TV again", comp, ok, detail)
                if not ok:  # never leave the TV worse than we found it
                    for h in hidden_pkgs:
                        tx.shell(self.serial, f"pm enable {h}")
                    for h in hidden_comps:
                        tx.shell(self.serial, f"pm enable {h}")
                    emit("Put things back", "-", INFO, "turned the original home app back on because the launcher did not take over")
                    hidden_pkgs, hidden_comps = [], []
        sess["actions"]["hidden_packages"] = hidden_pkgs
        sess["actions"]["hidden_components"] = hidden_comps
        sess["actions"]["stock_hidden"] = hidden_pkgs[0] if hidden_pkgs else None
        if ok:
            sess["actions"]["home_set"] = {"from": prev, "to": comp}
            if pkg == BUNDLED_COMP.split("/")[0]:
                self.configure_launcher(city, units, emit)
            self.go_home()
            time.sleep(2.5)
            shown = self._focus()
            if pkg in shown:
                emit("Default home", comp, OK, "confirmed: pressing Home now opens Taxis Launcher")
            else:
                emit("Default home", comp, INFO, f"the TV resolves Home to your launcher, but right now {shown} is on screen. Press Home on the remote; if it still goes elsewhere run 'Full home check'.")
        else:
            emit("Default home", comp, FAIL,
                 "This TV keeps its own system Home. Taxis will not turn off Google TV's launcher to force it, "
                 "because that can stop the TV from starting. Nothing was left changed.")
        sess["status"] = "done"
        self._save(d, sess)
        return ok

    def force_home(self, comp, emit, city="", units="C"):
        return self.make_default(comp, emit, city, units, hide=True)

    def _focus(self):
        """Which activity is on screen right now."""
        out = tx.shell(self.serial, "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=30)
        m = re.findall(r"([A-Za-z][A-Za-z0-9_.]*)/([A-Za-z0-9_.$]+)", out)
        if m:
            return f"{m[0][0]}/{m[0][1]}"
        return (out.strip().splitlines()[0][:120] if out.strip() else "unknown")

    def home_check(self, emit):
        """Find out WHY the Home button does not open the launcher: collects the facts and gives a verdict."""
        comp = BUNDLED_COMP
        pkg = comp.split("/")[0]
        report = [f"Taxis home check  {time.strftime('%Y-%m-%d %H:%M:%S')}",
                  f"TV: {self.info.get('manufacturer','')} {self.info.get('model','')}  Android {self.info.get('android','')}  sdk {self.info.get('sdk','')}",
                  f"build: {self.info.get('fingerprint','')}"]

        def note(step, target, ok, detail=""):
            emit(step, target, ok, detail)
            report.append(f"[{ {True:'OK',False:'FAIL',None:'..'}[ok] }] {step}: {target}  {detail}".rstrip())

        allp, dis = tx.pkg_sets(self.serial)
        note("Launcher installed", pkg, OK if pkg in allp else FAIL, "" if pkg in allp else "Install it first.")
        if pkg in dis:
            note("Launcher turned off", pkg, FAIL, "the launcher itself is disabled")
        homes = self.list_homes()
        note("Home apps the TV offers", ", ".join(homes) or "none", INFO)
        note("Our launcher is offered", comp, OK if comp in homes else FAIL)
        cur = self.current_home()
        note("TV's chosen home (resolve)", cur or "unknown", OK if cur == comp else INFO)
        holder = self.role_holder()
        note("HOME role holder", holder or "unknown", OK if holder == pkg else INFO)
        off = sorted(p for p in dis if re.search(r"launcher|home", p, re.I))
        note("Home-related apps turned off", ", ".join(off) or "none", INFO)
        rel = tx.shell(self.serial, "pm list packages | grep -iE 'launcher|home|tvrecommend|tvstartup'").replace("package:", "").split()
        note("Home-related apps on the TV", ", ".join(sorted(rel)) or "none", INFO)

        raw = tx.shell(self.serial, "cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME", timeout=30)
        cands = []
        for blk in re.split(r"(?=\bpriority=)", raw)[1:]:
            pr = re.match(r"priority=(-?\d+)", blk)
            nm = re.search(r"packageName=([\w.]+)", blk)
            an = re.search(r"\bname=([\w.$]+)", blk)
            if pr and nm:
                cands.append(f"{nm.group(1)}{'/' + an.group(1).split('.')[-1] if an else ''} (priority {pr.group(1)})")
        note("Home candidates and their priority", "; ".join(cands) or "could not read", INFO,
             "higher priority wins when the TV has no saved choice")
        report.append("--- raw query-activities ---")
        report.append(raw[:3000])
        report.append("--- end raw ---")

        tx.shell(self.serial, "input keyevent KEYCODE_HOME")
        time.sleep(2.5)
        key = self._focus()
        note("Pressing HOME opens", key, OK if pkg in key else FAIL)
        tx.shell(self.serial, "am start -a android.intent.action.MAIN -c android.intent.category.HOME")
        time.sleep(2.5)
        intent = self._focus()
        note("The HOME request opens", intent, OK if pkg in intent else FAIL)

        if pkg in key:
            verdict, nxt = OK, "The Home key opens Taxis Launcher. It works."
        else:
            verdict = FAIL
            if holder == pkg:
                why = "The TV accepted your launcher as its home setting, but its own launcher outranks it"
            else:
                why = "The TV did not accept the home setting"
            nxt = (f"The Home button opens {key}. {why}. "
                   "Taxis will not turn that launcher off because this TCL model needs it during startup. "
                   "Use the safe Home redirect instead.")
        note("Verdict", "-", verdict, nxt)
        try:
            f = self.dir / "home-report.txt"
            f.write_text("\n".join(report), encoding="utf-8")
            emit("Report saved", str(f), INFO, "send me this file or use 'Copy log' and paste it")
        except OSError:
            pass

    def set_background(self, path, dim_name, preset, emit, clear=False):
        """Send a picture and style to Taxis Launcher, which keeps its own private copy."""
        pkg = BUNDLED_COMP.split("/")[0]
        if pkg not in tx.pkg_sets(self.serial)[0]:
            emit("Background", pkg, FAIL, "Taxis Launcher is not installed yet. Install it first.")
            return
        dim = DIMS.get(dim_name, 45)
        extra = f"--ei dim {dim} --es preset {re.sub('[^a-z]', '', preset.lower()) or 'auto'}"
        if clear:
            out = tx.shell(self.serial, f"am start -n {BUNDLED_COMP} --ez bg_clear true {extra}")
            emit("Remove background image", "-", "error" not in out.lower(), "the launcher goes back to its plain background")
            return
        if path:
            ext = os.path.splitext(path)[1].lower()
            if not os.path.isfile(path) or ext not in IMG_EXT:
                emit("Background image", path, FAIL, "Choose a .jpg, .png, .webp or .bmp file that exists.")
                return
            mb = os.path.getsize(path) / 1048576
            if mb > 40:
                emit("Background image", os.path.basename(path), FAIL, f"The picture is {mb:.0f} MB. Please use one under 40 MB.")
                return
            remote = f"{BG_DIR}/upload{ext}"
            tx.shell(self.serial, f"mkdir -p {BG_DIR}")
            rc, out = tx.sh("push", path, remote, serial=self.serial, timeout=180)
            pushed = rc == 0 or "pushed" in out
            emit("Send picture to the TV", os.path.basename(path), pushed, out.splitlines()[-1] if out else "sent")
            if not pushed:
                return
            g = tx.shell(self.serial, f"pm grant {pkg} android.permission.READ_EXTERNAL_STORAGE")
            emit("Allow the launcher to read it", pkg, INFO, g.splitlines()[0] if g else "allowed")
            out = tx.shell(self.serial, f"am start -n {BUNDLED_COMP} --es bg {remote} {extra}")
            emit("Apply background", "-", "error" not in out.lower(), "Look at the TV. If it did not change, a note appears under the place name.")
            time.sleep(4)
            tx.shell(self.serial, f"rm -f {remote}")  # the launcher already kept its own copy
        else:
            out = tx.shell(self.serial, f"am start -n {BUNDLED_COMP} {extra}")
            emit("Background style", f"{preset}, {dim_name} darkness", "error" not in out.lower(), "applied")

    def emergency_restore(self, ip, port, emit, tries=30, wait=6):
        """For a TV that will not finish starting: wait for ADB, turn back on everything taxis ever hid, restart."""
        guard_call(tx.need_adb)
        target = f"{ip.strip()}:{(port or '5555').strip()}"
        state = None
        for i in range(tries):
            out = tx.sh("connect", target, timeout=15)[1]
            state = self._state(target)
            if state == "device":
                break
            note = "needs approval on the TV" if state == "unauthorized" else (out.splitlines()[-1] if out else "no answer yet")
            emit("Waiting for the TV", target, INFO, f"try {i + 1} of {tries}: {note}")
            time.sleep(wait)
        if state != "device":
            emit("Reach the TV", target, FAIL, "The TV did not answer. Check the IP address (it may have changed), wait a few minutes "
                                              "for it to finish starting, or switch it off at the wall for 30 seconds and try again.")
            return
        emit("Reach the TV", target, OK, "connected")
        ser = target
        allp, dis = tx.pkg_sets(ser)
        model = tx.shell(ser, "getprop ro.product.model").strip()
        serialno = tx.shell(ser, "getprop ro.serialno").strip()
        session_files = list((tv_dir_for(model, serialno, ip) / "sessions").glob("*/session.json"))
        todo = set(p for p in dis if p in NEVER_HIDE)
        for f in session_files:
            try:
                a = json.loads(f.read_text()).get("actions", {})
            except Exception:
                continue
            todo.update(a.get("hidden_packages") or [])
            if a.get("stock_hidden"):
                todo.add(a["stock_hidden"])
        comps = set()
        for f in session_files:
            try:
                comps.update(json.loads(f.read_text()).get("actions", {}).get("hidden_components") or [])
            except Exception:
                pass
        todo = {p for p in todo if tx.valid_pkg(p)}
        comps = {c for c in comps if tx.valid_comp(c)}
        if not todo and not comps:
            emit("Turn things back on", "-", INFO, "nothing recorded as turned off")
        for pkg in sorted(todo):
            out = tx.shell(ser, f"pm enable {pkg}")
            emit("Turn back on", pkg, "enabled" in out, out.splitlines()[0] if out else "no output")
        for c in sorted(comps):
            out = tx.shell(ser, f"pm enable {c}")
            emit("Turn back on", c, "enabled" in out, out.splitlines()[0] if out else "no output")
        _, dis = tx.pkg_sets(ser)
        homes = []
        for f in sorted(session_files, reverse=True):
            try:
                h = (json.loads(f.read_text()).get("before") or {}).get("home")
            except Exception:
                continue
            if h and tx.valid_comp(h) and h not in homes:
                homes.append(h)
        restored = False
        for h in homes:
            if h.split("/")[0] in allp and h.split("/")[0] not in dis:
                tx.shell(ser, f"cmd package set-home-activity --user 0 {h}")
                emit("Restore home screen", h, INFO, "asked the TV to use its previous home screen again")
                restored = True
                break
        if not restored and "com.google.android.apps.tv.launcherx" in allp:
            tx.shell(ser, "cmd package set-home-activity --user 0 com.google.android.apps.tv.launcherx/.home.HomeActivity")
            emit("Restore Google TV home", "launcherx", INFO, "asked the TV to use its own home screen again")
        elif not restored:
            emit("Restore home screen", "-", INFO, "no previous home recorded; choose one with the remote's Home button")
        redirect_active = self._set_home_redirect(ser, False)
        emit("Turn off Home redirect", HOME_REDIRECT_COMP, not redirect_active,
             "disabled so Google TV's home screen stays available during recovery")
        tx.sh("reboot", serial=ser, timeout=20)
        emit("Restart the TV", "-", OK, "Restarting now. Give it a few minutes. If it is still stuck, run this again.")
        self.serial = None

    def restart_check(self, emit):
        """Before restarting the TV: look for anything taxis changed that could stop it from finishing startup."""
        problems = 0
        allp, dis = tx.pkg_sets(self.serial)

        def rec(step, target, ok, detail=""):
            nonlocal problems
            if ok is False:
                problems += 1
            emit(step, target, ok, detail)

        for pkg in NEVER_HIDE:
            if pkg in allp:
                off = pkg in dis
                rec("Google TV launcher", pkg, FAIL if off else OK,
                    "it is OFF, which can stop the TV finishing startup. Press 'Rescue my TV' to turn it back on." if off else "turned on")
        ours = BUNDLED_COMP.split("/")[0]
        risky = sorted(p for p in dis if p != ours and (PROTECTED.search(p) or re.search(r"launcher|home|tvstartup|provision|setupwraith|tvrecommend", p, re.I)))
        rec("System apps that are turned off", ", ".join(risky) or "none", FAIL if risky else OK,
            "these look important for startup; turn them back on in Undo" if risky else "no important system apps are off")
        sessions_off = set()
        if self.dir:
            for f in (self.dir / "sessions").glob("*/session.json"):
                try:
                    data = json.loads(f.read_text())
                except Exception:
                    continue
                if not data.get("reverted"):
                    sessions_off.update(data.get("actions", {}).get("disabled", []))
        rec("Ordinary apps Taxis turned off", f"{len(sessions_off)} app(s)", INFO,
            "preloaded extras such as games and promo apps; low risk, and Undo turns them back on")
        cur = self.current_home()
        pkgc = cur.split("/")[0] if cur else ""
        good = bool(cur) and pkgc in allp and pkgc not in dis
        rec("Home screen at startup", cur or "unknown", OK if good else FAIL,
            "an installed, turned-on home app" if good else "the TV's chosen home app is missing or turned off")
        holder = self.role_holder()
        if ours in allp:
            rec("Taxis Launcher", ours, INFO, f"installed; HOME role holder is {holder or 'unknown'}; system Home is {cur or 'unknown'}")
        tcp = tx.shell(self.serial, "getprop persist.adb.tcp.port").strip()
        wifi_adb = tx.shell(self.serial, "settings get global adb_wifi_enabled").strip()
        stays = tcp.isdigit() or wifi_adb == "1"
        rec("Wi-Fi debugging after a restart", "-", INFO if stays else None,
            "should come back on after a restart" if stays else
            "NOT guaranteed to come back after a restart. If the TV ever hangs, 'Rescue my TV' may not be able to reach it. Keep this in mind for the first restart.")
        if problems:
            emit("Verdict", "-", FAIL, "Do not restart yet. Fix the red items first (Rescue my TV or Undo).")
        else:
            emit("Verdict", "-", OK,
                 "Nothing Taxis changed should stop the TV from starting. This is not a guarantee, because Taxis cannot test every firmware. "
                 "For the first restart, keep this window open and the TV's IP address handy.")

    def _setting(self, key):
        out = tx.shell(self.serial, f"settings get secure {key}").strip()
        return out.splitlines()[0] if out else "null"

    def _set_home_redirect(self, serial, enabled):
        """Add or remove only taxis's Accessibility service while preserving every other enabled service."""
        raw = tx.shell(serial, "settings get secure enabled_accessibility_services").strip()
        services = [] if raw in ("", "null") else [item for item in raw.split(":") if item]
        services = [item for item in services if item != HOME_REDIRECT_COMP]
        if enabled:
            services.append(HOME_REDIRECT_COMP)
        if services:
            tx.shell(serial, "settings put secure enabled_accessibility_services " + ":".join(services))
        else:
            tx.shell(serial, "settings delete secure enabled_accessibility_services")
        if enabled:
            tx.shell(serial, "settings put secure accessibility_enabled 1")
        elif not services:
            tx.shell(serial, "settings put secure accessibility_enabled 0")
        current = tx.shell(serial, "settings get secure enabled_accessibility_services").strip()
        return HOME_REDIRECT_COMP in current.split(":")

    def _home_redirect_active(self, serial=None):
        """Return whether Android currently has the Taxis Home redirect enabled."""
        raw = tx.shell(serial or self.serial, "settings get secure enabled_accessibility_services").strip()
        return HOME_REDIRECT_COMP in raw.split(":")

    def set_home_redirect(self, enabled, emit):
        """Enable or disable the Home-button redirect and report the verified TV setting."""
        pkg = BUNDLED_COMP.split("/")[0]
        if enabled and pkg not in tx.pkg_sets(self.serial)[0]:
            emit("Home redirect", pkg, FAIL, "Install Taxis Launcher first.")
            return
        active = self._set_home_redirect(self.serial, enabled)
        ok = active == enabled
        emit("Home redirect", "enabled" if active else "disabled", ok,
             "Press Home to test it. Google TV may appear briefly before Taxis returns."
             if active else "Google TV's normal Home button is restored.")

    def set_screensaver(self, emit):
        """Use Taxis Idle as the TV's screensaver and record every changed setting for Undo."""
        pkg = DREAM_COMP.split("/")[0]
        if pkg not in tx.pkg_sets(self.serial)[0]:
            emit("Screensaver", pkg, FAIL, "Taxis Launcher is not installed yet. Install it first.")
            return
        old = {"components": self._setting("screensaver_components"), "enabled": self._setting("screensaver_enabled"),
               "sleep": self._setting("screensaver_activate_on_sleep"), "dock": self._setting("screensaver_activate_on_dock")}
        if old["components"] == DREAM_COMP:
            emit("Screensaver", DREAM_COMP, INFO, "already in use")
            return
        d, sess = self._new_session("screensaver")
        tx.shell(self.serial, f"settings put secure screensaver_components {DREAM_COMP}")
        tx.shell(self.serial, "settings put secure screensaver_enabled 1")
        tx.shell(self.serial, "settings put secure screensaver_activate_on_sleep 1")
        tx.shell(self.serial, "settings put secure screensaver_activate_on_dock 1")
        now = self._setting("screensaver_components")
        ok = now == DREAM_COMP
        emit("Use Taxis Idle as screensaver", DREAM_COMP, ok,
             "enabled for idle and sleep; set the delay in the TV's Screen saver settings."
             if ok else f"the TV answered '{now}' instead")
        sess["actions"]["screensaver"] = old if ok else None
        sess["status"] = "done"
        self._save(d, sess)

    def preview_screensaver(self, emit):
        """Start the configured screensaver using Android's supported Dream manager command."""
        if self._setting("screensaver_components") != DREAM_COMP:
            self.set_screensaver(emit)
            if self._setting("screensaver_components") != DREAM_COMP:
                return
        out = tx.shell(self.serial, "cmd dreams start-dreaming")
        bad = "error" in out.lower() or "exception" in out.lower() or "not exist" in out.lower()
        emit("Preview screensaver", "-", not bad,
             "started. Press Back on the remote to close it." if not bad else
             "this TV cannot start it from here. Just leave the TV idle and it will appear (after the delay set in the TV's Settings).")

    def clear_screensaver(self, emit):
        """Put the TV's own screensaver back."""
        for s in self.sessions():
            if s["actions"].get("screensaver") and not s.get("reverted"):
                self.revert(s["id"], emit)
                return
        if self._setting("screensaver_components") == DREAM_COMP:
            tx.shell(self.serial, "settings delete secure screensaver_components")
            emit("Screensaver", "-", OK, "removed Taxis Idle; the TV's own screensaver is used again")
        else:
            emit("Screensaver", "-", INFO, "Taxis Idle is not the screensaver right now")

    def go_home(self):
        tx.shell(self.serial, "input keyevent KEYCODE_HOME")

    def diagnose(self, emit):
        """Run a plain-English health check of Taxis Launcher on the TV."""
        pkg = BUNDLED_COMP.split("/")[0]
        allp, _dis = tx.pkg_sets(self.serial)
        inst = pkg in allp
        emit("Launcher installed", pkg, OK if inst else FAIL, "yes" if inst else "No. Press 'Install and set as default' first.")
        if not inst:
            return
        homes = self.list_homes()
        emit("Offered as a home screen", BUNDLED_COMP, OK if BUNDLED_COMP in homes else FAIL,
             "the TV lists it as a home app" if BUNDLED_COMP in homes else "the TV does not list it as a home app")
        cur = self.current_home()
        emit("Default home right now", cur or "unknown", OK if cur == BUNDLED_COMP else INFO,
             "it is the default" if cur == BUNDLED_COMP else "another launcher is the default; press 'Install and set as default'")
        out = tx.shell(self.serial, f"am start -n {BUNDLED_COMP}")
        bad = "error" in out.lower() or "exception" in out.lower()
        emit("Open the launcher", BUNDLED_COMP, FAIL if bad else OK, (out.splitlines()[-1] if out else "started"))
        log = tx.shell(self.serial, "logcat -d -t 600 AndroidRuntime:E taxis:E *:S", timeout=30)
        hits = [l.strip() for l in log.splitlines() if "taxis" in l.lower()]
        if hits:
            emit("Crash log", "last problems", FAIL, " | ".join(hits[-3:])[:400])
        else:
            emit("Crash log", "-", OK, "no crashes recorded")

    def set_default_home(self, comp, emit):
        d, sess = self._new_session("set-home")
        prev = sess["before"]["home"]
        ok, detail = self._set_home(comp)
        emit("Set default home", comp, ok, detail)
        if ok:
            sess["actions"]["home_set"] = {"from": prev, "to": comp}
        sess["status"] = "done"
        self._save(d, sess)
        return sess

    def revert(self, sid, emit):
        """Undo the selected session while always keeping Taxis Launcher installed."""
        d, sess = self._load(sid)
        a = sess["actions"]
        if sess.get("reverted"):
            emit("Revert", sid, INFO, "already reverted")
            return sess
        hidden_pkgs = [h for h in (a.get("hidden_packages") or ([a["stock_hidden"]] if a.get("stock_hidden") else []))
                       if tx.valid_pkg(h)]
        hidden_comps = [h for h in a.get("hidden_components", []) if tx.valid_comp(h)]
        disabled_pkgs = [p for p in a.get("disabled", []) if tx.valid_pkg(p)]
        for h in hidden_pkgs:
            out = tx.shell(self.serial, f"pm enable {h}")
            emit("Re-enable original home", h, "enabled" in out, out.splitlines()[0] if out else "no output")
        for h in hidden_comps:
            out = tx.shell(self.serial, f"pm enable {h}")
            emit("Re-enable original home screen", h, "enabled" in out, out.splitlines()[0] if out else "no output")
        ss = a.get("screensaver")
        if ss:
            for k, key in (("components", "screensaver_components"), ("enabled", "screensaver_enabled"),
                           ("sleep", "screensaver_activate_on_sleep"), ("dock", "screensaver_activate_on_dock")):
                v = ss.get(k)
                if k not in ss:
                    continue
                cmd = f"settings delete secure {key}" if v in (None, "", "null") else f"settings put secure {key} {v}"
                out = tx.shell(self.serial, cmd)
                emit("Restore screensaver setting", key, "error" not in out.lower() and "exception" not in out.lower(),
                     "back to what it was before")
        if a.get("home_set"):
            frm, to = a["home_set"]["from"], a["home_set"]["to"]
            if frm and not frm.startswith("android/"):
                ok, detail = self._set_home(frm)
                emit("Restore default home", frm, ok, detail)
            else:
                emit("Restore default home", to, FAIL, "no previous default recorded; press Home on the remote and choose the stock launcher")
        for p in disabled_pkgs:
            out = tx.shell(self.serial, f"pm enable {p}")
            emit("Re-enable app", p, "enabled" in out, out.splitlines()[0] if out else "no output")
        sess["reverted"] = True
        sess["status"] = "reverted"
        self._save(d, sess)
        return sess

    # Re-enables every valid package currently disabled on the connected TV.
    def enable_all_disabled(self, emit):
        _, dis = tx.pkg_sets(self.serial)
        for p in sorted(dis):
            if not tx.valid_pkg(p):
                continue
            out = tx.shell(self.serial, f"pm enable {p}")
            emit("Re-enable app", p, "enabled" in out, out.splitlines()[0] if out else "no output")
        if not dis:
            emit("Re-enable all", "-", INFO, "nothing was disabled")


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
HOW_TO = (
    "Android TV / Google TV (TCL, Sony, Philips, Xiaomi, Hisense, Shield...)\n"
    "  1. Settings > Device Preferences > About\n"
    "  2. Press OK on 'Build' 7 times\n"
    "  3. Back > Developer options > turn on USB debugging (and Network / Wireless debugging)\n\n"
    "Amazon Fire TV / Firestick\n"
    "  1. Settings > My Fire TV > About\n"
    "  2. Select the device name 7 times\n"
    "  3. Back > Developer options > turn on ADB debugging\n\n"
    "Find the IP: Settings > Network & Internet > your network (Fire TV: My Fire TV > About > Network).\n"
    "Keep the TV awake while you work. Not supported: Samsung (Tizen), LG (webOS), Roku, Apple TV.")


class ScrollList(ttk.Frame):
    """A scrollable column of rows (used for the big, readable app list)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, yscrollincrement=24)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.sb.grid(row=0, column=1, sticky="ns")
        self.inner = tk.Frame(self.canvas, bd=0, highlightthickness=0)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))

    def retheme(self, bg):
        self.canvas.configure(bg=bg)
        self.inner.configure(bg=bg)

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


def cut_background(img, limit=115):
    """Make the dark tile behind the logo transparent.
    Starts at the image edges and clears every dark pixel connected to them, so the dark TV screen inside the logo stays."""
    try:
        w, h = img.width(), img.height()

        def is_bg(x, y):
            if img.transparency_get(x, y):
                return True
            px = img.get(x, y)
            if isinstance(px, str):
                px = tuple(int(v) for v in px.split())
            return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2] < limit

        seen = set()
        stack = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
        while stack:
            x, y = stack.pop()
            if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
                continue
            seen.add((x, y))
            if not is_bg(x, y):
                continue
            img.transparency_set(x, y, True)
            stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    except Exception:
        pass
    return img


TIER_PLAIN = {"safe": "Preinstalled extra. Safe to switch off.", "medium": "Extra app. Read before ticking.",
              "aggressive": "Can affect updates. Most people skip."}


def plain_desc(pkg, tier, note=""):
    """Short plain-language line for Simple view (keyword guess, then the risk level)."""
    s = f"{pkg} {note}".lower()
    if "game" in s:
        return "Games app, rarely used"
    if any(w in s for w in ("demo", "factory")):
        return "Factory demo app, safe to hide"
    if any(w in s for w in ("logkit", "logging", "analytics", "feedback")):
        return "Logging or feedback tool"
    if any(w in s for w in ("video", "stream", "movie", "qqlive", "bstar", "loklok", "wetv", "iptv")):
        return "Streaming app, came preinstalled"
    return TIER_PLAIN.get(tier, "Extra app")


def friendly_name(pkg):
    """Turn the last part of a package name into a readable application name."""
    return pkg.split(".")[-1].replace("_", " ").replace("-", " ").strip().title() or pkg


TIER_INFO = {
    "safe": ("Safe", "Preloaded games and promo apps. Recommended for everyone."),
    "medium": ("Medium", "Adds a few extras. Read each line before ticking it."),
    "aggressive": ("Aggressive", "Mostly for Fire TV. Can stop updates, so most people should skip it."),
}
SECTIONS = [("overview", "Overview"), ("clean", "Clean apps"), ("launcher", "Taxis Home"), ("undo", "Undo"), ("results", "Results")]


class App:
    # Builds the responsive Taxis desktop interface and restores saved preferences.
    def __init__(self, root):
        self.root = root
        self.eng = Engine()
        self.q = queue.Queue()
        self.busy = False
        self.sel = {}            # package -> BooleanVar (kept when you change tier or search)
        self.plan = []           # [(pkg, tier, note)] currently active on the TV
        self.pre_tick = False
        self.counts = [0, 0]
        self.catalog = load_catalog()
        self.prefs = load_prefs()
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.tname = self.prefs.get("theme") if self.prefs.get("theme") in THEMES else "Dark"
        self.sname = self.prefs.get("text_size") if self.prefs.get("text_size") in TEXT_SIZES else "Normal"
        self.t = THEMES[self.tname]
        self.fonts = {k: tkfont.Font(root=root) for k in ("title", "h2", "big", "bold", "small", "mono")}
        self.avail = set(tkfont.families(root))
        self.fname = self.prefs.get("font") or AUTO_FONT
        self.font_choices = [AUTO_FONT] + [f for f in FONT_CHOICES if f in self.avail] + [MORE_FONTS]
        self._conn_kind = "bad"
        self._sum_kind = None

        root.title("Taxis — your TV, simplified")
        root.geometry("1080x740")
        root.minsize(720, 520)
        self.brand_icon = None
        self.header_icon = None
        try:
            self.brand_icon = tk.PhotoImage(file=str(GUI_ICON))
            self.header_icon = cut_background(self.brand_icon.subsample(12, 12))
            root.iconphoto(True, self.brand_icon)
        except tk.TclError:
            pass
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self._build_topbar()
        self.container = ttk.Frame(root)
        self.container.grid(row=1, column=0, sticky="nsew")
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)
        self.pages = {}
        for name in ("connect", "work"):
            f = ttk.Frame(self.container)
            f.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = f
        self._build_connect(self.pages["connect"])
        self._build_work(self.pages["work"])

        self.apply_look()
        self._enable(False)
        self._src_changed()
        self.page("connect")
        self.ip.set(self.prefs.get("last_ip", ""))
        self.ip_box.configure(values=self.prefs.get("recent_ips", []))
        if not shutil.which("adb"):
            self.adb_lbl.configure(text="ADB was not found on this computer. Install it first:\n"
                                        "Windows: winget install Google.PlatformTools     macOS: brew install android-platform-tools     Ubuntu: sudo apt install adb")
            self.adb_lbl.grid()
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(ev, self._wheel)
        self._compact = None
        root.bind("<Configure>", self._on_resize)
        self.root.after(100, self._pump)

    # ------------------------------------------------------------ look & feel
    def family(self):
        """The font family to use: the saved choice, else the best nice font installed, else Tk's default."""
        if self.fname != AUTO_FONT and self.fname in self.avail:
            return self.fname
        for f in FONT_CHOICES:
            if f in self.avail:
                return f
        return tkfont.nametofont("TkDefaultFont").actual("family")

    # Applies the selected theme, font and text size to every desktop control.
    def apply_look(self):
        t, s, r = self.t, self.style, self.root
        size = TEXT_SIZES[self.sname]
        fam = self.family()
        for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            tkfont.nametofont(n).configure(family=fam, size=size)
        for f in self.fonts.values():
            f.configure(family=fam)
        self.fonts["title"].configure(size=size + 16, weight="bold")
        self.fonts["h2"].configure(size=size + 4, weight="bold")
        self.fonts["big"].configure(size=size + 1, weight="bold")
        self.fonts["bold"].configure(size=size, weight="bold")
        self.fonts["small"].configure(size=max(8, size - 1), weight="normal")
        self.fonts["mono"].configure(family=tkfont.nametofont("TkFixedFont").actual("family"), size=max(8, size - 1), weight="normal")
        r.configure(bg=t["bg"])
        r.option_add("*TCombobox*Listbox.background", t["field"])
        r.option_add("*TCombobox*Listbox.foreground", t["fg"])
        r.option_add("*TCombobox*Listbox.selectBackground", t["accent"])
        r.option_add("*TCombobox*Listbox.selectForeground", t["accent_fg"])
        s.configure(".", background=t["bg"], foreground=t["fg"], fieldbackground=t["field"], bordercolor=t["border"],
                    lightcolor=t["border"], darkcolor=t["border"], troughcolor=t["panel"], focuscolor=t["accent"],
                    insertcolor=t["fg"], selectbackground=t["accent"], selectforeground=t["accent_fg"])
        for st, bgc in (("TFrame", t["bg"]), ("Flat.TFrame", t["panel"]), ("Side.TFrame", t["panel"]),
                        ("Row.TFrame", t["field"]), ("RowOn.TFrame", t["sel"])):
            s.configure(st, background=bgc)
        s.configure("Card.TFrame", background=t["panel"], bordercolor=t["border"], relief="solid", borderwidth=1)
        pad = int(size * 1.0)
        for name, bgc, fgc in (("TLabel", t["bg"], t["fg"]), ("Card.TLabel", t["panel"], t["fg"]),
                               ("Muted.TLabel", t["bg"], t["muted"]), ("CardMuted.TLabel", t["panel"], t["muted"]),
                               ("Side.TLabel", t["panel"], t["fg"]), ("SideMuted.TLabel", t["panel"], t["muted"]),
                               ("Row.TLabel", t["field"], t["fg"]), ("RowOn.TLabel", t["sel"], t["fg"]),
                               ("RowSub.TLabel", t["field"], t["muted"]), ("RowOnSub.TLabel", t["sel"], t["muted"])):
            s.configure(name, background=bgc, foreground=fgc)
        s.configure("Title.TLabel", font=self.fonts["title"], foreground=t["fg"])
        s.configure("Brand.TLabel", background=t["panel"], foreground=t["fg"], font=self.fonts["h2"])
        s.configure("H2.TLabel", font=self.fonts["h2"])
        s.configure("CardH2.TLabel", background=t["panel"], font=self.fonts["h2"])
        s.configure("Ok.TLabel", foreground=t["ok"])
        s.configure("Bad.TLabel", foreground=t["bad"])
        s.configure("TLabelframe", background=t["bg"], bordercolor=t["border"])
        s.configure("TLabelframe.Label", background=t["bg"], foreground=t["accent"], font=self.fonts["bold"])
        s.configure("TButton", background=t["field"], foreground=t["fg"], bordercolor=t["border"], relief="flat", padding=(12, 7))
        s.map("TButton", background=[("disabled", t["panel"]), ("active", t["sel"])], foreground=[("disabled", t["muted"])])
        s.configure("Accent.TButton", background=t["accent"], foreground=t["accent_fg"], bordercolor=t["accent"],
                    relief="flat", font=self.fonts["bold"], padding=(14, 8))
        s.map("Accent.TButton", background=[("disabled", t["panel"]), ("active", t["accent"])],
              foreground=[("disabled", t["muted"])])
        s.configure("Big.Accent.TButton", font=self.fonts["big"], padding=(18, 10))
        s.configure("Card.TButton", font=self.fonts["big"], padding=(16, 12), justify="center")
        s.configure("Nav.TButton", background=t["panel"], foreground=t["fg"], bordercolor=t["panel"], focuscolor=t["panel"], anchor="w",
                    relief="flat", font=self.fonts["big"], padding=(16, 10))
        s.map("Nav.TButton", background=[("disabled", t["panel"]), ("active", t["sel"])], foreground=[("disabled", t["muted"])])
        s.configure("NavOn.TButton", background=t["sel"], foreground=t["accent"], bordercolor=t["accent"], focuscolor=t["sel"], anchor="w",
                    relief="flat", font=self.fonts["big"], padding=(16, 10))
        s.map("NavOn.TButton", background=[("active", t["sel"])], foreground=[("active", t["accent"])])
        s.configure("Seg.Toolbutton", background=t["field"], foreground=t["fg"], bordercolor=t["border"],
                    padding=(18, 9), font=self.fonts["bold"], anchor="center")
        s.map("Seg.Toolbutton", background=[("selected", t["accent"]), ("active", t["sel"])],
              foreground=[("selected", t["accent_fg"])])
        s.configure("Link.TButton", background=t["bg"], foreground=t["accent"], bordercolor=t["bg"], focuscolor=t["bg"],
                    relief="flat", padding=(8, 4), font=self.fonts["bold"])
        s.map("Link.TButton", background=[("active", t["sel"]), ("disabled", t["bg"])], foreground=[("disabled", t["muted"])])
        for w, bgc in (("TCheckbutton", t["bg"]), ("TRadiobutton", t["bg"]), ("Card.TRadiobutton", t["panel"]),
                       ("Card.TCheckbutton", t["panel"]), ("Row.TCheckbutton", t["field"]), ("RowOn.TCheckbutton", t["sel"])):
            s.configure(w, background=bgc, foreground=t["fg"], indicatorbackground=t["field"], indicatorforeground=t["fg"],
                        indicatorcolor=t["field"], indicatormargin=(0, 0, 8, 0))
            s.map(w, background=[("active", bgc)], indicatorbackground=[("selected", t["accent"]), ("disabled", t["panel"])],
                  indicatorforeground=[("selected", t["accent_fg"])], indicatorcolor=[("selected", t["accent"])],
                  foreground=[("disabled", t["muted"])])
        s.configure("TEntry", fieldbackground=t["field"], foreground=t["fg"], padding=6)
        s.configure("TCombobox", fieldbackground=t["field"], background=t["field"], foreground=t["fg"],
                    arrowcolor=t["fg"], selectbackground=t["field"], selectforeground=t["fg"], padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", t["field"]), ("disabled", t["panel"])],
              foreground=[("disabled", t["muted"])], selectbackground=[("readonly", t["field"])],
              selectforeground=[("readonly", t["fg"])])
        s.configure("Treeview", background=t["field"], fieldbackground=t["field"], foreground=t["fg"],
                    rowheight=int(size * 3), bordercolor=t["border"])
        s.configure("Treeview.Heading", background=t["panel"], foreground=t["fg"], font=self.fonts["bold"], relief="flat", padding=6)
        s.map("Treeview", background=[("selected", t["sel"])], foreground=[("selected", t["fg"])])
        s.configure("Horizontal.TProgressbar", background=t["accent"], troughcolor=t["panel"])
        s.configure("TScrollbar", background=t["field"], troughcolor=t["panel"], arrowcolor=t["fg"], bordercolor=t["border"], width=16)
        s.map("TScrollbar", background=[("active", t["sel"])])
        # plain tk widgets
        self.alist.retheme(t["bg"])
        self.lscroll.retheme(t["bg"])
        self.connect_scroll.retheme(t["bg"])
        self.log.configure(bg=t["field"], fg=t["fg"], insertbackground=t["fg"], selectbackground=t["sel"])
        for tag, col in (("ok", t["ok"]), ("fail", t["bad"]), ("info", t["muted"]), ("det", t["muted"]), ("tgt", t["fg"])):
            self.log.tag_configure(tag, foreground=col)
        self.log.tag_configure("b", font=self.fonts["bold"])
        self.sess.tag_configure("x", foreground=t["fg"])
        self._recolor_status()
        self._style_nav()
        self._draw_preview()
        for pkg in self.rows:
            self._restyle_row(pkg)

    def _recolor_status(self):
        pal = {"ok": self.t["ok"], "bad": self.t["bad"]}
        self.conn_lbl.configure(foreground=pal.get(self._conn_kind, self.t["fg"]))
        self.summary.configure(foreground=pal.get(self._sum_kind, self.t["fg"]))

    def on_theme(self, _e=None):
        self.tname, self.t = self.theme_var.get(), THEMES[self.theme_var.get()]
        self.prefs["theme"] = self.tname
        save_prefs(self.prefs)
        self.apply_look()

    def on_size(self, _e=None):
        self.sname = self.size_var.get()
        self.prefs["text_size"] = self.sname
        save_prefs(self.prefs)
        self.apply_look()

    def on_font(self, _e=None):
        choice = self.font_var.get()
        if choice == MORE_FONTS:
            self.font_var.set(self.fname if self.fname in self.font_choices else AUTO_FONT)
            return self.open_font_picker()
        self.set_font(choice)

    def set_font(self, name):
        self.fname = name
        self.prefs["font"] = name
        save_prefs(self.prefs)
        if name not in self.font_choices:
            self.font_choices.insert(len(self.font_choices) - 1, name)
            self.font_box.configure(values=self.font_choices)
        self.font_var.set(name)
        self.apply_look()

    def open_font_picker(self):
        win = tk.Toplevel(self.root)
        win.title("Choose a font")
        win.geometry("520x560")
        win.configure(bg=self.t["bg"])
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        ttk.Label(win, text="Type to search, click a font to preview it.", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        q = tk.StringVar()
        ent = ttk.Entry(win, textvariable=q)
        ent.grid(row=1, column=0, sticky="ew", padx=12)
        fams = sorted({f for f in self.avail if not f.startswith("@")}, key=str.lower)
        lb = tk.Listbox(win, activestyle="none", bg=self.t["field"], fg=self.t["fg"], selectbackground=self.t["accent"],
                        selectforeground=self.t["accent_fg"], highlightthickness=0, borderwidth=0, exportselection=False)
        lb.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        sb = ttk.Scrollbar(win, command=lb.yview)
        sb.grid(row=2, column=1, sticky="ns", pady=8, padx=(0, 8))
        lb.configure(yscrollcommand=sb.set)
        prev = tk.Label(win, text="The quick brown fox jumps over the lazy dog 0123456789", bg=self.t["panel"], fg=self.t["fg"],
                        wraplength=470, justify="left", padx=10, pady=10)
        prev.grid(row=3, column=0, sticky="ew", padx=12)
        shown = []

        def fill(*_):
            shown[:] = [f for f in fams if q.get().lower() in f.lower()]
            lb.delete(0, "end")
            lb.insert("end", *shown)

        def pick(_e=None):
            sel = lb.curselection()
            if sel:
                prev.configure(font=(shown[sel[0]], TEXT_SIZES[self.sname] + 4))

        def apply():
            sel = lb.curselection()
            if sel:
                self.set_font(shown[sel[0]])
            win.destroy()
        q.trace_add("write", fill)
        lb.bind("<<ListboxSelect>>", pick)
        lb.bind("<Double-Button-1>", lambda e: apply())
        row = ttk.Frame(win)
        row.grid(row=4, column=0, sticky="e", padx=12, pady=12)
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        ttk.Button(row, text="Use this font", style="Accent.TButton", command=apply).pack(side="left")
        fill()
        ent.focus_set()

    def page(self, name):
        self.pages[name].tkraise()

    def _wheel(self, e):
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        while w is not None:
            if isinstance(w, ScrollList):
                d = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
                w.canvas.yview_scroll(d * 2, "units")
                return
            w = getattr(w, "master", None)

    # Hides optional toolbar and device details when the window becomes narrow.
    def _on_resize(self, event):
        """Hide optional appearance controls when the window is narrow so core actions remain usable."""
        if event.widget is not self.root:
            return
        px = max(26, (event.width - 1180) // 2)
        if px != getattr(self, "_px", None):
            self._px = px
            self.connect_wrap.configure(padding=(px + 2, 12))
            self.content.configure(padding=(px, 20, px, 18))
        compact = event.width < 980
        if compact == self._compact:
            return
        self._compact = compact
        for widget in self.appearance_widgets:
            (widget.grid_remove if compact else widget.grid)()
        (self.side_info.grid_remove if compact else self.side_info.grid)()

    # ------------------------------------------------------------ top bar
    # Builds the compact brand, rescue and optional appearance toolbar.
    def _build_topbar(self):
        bar = ttk.Frame(self.root, style="Side.TFrame", padding=(18, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        brand_options = {"image": self.header_icon, "compound": "left"} if self.header_icon else {}
        ttk.Label(bar, text="Taxis", style="Brand.TLabel", **brand_options).grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Rescue TV", command=self.on_rescue).grid(row=0, column=1, sticky="w", padx=22)
        self.appearance_widgets = []
        for col, (label, var, vals, w, handler) in enumerate((
                ("Theme", "theme_var", list(THEMES), 13, self.on_theme),
                ("Text size", "size_var", list(TEXT_SIZES), 11, self.on_size),
                ("Font", "font_var", self.font_choices, 18, self.on_font))):
            lab = ttk.Label(bar, text=label, style="SideMuted.TLabel")
            lab.grid(row=0, column=2 + col * 2, padx=(16, 5))
            v = tk.StringVar(value={"theme_var": self.tname, "size_var": self.sname,
                                    "font_var": self.fname if self.fname in self.font_choices else AUTO_FONT}[var])
            setattr(self, var, v)
            c = ttk.Combobox(bar, textvariable=v, values=vals, width=w, state="readonly")
            c.grid(row=0, column=3 + col * 2)
            c.bind("<<ComboboxSelected>>", handler)
            self.appearance_widgets.extend((lab, c))
            if var == "font_var":
                self.font_box = c

    # ------------------------------------------------------------ connect page
    def _card(self, parent, row, title, sub=None):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=row, column=0, sticky="ew", pady=7)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="CardH2.TLabel").grid(row=0, column=0, sticky="w")
        if sub:
            ttk.Label(card, text=sub, style="CardMuted.TLabel", wraplength=800, justify="left").grid(row=1, column=0, sticky="w", pady=(3, 10))
        return card

    # Builds a scrollable, beginner-friendly connection page for small windows.
    def _build_connect(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.connect_scroll = ScrollList(page)
        self.connect_scroll.grid(row=0, column=0, sticky="nsew")
        self.connect_scroll.inner.columnconfigure(0, weight=1)
        wrap = ttk.Frame(self.connect_scroll.inner, padding=(28, 12))
        self.connect_wrap = wrap
        wrap.grid(row=0, column=0, sticky="ew")
        wrap.columnconfigure(0, weight=1)
        ttk.Label(wrap, text="Welcome to Taxis", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(wrap, text="A simpler home screen and safer controls for your TV.\n"
                             "System apps are never deleted, and Undo keeps Taxis Launcher installed.", style="Muted.TLabel", justify="left").grid(row=1, column=0, sticky="w", pady=(2, 8))
        self.adb_lbl = ttk.Label(wrap, text="", style="Bad.TLabel", justify="left", wraplength=820)
        self.adb_lbl.grid(row=2, column=0, sticky="w")
        self.adb_lbl.grid_remove()

        c1 = self._card(wrap, 3, "1   Prepare your TV", "Turn on debugging on the TV once (about a minute). Keep the TV awake and on the same Wi-Fi as this computer.")
        ttk.Button(c1, text="Show me how", command=lambda: messagebox.showinfo("Turn on debugging", HOW_TO)).grid(row=2, column=0, sticky="w")

        c2 = self._card(wrap, 4, "2   Connect")
        f = ttk.Frame(c2, style="Flat.TFrame")
        f.grid(row=2, column=0, sticky="w")
        ttk.Label(f, text="TV IP address", style="Card.TLabel").grid(row=0, column=0)
        self.ip = tk.StringVar()
        self.ip_box = ttk.Combobox(f, textvariable=self.ip, width=18)
        self.ip_box.grid(row=0, column=1, padx=8)
        self.ip_box.bind("<Return>", lambda e: self.on_connect())
        ttk.Label(f, text="Port", style="Card.TLabel").grid(row=0, column=2)
        self.port = tk.StringVar(value="5555")
        pe = ttk.Entry(f, textvariable=self.port, width=7)
        pe.grid(row=0, column=3, padx=8)
        pe.bind("<Return>", lambda e: self.on_connect())
        self.btn_connect = ttk.Button(f, text="Connect", style="Accent.TButton", command=self.on_connect)
        self.btn_connect.grid(row=0, column=4, padx=8)
        self.btn_scan = ttk.Button(f, text="Find TVs on my network", command=self.on_scan)
        self.btn_scan.grid(row=1, column=0, columnspan=5, sticky="w", pady=(10, 0))
        self.conn_lbl = ttk.Label(c2, text="Not connected yet.", style="Card.TLabel", font=self.fonts["bold"])
        self.conn_lbl.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.tv_lbl = ttk.Label(c2, text="", style="CardMuted.TLabel", wraplength=800, justify="left")
        self.tv_lbl.grid(row=4, column=0, sticky="w")

        c3 = self._card(wrap, 5, "3   What would you like to do?", "These unlock after you connect. Nothing changes until you confirm.")
        g = ttk.Frame(c3, style="Flat.TFrame")
        g.grid(row=2, column=0, sticky="ew")
        for i in range(3):
            g.columnconfigure(i, weight=1, uniform="cards")
        self.card_quick = ttk.Button(g, text="Quick clean", style="Card.TButton", command=self.go_quick)
        self.card_launch = ttk.Button(g, text="Taxis Home", style="Card.TButton", command=lambda: self.open_work("launcher"))
        self.card_undo = ttk.Button(g, text="Undo changes", style="Card.TButton", command=lambda: self.open_work("undo"))
        for i, b in enumerate((self.card_quick, self.card_launch, self.card_undo)):
            b.grid(row=0, column=i, sticky="nsew", padx=6)
        c4 = self._card(wrap, 6, "TV not starting after a change?",
                        "If the TV is stuck on its loading screen, type its IP above and press Rescue. Taxis keeps trying to reach it, "
                        "turns back on everything it ever turned off, and restarts the TV.")
        self.btn_rescue = ttk.Button(c4, text="Rescue my TV", command=self.on_rescue)
        self.btn_rescue.grid(row=2, column=0, sticky="w")
        ttk.Label(wrap, text="Works on Android TV, Google TV and Fire TV. Samsung (Tizen), LG (webOS), Roku and Apple TV are not supported.",
                  style="Muted.TLabel", wraplength=820, justify="left").grid(row=7, column=0, sticky="w", pady=(8, 0))
        tip = ttk.Frame(wrap)
        tip.grid(row=8, column=0, sticky="w", pady=(14, 0))
        ttk.Label(tip, text="Taxis is free. If it helped, you can support it.", style="Muted.TLabel").grid(row=0, column=0)
        ttk.Button(tip, text="Buy me a coffee", style="Link.TButton", command=self.on_coffee).grid(row=0, column=1, padx=(6, 0))

    def on_rescue(self):
        ip = self.ip.get().strip()
        if not ip or not re.match(r"^[A-Za-z0-9.-]+$", ip):
            return messagebox.showinfo("IP needed", "Type your TV's IP address in the box above first (check your router if it changed).")
        if not messagebox.askyesno("Rescue my TV",
                                   "Taxis will keep trying to reach the TV for up to a few minutes, turn back on the apps it turned off "
                                   "(including Google TV's launcher), and restart the TV.\n\nContinue?"):
            return
        port = self.port.get().strip() or "5555"
        self.page("work")
        self.run_bg("Rescuing the TV...", lambda emit: self.eng.emergency_restore(ip, port, emit))

    # ------------------------------------------------------------ work page (connection strip + sections)
    # Builds responsive top navigation and the four main work sections.
    def _build_work(self, page):
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        side = ttk.Frame(page, style="Side.TFrame", padding=(0, 18, 0, 16), width=216)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(20, weight=1)
        self.navbtns, self.navind = {}, {}
        for i, (key, label) in enumerate(SECTIONS):
            row = ttk.Frame(side, style="Side.TFrame")
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.columnconfigure(1, weight=1)
            ind = tk.Frame(row, width=3, bd=0, highlightthickness=0)
            ind.grid(row=0, column=0, sticky="ns")
            b = ttk.Button(row, text=label, style="Nav.TButton", command=lambda k=key: self.go(k))
            b.grid(row=0, column=1, sticky="ew")
            self.navbtns[key] = b
            self.navind[key] = ind
        st = ttk.Frame(side, style="Side.TFrame", padding=(16, 0))
        st.grid(row=21, column=0, sticky="sew")
        st.columnconfigure(0, weight=1)
        self.side_name = ttk.Label(st, text="", style="Side.TLabel", font=self.fonts["bold"], justify="left", wraplength=180)
        self.side_name.grid(row=0, column=0, sticky="w")
        self.side_info = ttk.Label(st, text="", style="SideMuted.TLabel", justify="left", wraplength=180)
        self.side_info.grid(row=1, column=0, sticky="w", pady=(2, 8))
        ttk.Button(st, text="Connection", command=lambda: self.page("connect")).grid(row=2, column=0, sticky="ew")
        self.btn_disconnect = ttk.Button(st, text="Disconnect", command=self.on_disconnect)
        self.btn_disconnect.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(st, text="Buy me a coffee", style="Link.TButton", command=self.on_coffee).grid(row=4, column=0, sticky="w", pady=(14, 0))

        self.content = ttk.Frame(page, padding=(26, 18, 26, 18))
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)
        self.mode = tk.StringVar(value=self.prefs.get("mode", "simple"))
        mb = ttk.Frame(self.content)
        mb.grid(row=0, column=0, sticky="e", pady=(0, 6))
        ttk.Label(mb, text="View", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 8))
        for i, (label, val) in enumerate((("Simple", "simple"), ("Pro", "pro"))):
            ttk.Radiobutton(mb, text=label, value=val, variable=self.mode, style="Seg.Toolbutton",
                            command=self._mode_changed).grid(row=0, column=i + 1)
        self.secs = {}
        for key, _ in SECTIONS:
            f = ttk.Frame(self.content)
            f.grid(row=1, column=0, sticky="nsew")
            f.columnconfigure(0, weight=1)
            self.secs[key] = f
        self._build_overview(self.secs["overview"])
        self._build_clean(self.secs["clean"])
        self._build_launcher(self.secs["launcher"])
        self._build_undo(self.secs["undo"])
        self._build_results(self.secs["results"])
        self.current = "overview"
        self._apply_mode()

    def on_coffee(self):
        """Open the fixed Taxis support page or show its URL when no browser opens."""
        try:
            if not webbrowser.open(COFFEE_URL):
                raise OSError("no browser")
        except Exception:
            messagebox.showinfo("Buy me a coffee", f"Open this link in your browser:\n{COFFEE_URL}")

    def _head(self, parent, title, sub):
        ttk.Label(parent, text=title, style="H2.TLabel", font=self.fonts["title"]).grid(row=0, column=0, sticky="w")
        ttk.Label(parent, text=sub, style="Muted.TLabel", wraplength=820, justify="left").grid(row=1, column=0, sticky="w", pady=(2, 12))

    def _style_nav(self):
        for k, b in self.navbtns.items():
            b.configure(style="NavOn.TButton" if k == self.current else "Nav.TButton")
            self.navind[k].configure(bg=self.t["accent"] if k == self.current else self.t["panel"])

    def go(self, key):
        self.current = key
        self.secs[key].tkraise()
        self._style_nav()
        if key in ("clean", "overview"):
            self.load_apps()
        elif key == "undo":
            self.refresh_sessions()
        elif key == "launcher":
            self.refresh_home()
            self._draw_preview()

    def open_work(self, key):
        self.page("work")
        self.go(key)

    def go_quick(self):
        self.tier.set("safe")
        self.pre_tick = True
        self.open_work("clean")

    # ---- Overview section
    def _build_overview(self, p):
        self._head(p, "Overview", "Your TV at a glance. Nothing changes until you confirm.")
        hero = ttk.Frame(p)
        hero.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(hero, text="Ready to tidy your TV", font=self.fonts["h2"]).grid(row=0, column=0, sticky="w")
        self.ov_sub = ttk.Label(hero, text="Connect a TV first.", style="Muted.TLabel", wraplength=700, justify="left")
        self.ov_sub.grid(row=1, column=0, sticky="w", pady=(4, 14))
        btns = ttk.Frame(hero)
        btns.grid(row=2, column=0, sticky="w")
        self.btn_quick = ttk.Button(btns, text="Clean my TV", style="Big.Accent.TButton", command=self.go_quick)
        self.btn_quick.grid(row=0, column=0)
        ttk.Button(btns, text="Choose apps myself", style="Link.TButton", command=lambda: self.go("clean")).grid(row=0, column=1, padx=(14, 0))
        ttk.Separator(p, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=(20, 0))
        self._ov_row(p, 4, "Taxis Home", "A calm home screen with your apps, clock and weather.", "Change", "launcher")
        self._ov_row(p, 5, "Undo", "Turn switched-off apps and home changes back on.", "Open", "undo")
        self._ov_row(p, 6, "Results", "See what Taxis did, step by step.", "Open", "results")
        p.rowconfigure(7, weight=1)

    def _ov_row(self, parent, row, title, sub, action, target):
        f = ttk.Frame(parent)
        f.grid(row=row, column=0, sticky="ew")
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text=title, font=self.fonts["bold"]).grid(row=0, column=0, sticky="w", pady=(14, 0))
        ttk.Label(f, text=sub, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 14))
        ttk.Button(f, text=action, style="Link.TButton", command=lambda: self.go(target)).grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Separator(f, orient="horizontal").grid(row=2, column=0, columnspan=2, sticky="ew")

    def _update_overview(self):
        if not hasattr(self, "ov_sub"):
            return
        if not self.eng.serial:
            text = "Connect a TV first."
        elif getattr(self, "empty_msg", None):
            text = "No ready-made app list exists for this TV model yet. Open Clean apps to pick one."
        elif self.tier.get() == "safe" and self.plan:
            n = len(self.plan)
            text = f"{n} preinstalled app{'s' if n != 1 else ''} can be switched off safely. Nothing is deleted, and you can undo it."
        elif self.tier.get() == "safe":
            text = "Nothing to clean here. Your TV is already tidy."
        else:
            text = "Preinstalled extras can be switched off safely. Nothing is deleted, and you can undo it."
        self.ov_sub.configure(text=text)

    # ---- Simple / Pro view
    def _mode_changed(self):
        self.prefs["mode"] = self.mode.get()
        save_prefs(self.prefs)
        if self.mode.get() == "simple" and self.tier.get() != "safe":
            self.tier.set("safe")
            self._tier_changed()
        self._apply_mode()

    def _apply_mode(self):
        pro = self.mode.get() == "pro"
        for w in (self.tier_bar, self.tier_desc, self.btn_preview,
                  self.card_sys, self.card_choice, self.bg_opts, self.card_also):
            (w.grid if pro else w.grid_remove)()
        (self.home_hint.grid_remove if pro else self.home_hint.grid)()
        if not pro and BUNDLED_APK.is_file():
            self.lsrc.set("bundled")
            self._src_changed()
        if self.plan:
            self._render_apps()

    def on_preview(self):
        chosen = self.selected()
        if not chosen:
            return messagebox.showinfo("Nothing selected", "Tick at least one app first.")
        ser = self.eng.serial or "<tv>"
        lines = [f"adb -s {ser} shell pm disable-user --user 0 {pkg}" for pkg in chosen]
        win = tk.Toplevel(self.root)
        win.title("Preview commands")
        win.configure(bg=self.t["bg"])
        win.geometry("780x380")
        ttk.Label(win, text="Equivalent commands, one per app. Nothing is uninstalled; Undo turns the apps back on.",
                  style="Muted.TLabel", wraplength=740, justify="left").pack(anchor="w", padx=16, pady=(14, 8))
        txt = tk.Text(win, height=12, wrap="none", bg=self.t["field"], fg=self.t["fg"], insertbackground=self.t["fg"],
                      relief="flat", font=self.fonts["mono"], padx=10, pady=8)
        txt.pack(fill="both", expand=True, padx=16)
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=16, pady=12)
        ttk.Button(bar, text="Copy", command=lambda: (self.root.clipboard_clear(), self.root.clipboard_append("\n".join(lines)))).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")

    # ---- TV preview (Taxis Home)
    def _rr(self, c, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return c.create_polygon(pts, smooth=True, **kw)

    def _draw_preview(self):
        c = getattr(self, "preview", None)
        if c is None:
            return
        t = self.t
        W, H = int(c.cget("width")), int(c.cget("height"))
        c.delete("all")
        c.configure(bg=t["panel"])
        self._rr(c, 4, 4, W - 4, H - 26, 16, fill="#101216", outline=t["border"])
        self._rr(c, 12, 12, W - 12, H - 34, 10, fill="#1b1e25", outline="")
        city = (self.city.get().strip() if hasattr(self, "city") else self.prefs.get("city", "")) or "Your city"
        c.create_text(32, 58, text=time.strftime("%H:%M"), anchor="w", fill="#f4f1ea", font=self.fonts["title"])
        c.create_text(32, 90, text=city, anchor="w", fill="#a6abb4", font=self.fonts["small"])
        for i in range(5):
            x = 32 + i * 58
            self._rr(c, x, 128, x + 48, 164, 8, fill=t["accent"] if i == 0 else "#2e333d", outline="")
        c.create_rectangle(W // 2 - 40, H - 22, W // 2 + 40, H - 14, fill=t["border"], outline="")

    # ---- Clean section
    def _build_clean(self, p):
        p.rowconfigure(4, weight=1)
        self._head(p, "Choose apps to switch off",
                   "Switched-off apps are stopped and hidden, never deleted. You can turn any of them back on in 'Undo'.")
        bar = ttk.Frame(p)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(10, weight=1)
        self.tier_bar = bar
        self.tier = tk.StringVar(value="safe")
        for i, key in enumerate(tx.TIERS):
            ttk.Radiobutton(bar, text=TIER_INFO[key][0], value=key, variable=self.tier, style="Seg.Toolbutton",
                            command=self._tier_changed).grid(row=0, column=i, padx=(0, 6))
        ttk.Label(bar, text="App list for", style="Muted.TLabel").grid(row=0, column=11, padx=(10, 5))
        self.pset = tk.StringVar()
        s = ttk.Combobox(bar, textvariable=self.pset, values=tx.sets(), width=11, state="readonly")
        s.grid(row=0, column=12)
        s.bind("<<ComboboxSelected>>", self._pset_changed)
        self.tier_desc = ttk.Label(p, text=TIER_INFO["safe"][1], style="Muted.TLabel")
        self.tier_desc.grid(row=3, column=0, sticky="w", pady=(8, 8))

        box = ttk.Frame(p)
        box.grid(row=4, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        tools = ttk.Frame(box)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tools.columnconfigure(1, weight=1)
        ttk.Label(tools, text="Search").grid(row=0, column=0, padx=(0, 8))
        self.search = tk.StringVar()
        e = ttk.Entry(tools, textvariable=self.search)
        e.grid(row=0, column=1, sticky="ew")
        self.search.trace_add("write", lambda *_: self._render_apps())
        ttk.Button(tools, text="Select all", command=lambda: self._tick_all(True)).grid(row=0, column=2, padx=(10, 4))
        ttk.Button(tools, text="Select none", command=lambda: self._tick_all(False)).grid(row=0, column=3)
        self.alist = ScrollList(box)
        self.alist.grid(row=1, column=0, sticky="nsew")
        self.rows = {}
        self.empty_lbl = None

        foot = ttk.Frame(p)
        foot.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        foot.columnconfigure(0, weight=1)
        self.cnt = ttk.Label(foot, text="", font=self.fonts["bold"])
        self.cnt.grid(row=0, column=0, sticky="w")
        self.btn_switch = ttk.Button(foot, text="Switch off apps", style="Big.Accent.TButton", command=self.on_switch_off)
        self.btn_switch.grid(row=0, column=2)
        self.btn_preview = ttk.Button(foot, text="Preview commands", command=self.on_preview)
        self.btn_preview.grid(row=0, column=1, padx=(0, 10))

    def _tier_changed(self):
        self.tier_desc.configure(text=TIER_INFO[self.tier.get()][1])
        self.load_apps()

    def _pset_changed(self, _e=None):
        self.eng.use_set(self.pset.get())
        self.load_apps()

    def load_apps(self):
        if not self.eng.serial:
            return self._set_plan([])
        if not self.eng.set:
            return self._set_plan([], "No ready-made app list exists for this TV model yet.\nPick one from 'App list for' above, or use the Launcher section.")
        self.cnt.configure(text="Reading apps from the TV...")
        tier = self.tier.get()

        def work():
            try:
                self.q.put(("apps", self.eng.plan(tier), tier))
            except Exception as e:
                self.q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _set_plan(self, items, empty_msg=None):
        self.plan = list(items)
        for pkg, _t, _n in self.plan:
            if pkg not in self.sel:
                self.sel[pkg] = tk.BooleanVar(value=self.pre_tick)
            elif self.pre_tick:
                self.sel[pkg].set(True)
        self.pre_tick = False
        self.empty_msg = empty_msg
        self._render_apps()
        self._update_overview()

    def _render_apps(self):
        self.alist.clear()
        self.rows = {}
        q = self.search.get().strip().lower()
        shown = [a for a in self.plan if not q or q in a[0].lower() or q in a[2].lower()]
        if not shown:
            msg = getattr(self, "empty_msg", None) or ("No apps match your search." if self.plan else
                                                        "Nothing to switch off here. Everything in this tier is already off.")
            tk.Label(self.alist.inner, text=msg, bg=self.t["bg"], fg=self.t["muted"], font=self.fonts["bold"],
                     justify="left", pady=30).pack(anchor="w")
        for pkg, tier, note in shown:
            self._make_row(pkg, tier, note)
        self._count()

    def _make_row(self, pkg, tier, note):
        var = self.sel[pkg]
        pro = self.mode.get() == "pro"
        row = ttk.Frame(self.alist.inner, padding=(16, 12))
        row.pack(fill="x", pady=3, padx=(0, 8))
        row.columnconfigure(1, weight=1)
        cb = ttk.Checkbutton(row, variable=var, command=lambda p=pkg: self._row_changed(p))
        cb.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        name = ttk.Label(row, text=note or (pkg if pro else friendly_name(pkg)), font=self.fonts["big"])
        name.grid(row=0, column=1, sticky="w")
        sub = ttk.Label(row, text=pkg if pro else plain_desc(pkg, tier, note),
                        font=self.fonts["mono"] if pro else self.fonts["small"])
        sub.grid(row=1, column=1, sticky="w")
        badge = ttk.Label(row, text=TIER_INFO.get(tier, (tier,))[0], font=self.fonts["small"])
        badge.grid(row=0, column=2, rowspan=2, padx=(12, 0))
        badge._tier = tier
        if not pro:
            badge.grid_remove()
        for w in (row, name, sub, badge):
            w.bind("<Button-1>", lambda e, p=pkg: self._toggle(p))
        self.rows[pkg] = (row, cb, name, sub, badge)
        self._restyle_row(pkg)

    def _restyle_row(self, pkg):
        if pkg not in self.rows or pkg not in self.sel:
            return
        row, cb, name, sub, badge = self.rows[pkg]
        on = "On" if self.sel[pkg].get() else ""
        row.configure(style=f"Row{on}.TFrame")
        cb.configure(style=f"Row{on}.TCheckbutton")
        name.configure(style=f"Row{on}.TLabel")
        sub.configure(style=f"Row{on}Sub.TLabel")
        badge.configure(style=f"Row{on}Sub.TLabel")
        tcol = {"safe": self.t["ok"], "medium": self.t["accent"], "aggressive": self.t["bad"]}
        badge.configure(foreground=tcol.get(getattr(badge, "_tier", ""), self.t["muted"]))

    def _toggle(self, pkg):
        self.sel[pkg].set(not self.sel[pkg].get())
        self._row_changed(pkg)

    def _row_changed(self, pkg):
        self._restyle_row(pkg)
        self._count()

    def _tick_all(self, on):
        q = self.search.get().strip().lower()
        for pkg, _t, note in self.plan:
            if not q or q in pkg.lower() or q in note.lower():
                self.sel[pkg].set(on)
                self._restyle_row(pkg)
        self._count()

    def selected(self):
        return [p for p, _t, _n in self.plan if self.sel.get(p) and self.sel[p].get()]

    def _count(self):
        n = len(self.selected())
        self.cnt.configure(text=f"{n} of {len(self.plan)} app(s) selected" if self.plan else "")
        self.btn_switch.configure(text=f"Switch off {n} app{'s' if n != 1 else ''}")
        if hasattr(self, "also_clean_chk"):
            self.also_clean_chk.configure(text=f"Also switch off the {n} app(s) selected in 'Clean apps'")

    # ---- Launcher section
    # Builds the Taxis Home controls for redirect, location, background and idle display.
    def _build_launcher(self, p):
        p.rowconfigure(2, weight=1)
        self._head(p, "Taxis Home",
                   "A calm home screen with your apps, local weather, background and idle display. Google TV stays installed so startup remains safe.")
        self.lscroll = ScrollList(p)
        self.lscroll.grid(row=2, column=0, sticky="nsew")
        self.home_hint = ttk.Label(p, text="Simple view shows the essentials. Switch to Pro for system-home checks, launcher choice and background options.",
                                   style="Muted.TLabel", wraplength=800, justify="left")
        self.home_hint.grid(row=3, column=0, sticky="w", pady=(8, 0))
        sc = self.lscroll.inner
        sc.columnconfigure(0, weight=1)
        r = 0
        pv = ttk.Frame(sc, style="Card.TFrame", padding=16)
        pv.grid(row=r, column=0, sticky="ew", pady=5)
        ttk.Label(pv, text="Preview", style="CardH2.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(pv, text="How your TV home screen will look. The clock and city update as you change them below.",
                  style="CardMuted.TLabel", wraplength=700, justify="left").grid(row=1, column=0, sticky="w", pady=(3, 10))
        self.preview = tk.Canvas(pv, width=360, height=210, highlightthickness=0, bd=0)
        self.preview.grid(row=2, column=0, sticky="w")
        r += 1
        cur = ttk.Frame(sc, style="Card.TFrame", padding=(16, 12))
        self.card_sys = cur
        cur.grid(row=r, column=0, sticky="ew", pady=5)
        cur.columnconfigure(0, weight=1)
        self.home_lbl = ttk.Label(cur, text="Safe system Home: checking...", style="Card.TLabel")
        self.home_lbl.grid(row=0, column=0, sticky="w")
        ttk.Button(cur, text="Refresh", command=self.refresh_home).grid(row=0, column=1)
        hb = ttk.Frame(cur, style="Flat.TFrame")
        hb.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.btn_diag = ttk.Button(hb, text="Check Taxis", command=self.on_diagnose)
        self.btn_diag.grid(row=0, column=0)
        self.btn_fix = ttk.Button(hb, text="Use as system Home", command=self.on_make_default)
        self.btn_fix.grid(row=0, column=1, padx=8)
        self.btn_hcheck = ttk.Button(hb, text="Full home check", command=self.on_home_check)
        self.btn_hcheck.grid(row=0, column=2)
        r += 1

        hr = ttk.Frame(sc, style="Card.TFrame", padding=16)
        hr.grid(row=r, column=0, sticky="ew", pady=5)
        ttk.Label(hr, text="Remote Home button", style="CardH2.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(hr, text="Taxis watches only for Google TV's home screen, then returns here. "
                           "Google TV stays enabled for safe startup and may flash briefly. You can turn this off at any time.",
                  style="CardMuted.TLabel", wraplength=760, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))
        self.btn_redirect_on = ttk.Button(hr, text="Home opens Taxis", style="Accent.TButton", command=self.on_redirect_on)
        self.btn_redirect_on.grid(row=2, column=0, sticky="w")
        self.btn_redirect_off = ttk.Button(hr, text="Use Google TV Home", command=self.on_redirect_off)
        self.btn_redirect_off.grid(row=2, column=1, sticky="w", padx=8)
        r += 1

        ch = ttk.Frame(sc, style="Card.TFrame", padding=16)
        ch.grid(row=r, column=0, sticky="ew", pady=5)
        ch.columnconfigure(1, weight=1)
        self.card_choice = ch
        self.lsrc = tk.StringVar(value="bundled" if BUNDLED_APK.is_file() else "installed")
        names = [e["name"] for e in self.catalog]
        ttk.Label(ch, text="Which launcher?", style="CardH2.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.rb_bundled = ttk.Radiobutton(ch, text="Taxis Launcher  (included, recommended)", value="bundled", variable=self.lsrc,
                                          style="Card.TRadiobutton", command=self._src_changed)
        self.rb_bundled.grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(ch, text="Ad-free and works offline. Big clock, place and weather on the left of the landing page, a calm app list behind it.",
                  style="CardMuted.TLabel", wraplength=760, justify="left").grid(row=2, column=0, columnspan=3, sticky="w", padx=(26, 0), pady=(0, 8))
        self.rb_inst = ttk.Radiobutton(ch, text="A launcher already on the TV", value="installed", variable=self.lsrc,
                                       style="Card.TRadiobutton", command=self._src_changed)
        self.rb_inst.grid(row=3, column=0, sticky="w")
        self.home_choice = tk.StringVar()
        self.home_box = ttk.Combobox(ch, textvariable=self.home_choice, state="readonly")
        self.home_box.grid(row=3, column=1, sticky="ew", padx=10)
        self.rb_apk = ttk.Radiobutton(ch, text="My own APK file", value="apk", variable=self.lsrc,
                                      style="Card.TRadiobutton", command=self._src_changed)
        self.rb_apk.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.apk = tk.StringVar()
        self.apk_entry = ttk.Entry(ch, textvariable=self.apk)
        self.apk_entry.grid(row=4, column=1, sticky="ew", padx=10, pady=(8, 0))
        self.apk_btn = ttk.Button(ch, text="Browse...", command=self.on_browse)
        self.apk_btn.grid(row=4, column=2, pady=(8, 0))
        self.rb_builtin = ttk.Radiobutton(ch, text="Download from GitHub", value="builtin", variable=self.lsrc,
                                          style="Card.TRadiobutton", command=self._src_changed)
        self.builtin_choice = tk.StringVar(value=names[0] if names else "")
        self.builtin_box = ttk.Combobox(ch, textvariable=self.builtin_choice, values=names, state="readonly")
        if self.catalog:
            self.rb_builtin.grid(row=5, column=0, sticky="w", pady=(8, 0))
            self.builtin_box.grid(row=5, column=1, sticky="ew", padx=10, pady=(8, 0))
        r += 1

        wf = ttk.Frame(sc, style="Card.TFrame", padding=16)
        wf.grid(row=r, column=0, sticky="ew", pady=5)
        ttk.Label(wf, text="Weather location", style="CardH2.TLabel").grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Label(wf, text="Your city", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.city = tk.StringVar(value=self.prefs.get("city", ""))
        self.city.trace_add("write", lambda *_: self._draw_preview())
        ttk.Entry(wf, textvariable=self.city, width=24).grid(row=1, column=1, padx=8, pady=(8, 0))
        self.units = tk.StringVar(value=self.prefs.get("units", "C"))
        ttk.Combobox(wf, textvariable=self.units, values=["C", "F"], width=3, state="readonly").grid(row=1, column=2, pady=(8, 0))
        self.btn_city = ttk.Button(wf, text="Save location", command=self.on_city)
        self.btn_city.grid(row=1, column=3, padx=8, pady=(8, 0))
        ttk.Label(wf, text="Enter a city, or leave it empty to use the TV's approximate network location (with IP fallback).",
                  style="CardMuted.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))
        r += 1

        bf = ttk.Frame(sc, style="Card.TFrame", padding=16)
        bf.grid(row=r, column=0, sticky="ew", pady=5)
        bf.columnconfigure(1, weight=1)
        ttk.Label(bf, text="Background", style="CardH2.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(bf, text="Picture", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.bg_path = tk.StringVar(value=self.prefs.get("bg_path", ""))
        ttk.Entry(bf, textvariable=self.bg_path).grid(row=1, column=1, sticky="ew", padx=8, pady=(10, 0))
        ttk.Button(bf, text="Choose picture", command=self.on_pick_bg).grid(row=1, column=2, pady=(10, 0))
        opts = ttk.Frame(bf, style="Flat.TFrame")
        self.bg_opts = opts
        opts.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(opts, text="Darkness over the picture", style="Card.TLabel").grid(row=0, column=0)
        self.bg_dim = tk.StringVar(value=self.prefs.get("bg_dim", "Medium"))
        ttk.Combobox(opts, textvariable=self.bg_dim, values=list(DIMS), width=8, state="readonly").grid(row=0, column=1, padx=(8, 20))
        ttk.Label(opts, text="Colour style (no picture)", style="Card.TLabel").grid(row=0, column=2)
        self.bg_preset = tk.StringVar(value=self.prefs.get("bg_preset", "Auto"))
        ttk.Combobox(opts, textvariable=self.bg_preset, values=PRESETS, width=10, state="readonly").grid(row=0, column=3, padx=8)
        btns = ttk.Frame(bf, style="Flat.TFrame")
        btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))
        self.btn_bg = ttk.Button(btns, text="Apply picture", command=self.on_apply_bg)
        self.btn_bg.grid(row=0, column=0)
        self.btn_bgclear = ttk.Button(btns, text="Remove picture", command=self.on_clear_bg)
        self.btn_bgclear.grid(row=0, column=1, padx=8)
        ttk.Label(bf, text="Any photo works (jpg, png, webp). It is cropped to 16:9 and used on Taxis Home, its idle view and Taxis Idle screensaver.",
                  style="CardMuted.TLabel", wraplength=760, justify="left").grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        r += 1

        sf = ttk.Frame(sc, style="Card.TFrame", padding=16)
        sf.grid(row=r, column=0, sticky="ew", pady=5)
        ttk.Label(sf, text="Taxis Idle screensaver", style="CardH2.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(sf, text="Shows the time and weather on the left and the place in the corner, on black, when the TV is idle. "
                           "It does not touch the Home button and can be switched off any time. How soon it starts is set in the TV's own "
                           "Settings (look for Ambient mode or Screen saver; the name varies).",
                  style="CardMuted.TLabel", wraplength=760, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 10))
        sb = ttk.Frame(sf, style="Flat.TFrame")
        sb.grid(row=2, column=0, sticky="w")
        self.btn_ss = ttk.Button(sb, text="Use Taxis Idle", style="Accent.TButton", command=self.on_ss_on)
        self.btn_ss.grid(row=0, column=0)
        self.btn_ss_prev = ttk.Button(sb, text="Preview now", command=self.on_ss_preview)
        self.btn_ss_prev.grid(row=0, column=1, padx=8)
        self.btn_ss_off = ttk.Button(sb, text="Use TV screensaver", command=self.on_ss_off)
        self.btn_ss_off.grid(row=0, column=2)
        r += 1

        op = ttk.Frame(sc)
        self.card_also = op
        op.grid(row=r, column=0, sticky="ew", pady=(8, 0))
        self.also_clean = tk.BooleanVar(value=False)
        self.also_clean_chk = ttk.Checkbutton(op, text="Also switch off the 0 app(s) selected in 'Clean apps'", variable=self.also_clean)
        self.also_clean_chk.grid(row=0, column=0, sticky="w")
        foot = ttk.Frame(p)
        foot.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        foot.columnconfigure(0, weight=1)
        self.btn_install = ttk.Button(foot, text="Install / update", command=self.on_install)
        self.btn_install.grid(row=0, column=1, sticky="e")

    # Enables only the fields required by the selected launcher source.
    def _src_changed(self):
        src = self.lsrc.get()
        self.home_box.configure(state="readonly" if src == "installed" else "disabled")
        on = lambda c: "normal" if c else "disabled"
        self.apk_entry.configure(state=on(src == "apk"))
        self.apk_btn.configure(state=on(src == "apk"))
        self.builtin_box.configure(state="readonly" if src == "builtin" else "disabled")
        if not BUNDLED_APK.is_file():
            self.rb_bundled.configure(state="disabled", text="Taxis Launcher (included APK is missing)")
        self.btn_install.configure(text="Use selected launcher" if src == "installed" else "Install / update")

    # ---- Undo section
    # Builds Undo without any option that can uninstall Taxis Launcher.
    def _build_undo(self, p):
        p.rowconfigure(2, weight=1)
        self._head(p, "Undo", "Pick a session and Taxis restores its changes. Taxis Launcher always stays installed.")
        cols = ("time", "mode", "apps", "home", "status")
        self.sess = ttk.Treeview(p, columns=cols, show="headings", selectmode="browse")
        for c, w, t in (("time", 160, "When"), ("mode", 150, "What"), ("apps", 90, "Apps off"), ("home", 330, "Home change"), ("status", 100, "Status")):
            self.sess.heading(c, text=t)
            self.sess.column(c, width=w, anchor="w")
        self.sess.grid(row=2, column=0, sticky="nsew")
        self.sess.bind("<<TreeviewSelect>>", self._sess_select)
        self.sess_info = ttk.Label(p, text="Select a session above.", style="Muted.TLabel", wraplength=820, justify="left")
        self.sess_info.grid(row=3, column=0, sticky="w", pady=(10, 0))
        b = ttk.Frame(p)
        b.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.btn_revert = ttk.Button(b, text="Undo selected session", style="Big.Accent.TButton", command=self.on_revert)
        self.btn_revert.grid(row=0, column=0)
        self.btn_all = ttk.Button(b, text="Turn ALL disabled apps back on", command=self.on_enable_all)
        self.btn_all.grid(row=0, column=1, padx=6)
        ttk.Button(b, text="Open this TV's folder", command=self.on_open_folder).grid(row=0, column=2, padx=6)
        self.btn_restart_check = ttk.Button(b, text="Is it safe to restart the TV?", command=self.on_restart_check)
        self.btn_restart_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # ---- Results section
    def _build_results(self, p):
        p.rowconfigure(3, weight=1)
        self._head(p, "Results", "What Taxis did, step by step. Green worked; red needs attention.")
        top = ttk.Frame(p)
        top.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)
        self.summary = ttk.Label(top, text="Nothing run yet.", font=self.fonts["h2"])
        self.summary.grid(row=0, column=0, sticky="w")
        self.prog = ttk.Progressbar(top, mode="indeterminate", length=180)
        self.prog.grid(row=0, column=1, sticky="e")
        ttk.Button(top, text="Copy log", command=self.on_copy_log).grid(row=0, column=2, padx=(10, 0))
        box = ttk.Frame(p)
        box.grid(row=3, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, wrap="word", bd=0, highlightthickness=0, padx=16, pady=12, spacing1=3, spacing3=3,
                           font="TkTextFont", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

    def on_copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get("1.0", "end"))
        self._set_summary("Log copied to the clipboard.", self._sum_kind)

    # ------------------------------------------------------------ helpers
    # Enables or disables every control that requires an active TV connection.
    def _enable(self, on):
        st = "normal" if on else "disabled"
        for w in (self.btn_switch, self.btn_install, self.btn_revert, self.btn_all, self.btn_diag, self.btn_fix, self.btn_hcheck, self.btn_redirect_on, self.btn_redirect_off, self.btn_city, self.btn_bg, self.btn_bgclear, self.btn_restart_check, self.btn_ss, self.btn_ss_prev, self.btn_ss_off,
                  self.card_quick, self.card_undo, self.btn_quick):
            w.configure(state=st)
        self.card_launch.configure(state=st)
        self.btn_disconnect.configure(state=st)
        for b in self.navbtns.values():
            b.configure(state="normal" if self.eng.serial else "disabled")

    def _set_conn(self, text, kind):
        self._conn_kind = kind
        self.conn_lbl.configure(text=text)
        self._recolor_status()

    def _set_summary(self, text, kind=None):
        self._sum_kind = kind
        self.summary.configure(text=text)
        self._recolor_status()

    def add_row(self, step, target, ok, detail):
        icon, tag = ("✔", "ok") if ok is True else ("✘", "fail") if ok is False else ("•", "info")
        if ok is True:
            self.counts[0] += 1
        elif ok is False:
            self.counts[1] += 1
        lg = self.log
        lg.configure(state="normal")
        lg.insert("end", f"{icon}  {step}", (tag, "b"))
        lg.insert("end", f"   {target}\n", ("tgt",))
        if detail:
            lg.insert("end", f"      {detail}\n", ("det",))
        lg.configure(state="disabled")
        lg.see("end")

    def refresh_home(self):
        if not self.eng.serial:
            return

        def work():
            try:
                self.q.put(("home", self.eng.current_home(), self.eng.list_homes()))
            except Exception as e:
                self.q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def refresh_sessions(self):
        self.sess.delete(*self.sess.get_children())
        if not self.eng.dir:
            return
        for s in self.eng.sessions():
            hs = s["actions"].get("home_set")
            home = f"{hs['from']}  ->  {hs['to']}" if hs else "-"
            self.sess.insert("", "end", iid=s["id"], values=(s["time"], s["mode"], len(s["actions"].get("disabled", [])), home, s["status"]))

    # Explains exactly what the selected Undo session will restore.
    def _sess_select(self, _e=None):
        sel = self.sess.selection()
        if not sel:
            return
        _, s = self.eng._load(sel[0])
        a = s["actions"]
        parts = []
        if a.get("disabled"):
            parts.append(f"turn {len(a['disabled'])} app(s) back on")
        if a.get("home_set"):
            parts.append(f"set the home screen back to {a['home_set']['from']}")
        if a.get("hidden_packages") or a.get("hidden_components") or a.get("stock_hidden"):
            parts.append("turn the original home app back on")
        if a.get("screensaver"):
            parts.append("put the TV's own screensaver back")
        self.sess_info.configure(text="Undoing this session will: " + ("; ".join(parts) if parts else "do nothing (nothing was changed)") + ".")

    # ------------------------------------------------------------ background plumbing
    def run_bg(self, title, fn):
        if self.busy:
            return
        self.busy = True
        self._enable(False)
        self.prog.start(12)
        self.counts = [0, 0]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._set_summary(title)
        self.current = "results"
        self.secs["results"].tkraise()
        self._style_nav()
        emit = lambda step, target, ok, detail: self.q.put(("row", step, target, ok, detail))

        def work():
            try:
                fn(emit)
            except Exception as e:
                self.q.put(("row", "Error", "-", False, str(e)))
            self.q.put(("done",))
        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        try:
            for _ in range(200):
                m = self.q.get_nowait()
                getattr(self, "_m_" + m[0])(*m[1:])
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _m_row(self, *a):
        self.add_row(*a)

    # Restores controls and summarizes a completed background operation.
    def _m_done(self):
        self.busy = False
        self.prog.stop()
        self._enable(bool(self.eng.serial))
        ok, bad = self.counts
        if bad:
            self._set_summary(f"Finished with problems: {ok} worked, {bad} failed. See the red lines.", "bad")
        else:
            self._set_summary(f"All done: {ok} step(s) worked, none failed.", "ok")
        self.refresh_sessions()
        self.refresh_home()
        self.load_apps()
        if self.eng.home_failed:
            self.eng.home_failed = None
            messagebox.showinfo(
                "Your TV keeps its own home screen",
                "The launcher is installed, but this TV still opens its own home screen when you press Home.\n\n"
                "Taxis keeps Google TV enabled because this model needs it during startup. Nothing risky was changed.\n\n"
                "Use 'Home opens Taxis' on the Taxis Home page instead.")

    def _m_apps(self, items, tier):
        self._set_plan(items)

    # Shows the safe system Home while Taxis handles the remote through its redirect.
    def _m_home(self, cur, homes):
        self.home_lbl.configure(text=f"Safe system Home:  {cur or 'unknown'}")
        self.home_box.configure(values=homes)
        if self.home_choice.get() not in homes:
            self.home_choice.set("")

    def _m_found(self, hits):
        self.btn_scan.configure(state="normal")
        if hits:
            self.ip_box.configure(values=hits)
            self.ip.set(hits[0])
            self._set_conn(f"Found {len(hits)} device(s) with ADB open: {', '.join(hits)}. Press Connect.", None)
        else:
            self._set_conn("No device found. Turn on debugging on the TV, or type the IP and press Connect.", "bad")

    # Resets the desktop to its disconnected state after ADB releases the TV endpoint.
    def _m_disconnected(self, serial, confirmed):
        self.eng = Engine()
        self._enable(False)
        self.side_name.configure(text="")
        self.side_info.configure(text="")
        self.tv_lbl.configure(text="")
        message = (f"Disconnected from {serial}." if confirmed else
                   f"Connection closed locally, but ADB could not confirm disconnecting from {serial}.")
        self._set_conn(message, None if confirmed else "bad")
        self.page("connect")

    # Populates connected-TV details and hides unsupported system-Home controls on TCL G13.
    def _m_connected(self, info):
        self.btn_connect.configure(state="normal")
        self._set_conn(f"Connected to {self.eng.serial}", "ok")
        txt = f"{info['manufacturer']} {info['model']}   |   device {info['device']}   |   Android {info['android']}"
        self.tv_lbl.configure(text=txt + ("\nFire TV: replacing the home screen is not supported." if self.eng.is_fire else ""))
        self.side_name.configure(text=f"{info['manufacturer']} {info['model']}".strip())
        self.side_info.configure(text=f"•  Android {info['android']}  •  Connected\n{self.eng.serial}")
        self.pset.set(self.eng.set or "")
        self._enable(True)
        if info.get("device") == "G13":
            self.btn_fix.grid_remove()
        else:
            self.btn_fix.grid()
        if self.eng.is_fire:
            self.card_launch.configure(state="disabled")
            self.btn_install.configure(state="disabled")
        self._src_changed()
        recent = [info["ip"]] + [x for x in self.prefs.get("recent_ips", []) if x != info["ip"]]
        self.prefs.update(last_ip=info["ip"], recent_ips=recent[:6])
        self.ip_box.configure(values=self.prefs["recent_ips"])
        save_prefs(self.prefs)
        self.open_work("overview")

    def _m_error(self, msg):
        self.btn_connect.configure(state="normal")
        self.btn_scan.configure(state="normal")
        self.prog.stop()
        if not self.eng.serial:
            self._set_conn("Not connected.", "bad")
        messagebox.showerror("Problem", msg)

    # ------------------------------------------------------------ handlers
    def on_scan(self):
        self.btn_scan.configure(state="disabled")
        self._set_conn("Scanning your network for ADB (port 5555)...", None)

        def work():
            try:
                pre = tx.local_prefix()
                with ThreadPoolExecutor(128) as ex:
                    hits = [h for h in ex.map(tx.probe, [f"{pre}.{i}" for i in range(1, 255)]) if h]
                self.q.put(("found", hits))
            except Exception as e:
                self.q.put(("error", f"Scan failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def on_connect(self):
        ip = self.ip.get().strip()
        if not ip:
            return messagebox.showinfo("IP needed", "Type your TV's IP address (Settings > Network on the TV), for example 192.168.1.50.")
        if ip.lower() == "ip" or not re.match(r"^[A-Za-z0-9.-]+$", ip):
            return messagebox.showwarning("IP address", "Please type the real IP address, for example 192.168.1.50.")
        port = self.port.get().strip() or "5555"
        if not port.isdigit():
            return messagebox.showwarning("Port", "The port must be a number, usually 5555.")
        self.btn_connect.configure(state="disabled")
        self._set_conn(f"Connecting to {ip}... (watch the TV for an 'Allow USB debugging?' box)", None)

        def work():
            try:
                self.q.put(("connected", self.eng.connect(ip, port)))
            except Exception as e:
                self.q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    # Disconnects only this computer's ADB session and leaves every TV setting unchanged.
    def on_disconnect(self):
        if self.busy or not self.eng.serial:
            return
        serial = self.eng.serial
        self.btn_disconnect.configure(state="disabled")

        def work():
            code, _detail = tx.sh("disconnect", serial, timeout=10)
            self.q.put(("disconnected", serial, code == 0))
        threading.Thread(target=work, daemon=True).start()

    def on_browse(self):
        f = filedialog.askopenfilename(title="Choose a launcher APK", filetypes=[("Android app", "*.apk"), ("All files", "*.*")])
        if f:
            self.apk.set(f)

    def on_pick_bg(self):
        f = filedialog.askopenfilename(title="Choose a background picture",
                                       filetypes=[("Pictures", "*.jpg *.jpeg *.png *.webp *.bmp"), ("All files", "*.*")])
        if f:
            self.bg_path.set(f)

    def _bg_prefs(self):
        self.prefs.update(bg_path=self.bg_path.get().strip(), bg_dim=self.bg_dim.get(), bg_preset=self.bg_preset.get())
        save_prefs(self.prefs)

    def on_apply_bg(self):
        self._bg_prefs()
        path, dim, preset = self.bg_path.get().strip(), self.bg_dim.get(), self.bg_preset.get()
        self.run_bg("Sending the background to the TV...", lambda emit: self.eng.set_background(path or None, dim, preset, emit))

    def on_clear_bg(self):
        self._bg_prefs()
        dim, preset = self.bg_dim.get(), self.bg_preset.get()
        self.run_bg("Removing the picture...", lambda emit: self.eng.set_background(None, dim, preset, emit, clear=True))

    def on_city(self):
        city, units = self.city.get().strip(), self.units.get()
        self.prefs.update(city=city, units=units)
        save_prefs(self.prefs)
        self.run_bg("Sending weather settings to the launcher...", lambda emit: self.eng.configure_launcher(city, units, emit))

    def on_make_default(self):
        if self.eng.is_fire:
            return messagebox.showwarning("Fire TV", "Fire TV does not allow a replacement home screen.")
        if not messagebox.askyesno(
                "Make the launcher the default",
                "Taxis will ask the TV to use Taxis Launcher as its system home screen.\n\n"
                "It will not turn off any home app. If the TV refuses, the result says so and nothing is changed.\n\nContinue?"):
            return
        city, units = self.city.get().strip(), self.units.get()
        self.run_bg("Making the launcher the default...", lambda emit: self.eng.make_default(BUNDLED_COMP, emit, city, units, False))

    # Enables the approved Accessibility redirect after explaining its limited access.
    def on_redirect_on(self):
        if not messagebox.askyesno(
                "Enable Home redirect",
                "This enables Taxis Home assistance. It watches only for Google TV's home screen and immediately reopens Taxis.\n\n"
                "Google TV remains enabled for safe startup and may flash briefly. Continue?"):
            return
        self.prefs["home_redirect"] = True
        save_prefs(self.prefs)
        self.run_bg("Enabling the Home redirect...", lambda emit: self.eng.set_home_redirect(True, emit))

    # Disables the Accessibility redirect so the remote opens Google TV normally.
    def on_redirect_off(self):
        self.prefs["home_redirect"] = False
        save_prefs(self.prefs)
        self.run_bg("Disabling the Home redirect...", lambda emit: self.eng.set_home_redirect(False, emit))

    def on_ss_on(self):
        self.run_bg("Setting the screensaver...", lambda emit: self.eng.set_screensaver(emit))

    def on_ss_preview(self):
        self.run_bg("Starting the screensaver...", lambda emit: self.eng.preview_screensaver(emit))

    def on_ss_off(self):
        self.run_bg("Putting the TV's screensaver back...", lambda emit: self.eng.clear_screensaver(emit))

    def on_restart_check(self):
        self.run_bg("Checking that the TV can restart safely...", lambda emit: self.eng.restart_check(emit))

    def on_home_check(self):
        if not messagebox.askyesno("Full home check",
                                   "This presses Home on the TV twice to see what really opens, and reads a few settings. "
                                   "It changes nothing. The TV screen will flick to its home screen for a few seconds.\n\nRun it?"):
            return
        self.run_bg("Checking why Home does not open the launcher...", lambda emit: self.eng.home_check(emit))

    def on_diagnose(self):
        self.run_bg("Checking the launcher on the TV...", lambda emit: self.eng.diagnose(emit))

    def on_switch_off(self):
        chosen = self.selected()
        if not chosen:
            return messagebox.showinfo("Nothing selected", "Tick at least one app first.")
        if not messagebox.askyesno("Please confirm", f"Switch off {len(chosen)} app(s)?\n\nNothing is uninstalled. You can turn them back on in 'Undo'."):
            return
        self.run_bg("Switching off apps...", lambda emit: self.eng.run("2", chosen, {}, emit))

    # Confirms and runs a Taxis install or update without removing Google TV Home.
    def on_install(self):
        if self.eng.is_fire:
            return messagebox.showwarning("Fire TV", "Fire TV does not allow a replacement home screen.")
        src = self.lsrc.get()
        launcher = {"source": src, "apk": self.apk.get().strip() or None, "component": self.home_choice.get() or None,
                    "hide_stock": False, "city": self.city.get().strip(), "units": self.units.get(),
                    "home_redirect": self.prefs.get("home_redirect", False)}
        self.prefs.update(city=launcher["city"], units=launcher["units"])
        save_prefs(self.prefs)
        self._bg_prefs()
        bgp = self.bg_path.get().strip()
        if bgp or self.bg_preset.get() != "Auto":
            launcher["bg"] = {"path": bgp or None, "dim": self.bg_dim.get(), "preset": self.bg_preset.get()}
        lines = []
        if src == "bundled":
            if not BUNDLED_APK.is_file():
                return messagebox.showwarning("Launcher missing", "The included Taxis Launcher file was not found. Extract taxis.zip again and retry.")
            lines.append("Install or update Taxis Launcher and keep Google TV enabled for safe startup.")
            lines.append("(Google Play Protect may ask you to confirm on the TV: choose 'Install anyway'.)")
        elif src == "installed":
            if not launcher["component"]:
                return messagebox.showwarning("Pick a launcher", "Choose a launcher from the list.")
            lines.append(f"Make this the default home screen:\n   {launcher['component']}")
        elif src == "apk":
            if not launcher["apk"] or not os.path.isfile(launcher["apk"]):
                return messagebox.showwarning("APK", "Choose an APK file that exists (Browse...).")
            lines.append(f"Install {os.path.basename(launcher['apk'])} and make it the default home screen.")
        else:
            entry = next((e for e in self.catalog if e["name"] == self.builtin_choice.get()), None)
            if not entry:
                return messagebox.showwarning("Pick a launcher", "Choose a launcher from the list.")
            launcher["entry"] = entry
            lines.append(f"Download {entry['name']} from github.com/{entry['github']}, install it and make it the default home screen.")
        pkgs = self.selected() if self.also_clean.get() else []
        if pkgs:
            lines.append(f"Also switch off {len(pkgs)} app(s).")
        lines.append("\nEverything can be undone in 'Undo'; Taxis Launcher stays installed.")
        if not messagebox.askyesno("Please confirm", "\n".join(lines) + "\n\nContinue?"):
            return
        self.run_bg("Setting up the launcher...", lambda emit: self.eng.run("1", pkgs, launcher, emit))

    # Runs Undo for the selected session while always keeping Taxis installed.
    def on_revert(self):
        sel = self.sess.selection()
        if not sel:
            return messagebox.showinfo("Undo", "Select a session in the list first.")
        sid = sel[0]
        if not messagebox.askyesno("Undo session", f"Undo this session?\n\n{sid}\n\n{self.sess_info.cget('text')}"):
            return
        self.run_bg("Undoing...", lambda emit: self.eng.revert(sid, emit))

    def on_enable_all(self):
        if not messagebox.askyesno("Turn everything back on", "This turns ON every app that is currently disabled on the TV, including ones disabled by something else.\n\nContinue?"):
            return
        self.run_bg("Turning everything back on...", lambda emit: self.eng.enable_all_disabled(emit))

    def on_open_folder(self):
        if not self.eng.dir:
            return messagebox.showinfo("Folder", "Connect to a TV first.")
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.eng.dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(self.eng.dir)])
            else:
                subprocess.run(["xdg-open", str(self.eng.dir)])
        except Exception as e:
            messagebox.showinfo("Folder", f"{self.eng.dir}\n\n({e})")


def main():
    if sys.platform.startswith("win"):
        try:  # crisp text on high-DPI Windows screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
