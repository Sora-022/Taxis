# taxis: full step-by-step instructions

This is the detailed guide for running taxis from start to finish. For an overview and the list of supported TVs, read [README.md](README.md) first.

**What taxis does:** it shows you the preinstalled apps it found on your TV, lets you choose which ones to switch off, and can switch them back on later. It never uninstalls anything.

**What it needs:** an Android-based TV (Android TV, Google TV or Fire TV), a computer on the same router, ADB, and Python 3.

> **Samsung (Tizen), LG (webOS), Roku and Apple TV are not supported.** If you run taxis on one, it stops and changes nothing.

---

## Contents

1. [The short version](#1-the-short-version)
2. [Before you start](#2-before-you-start)
3. [Get the files](#3-get-the-files)
4. [Install Python and ADB](#4-install-python-and-adb)
5. [Prepare the TV](#5-prepare-the-tv)
6. [Connect the computer to the TV](#6-connect-the-computer-to-the-tv)
7. [Open a terminal in the taxis folder](#7-open-a-terminal-in-the-taxis-folder)
8. [Step A: look first (dry run)](#8-step-a-look-first-dry-run)
9. [Step B: choose and disable](#9-step-b-choose-and-disable)
10. [After disabling](#10-after-disabling)
11. [Second round: medium tier](#11-second-round-medium-tier)
12. [Undo (every way)](#12-undo-every-way)
13. [After a firmware update](#13-after-a-firmware-update)
14. [When you are finished](#14-when-you-are-finished)
15. [Error messages and fixes](#15-error-messages-and-fixes)
16. [FAQ](#16-faq)
17. [Using the window (GUI)](#17-using-the-window-gui)

---

## 1. The short version

```
adb connect YOUR_TV_IP:5555
python taxis.py debloat -p safe -d YOUR_TV_IP --dry-run
python taxis.py debloat -p safe -d YOUR_TV_IP
python taxis.py restore
```

Connect, look, choose and confirm, and undo if needed. The sections below explain each step.

---

## 2. Before you start

Tick these off:

- [ ] The TV is Android TV, Google TV or Fire TV (see the table in the README).
- [ ] The TV is turned on and the computer is on the **same router** (Wi-Fi or Ethernet both work).
- [ ] You can use the TV's remote (you will need to press a few menus).
- [ ] You have about 20 minutes.
- [ ] You know that disabling apps can remove features that depend on them. Everything is reversible, and the tool asks before changing anything.

Good habits: change a few apps at a time, restart the TV, and test before doing more.

---

## 3. Get the files

1. Download `taxis.zip`.
2. **Extract it** (Windows: right-click > Extract All. macOS: double-click. Linux: `unzip taxis.zip`).
3. You should now have a folder named `taxis` containing `taxis.py`, `README.md`, `INSTRUCTIONS.md`, `restore.ps1`, `restore.sh` and a `profiles` folder.

Do not run files from inside the zip. Extract first.

---

## 4. Install Python and ADB

### Windows
Open **PowerShell** (right-click Start > Terminal or Windows PowerShell) and run:

```
winget install Python.Python.3.12
winget install Google.PlatformTools
```

Close PowerShell and open a **new** one. Then check both:

```
python --version
adb version
```

- If `python` opens the Microsoft Store or says it is not found, install Python from python.org, tick **Add python.exe to PATH** during setup, and try again. You can also try `py --version` and then use `py` instead of `python` in every command below.
- If `adb` is not found, you did not open a new window, or ADB was not added to PATH. As a fallback, download Google's **platform-tools** zip, extract it to `C:\platform-tools`, and run `C:\platform-tools\adb` instead of `adb`.

### macOS
```
brew install python android-platform-tools
python3 --version
adb version
```
On macOS use `python3` where this guide says `python`.

### Ubuntu / Debian
```
sudo apt update
sudo apt install python3 adb
python3 --version
adb version
```

---

## 5. Prepare the TV

Menu names vary a little by brand and software version. If yours differs, look for "About" and "Developer options".

### Android TV / Google TV (TCL, Sony, Philips, Xiaomi, Hisense, Nvidia Shield and others)

1. Settings > **Device Preferences** > **About**.
2. Press **OK** on **Build** (sometimes "Android TV OS build") **7 times**. A message says you are now a developer.
3. Press Back, then open **Developer options**.
4. Turn on **USB debugging**.
5. If you see **Network debugging**, **ADB over network** or **Wireless debugging**, turn that on too.
6. Keep the TV awake while you work. Do not let it go to standby.

### Amazon Fire TV / Firestick

1. Settings > **My Fire TV** > **About**.
2. Select the device name (for example "Fire TV Stick") **7 times**.
3. Press Back, then open **Developer options**.
4. Turn on **ADB debugging**.

### Find the TV's IP address

- Android TV / Google TV: Settings > **Network & Internet** > your network. Look for **IP address**, for example `192.168.1.50`.
- Fire TV: Settings > My Fire TV > About > **Network**.
- Or check your router's list of connected devices.

Write it down. This guide uses `192.168.1.50` as an example. **Use your own.**

---

## 6. Connect the computer to the TV

In your terminal run:

```
adb connect 192.168.1.50:5555
```

Rules:
- Use **your** IP address, not the example.
- Put the port (`:5555`) **after** the IP.
- Do not type the word `ip`.

You will see `connected to 192.168.1.50:5555` (or `already connected to ...`).

**Now look at the TV.** A box says **Allow USB debugging?** Tick **Always allow** and press **OK**.

Check:

```
adb devices
```

Expected:
```
List of devices attached
192.168.1.50:5555    device
```

If it says `unauthorized`, accept the prompt on the TV and run `adb devices` again.

### If your TV uses Wireless debugging with a pairing code (some Android 11+ TVs)

Port 5555 will not work. Instead, on the TV open **Wireless debugging** and choose **Pair device with pairing code**. It shows an IP, a **pairing port** and a 6-digit code. On the computer:

```
adb pair 192.168.1.50:PAIRING_PORT
```
Enter the 6-digit code. Then use the **connect port** shown on the main Wireless debugging screen (it is different):

```
adb connect 192.168.1.50:CONNECT_PORT
```

---

## 7. Open a terminal in the taxis folder

**Windows:** open the extracted `taxis` folder in File Explorer, click the address bar, type `powershell`, press Enter. Or in PowerShell:

```
cd C:\Users\YourName\Downloads\taxis
```

**macOS / Linux:**

```
cd ~/Downloads/taxis
```

Check you are in the right place:

```
python taxis.py --help
```

You should see a list of commands (`go`, `debloat`, `restore`, `status`, `audit`, `scan`).

---

## 8. Step A: look first (dry run)

A dry run **changes nothing**. It only shows what taxis found.

```
python taxis.py debloat -p safe -d 192.168.1.50 --dry-run
```

Example output (your TV may show different apps):

```
connected to 192.168.1.50:5555
Profile set: tcl-g13
Device : Smart TV (192.168.1.50:5555)
Android SDK 34

Profile 'safe': 11 installed package(s) found. Disabling does NOT uninstall them:

   1) [safe      ] com.vectorunit.red                           preloaded game
   2) [safe      ] com.vectorunit.purple.googleplay             preloaded game
   3) [safe      ] com.tencent.qqlivei18n                       WeTV
   ...

Dry run only. Nothing changed.
```

How to read it:

- **Profile set:** which list was matched to your TV. `tcl-g13` or `firetv` means a ready-made list. If you see "No profile set matches this device", your model has no list yet (see the README, section 9).
- **The numbered list** contains only apps that are really installed and still active on **your** TV.
- **"Nothing to do"** means none of the listed apps are currently active. That is fine: they may already be disabled.

If the tool says it refused to continue (not a TV, or the connection failed), nothing was changed. See [section 15](#15-error-messages-and-fixes).

---

## 9. Step B: choose and disable

Run the same command without `--dry-run`:

```
python taxis.py debloat -p safe -d 192.168.1.50
```

It prints the same numbered list, then asks:

```
Which apps do you want to disable?
  type numbers (e.g. 1,3,5-7), 'all', or 'none':
```

What you can type:

| You type | Meaning |
|---|---|
| `1,3,5` | apps 1, 3 and 5 |
| `1-4` | apps 1 to 4 |
| `1-4,8` | apps 1 to 4 and 8 |
| `all` | every app in the list |
| `none` or just Enter | nothing, and the tool exits with no changes |

**Tip:** if you are not sure what an app is, **leave it out**. If you do use an app (for example AnyDesk, or a streaming app), do not select it.

The tool then repeats your choice and asks for confirmation:

```
You selected 9 app(s):
  - com.vectorunit.red  (preloaded game)
  ...

Disable these apps? Type YES to continue:
```

- Type exactly `YES` (capital letters) to continue.
- Anything else cancels with "Cancelled. Nothing changed."

After `YES`:

```
Backup saved: C:\Users\YourName\.taxis\snapshots\192.168.1.50_5555_20261025-051613.json
  OK   com.vectorunit.red
  OK   com.vectorunit.purple.googleplay
  ...
Disabled 9/9. Undo anytime:  python taxis.py restore  (or restore.ps1 / restore.sh)
```

- `OK` means the app is now disabled.
- `FAIL` followed by a reason means that one app could not be changed. It stays as it was.
- The **backup** is your undo information. Do not delete the `.taxis` folder.

Then the tool prints a short **DONE** guide (next section).

---

## 10. After disabling

### 10.1 Restart the TV
Unplug it for about 10 seconds, or use the TV's restart option.

### 10.2 Test what you use
- [ ] Your streaming apps open and play (YouTube, Netflix and so on)
- [ ] HDMI inputs work (consoles, set-top boxes)
- [ ] The remote works (volume, home, mic button)
- [ ] The home screen loads normally

Use the TV normally for a day. Some problems show up later.

If something is wrong, jump to [Undo](#12-undo-every-way).

### 10.3 Optional: cleaner home screen (Google TV only)

Disabling apps does **not** change how the home screen looks. If you want fewer recommendation rows, turn on Google's **Apps only mode**:

1. Settings > **Accounts & Sign In**.
2. Select your profile > **Apps only mode** > **Turn on**.
3. Press **Home** on the remote.

Trade-offs:
- Search and the voice assistant stop working.
- You must switch it off to install apps.
- Sponsored content may still appear.

To undo: same menu > turn **Apps only mode** off. Fire TV has no Apps-only mode.

---

## 11. Second round: medium tier

Only do this after the first round has been fine for a day.

```
python taxis.py debloat -p medium -d 192.168.1.50 --dry-run
python taxis.py debloat -p medium -d 192.168.1.50
```

The `medium` list is shorter once the `safe` apps are already disabled, because taxis skips apps that are already off. It usually contains vendor promo or message services. Select them **one at a time** if you want to know which one changes something, then restart and test again.

The `aggressive` tier exists only for Fire TV. It includes update services and can stop security updates. Most people should not use it.

---

## 12. Undo (every way)

### 12.1 Undo the last run (easiest)

```
python taxis.py restore
```

It prints the apps it will re-enable and asks you to type `YES`:

```
Using snapshot 192.168.1.50_5555_20261025-051613.json: 9 package(s) to re-enable
Re-enable these? Type YES to continue:
```

Then each app shows `OK`.

### 12.2 Undo without Python

**Windows:**
```
powershell -ExecutionPolicy Bypass -File restore.ps1 -Device 192.168.1.50
```
**macOS / Linux:**
```
./restore.sh 192.168.1.50
```
(If `./restore.sh` is not allowed, run `chmod +x restore.sh` first.)

When you provide a TV address, these read the newest matching `.restore.txt` for that TV in `~/.taxis/snapshots/`. Without an address, they use the newest restore file overall.

### 12.3 Undo one app

```
adb shell pm enable com.example.package
```
Replace with the package name from your list.

### 12.4 Undo every disabled app

```
python taxis.py restore --everything
```
It shows the full list first. This includes apps disabled by something else, not only taxis, so read it before typing `YES`.

### 12.5 Undo with only the TV remote

Settings > **Apps** > **See all apps** > choose the app > **Enable**.

### 12.6 Check the result

```
adb shell pm list packages -d
```
An empty result means nothing is disabled.

### 12.7 Last resort

A factory reset restores everything but erases your accounts and apps. Use it only if the TV will not work normally.

---

## 13. After a firmware update

An update can turn disabled apps back on. Check:

```
python taxis.py status -d 192.168.1.50
```

Example: `9/9 still disabled.` means nothing changed. If some came back it lists them. To disable them again (with confirmation):

```
python taxis.py status -d 192.168.1.50 --fix
```

To look for new unknown apps after an update:

```
python taxis.py audit -d 192.168.1.50
```
`audit` only lists packages that no profile knows about. It changes nothing.

---

## 14. When you are finished

1. Turn **USB debugging**, **Network debugging** and **ADB debugging** **off** in the TV's Developer options.
2. Keep the folder `~/.taxis/snapshots/` (Windows: `C:\Users\YourName\.taxis\snapshots\`). It holds your undo information.
3. Optionally disconnect: `adb disconnect 192.168.1.50:5555`.

---

## 15. Error messages and fixes

| Message | Meaning and fix |
|---|---|
| `adb not found` | ADB is not installed or not on PATH. Redo [section 4](#4-install-python-and-adb) and open a **new** terminal. |
| `python` is not recognized / opens Microsoft Store | Install Python (section 4), or try `py taxis.py ...`. |
| `cannot resolve host 'ip'` | You typed the word `ip`. Use your real address, for example `192.168.1.50:5555`. |
| `Could not connect ... Samsung (Tizen) or LG (webOS) ...` | The TV did not accept ADB. Check the IP, that debugging is on and the TV is awake. Samsung and LG TVs are not supported. Nothing was changed. |
| `No Android-based TV found on port 5555` | Auto-scan found nothing. Turn debugging on and pass the IP with `-d`. |
| `unauthorized` in `adb devices` | Accept **Allow USB debugging?** on the TV screen. |
| `... is Android but does not report TV features` | The device looks like a phone or tablet. The tool refuses and changed nothing. |
| `does not look like an Android device` | Not supported. Nothing was changed. |
| `No profile set matches this device` | No ready-made list for your model. Pass `-s tcl-g13` or `-s firetv` only if they truly match, or build your own (README, section 9). |
| `Nothing to do: none of the profile's packages are active` | Those apps are already disabled, or are not on your TV. This is fine. |
| `FAIL ...` on an app | That app could not be disabled and stays as it was. |
| `No snapshot found` when restoring | Use `python taxis.py restore --everything`, or `adb shell pm enable PACKAGE`. |
| The TV is slow or an app misbehaves | Undo (section 12). Re-enable that app first. |

If it still fails: run `adb kill-server`, then `adb connect IP:5555` again, and restart the TV.

---

## 16. FAQ

**Does this uninstall apps?**
No. It only disables them. They can be switched back on at any time.

**Will it block ads?**
It does not block ads inside apps such as YouTube or Netflix, and it does not change the home screen layout. See [10.3](#103-optional-cleaner-home-screen-google-tv-only) for Apps-only mode.

**Is it safe?**
It is reversible and asks before changing anything, but any change can have side effects on a particular TV. Start with `safe`, change little, and test.

**Why is the list different from my friend's TV?**
Package names differ by model, region and firmware. Only apps installed on **your** TV are listed.

**Can I use it on a Samsung or LG TV?**
No. They do not use ADB this way. The tool refuses to run and changes nothing.

**Can I use it on my phone?**
No. It checks for TV features and refuses on phones and tablets.

**My TV is not listed.**
Read README section 9 to build a profile, and test one app at a time.

**Does it send data anywhere?**
No. It talks only to your TV on your local network. It does not use the internet.

**What does `-y` do?**
It skips the typed `YES` confirmation. It is not recommended.

---

## 17. Using the window (GUI)

Steps 1 to 6 (prepare the TV, install ADB and Python, connect) are the same as above.

### Start it
- **Windows:** double-click `start_gui.bat` (or run `python taxis_gui.py`).
- **macOS / Linux:** `./start_gui.sh` (or `python3 taxis_gui.py`).
- If it says tkinter is missing: Ubuntu `sudo apt install python3-tk`, macOS Homebrew `brew install python-tk`.

### Look and feel
The bar at the top has a **Theme** (Dark, Light, Ocean, Forest, High contrast), a **Text size** (Small to Extra large) and a **Font**. Pick from the nicest fonts found on your computer, or choose **More fonts...** to search every installed font with a live preview. All three are remembered next time.

### The window
The first page has three cards: **1 Prepare your TV** (press *Show me how*), **2 Connect** (type the TV's IP, or press *Find TVs on my network*; accept **Allow USB debugging?** on the TV) and **3 What would you like to do?**. After connecting, the navigation bar takes you around. **Disconnect** releases only this computer's ADB connection; it does not change anything on the TV.

- **Clean apps:** a big, searchable list. Choose **Safe**, **Medium** or **Aggressive** at the top, tick apps by clicking anywhere on a row, then press **Switch off N apps**. *Quick clean* on the first page opens this list with every safe app already ticked.
- **Taxis Home:** install or update Taxis, make the remote Home button return to it, set weather/location, choose a shared Home-and-idle background, and check that it works.
- **Undo:** every run for this TV; pick one and undo it.
- **Results:** a colour-coded log (green worked, red needs attention) with a **Copy log** button. It opens by itself whenever something runs.

### Launcher options (no upload needed)
- **Taxis Launcher (included, recommended):** a small ad-free home screen that ships inside the `launcher` folder. Its landing page shows time, date and local weather, with a simple app grid and quick settings. Leave **Weather city** empty to use the TV's approximate network location; IP location is the fallback. The selected background is also used by the idle view and Taxis Idle screensaver.
- **Download from GitHub:** optional extra launchers listed in `profiles/launchers.json` (add `{"name": "...", "github": "owner/repo"}`; the repo's latest release must contain an `.apk`). The list is empty by default.
- **Already on the TV:** pick a home app that is installed and ask Android to use it as Home.
- **My own APK file:** optional, for a launcher you downloaded yourself.

Taxis never disables Google TV Home to force the change. On this TCL model that system app is required for reliable startup.

Fire TV does not allow a replacement home screen, so the launcher option is switched off there.

To rebuild the launcher from source: `launcher/build.sh` (needs a JDK, aapt, apksigner, zipalign, dx and the Android API 23 jar; on Ubuntu `sudo apt install default-jdk-headless aapt apksigner zipalign dalvik-exchange android-sdk-platform-23`).

### Results and Undo
Every step is a row: green **OK**, red **FAILED** (with the reason), grey info. The **Undo / sessions** tab lists every run for this TV; select one and press **Undo selected session**. **Re-enable ALL disabled apps** turns on everything currently disabled (it asks first).

### Where things are saved
```
~/.taxis/gui.json                theme, text size, recent IPs
~/.taxis/downloads/              launcher APKs fetched by the built-in option
~/.taxis/tvs/<model>_<serial>/
    device.json
    sessions/<time>_<mode>/session.json, packages-before.txt
```

### GUI limits
- Samsung (Tizen), LG (webOS), Roku and Apple TV are not supported.
- Setting a default home is not verified on every TV. Some Google TV builds refuse it; the Results table then shows a red FAILED and nothing else is affected.
- Only the built-in launcher download uses the internet.

### Taxis Launcher in detail
- **Apps view:** minimalist and calm. Icons on a soft dark veil, no boxes; the app you choose lifts slightly, brightens and shows a small dot, the rest rest at lower brightness.
- **Place:** shows on the right of the landing page. If the city or the internet lookup fails it falls back to the city from the TV's own time zone, and a small grey line under it says why (for example *No internet (location)* or *City not found: Xyz*). Set the city on the Launcher page and press **Apply to TV**.
- **Icon and banner:** the launcher now has an icon and a banner, so it is visible in the TV's app lists and in the home-app chooser.
- **If Home does not return to Taxis:** open **Taxis Home**, press **Home opens Taxis**, then run **Check Taxis Launcher**. It reports whether Taxis is installed, offered as a home app, running, or crashing.

### Quick settings (inside the launcher)
On the landing page, **Quick settings** opens a side panel so you do not have to dig through the TV's Settings:
- **Wi-Fi:** shows the network and signal; press OK to turn Wi-Fi on or off. Some TVs do not let apps switch Wi-Fi; the launcher then opens the system Wi-Fi page instead. **Connection** shows Wi-Fi or Ethernet, and **Choose a Wi-Fi network** opens the network list.
- **Inputs:** one button per HDMI / AV input the TV reports (for example HDMI 1, HDMI 2). OK switches to it through the TV's Live TV app. If the TV reports none, use the INPUT / SOURCE button on the remote.
- **Sound:** volume down and up.
- **Shortcuts:** Bluetooth, Display, Sound settings, Date and time.
Back closes the panel.

### The look
Everything in the launcher follows one minimalist style: soft blue-grey background, thin type, no bright colours. The landing page has the time, date and weather on the left, the place on the right and three quiet links (**Apps**, **Quick settings**, **Settings**). Focus is shown by a soft highlight that fades in, never by a bright block. The apps screen is a spacious grid with the same quiet highlight; the icon grows a little and its name brightens. Screens fade smoothly into each other.

### Full home check (when Home still opens the TV's own screen)
On the Taxis Home page, **Full home check** presses Home twice on the TV and reads the relevant settings. It changes nothing. It reports which home apps the TV offers, which one it has chosen, who holds the HOME role, what the **Home button** really opens and what the normal **HOME request** opens, then gives a verdict and a next step. The full report is saved as `home-report.txt` in the TV's folder (also available through **Copy log**).

### Background picture and colour style
On the Taxis Home page, the **Background** card sets one photo for Taxis Home, its in-app idle view and Taxis Idle: press **Choose picture...** (jpg, png, webp or bmp, up to 40 MB), pick how dark it should be (**Light**, **Medium** or **Strong**, so the text stays readable) and press **Apply to TV**. Taxis sends the picture to the TV, crops it to 16:9 and keeps its own private copy. **Remove picture** goes back to the plain background. Without a picture you can pick a **Colour style** (Auto, Midnight, Ocean, Forest, Dusk, Graphite).

The idle screen shows the selected background behind the time, weather and place. It adds the selected dim layer to keep text readable.

### IMPORTANT: Google TV and the Home button
Some Google TV builds keep opening their own launcher when you press Home. Taxis keeps Google TV's launcher (`com.google.android.apps.tv.launcherx`) enabled because this TCL model needs it during startup.

Taxis Launcher asks Android to open after every full reboot. **Home opens Taxis** enables a limited Accessibility service that watches only for Google TV Home and returns to Taxis; reinstalling Taxis preserves this setting.

To make the remote Home button return to Taxis on a TV that reserves Home, open **Taxis Home** and press **Home opens Taxis**. This enables a limited Accessibility service that watches only for Google TV Home and immediately reopens Taxis; Google TV may flash briefly. Press **Use Google TV Home** to restore the normal Home button. **Rescue TV** also disables the redirect.

**If your TV is stuck on loading after an older version:** on the first page type the TV's IP and press **Rescue my TV**. taxis keeps trying to reach the TV for a few minutes, turns back on everything it ever turned off and restarts the TV. By hand: `adb connect IP:5555`, then `adb shell pm enable com.google.android.apps.tv.launcherx`, then `adb reboot`.

### Before restarting the TV
On the **Undo** page, **Is it safe to restart the TV?** looks for anything taxis changed that could stop the TV from finishing startup: whether Google TV's launcher is on, whether any important system apps are off, whether the TV's chosen home app is valid, and whether Wi-Fi debugging is likely to come back after a restart (if not, Rescue could not reach a TV that hangs). It cannot promise the TV will start, because taxis cannot test a restart. For the first restart after any change, keep the taxis window open and the TV's IP address handy.

### What your home check shows on a Google TV
The check lists every home candidate with its priority. On the tested TCL Google TV, Google TV Home outranks third-party launchers even when Taxis holds the Android Home role. Taxis therefore leaves Google TV enabled and uses the limited Home redirect instead of disabling a startup-critical system app.

### Idle screen as a real screensaver
The launcher includes **Taxis Idle**: time, weather and place over the selected background, with slow movement. **Use Taxis Idle** enables it for idle/sleep, **Preview now** starts it through Android's Dream manager, and **Use TV screensaver** restores the previous choice. Undo restores all saved screensaver settings without uninstalling Taxis.
