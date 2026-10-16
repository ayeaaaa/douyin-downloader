#!/usr/bin/env python3
"""Consistency check: Android CDN whitelist must match app/security.py.

The standalone LocalServer proxies media only for hosts the server version
also allows; divergence silently breaks downloads for some payloads.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

security = (ROOT / "app" / "security.py").read_text(encoding="utf-8")
match = re.search(r"ALLOWED_MEDIA_SUFFIXES\s*=\s*\((.*?)\)", security, re.S)
if not match:
    print("FAIL cannot find ALLOWED_MEDIA_SUFFIXES in app/security.py")
    sys.exit(1)
server_list = re.findall(r'"([^"]+)"', match.group(1))

kotlin = (
    ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "ayeaaaa"
    / "dydl"
    / "LocalServer.kt"
).read_text(encoding="utf-8")
match = re.search(r"ALLOWED_MEDIA_SUFFIXES\s*=\s*listOf\((.*?)\)", kotlin, re.S)
if not match:
    print("FAIL cannot find ALLOWED_MEDIA_SUFFIXES in LocalServer.kt")
    sys.exit(1)
android_list = re.findall(r'"([^"]+)"', match.group(1))

if server_list != android_list:
    print("FAIL whitelist divergence")
    print("  server :", server_list)
    print("  android:", android_list)
    sys.exit(1)
print(f"whitelist OK ({len(server_list)} suffixes)")
