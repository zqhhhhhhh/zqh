# -*- coding: utf-8 -*-
"""组装待打包目录 _pkg/（补丁 exe + _internal + 卸载器 + 说明）。"""
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r"C:\Users\EDY\AppData\Local\Programs\dsh-pet-standalone-webm"
PKG = os.path.join(HERE, "_pkg")

SKIP_NAMES = {
    "dsh-pet-standalone-webm.exe.prev",
}
SKIP_EXT = {".prev", ".log", ".tmp"}


def ignore(dirpath, names):
    out = []
    for n in names:
        if n in SKIP_NAMES:
            out.append(n)
            continue
        if os.path.splitext(n)[1].lower() in SKIP_EXT:
            out.append(n)
    return out


def main():
    if os.path.exists(PKG):
        shutil.rmtree(PKG)
    os.makedirs(PKG)

    for item in os.listdir(SRC):
        s = os.path.join(SRC, item)
        d = os.path.join(PKG, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=ignore)
        else:
            if item in SKIP_NAMES:
                continue
            if os.path.splitext(item)[1].lower() in SKIP_EXT:
                continue
            shutil.copy2(s, d)

    # 写入说明
    readme = """DshPet 桌宠 —— 带「脚底网速显示」补丁版
=========================================

版本   : 基于官方 4.2.1（作者 merzlin）
补丁   : 人物脚底显示实时 上行/下行 速率
作者   : 本补丁由本地注入生成

【安装】
  关闭正在运行的桌宠（托盘图标右键 → 退出），再运行本安装包。
  安装目录：%LOCALAPPDATA%\\Programs\\dsh-pet-standalone-webm

【网速显示说明】
  - 显示条件：下载速率 > 30 KB/s 才出现（低于阈值自动隐藏）
  - 格式    ：↑ 上行  ↓ 下行，单位自动 B/KB/MB/GB
  - 位置    ：紧贴人物脚底下方
  - 颜色    ：上行=琥珀，下行=蓝

【调参】
  编辑  _internal\\net_speed_overlay.py  顶部参数区，重启桌宠生效：
    MIN_SHOW_BPS   显示阈值（字节/秒）
    FONT_PT        字号
    GAP_BELOW_FOOT 与脚部的缝隙
    COL_UP/COL_DOWN 上下行颜色

【卸载】
  运行目录下的  卸载.bat  ，或从「设置 → 应用」卸载 DshPet，
  再手动删除  _internal\\net_speed_overlay.py  即可。

【注意】
  本程序未签名，Windows SmartScreen 可能拦截：
  点「更多信息」→「仍要运行」。
"""
    with open(os.path.join(PKG, "安装说明.txt"), "w",
              encoding="utf-8-sig") as f:
        f.write(readme)

    # 卸载脚本
    uninst = r"""@echo off
chcp 65001 >nul
title DshPet 卸载
echo.
echo   正在卸载 DshPet（补丁版）...
echo.

taskkill /F /IM dsh-pet-standalone-webm.exe >nul 2>&1
timeout /t 2 /nobreak >nul

set "TARGET=%~dp0"
if /I not "%TARGET:~-1%"=="\" set "TARGET=%TARGET%\"

echo   删除程序目录: %TARGET%
cd /d "%TEMP%"
rmdir /S /Q "%TARGET%" 2>nul

echo   清理开机自启项...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v dsh-pet-standalone-webm /f >nul 2>&1

echo.
echo   已删除程序。用户配置保留在:
echo     %APPDATA%\dsh-pet-standalone-webm
echo   （如需彻底清理，请手动删除该文件夹）
echo.
pause
"""
    with open(os.path.join(PKG, "卸载.bat"), "w",
              encoding="utf-8") as f:
        f.write(uninst)

    tot = n = 0
    for dp, dn, fn in os.walk(PKG):
        for f in fn:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
                n += 1
            except Exception:
                pass
    print("_pkg 组装完成: %d 文件, %.1f MB" % (n, tot / 1048576))
    exe = os.path.join(PKG, "dsh-pet-standalone-webm.exe")
    ovl = os.path.join(PKG, "_internal", "net_speed_overlay.py")
    import hashlib

    def md5(p):
        h = hashlib.md5()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()[:16]

    print("  exe   %s  %d B" % (md5(exe), os.path.getsize(exe)))
    print("  ovl   %d B" % os.path.getsize(ovl))
    print("  说明  %s" % os.path.exists(os.path.join(PKG, "安装说明.txt")))
    print("  卸载  %s" % os.path.exists(os.path.join(PKG, "卸载.bat")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
