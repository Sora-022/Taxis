# Third-party notices

Taxis source code is licensed under the MIT Licence in `LICENSE`.

The self-contained Windows executable includes:

- CPython, under the Python Software Foundation Licence and incorporated
  software licences. The exact `LICENSE.txt` from the bundled Python runtime is
  included inside the executable.
- PyInstaller's compiled bootloader under its Bootloader Exception, plus
  Apache-licensed runtime hooks. PyInstaller's exact `COPYING.txt` is included
  inside the executable.
- Tcl/Tk, whose `license.terms` is included automatically in the executable.
- Google Android Platform Tools (`adb.exe` and its Windows DLLs). Google's
  complete `NOTICE.txt` is included inside the executable.

Pillow is used only while building the Windows icon and is not bundled as an
imported runtime library.

Taxis Launcher displays weather data supplied by
[Open-Meteo.com](https://open-meteo.com/) under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Taxis converts
weather codes into short labels and rounds temperatures for display.

The TV-and-broom artwork is an original Taxis concept generated with Claude at
the project owner's request. It was not copied from another application or
artist.
