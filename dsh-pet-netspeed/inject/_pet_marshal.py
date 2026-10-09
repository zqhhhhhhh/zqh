# -*- coding: utf-8 -*-
"""Python 3.11 marshal 序列化器（自写，正确支持 bytes/str 长度）。

参考 CPython marshal.c 3.11 的 w_object / TYPE_CODE 分支。
code object 字段顺序（3.11）：
    argcount, posonlyargcount, kwonlyargcount, stacksize, flags,
    code, consts, names, varnames, freevars, cellvars,
    filename, name, qualname, firstlineno, linetable
"""
import struct

TYPE_NULL = 0x30
TYPE_NONE = 0x4E
TYPE_FALSE = 0x46
TYPE_TRUE = 0x54
TYPE_INT = 0x69
TYPE_FLOAT = 0x66
TYPE_LONG = 0x6C
TYPE_STRING = 0x73
TYPE_UNICODE = 0x75
TYPE_TUPLE = 0x28
TYPE_SMALL_TUPLE = 0x29
TYPE_LIST = 0x5B
TYPE_DICT = 0x7B
TYPE_CODE = 0x63
TYPE_REF = 0x72
TYPE_ASCII = 0x61
TYPE_SHORT_ASCII = 0x7A
FLAG_REF = 0x80
MAX_MARSHAL_STACK = 2000

# 3.11 已移除 interned/dict 的 ref 优化，但保留 FLAG_REF 机制。
# 为简化且安全：所有字符串/code 都带 FLAG_REF，并维护 ref 表。


class Marsh311:
    def __init__(self):
        self.buf = bytearray()
        self.refs = {}

    def w(self, b):
        self.buf += b if isinstance(b, (bytes, bytearray)) else bytes([b])

    def w_long(self, x):
        self.w(struct.pack("<i", x))

    def w_byte(self, x):
        self.buf.append(x & 0xFF)

    # ---- 各类型 ----
    def w_none(self):
        self.w(TYPE_NONE)

    def w_bool(self, x):
        self.w(TYPE_TRUE if x else TYPE_FALSE)

    def w_int(self, x):
        if -0x80000000 <= x <= 0x7FFFFFFF:
            self.w(TYPE_INT)
            self.w_long(x)
        else:
            self.w_long_obj(x)

    def w_long_obj(self, x):
        self.w(TYPE_LONG)
        n = abs(x)
        digits = []
        while n:
            digits.append(n & 0x7FFF)
            n >>= 15
        if x < 0:
            digits[-1] |= 0x4000
        self.w_long(len(digits))
        for d in digits:
            self.w(struct.pack("<H", d))

    def w_float(self, x):
        self.w(TYPE_FLOAT)
        self.w(struct.pack("<d", x))

    def w_bytes(self, b):
        self.w(TYPE_STRING | FLAG_REF)
        self.w_long(len(b))
        self.w(bytes(b))

    def w_str(self, s):
        """3.11: 全 ASCII 且 <256 用 SHORT_ASCII，否则用 unicode(UTF-8)。"""
        try:
            raw = s.encode("ascii")
            if len(raw) < 256:
                self.w(TYPE_SHORT_ASCII)
                self.w_byte(len(raw))
                self.w(raw)
                return
            self.w(TYPE_ASCII)
            self.w_long(len(raw))
            self.w(raw)
            return
        except UnicodeEncodeError:
            pass
        raw = s.encode("utf-8")
        self.w(TYPE_UNICODE)
        self.w_long(len(raw))
        self.w(raw)

    def w_tuple(self, t, as_tuple=True):
        n = len(t)
        if as_tuple and n < 256:
            self.w(TYPE_SMALL_TUPLE)
            self.w_byte(n)
        else:
            self.w(TYPE_TUPLE)
            self.w_long(n)
        for it in t:
            self.w_obj(it)

    def w_obj(self, x):
        if x is None:
            self.w_none()
        elif x is True or x is False:
            self.w_bool(x)
        elif isinstance(x, int):
            self.w_int(x)
        elif isinstance(x, float):
            self.w_float(x)
        elif isinstance(x, str):
            self.w_str(x)
        elif isinstance(x, (bytes, bytearray)):
            self.w_bytes(x)
        elif isinstance(x, tuple):
            self.w_tuple(x)
        elif type(x).__name__ in ("Code311", "Code310", "Code38", "Code3",
                                  "CodeType") and hasattr(x, "co_code"):
            self.w_code(x)
        else:
            raise TypeError(f"不支持: {type(x)}")

    def w_code(self, c):
        self.w(TYPE_CODE | FLAG_REF)
        self.w_long(c.co_argcount)
        self.w_long(getattr(c, "co_posonlyargcount", 0))
        self.w_long(c.co_kwonlyargcount)
        self.w_long(c.co_stacksize)
        self.w_long(c.co_flags)
        self.w_bytes(c.co_code)
        self.w_tuple(c.co_consts)
        self.w_tuple(c.co_names)
        self.w_tuple(c.co_varnames)
        self.w_tuple(c.co_freevars)
        self.w_tuple(c.co_cellvars)
        self.w_str(c.co_filename)
        self.w_str(c.co_name)
        self.w_str(getattr(c, "co_qualname", c.co_name))
        self.w_long(c.co_firstlineno)
        self.w_bytes(self._linetable(c))


def _linetable(c):
    lt = getattr(c, "co_linetable", None)
    if isinstance(lt, (bytes, bytearray)):
        return bytes(lt)
    return b""


Marsh311._linetable = staticmethod(_linetable)


def dumps(obj):
    m = Marsh311()
    m.w_obj(obj)
    return bytes(m.buf)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    import xdis.unmarshal as U
    src = open("_pet_src/pet/window.pyc", "rb").read()[16:]
    c = U.load_code(src, 3495)
    out = dumps(c)
    print("src", len(src), "out", len(out), "equal", out == src)
    c2 = U.load_code(out, 3495)
    print("reload ok  name=%s codelen=%d names=%d consts=%d" % (
        c2.co_name, len(c2.co_code), len(c2.co_names), len(c2.co_consts)))
    print("codelen same:", len(c2.co_code) == len(c.co_code))
    print("names same:", tuple(c2.co_names) == tuple(c.co_names))
