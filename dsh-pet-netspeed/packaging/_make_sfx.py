# -*- coding: utf-8 -*-
"""用 WinRAR 生成自解压安装包（SFX）。

产物：outputs/dsh-pet-standalone-webm-setup-patched.exe
行为：双击 -> 解压到 %LOCALAPPDATA%\\Programs\\dsh-pet-standalone-webm -> 自动启动桌宠
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "_pkg")
OUTDIR = os.path.join(HERE, "outputs")
OUT = os.path.join(OUTDIR, "dsh-pet-standalone-webm-setup-patched.exe")
COMMENT = os.path.join(HERE, "_sfx_comment.txt")
RAR = r"C:\Program Files\WinRAR\Rar.exe"
ICO = os.path.join(HERE, "_icon_setup.ico")   # 由 _extract_icon.py 从原安装包提取
SFXMOD = os.path.join(HERE, "_sfx64_custom.SFX")  # 由 _set_sfx_icon.py 换上原图标

SFX_SCRIPT = """;DshPet standalone (WebM) - 脚底网速补丁版
;由本地注入生成，基于官方 4.2.1

Path=%LOCALAPPDATA%\\Programs\\dsh-pet-standalone-webm
Setup=dsh-pet-standalone-webm.exe
Overwrite=1
"""


def main():
    if not os.path.isdir(PKG):
        print("!! _pkg 不存在，先跑 _build_pkg.py")
        return 1
    os.makedirs(OUTDIR, exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    with open(COMMENT, "w", encoding="utf-8") as f:
        f.write(SFX_SCRIPT)
    print("SFX 脚本:")
    print(SFX_SCRIPT)

    cmd = [
        RAR, "a",
        "-r",                  # 递归
        "-m5",                 # 最高压缩
        "-s",                  # 固实压缩
        "-ep1",                # 不含基础目录
        "-sfx" + SFXMOD,       # 自定义 SFX 模块（已换上原安装包图标）
        "-z" + COMMENT,        # 注释（= SFX 脚本）
        OUT,
        os.path.join(PKG, "*"),
    ]
    print("命令:", " ".join('"%s"' % c if " " in c else c for c in cmd))
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True)
    dt = time.time() - t0
    out = r.stdout.decode("gbk", "ignore")
    err = r.stderr.decode("gbk", "ignore")
    tail = [x for x in out.splitlines() if x.strip()][-8:]
    print("\n".join(tail))
    if err.strip():
        print("STDERR:", err.strip()[-500:])
    print("耗时 %.1fs  rc=%d" % (dt, r.returncode))

    if os.path.exists(OUT):
        print("产物: %s  %.1f MB" % (OUT, os.path.getsize(OUT) / 1048576))
    else:
        print("!! 未生成")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
