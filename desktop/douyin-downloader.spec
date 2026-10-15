# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Douyin Downloader desktop bundle.

Build (Windows, from the repo root):

    pyinstaller desktop/douyin-downloader.spec --noconfirm

Requires before building:
  * signer dependencies installed:  cd signer && npm install --omit=dev
  * signer SDK files downloaded:    cd signer && node fetch-sdk.js
  * Node runtime placed in ./node/  (node.exe, version must match the .jsc
    build — Node 20.19.x)
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(os.getcwd()))

datas = [
    (os.path.join(ROOT, "app", "static"), "app/static"),
    (os.path.join(ROOT, "signer", "signer.js"), "signer"),
    (os.path.join(ROOT, "signer", "package.json"), "signer"),
    (os.path.join(ROOT, "signer", "dist"), "signer/dist"),
    (os.path.join(ROOT, "signer", "sdk"), "signer/sdk"),
    (os.path.join(ROOT, "signer", "node_modules"), "signer/node_modules"),
]

node_dir = os.path.join(ROOT, "node")
if os.path.isdir(node_dir):
    datas.append((node_dir, "node"))

binaries = []
hiddenimports = []

for package in ("uvicorn", "fastapi", "starlette", "anyio", "httpx", "yt_dlp", "curl_cffi"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

hiddenimports += [
    "app",
    "app.main",
    "app.douyin",
    "app.extractor",
    "app.downloader",
    "app.http_safe",
    "app.security",
    "app.cookies",
    "app.signer_client",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "desktop", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="douyin-downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
