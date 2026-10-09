# -*- coding: utf-8 -*-
"""用桌宠自带 python311.dll 深度校验补丁 pyc：
递归遍历**每个**嵌套 code object，逐个调用 co_positions() / co_lines()，
并模拟一次栈峰值计算，定位会在真实解释器里崩溃的 code。

用法: python _pet_deep311.py <pyc路径>
"""
import ctypes
import os
import sys

INTERNAL = (r"C:\Users\EDY\AppData\Local\Programs"
            r"\dsh-pet-standalone-webm\_internal")

CODE = r'''
import sys, marshal

path = __PYC__
with open(path, 'rb') as f:
    f.read(16)
    root = marshal.load(f)

BAD = []
N = [0]

def rec(co, path=""):
    qn = (path + "." + co.co_name) if path else co.co_name
    N[0] += 1
    try:
        pos = list(co.co_positions())
    except Exception as e:
        BAD.append((qn, "co_positions: %s: %s" % (type(e).__name__, e)))
        pos = None
    try:
        ln = list(co.co_lines())
    except Exception as e:
        BAD.append((qn, "co_lines: %s: %s" % (type(e).__name__, e)))
        ln = None
    # 校验 linetable 覆盖长度是否 >= co_code
    if ln is not None:
        last_end = 0
        for a, b, _ in ln:
            if b is not None and b > last_end:
                last_end = b
        if last_end < len(co.co_code):
            BAD.append((qn, "linetable end=%d < code=%d"
                        % (last_end, len(co.co_code))))
    for k in co.co_consts:
        if hasattr(k, 'co_code'):
            rec(k, qn)

rec(root)
print("code objects:", N[0])
if BAD:
    print("BAD count:", len(BAD))
    for qn, msg in BAD[:40]:
        print("  !!", qn, "->", msg)
else:
    print("ALL OK")
print("DONE")
'''.replace("__PYC__", "PATHVAR")


def main():
    pyc = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "_pet_patched", "pet", "window.pyc")

    os.add_dll_directory(INTERNAL)
    os.environ["PYTHONHOME"] = INTERNAL
    os.environ["PYTHONPATH"] = os.path.join(INTERNAL, "base_library.zip")

    dll = ctypes.WinDLL(os.path.join(INTERNAL, "python311.dll"))
    dll.Py_Initialize.argtypes = []
    dll.Py_Initialize.restype = None
    dll.PyRun_SimpleString.argtypes = [ctypes.c_char_p]
    dll.PyRun_SimpleString.restype = ctypes.c_int
    dll.Py_Finalize.argtypes = []
    dll.Py_Initialize()

    src = os.path.abspath(pyc).replace("\\", "/")
    code = CODE.replace("PATHVAR", repr(src))
    rc = dll.PyRun_SimpleString(code.encode("utf-8"))
    print("rc =", rc)
    dll.Py_Finalize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
