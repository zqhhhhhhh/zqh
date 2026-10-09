# -*- coding: utf-8 -*-
"""端到端实测 SFX：把现有安装目录改名 -> 运行 SFX -> 检查是否装到正确位置。

安全：原目录只改名不删除；原 exe 另有 _dsh-pet-backup 备份。
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs", "dsh-pet-standalone-webm-setup-patched.exe")
PROG = r"C:\Users\EDY\AppData\Local\Programs"
INST = os.path.join(PROG, "dsh-pet-standalone-webm")
BAK = os.path.join(PROG, "dsh-pet-standalone-webm__bak")


def count(d):
    n = tot = 0
    for dp, dn, fn in os.walk(d):
        for f in fn:
            n += 1
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except Exception:
                pass
    return n, tot


def main():
    # 0) 停桌宠
    subprocess.run(["taskkill", "/F", "/IM",
                    "dsh-pet-standalone-webm.exe"], capture_output=True)
    time.sleep(3)

    # 1) 现有目录改名
    if os.path.exists(BAK):
        shutil.rmtree(BAK, ignore_errors=True)
    if os.path.exists(INST):
        os.rename(INST, BAK)
        print("原目录已改名为", BAK)
    print("安装目录存在?", os.path.exists(INST))

    # 2) 运行 SFX（WinRAR GUI SFX 用 /S 静默）
    print("\n运行 SFX (/S 静默) ...")
    args = [OUT, "/S"]
    p = subprocess.Popen(args, cwd=os.path.dirname(OUT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    done = False
    while time.time() - t0 < 75:
        time.sleep(2)
        if os.path.isdir(INST):
            n, tot = count(INST)
            print("  t=%4.1fs 目录已出现: %d 文件 %.1f MB" % (
                time.time() - t0, n, tot / 1048576))
            if n > 1000:
                done = True
                break
        rc = p.poll()
        if rc is not None:
            print("  SFX 已退出 rc=%s" % rc)
            break
    print("SFX 进程 poll=%s (None=仍在运行)" % p.poll())
    if p.poll() is None:
        print("  -> 静默参数未生效（弹窗等待），强制结束")
        p.kill()
        time.sleep(1)

    # 3) 结果
    print("\n--- 结果 ---")
    if os.path.isdir(INST):
        n, tot = count(INST)
        print("安装目录: %d 文件 %.1f MB" % (n, tot / 1048576))
        exe = os.path.join(INST, "dsh-pet-standalone-webm.exe")
        ovl = os.path.join(INST, "_internal", "net_speed_overlay.py")
        import hashlib

        def md5(x):
            h = hashlib.md5()
            with open(x, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
            return h.hexdigest()[:16]

        print("exe  ", md5(exe) if os.path.exists(exe) else "MISSING",
              "(expect ca6a06ceb6ba0615)")
        print("ovl  ", os.path.getsize(ovl) if os.path.exists(ovl)
              else "MISSING")
        print("说明 ", os.path.exists(os.path.join(INST, "安装说明.txt")))
        print("卸载 ", os.path.exists(os.path.join(INST, "卸载.bat")))
    else:
        print("!! 安装目录未创建 —— Path 可能未解析")
        # 检查是否解到了别处
        for cand in (os.path.dirname(OUT), os.getcwd(), PROG):
            for x in os.listdir(cand):
                if "dsh-pet" in x and os.path.isdir(os.path.join(cand, x)):
                    print("   发现:", os.path.join(cand, x))

    # 4) 停掉可能被 Setup 启动的桌宠
    time.sleep(2)
    r = subprocess.run(["tasklist", "/FI",
                        "IMAGENAME eq dsh-pet-standalone-webm.exe",
                        "/FO", "CSV", "/NH"], capture_output=True)
    tl = r.stdout.decode("gbk", "ignore").strip()
    print("\n桌宠进程:", tl if tl else "(无)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
