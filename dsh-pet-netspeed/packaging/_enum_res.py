# -*- coding: utf-8 -*-
"""用 Enum API 枚举 PE 资源（type / name / lang），避免自解析 PE 的偏差。"""
import ctypes
import sys
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
k32.LoadLibraryExW.restype = wintypes.HMODULE

LOAD_LIBRARY_AS_DATAFILE = 0x00000002
LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x00000020

ENUMRESNAMEPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE,
                                     ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.LPARAM)
ENUMRESLANGPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE,
                                     ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.WORD, wintypes.LPARAM)

k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                   ENUMRESNAMEPROC, wintypes.LPARAM]
k32.EnumResourceNamesW.restype = wintypes.BOOL
k32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p,
                                       ctypes.c_void_p, ENUMRESLANGPROC,
                                       wintypes.LPARAM]
k32.EnumResourceLanguagesW.restype = wintypes.BOOL


def kind(v):
    """v: 回调给的值。整数 ID 很小；字符串名是大指针。"""
    if v is None:
        return "None"
    if v < 0x10000:
        return "id=%d" % v
    try:
        return "str=%r" % ctypes.cast(v, wintypes.LPCWSTR).value
    except Exception:
        return "ptr=0x%X" % v


def main():
    path = sys.argv[1]
    h = k32.LoadLibraryExW(path, None,
                           LOAD_LIBRARY_AS_DATAFILE |
                           LOAD_LIBRARY_AS_IMAGE_RESOURCE)
    if not h:
        raise SystemExit("LoadLibraryEx 失败: %s"
                         % ctypes.FormatError(ctypes.get_last_error()))
    print("模块已加载 h=0x%X  %s" % (h or 0, path))

    found = []

    def on_name(hM, typ, name, lp):
        langs = []

        def on_lang(hM2, t2, n2, lang, lp2):
            langs.append(lang)
            return True

        k32.EnumResourceLanguagesW(hM, typ, name, ENUMRESLANGPROC(on_lang), 0)
        ti = typ if (typ or 0) < 0x10000 else -1
        ni = name if (name or 0) < 0x10000 else -1
        found.append((ti, ni, sorted(langs)))
        return True

    k32.EnumResourceNamesW(h, ctypes.c_void_p(14),
                           ENUMRESNAMEPROC(on_name), 0)   # RT_GROUP_ICON
    print("\nRT_GROUP_ICON(14):")
    for t, n, langs in found:
        print("  name=%s langs=%s" % (kind(n), langs))

    found2 = []

    def on_name2(hM, typ, name, lp):
        langs = []

        def on_lang(hM2, t2, n2, lang, lp2):
            langs.append(lang)
            return True

        k32.EnumResourceLanguagesW(hM, typ, name, ENUMRESLANGPROC(on_lang), 0)
        ni = name if (name or 0) < 0x10000 else -1
        found2.append((ni, sorted(langs)))
        return True

    k32.EnumResourceNamesW(h, ctypes.c_void_p(3),
                           ENUMRESNAMEPROC(on_name2), 0)   # RT_ICON
    print("\nRT_ICON(3): %d 个" % len(found2))
    for n, langs in found2:
        print("  name=%s langs=%s" % (kind(n), langs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
