# -*- coding: utf-8 -*-
"""在原始 3.11 marshal 字节流中定位 code object 的字段区段（只读，不改）。

用途：对 pet.window 的 paintEvent / 模块级 code 做定点字节替换。
"""
import struct

import xdis.op_imports as oi

def _opc311():
    """兼容 xdis 各版本的 get_opcode_module 签名（<<3.x tuple / int>>）。"""
    for call in (lambda: oi.get_opcode_module((3, 11), "CPython"),
                 lambda: oi.get_opcode_module(311, "CPython"),
                 lambda: oi.get_opcode_module(311),
                 lambda: oi.get_opcode_module((3, 11))):
        try:
            return call()
        except Exception:
            continue
    raise RuntimeError("xdis: 无法取得 3.11 opcode module")


OPC311 = _opc311()
NAMES = OPC311.opname

# CPython 3.11 Include/internal/pycore_opcode.h  _PyOpcode_Caches
# 注意：LOAD_ATTR 是 4（不是 1）；LOAD_METHOD 是 10。
CACHE_ENTRIES = {
    "BINARY_SUBSCR": 4,
    "STORE_SUBSCR": 1,
    "UNPACK_SEQUENCE": 1,
    "STORE_ATTR": 4,
    "LOAD_ATTR": 4,
    "COMPARE_OP": 2,
    "LOAD_GLOBAL": 5,
    "BINARY_OP": 1,
    "LOAD_METHOD": 10,
    "PRECALL": 1,
    "CALL": 4,
}

T_NONE = 0x4E
T_FALSE = 0x46
T_TRUE = 0x54
T_STOPITER = 0x53
T_ELLIPSIS = 0x2E
T_INT = 0x69
T_INT64 = 0x49
T_FLOAT = 0x66
T_BINARY_FLOAT = 0x67
T_COMPLEX = 0x78
T_BINARY_COMPLEX = 0x79
T_LONG = 0x6C
T_STRING = 0x73
T_INTERNED = 0x74
T_REF = 0x72
T_TUPLE = 0x28
T_SMALL_TUPLE = 0x29
T_LIST = 0x5B
T_DICT = 0x7B
T_CODE = 0x63
T_UNICODE = 0x75
T_SET = 0x3C
T_FROZENSET = 0x3E
T_ASCII = 0x61
T_ASCII_INTERNED = 0x41
T_SHORT_ASCII = 0x7A
T_SHORT_ASCII_INTERNED = 0x5A
T_UNKNOWN = 0x3F
FLAG_REF = 0x80


class R:
    def __init__(self, buf):
        self.b = buf
        self.i = 0

    def u8(self):
        v = self.b[self.i]
        self.i += 1
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.i)[0]
        self.i += 4
        return v

    def raw(self, n):
        v = self.b[self.i:self.i + n]
        self.i += n
        return v


def skip(r, depth=0):
    """跳过一个 marshal 对象；若为 code object 返回其字段偏移表。"""
    if depth > 60:
        raise RecursionError("嵌套过深")
    tc = r.u8()
    base = tc & 0x7F
    if base == T_NONE or base == T_FALSE or base == T_TRUE \
            or base == T_STOPITER or base == T_ELLIPSIS:
        return None
    if base == T_INT:
        r.i += 4
        return None
    if base == T_INT64:
        r.i += 8
        return None
    if base in (T_FLOAT, T_BINARY_FLOAT):
        r.i += 8
        return None
    if base in (T_COMPLEX, T_BINARY_COMPLEX):
        r.i += 16
        return None
    if base == T_LONG:
        n = r.i32()
        r.i += abs(n) * 2
        return None
    if base in (T_STRING, T_INTERNED, T_UNICODE):
        n = r.u32()
        r.i += n
        return None
    if base in (T_ASCII, T_ASCII_INTERNED):
        n = r.u32()
        r.i += n
        return None
    if base in (T_SHORT_ASCII, T_SHORT_ASCII_INTERNED):
        n = r.u8()
        r.i += n
        return None
    if base == T_REF:
        r.i += 4
        return None
    if base in (T_TUPLE, T_LIST, T_SET, T_FROZENSET):
        n = r.u32()
        for _ in range(n):
            skip(r, depth + 1)
        return None
    if base == T_SMALL_TUPLE:
        n = r.u8()
        for _ in range(n):
            skip(r, depth + 1)
        return None
    if base == T_DICT:
        while True:
            if r.b[r.i] == T_NULL:
                r.i += 1
                break
            skip(r, depth + 1)
            skip(r, depth + 1)
        return None
    if base == T_CODE:
        return read_code(r, depth)
    if base == T_UNKNOWN:
        return None
    raise ValueError(f"未知类型 0x{base:02x}({chr(base)!r}) @ {r.i - 1}")


def read_code(r, depth=0):
    """code object 字段（CPython 3.11）：

    argcount, posonlyargcount, kwonlyargcount, stacksize, flags,
    code, consts, names, localsplusnames, localspluskinds,
    filename, name, qualname, firstlineno, linetable

    注意 3.11 用 localsplusnames/localspluskinds 取代 3.10 的
    varnames/freevars/cellvars 三个字段。
    """
    f = {}
    for key in ("argcount", "posonly", "kwonly", "stacksize", "flags"):
        f[key] = r.i
        r.i += 4
    for key in ("code", "consts", "names", "localsplusnames",
                "localspluskinds", "filename", "name", "qualname"):
        s = r.i
        skip(r, depth + 1)
        f[key] = (s, r.i)
    f["firstlineno"] = r.i
    r.i += 4
    for key in ("linetable", "exceptiontable"):
        s = r.i
        skip(r, depth + 1)
        f[key] = (s, r.i)
    f["end"] = r.i
    return f


def read_str(r, span):
    """从字符串对象区段读取值。"""
    s, e = span
    tc = r.b[s] & 0x7F
    if tc in (T_STRING, T_INTERNED, T_UNICODE):
        n = struct.unpack_from("<I", r.b, s + 1)[0]
        return r.b[s + 5:s + 5 + n].decode("utf-8", "replace")
    if tc == T_SHORT_ASCII_INTERNED:  # '|' 变体（长度 4 字节）
        n = struct.unpack_from("<I", r.b, s + 1)[0]
        return r.b[s + 5:s + 5 + n].decode("ascii", "replace")
    if tc in (T_SHORT_ASCII,):
        n = r.b[s + 1]
        return r.b[s + 2:s + 2 + n].decode("ascii", "replace")
    if tc in (T_ASCII, T_ASCII_INTERNED):
        n = struct.unpack_from("<I", r.b, s + 1)[0]
        return r.b[s + 5:s + 5 + n].decode("ascii", "replace")
    return f"<{tc:02x}>"


def walk(buf, r=None, want=()):
    """遍历所有 code object，按 qualname 收集字段位置。

    返回 [(qualname, fields, code_start)]，code_start 是类型码偏移。
    """
    out = []
    want = set(want)

    def rec(rr, depth, parent):
        code_start = rr.i
        tc = rr.u8()
        if (tc & 0x7F) != T_CODE:
            raise ValueError(f"期望 code，得到 0x{tc:02x} @ {code_start}")
        f = read_code(rr, depth)
        qn = read_str(rr, f["qualname"])
        full = qn if not parent else f"{parent}.{qn}"
        out.append((full, f, code_start))
        # 进入 consts 找嵌套 code
        cs, ce = f["consts"]
        r2 = R(buf)
        r2.i = cs
        t2 = r2.u8()
        base2 = t2 & 0x7F
        if base2 == T_SMALL_TUPLE:
            cnt = r2.u8()
        elif base2 == T_TUPLE:
            cnt = r2.u32()
        else:
            return
        for _ in range(cnt):
            if (r2.b[r2.i] & 0x7F) == T_CODE:
                rec(r2, depth + 1, full)
            else:
                skip(r2, depth + 1)
    rec(r or R(buf), 0, "")
    return out


if __name__ == "__main__":
    buf = open("_pet_src/pet/window.pyc", "rb").read()[16:]
    items = walk(buf)
    print("code 对象总数:", len(items))
    for qn, f, cs in items:
        if qn in ("paintEvent", "<module>") or "paintEvent" in qn:
            print(f"\n=== {qn}  (类型码 @ {cs}) ===")
            for k, v in f.items():
                if isinstance(v, tuple):
                    print(f"  {k:16s} {v[0]:>8}..{v[1]:<8} ({v[1]-v[0]})")
                else:
                    print(f"  {k:16s} off={v}")

