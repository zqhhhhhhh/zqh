# -*- coding: utf-8 -*-
"""用 3.11 逐版本验证补丁：能 load 且 co_positions() 不崩即安全。

用法: python _pet_check311.py            # 依次测 none / show / paint
"""
import ctypes
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTERNAL = (r"C:\Users\EDY\AppData\Local\Programs"
            r"\dsh-pet-standalone-webm\_internal")
PY = sys.executable
INJ = os.path.join(HERE, "_pet_inject.py")
PATCHED = os.path.join(HERE, "_pet_patched", "pet", "window.pyc")
RUN311 = os.path.join(HERE, "_pet_run311.py")


def build(target):
    p = subprocess.run([PY, INJ, "--target=" + target],
                       capture_output=True, text=True, cwd=HERE)
    tail = (p.stdout or "").strip().splitlines()[-2:]
    return p.returncode, " | ".join(tail)


def run311(path):
    p = subprocess.run([PY, RUN311, path], capture_output=True,
                       text=True, cwd=HERE, timeout=120)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def main():
    for t in ("none", "show", "paint"):
        if os.path.exists(PATCHED):
            os.remove(PATCHED)
        rc, info = build(t)
        print("\n===== target=%-6s build rc=%d  %s" % (t, rc, info))
        if rc != 0:
            print("  构建失败")
            continue
        rc2, out = run311(PATCHED)
        print("  3.11 运行 rc=%d" % rc2)
        for line in out.strip().splitlines():
            if any(k in line for k in ("py 3.11", "loaded", "co_code",
                                       "positions", "OK", "Error",
                                       "error", "Traceback", "line ")):
                print("   ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
