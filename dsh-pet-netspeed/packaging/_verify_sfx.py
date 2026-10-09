# -*- coding: utf-8 -*-
"""验证 SFX 安装包：解压到临时目录，比对关键文件。"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs", "dsh-pet-standalone-webm-setup-patched.exe")
UNRAR = r"C:\Program Files\WinRAR\UnRAR.exe"


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def main():
    # 1) PE 头
    with open(OUT, "rb") as f:
        head = f.read(2)
    print("PE 头:", head, "(expect b'MZ')")
    print("大小 : %.1f MB" % (os.path.getsize(OUT) / 1048576))

    # 2) 解压到临时目录
    tmp = os.path.join(tempfile.gettempdir(), "_sfx_verify")
    if os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    print("\n解压到", tmp)
    r = subprocess.run([UNRAR, "x", "-o+", "-idq", OUT, tmp + os.sep],
                       capture_output=True)
    print("rc=%d" % r.returncode)
    msg = (r.stdout + r.stderr).decode("gbk", "ignore").strip()
    if msg:
        print(msg[-400:])

    # 3) 关键文件比对
    pairs = [
        ("dsh-pet-standalone-webm.exe",
         os.path.join(HERE, "_pkg", "dsh-pet-standalone-webm.exe")),
        (os.path.join("_internal", "net_speed_overlay.py"),
         os.path.join(HERE, "_pkg", "_internal", "net_speed_overlay.py")),
        ("安装说明.txt", os.path.join(HERE, "_pkg", "安装说明.txt")),
        ("卸载.bat", os.path.join(HERE, "_pkg", "卸载.bat")),
    ]
    allok = True
    print("\n--- 关键文件 ---")
    for rel, ref in pairs:
        got = os.path.join(tmp, rel)
        if not os.path.exists(got):
            print("  MISSING %s" % rel)
            allok = False
            continue
        a, b = md5(got), md5(ref)
        ok = a == b
        allok &= ok
        print("  %-42s %s %s%s" % (rel, a, "==" if ok else "!=", b))
        # 额外：确认 overlay 阈值
        if rel.endswith("net_speed_overlay.py"):
            for line in open(got, encoding="utf-8"):
                if "MIN_SHOW_BPS =" in line:
                    print("      -> %s" % line.strip())

    # 4) 文件总数
    n = tot = 0
    for dp, dn, fn in os.walk(tmp):
        for f in fn:
            n += 1
            tot += os.path.getsize(os.path.join(dp, f))
    print("\n解压后: %d 文件 %.1f MB" % (n, tot / 1048576))
    print("结论:", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
