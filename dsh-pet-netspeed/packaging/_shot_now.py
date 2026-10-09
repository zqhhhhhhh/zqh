# -*- coding: utf-8 -*-
"""只验证：造流量 + 截图当前运行的桌宠（不部署、不改文件）。"""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _snap_pet as S  # noqa: E402

out = sys.argv[1]


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


d = json.load(urllib.request.urlopen("https://pypi.org/pypi/numpy/json",
                                     timeout=10))
FURL = max(d["urls"], key=lambda x: x["size"])["url"]
stop = [False]


def pump():
    while not stop[0]:
        try:
            r = urllib.request.urlopen(FURL, timeout=20)
            while not stop[0]:
                if not r.read(1 << 20):
                    break
        except Exception:
            time.sleep(0.3)


pids, hw, log = S.find_pet()
if not hw:
    import subprocess
    INST = r"C:\Users\EDY\AppData\Local\Programs\dsh-pet-standalone-webm"
    print("桌宠未运行，启动之 ...")
    subprocess.Popen([os.path.join(INST, "dsh-pet-standalone-webm.exe")],
                     cwd=INST, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    time.sleep(9)
    pids, hw, log = S.find_pet()
print("pids=%s pet=%s" % (pids, hw))
if not hw:
    print("!! 桌宠未运行")
    sys.exit(1)

inst = r"C:\Users\EDY\AppData\Local\Programs\dsh-pet-standalone-webm"
print("exe md5 =", md5(os.path.join(inst, "dsh-pet-standalone-webm.exe")),
      "(expect ca6a06ceb6ba0615)")

threading.Thread(target=pump, daemon=True).start()
time.sleep(9)
print(S.snap(hw[0], out))
stop[0] = True
time.sleep(13)
pids, hw2, log2 = S.find_pet()
print("idle overlay(h=15) =", [x for x in log2 if x[2] == 15])
