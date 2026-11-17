# Taxis

<p align="center">
  <img src="launcher/artwork/taxis-icon.svg" alt="Taxis logo" width="180">
</p>

A safe, reversible Windows tool for simplifying Android TV, Google TV, and Amazon Fire TV.

Taxis can switch off selected preinstalled apps, install Taxis Launcher, manage the Home button, and restore recorded settings. Apps are disabled—not uninstalled—and cleaning sessions can be undone.

![Taxis Results screen](assets/images/gui-results.png)

## Download for Windows

Download `Taxis.exe` from the [latest GitHub release](../../releases/latest).

The Windows application includes Python, Google ADB, and Taxis Launcher. No separate installation is required.

> Taxis.exe is not commercially code-signed, so Windows SmartScreen may display a warning. Download it only from this repository and compare its SHA-256 with the checksum in the release notes.

## Quick start

1. Connect your computer and TV to the same network.
2. On the TV, enable Developer options and USB or network debugging.
3. Open `Taxis.exe`.
4. Enter the TV’s IP address and select **Connect**.
5. Accept the debugging permission shown on the TV.
6. Start with **Quick clean** or **Set up Taxis Home**.
7. Review every selected app before confirming.
8. Turn debugging off when finished.

For detailed setup, troubleshooting, terminal commands, and profile creation, read [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Supported devices

| Device | Support |
|---|---|
| TCL G13 Google TV | Verified on real hardware |
| Other Android TV and Google TV models | Likely compatible, but profiles may differ |
| Amazon Fire TV | App cleaning supported; replacement Home is unavailable |
| Samsung Tizen, LG webOS, Roku, Apple TV | Not supported |

Begin with the **Safe** profile. Package names vary between manufacturers, regions, and firmware versions.

## Taxis Launcher

The included launcher provides:

- A simple app screen
- Clock, date, place, and weather
- Custom backgrounds
- An idle screensaver
- Optional Home-button redirect

Taxis keeps Google TV Home enabled for reliable startup. The optional Home redirect uses Android Accessibility only to notice when Google TV Home opens and return to Taxis Launcher.

## Safety and recovery

- Apps are disabled, never deleted.
- Protected system apps are excluded from cleaning plans.
- Changes require confirmation.
- Every TV has separate recovery records.
- **Undo** restores an individual session.
- **Turn everything back on** re-enables disabled apps.
- **Rescue TV** restores recorded Home components if startup becomes stuck.
- Taxis Launcher remains installed when a session is undone.

Recovery records are stored locally under:

```text
~/.taxis/
```

Do not delete this folder if you may need Undo or Rescue TV.

## Privacy

Taxis has no accounts, advertising, analytics, or telemetry.

Desktop settings and recovery history stay on your computer. Weather features may send a city, approximate coordinates, or public IP information to Open-Meteo and the documented IP-location providers.

Read [PRIVACY.md](PRIVACY.md) for complete details.

## Run from source

Requirements:

- Python 3 with Tkinter
- Google Android Platform Tools (`adb`)

Start the graphical interface:

```text
python taxis_gui.py
```

On Windows, you can also double-click `start_gui.bat`.

## Build the Windows application

Install Python and Google Platform Tools, then run:

```powershell
.\build_windows.ps1
```

The unsigned executable is created at:

```text
outputs\Taxis.exe
```

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled software licences.

## Support the project

Taxis is free with no paid features or subscriptions.

If it helps you, an optional tip is welcome at [Buy Me a Coffee](https://buymeacoffee.com/soranagi).

## Licence

Taxis is released under the [MIT Licence](LICENSE).

Inspired by [Gathin23/cleanyourtv](https://github.com/Gathin23/cleanyourtv). No code was copied. Taxis is not affiliated with Amazon, Google, TCL, or any TV manufacturer.
