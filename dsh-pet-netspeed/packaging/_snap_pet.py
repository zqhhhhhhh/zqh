# -*- coding: utf-8 -*-
"""造流量 + PrintWindow 截桌宠窗口（绕过遮挡）。用法: python _snap_pet.py <out.png> [seconds]
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from PIL import Image

u = ctypes.windll.user32
gdi = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 0x00000002


def pet_pids():
    r = subprocess.run(["tasklist", "/FI",
                        "IMAGENAME eq dsh-pet-standalone-webm.exe",
                        "/FO", "CSV", "/NH"], capture_output=True)
    out = []
    for line in r.stdout.decode("gbk", "ignore").splitlines():
        ps = [x.strip('"') for x in line.split('","')]
        if len(ps) > 1:
            try:
                out.append(int(ps[1]))
            except Exception:
                pass
    return out


def find_pet():
    pids = pet_pids()
    hw = []
    log = []

    def cb(h, l):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value in pids:
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            w, hh = r.right - r.left, r.bottom - r.top
            vis = bool(u.IsWindowVisible(h))
            log.append((h, w, hh, "VIS" if vis else "hid"))
            if (w, hh) == (320, 195):
                hw.append(h)
        return True

    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND,
                                     wintypes.LPARAM)(cb), 0)
    return pids, hw, log


def snap(hwnd, out, scale=3):
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    W, H = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mdc = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, W, H)
    gdi.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    bi = BMIH()
    bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth = W
    bi.biHeight = -H
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(W * H * 4)
    gdi.GetDIBits(mdc, bmp, 0, H, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (W, H), buf, "raw", "BGRA", 0, 1)
    img = img.resize((W * scale, H * scale), Image.LANCZOS)
    img.save(out)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)
    return "saved %s (%dx%d x%d)" % (out, W, H, scale)


def main():
    out = sys.argv[1]
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    pids, hw, log = find_pet()
    print("pids", pids, "allwins", log, "pet", hw)
    if not hw:
        return 1
    stop = [False]

    def pump():
        import urllib.request
        while not stop[0]:
            try:
                urllib.request.urlopen(
                    "https://speed.cloudflare.com/__down?bytes=8000000",
                    timeout=20).read()
            except Exception:
                pass

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    time.sleep(secs)
    print(snap(hw[0], out))
    stop[0] = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
