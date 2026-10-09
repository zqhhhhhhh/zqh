# -*- coding: utf-8 -*-
"""把补丁 exe + overlay 部署到安装目录，启动并验证（截图 + 隐藏行为）。

用法: python _apply_patch.py [out.png]
"""
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _snap_pet as S  # noqa: E402

INST = r"C:\Users\EDY\AppData\Local\Programs\dsh-pet-standalone-webm"
EXE = os.path.join(INST, "dsh-pet-standalone-webm.exe")
OVL = os.path.join(INST, "_internal", "net_speed_overlay.py")
PATCHED = os.path.join(HERE, "_pet_patched", "dsh-pet-standalone-webm.exe")
OVLSRC = os.path.join(HERE, "net_speed_overlay.py")
BKP = r"C:\Users\EDY\AppData\Local\Programs\_dsh-pet-backup\dsh-pet-standalone-webm.exe"
LOGP = os.path.join(os.environ.get("LOCALAPPDATA", "."),
                    "dsh-pet-standalone-webm", "nso-final.log")

out = sys.argv[1] if len(sys.argv) > 1 else None


def md5(p):
    import hashlib
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


# ---- 0) 先停掉运行中的桌宠（否则 exe 被锁）----
subprocess.run(["taskkill", "/F", "/IM",
                "dsh-pet-standalone-webm.exe"], capture_output=True)
time.sleep(3)

# ---- 0b) 把当前 exe 备份（若还是原版则跳过）----
cur = md5(EXE)
if cur != md5(BKP):
    print("当前 exe 非原版(=%s)，另存为 .prev" % cur)
    shutil.copyfile(EXE, EXE + ".prev")

# ---- 1) 部署 ----
shutil.copyfile(PATCHED, EXE)
shutil.copyfile(OVLSRC, OVL)
print("部署 exe  md5=%s  size=%d" % (md5(EXE), os.path.getsize(EXE)))
print("部署 ovl  %d B" % os.path.getsize(OVL))

# ---- 2) 启动 ----
if os.path.exists(LOGP):
    os.remove(LOGP)
p = subprocess.Popen([EXE], cwd=INST, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
print("pid", p.pid)
time.sleep(7)

stage = []


def snap(tag, logfile):
    pids, hw, log = S.find_pet()
    print("  [%s] pids=%s wins=%s" % (tag, pids, log))
    if hw and out:
        f = out if tag == "flow" else out.replace(".png", "_%s.png" % tag)
        print("  ", S.snap(hw[0], f))
    return hw


hw = snap("boot", None)

# ---- 3) 造流量（PyPI，已验证 3MB/s 可达；Cloudflare/镜像站均 403）----
def flood_url():
    import json
    import urllib.request as U
    d = json.load(U.urlopen("https://pypi.org/pypi/numpy/json", timeout=10))
    return max(d["urls"], key=lambda x: x["size"])["url"]


try:
    FURL = flood_url()
    print("flood url:", FURL[:90])
except Exception as e:
    FURL = None
    print("!! 无法取得流量源:", e)

stop = [False]


def pump():
    import urllib.request as U
    while not stop[0]:
        if not FURL:
            time.sleep(0.5)
            continue
        try:
            r = U.urlopen(FURL, timeout=20)
            while not stop[0]:
                if not r.read(1 << 20):
                    break
        except Exception:
            time.sleep(0.3)


threading.Thread(target=pump, daemon=True).start()
time.sleep(10)
snap("flow", None)
stop[0] = True

# ---- 4) 静默后应隐藏 ----
time.sleep(14)
pids, hw2, log2 = S.find_pet()
ov = [x for x in log2 if x[2] == 15]
print("  [idle] overlay(h=15)=%s" % ov)

# ---- 5) 日志 ----
if os.path.exists(LOGP):
    print("LOG:", open(LOGP, encoding="utf-8").read().strip() or "(empty)")
else:
    print("LOG: clean")

p.terminate()
