# PyInstaller spec — build with:  build.bat
# Produces a single self-contained dist\FFmpegStudio518-<version>.exe
# (onefile, windowed). The version is read from the package so the exe name
# always matches the build.

import re
import pathlib
import sys

_init = pathlib.Path("ffmpeg_studio/__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)

# Windows takes the .ico; ELF binaries carry no icon, and handing PyInstaller
# an .ico there just makes it complain — the AppImage uses icon.png instead.
ICON = 'ffmpeg_studio/assets/icon.ico' if sys.platform == 'win32' else None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ffmpeg_studio/assets', 'ffmpeg_studio/assets'),
    ],
    hiddenimports=[],
    excludes=['tkinter'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name=f'FFmpegStudio518-{VERSION}',
    icon=ICON,
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
