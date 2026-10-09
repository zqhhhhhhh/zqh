# -*- coding: utf-8 -*-
"""把补丁后的 pet.window 写回桌宠 exe 的 PYZ。

策略：
  1. 解析 exe 定位 PYZ
  2. 读 TOC（marshal），取出各模块原始（压缩）字节
  3. 用新 window.pyc 的 zlib 压缩替换对应项
  4. 重新计算所有 offset，重新 marshal TOC
  5. 重组 PYZ 字节，更新 exe 的 cookie（toc_len / toc_off 等）

exe 结构（PyInstaller 6.x onedir）：
  [PE 引导段][PKG...][PYZ...][cookie 88B]
cookie = MEI(8) + pkg_len(4) + toc_off(4) + toc_len(4) + pyver(4) + pylib(64)
其中 toc_off 相对 PKG 起点，PYZ 是 PKG 的一部分（作为 CArchive 的一项，
其数据就地存放）。实测本包 PKG 内只有 PYZ 一项，且 PYZ 紧邻文件尾之前。
"""
import marshal
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pet_marshal import Marsh311  # noqa

EXE = (r"C:\Users\EDY\AppData\Local\Programs"
       r"\_dsh-pet-backup\dsh-pet-standalone-webm.exe")
NEW_WINDOW = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_pet_patched", "pet", "window.pyc")
PYZM = b"PYZ\x00"
MEI = b"MEI\x0c\x0b\x0a\x0b\x0e"


def locate(data):
    pyz = data.find(PYZM)
    if pyz < 0:
        raise SystemExit("PYZ 未找到")
    toc_pos = struct.unpack_from("!I", data, pyz + 8)[0]
    toc = marshal.loads(data[pyz + toc_pos:])
    return pyz, toc_pos, toc


def rebuild_pyz(data, pyz, toc, repl):
    """repl: {module_name: new_raw_bytes(未压缩)}；返回新 PYZ 字节。"""
    # 解出每个模块的原始（压缩态）数据
    blobs = {}
    for name, (typ, off, clen) in toc:
        blobs[name] = bytes(data[pyz + off:pyz + off + clen])

    # 替换
    for name, raw in repl.items():
        if name not in blobs:
            raise SystemExit(f"TOC 无模块 {name}")
        blobs[name] = zlib.compress(raw, 9)

    # 重排：按原 TOC 顺序
    new_toc = []
    body = bytearray()
    head = 12                     # PYZ magic(4) + pyc_magic(4) + toc_pos(4)
    for name, (typ, off, clen) in toc:
        b = blobs[name]
        new_toc.append((name, (typ, head + len(body), len(b))))
        body += b
    toc_pos = head + len(body)
    toc_bytes = marshal.dumps(new_toc)      # 标准 marshal 足够（纯 str/tuple/int）

    out = bytearray()
    out += PYZM
    out += data[pyz + 4:pyz + 8]            # pyc magic 原样
    out += struct.pack("!I", toc_pos)
    out += body
    out += toc_bytes
    return bytes(out), new_toc


def main():
    data = open(EXE, "rb").read()
    pyz, toc_pos, toc = locate(data)
    print("PYZ @", pyz, "  TOC 项数", len(toc))
    # PYZ 区段 = magic..TOC 末尾（TOC 之后还有 CArchive 项表，不属 PYZ）
    toc_bytes_len = len(marshal.dumps(toc))
    pyz_end = pyz + toc_pos + toc_bytes_len
    print("PYZ 区段:", pyz, "..", pyz_end, " 长度", pyz_end - pyz,
          " (TOC", toc_bytes_len, "字节)")

    win = [t for t in toc if t[0] == "pet.window"]
    print("pet.window 项:", win[0] if win else None)

    raw = open(NEW_WINDOW, "rb").read()
    payload = raw[16:]
    print("新 window 载荷:", len(payload), "字节")

    new_pyz, new_toc = rebuild_pyz(data, pyz, toc, {"pet.window": payload})
    print("新 PYZ:", len(new_pyz), "字节")

    # ---- 关键：padding 到原始长度，保持 exe 内所有偏移不变 ----
    orig_len = pyz_end - pyz
    if len(new_pyz) < orig_len:
        pad = orig_len - len(new_pyz)
        new_pyz = new_pyz + b"\x00" * pad
        print("补零", pad, "字节 ->", len(new_pyz))
    elif len(new_pyz) > orig_len:
        raise SystemExit(f"新 PYZ 超出 {len(new_pyz) - orig_len} 字节，"
                         "需整体重排（当前不支持）")

    out = bytearray(data)
    out[pyz:pyz_end] = new_pyz
    print("新 exe:", len(out), "字节 (原", len(data), ") 偏移保持不变")

    # ---- 关键：同步更新 CArchive 里 PYZ.pyz 项的压缩长度 ----
    # CArchive TOC 项（就在 cookie 之前）：
    #   [slen(4)][pos(4)][clen(4)][ulen(4)][flag(1)][typecode(1)][name(NUL 结尾)]
    marker = b"PYZ.pyz\x00"
    mi = data.find(marker)
    if mi < 0:
        raise SystemExit("未找到 CArchive 的 PYZ.pyz 项")
    # 项体起点：name 之前是 typecode(1)+flag(1)，再往前是 ulen/clen/pos
    name_off = mi
    tc_off = name_off - 1
    flag_off = tc_off - 1
    ulen_off = flag_off - 4
    clen_off = ulen_off - 4
    old_clen = struct.unpack_from("!I", data, clen_off)[0]
    old_ulen = struct.unpack_from("!I", data, ulen_off)[0]
    print("CArchive PYZ.pyz: clen %d -> %d" % (old_clen, len(new_pyz)))
    if old_clen != (pyz_end - pyz):
        print("  !! 警告：clen(%d) 与推算 PYZ 长度(%d) 不一致"
              % (old_clen, pyz_end - pyz))
    struct.pack_into("!I", out, clen_off, len(new_pyz))
    struct.pack_into("!I", out, ulen_off, len(new_pyz))
    print("  已同步 clen/ulen")

    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_pet_patched", "dsh-pet-standalone-webm.exe")
    open(dst, "wb").write(bytes(out))
    print("写出:", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
