# -*- mode: python ; coding: utf-8 -*-
import importlib.metadata as metadata
import os
import sys
from pathlib import Path

project_root = Path(SPECPATH)
adb_dir = Path(os.environ["TAXIS_ADB_DIR"])
python_license = Path(sys.base_prefix) / "LICENSE.txt"
pyinstaller_dist = metadata.distribution("pyinstaller")
pyinstaller_license_entry = next(
    entry for entry in pyinstaller_dist.files
    if entry.name == "COPYING.txt" and "licenses" in entry.parts
)
pyinstaller_license = Path(pyinstaller_dist.locate_file(pyinstaller_license_entry))
platform_tools = [
    (str(adb_dir / name), "platform-tools")
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
]

analysis = Analysis(
    ["taxis_gui.py"],
    pathex=[str(project_root)],
    binaries=platform_tools,
    datas=[
        (str(project_root / "profiles"), "profiles"),
        (str(project_root / "launcher" / "taxis-launcher.apk"), "launcher"),
        (str(adb_dir / "NOTICE.txt"), "licenses"),
        (str(project_root / "LICENSE"), "licenses/taxis"),
        (str(project_root / "PRIVACY.md"), "licenses/taxis"),
        (str(project_root / "THIRD_PARTY_NOTICES.md"), "licenses/taxis"),
        (str(python_license), "licenses/python"),
        (str(pyinstaller_license), "licenses/pyinstaller"),
        (
            str(project_root / "launcher" / "res" / "drawable" / "ic_launcher.png"),
            "launcher/res/drawable",
        ),
    ],
    hiddenimports=[],
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="Taxis",
    icon=str(project_root / "launcher" / "res" / "drawable" / "ic_launcher.png"),
    console=False,
    onefile=True,
)
