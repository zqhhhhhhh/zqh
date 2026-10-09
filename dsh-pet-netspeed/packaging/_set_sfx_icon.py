# -*- coding: utf-8 -*-
"""把源 exe 的图标资源写入 SFX 模块（纯 PE，无附加数据，安全）。

为什么改模块而不是改最终 SFX：
  最终 SFX = [PE 模块][RAR 数据]，RAR 数据位置由模块大小决定。
  直接改最终文件会让 RAR 数据偏移失配 -> 包损坏。
  先改模块，再用 -sfx<模块> 打包，RAR 会自行算好偏移。

用法: python _set_sfx_icon.py <图标源.exe> <模块.SFX> <输出.SFX>
"""
import ctypes
import os
import struct
import sys
from ctypes import wintypes

RT_ICON = 3
RT_GROUP_ICON = 14
NEW_ICON_ID_BASE = 200        # 避开模块原有 ID
KEEP_GROUP_ID = 100


# ---------------- PE 资源解析 ----------------
def rva2off(data, secs, rva):
    for name, va, vsz, praw, rsz in secs:
        if va <= rva < va + max(vsz, rsz):
            return rva - va + praw
    raise ValueError("RVA 0x%X 越界" % rva)


def parse(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\x00\x00":
        raise SystemExit("非 PE")
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    dd = pe + 24 + (96 if magic == 0x10B else 112)
    res_rva, res_sz = struct.unpack_from("<II", data, dd + 2 * 8)
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    b = pe + 24 + optsz
    secs = []
    for i in range(nsec):
        o = b + i * 40
        nm = data[o:o + 8].rstrip(b"\x00").decode("ascii", "ignore")
        vsz, va, rsz, praw = struct.unpack_from("<IIII", data, o + 8)
        secs.append((nm, va, vsz, praw, rsz))
    return secs, res_rva


def list_res(data):
    """-> {type: [(name, lang, bytes)]}"""
    secs, res_rva = parse(data)
    base = rva2off(data, secs, res_rva)
    out = {}

    def rd(off, path):
        _, _, _, _, nnamed, nid = struct.unpack_from("<IIHHHH", data, off)
        for i in range(nnamed + nid):
            eo = off + 16 + i * 8
            nm, od = struct.unpack_from("<II", data, eo)
            if od & 0x80000000:
                rd(base + (od & 0x7FFFFF), path + [nm])
            else:
                doff = base + od
                d_rva, d_sz, cp, rsv = struct.unpack_from("<IIII", data, doff)
                o = rva2off(data, secs, d_rva)
                t = path[0] if path else 0
                n = path[1] if len(path) > 1 else 0
                lg = path[2] if len(path) > 2 else 0
                out.setdefault(t, []).append((n, lg, data[o:o + d_sz]))

    rd(base, [])
    return out


# ---------------- 写资源 ----------------
def MAKEINTRESOURCE(i):
    """整型资源 ID -> 指针（lpType/lpName 均为 c_void_p，避免 LPCWSTR 转换）"""
    return ctypes.c_void_p(i)


def update_resources(path, ops):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.WORD,
                                    ctypes.c_void_p, wintypes.DWORD]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k32.EndUpdateResourceW.restype = wintypes.BOOL

    h = k32.BeginUpdateResourceW(str(path), False)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    keep = []            # 保持 buffer 引用，防止 GC
    try:
        for typ, name, lang, blob in ops:
            if blob is None:
                ptr, cb = None, 0
            else:
                b = ctypes.create_string_buffer(blob, len(blob))
                keep.append(b)
                ptr, cb = ctypes.cast(b, ctypes.c_void_p), len(blob)
            ok = k32.UpdateResourceW(h, MAKEINTRESOURCE(typ),
                                     MAKEINTRESOURCE(name), lang, ptr, cb)
            if not ok:
                e = ctypes.get_last_error()
                raise OSError(
                    "UpdateResource 失败 typ=%d name=%d lang=%d cb=%d: %s"
                    % (typ, name, lang, cb, ctypes.FormatError(e)))
    except Exception:
        k32.EndUpdateResourceW(h, True)     # discard
        raise
    if not k32.EndUpdateResourceW(h, False):
        raise ctypes.WinError(ctypes.get_last_error())


def enum_icon_res(path, types=(RT_GROUP_ICON, RT_ICON)):
    """用 Enum API 拿到精确的 (type, name, lang)。自解析 PE 易把 lang 读错。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE,
                                   wintypes.DWORD]
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    k32.FreeLibrary.restype = wintypes.BOOL
    NAMEPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE,
                                  ctypes.c_void_p, ctypes.c_void_p,
                                  wintypes.LPARAM)
    LANGPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE,
                                  ctypes.c_void_p, ctypes.c_void_p,
                                  wintypes.WORD, wintypes.LPARAM)
    k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                       NAMEPROC, wintypes.LPARAM]
    k32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                           ctypes.c_void_p, LANGPROC,
                                           wintypes.LPARAM]

    h = k32.LoadLibraryExW(str(path), None, 0x2 | 0x20)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    out = []
    keep = []
    try:
        for t in types:
            def on_name(hM, typ, name, lp, t=t):
                def on_lang(hM2, t2, n2, lang, lp2):
                    out.append((t, n2, lang))
                    return True
                cb = LANGPROC(on_lang)
                keep.append(cb)
                k32.EnumResourceLanguagesW(hM, typ, name, cb, 0)
                return True
            cb = NAMEPROC(on_name)
            keep.append(cb)
            k32.EnumResourceNamesW(h, ctypes.c_void_p(t), cb, 0)
    finally:
        k32.FreeLibrary(h)
    return out


def main():
    src, mod, dst = sys.argv[1], sys.argv[2], sys.argv[3]

    # 1) 从源 exe 取图标
    sres = list_res(open(src, "rb").read())
    grps = sres.get(RT_GROUP_ICON, [])
    if not grps:
        raise SystemExit("源无图标组")
    gname, glang, gdata = grps[0]
    icons = {n: (lg, b) for n, lg, b in sres.get(RT_ICON, [])}
    cnt = struct.unpack_from("<H", gdata, 4)[0]
    print("源图标组 %d 张 (lang=%d)" % (cnt, glang))

    # 2) 重建 group 数据：把 nID 换成新 ID
    newg = bytearray(gdata)
    for i in range(cnt):
        o = 6 + i * 14
        nid = struct.unpack_from("<H", newg, o + 12)[0]
        if nid not in icons:
            raise SystemExit("缺 RT_ICON id=%d" % nid)
        struct.pack_into("<H", newg, o + 12, NEW_ICON_ID_BASE + i)

    # 3) 目标模块现有图标资源（用 Enum 拿精确 lang）
    existing = enum_icon_res(mod)
    print("模块现有图标资源 %d 项:" % len(existing))
    ops = []
    tgt_lang = None
    for t, n, lang in existing:
        if t == RT_GROUP_ICON:
            tgt_lang = lang
        print("   type=%d name=%s lang=%d"
              % (t, n if n < 0x10000 else "str", lang))
        ops.append((t, n, lang, None))          # None = 删除
    if tgt_lang is None:
        tgt_lang = 0
    print("采用 lang=%d 写入新图标" % tgt_lang)

    # 4) 写新图标
    ops.append((RT_GROUP_ICON, KEEP_GROUP_ID, tgt_lang, bytes(newg)))
    for i in range(cnt):
        nid = struct.unpack_from("<H", gdata, 6 + i * 14 + 12)[0]
        lg, blob = icons[nid]
        ops.append((RT_ICON, NEW_ICON_ID_BASE + i, tgt_lang, blob))
    print("  写 group id=%d + %d 张 (icon id %d..%d)"
          % (KEEP_GROUP_ID, cnt, NEW_ICON_ID_BASE,
             NEW_ICON_ID_BASE + cnt - 1))

    # 5) 复制并更新
    import shutil
    shutil.copyfile(mod, dst)
    update_resources(dst, ops)
    print("写出 %s  %d -> %d B (+%d)"
          % (dst, os.path.getsize(mod), os.path.getsize(dst),
             os.path.getsize(dst) - os.path.getsize(mod)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
