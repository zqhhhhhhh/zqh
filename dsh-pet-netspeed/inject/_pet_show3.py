# -*- coding: utf-8 -*-
"""用 xdis.unmarshal 正确解析 3.11 pyc，反汇编注入区域。

用法: python _pet_show3.py [method] [around] [window] [pyc]
"""
import os
import sys

import xdis.unmarshal as U
from xdis.op_imports import get_opcode_module

HERE = os.path.dirname(os.path.abspath(__file__))
OPC = get_opcode_module((3, 11), "CPython")
NAMES = list(OPC.opname)
names_len = len(NAMES)


def opname(op):
    if 0 <= op < names_len:
        return NAMES[op]
    return "?%02x" % op

# CPython 3.11 _PyOpcode_Caches
CACHE = {
    "BINARY_SUBSCR": 4, "STORE_SUBSCR": 1, "UNPACK_SEQUENCE": 1,
    "STORE_ATTR": 4, "LOAD_ATTR": 4, "COMPARE_OP": 2,
    "LOAD_GLOBAL": 5, "BINARY_OP": 1, "LOAD_METHOD": 10,
    "PRECALL": 1, "CALL": 4,
}


def disasm(body):
    out = []
    i = 0
    ext = 0
    ext_at = None
    while i < len(body):
        op = body[i]
        arg = body[i + 1] if i + 1 < len(body) else 0
        nm = opname(op)
        if nm == "EXTENDED_ARG":
            ext = (ext << 8) | arg
            if ext_at is None:
                ext_at = i
            i += 2
            continue
        full = (ext << 8) | arg if ext else arg
        out.append((ext_at if ext_at is not None else i, nm, full))
        ext = 0
        ext_at = None
        i += 2 + CACHE.get(nm, 0) * 2
    return out


def walk(root, parent="", depth=0):
    qn = parent + "." + root.co_name if parent else root.co_name
    yield qn, root
    for k in root.co_consts:
        if hasattr(k, "co_code"):
            yield from walk(k, qn, depth + 1)


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "showEvent"
    around = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    win = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    pyc = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
        HERE, "_pet_patched", "pet", "window.pyc")
    raw = open(pyc, "rb").read()
    root = U.load_code(raw[16:], 3495)

    found = False
    for qn, co in walk(root):
        if not (qn.endswith("." + want) or qn == want
                or co.co_name == want):
            continue
        found = True
        body = co.co_code
        print("=== %s  code=%dB  stack=%d  argcount=%d  nlocals=%d "
              "names=%d freevars=%r ==="
              % (qn, len(body), co.co_stacksize, co.co_argcount,
                 co.co_nlocals, len(co.co_names), co.co_freevars))
        print("  names[-3:] =", co.co_names[-3:])
        print("  varnames =", co.co_varnames)
        for off, nm, arg in disasm(body):
            if abs(off - around) <= win:
                extra = ""
                if nm == "LOAD_GLOBAL":
                    i = arg >> 1
                    if i < len(co.co_names):
                        extra = "  # %s%s" % (co.co_names[i],
                                              " (+NULL)" if arg & 1 else "")
                elif nm in ("LOAD_NAME", "STORE_NAME", "DELETE_NAME",
                            "IMPORT_NAME", "IMPORT_FROM"):
                    if arg < len(co.co_names):
                        extra = "  # %s" % co.co_names[arg]
                elif nm in ("LOAD_FAST", "STORE_FAST", "DELETE_FAST"):
                    if arg < len(co.co_varnames):
                        extra = "  # %s" % co.co_varnames[arg]
                elif nm == "LOAD_CONST":
                    if arg < len(co.co_consts):
                        v = co.co_consts[arg]
                        extra = "  # %r" % (v if not hasattr(v, "co_code")
                                            else "<code %s>" % v.co_name)
                print("  %6d  %-32s %-6d%s" % (off, nm, arg, extra))
        print()
    if not found:
        print("NOT FOUND:", want)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
