# Taxis privacy notice

Taxis has no user accounts, advertising, analytics or telemetry. The Taxis
developer does not operate a server and does not receive your TV information.

## Information stored locally

The Windows application stores preferences, device details, recovery snapshots
and action logs under `~/.taxis/` on your computer. Taxis Launcher stores its
selected city, approximate coordinates, weather cache and background settings
inside the launcher's private storage on the TV.

## Online requests

Taxis Launcher retrieves local weather when it starts and periodically while it
is running:

- If you enter a city, the city is sent to Open-Meteo's geocoding service.
- Otherwise, the launcher first uses the TV's last known approximate location.
- If the TV has no location, it requests approximate IP location from
  `ipwho.is`, with `ipapi.co` as a fallback. These services necessarily see the
  TV's public IP address.
- Coordinates are sent to Open-Meteo to retrieve current weather.

Open-Meteo may retain API logs containing IP addresses and coordinates as
described in its privacy policy. The IP-location providers process requests
under their own privacy policies and terms.

The optional “Download from GitHub” launcher source contacts GitHub only when
you choose a listed third-party launcher. The included Taxis Launcher does not
require that download.

## Accessibility

The optional Taxis Home accessibility service watches only for Google TV Home
becoming the active package. It cannot retrieve window content, read text or
record remote input. Disabling “Home opens Taxis” turns the service off.

## Your choices

Entering a city avoids IP-based location but still sends the city and resulting
coordinates to Open-Meteo. Removing Taxis Launcher deletes its private settings.
Removing `~/.taxis/` deletes the desktop application's local history, but also
removes its saved recovery information.

Service policies:

- Open-Meteo: <https://open-meteo.com/en/terms>
- IPWhois: <https://ipwhois.io/privacy>
- ipapi: <https://ipapi.co/privacy/>
- GitHub: <https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement>

Last updated: 15 November 2026.
