# -*- coding: utf-8 -*-
"""3.11 co_exceptiontable 解码 / 重定位（依据 CPython 3.11 官方说明）。

格式：每条 entry 4 个 varint：start, length, target, ((depth<<1)|lasti)
- varint: val = b & 63; while b & 64: val = (val<<6) | (b & 63)
  （**首组为最高位**，大端式）
- 表中数值单位是**指令条数（code unit, 2 字节）**；字节偏移 = 值 * 2
"""

MASK63 = 0x3F
CONT = 0x40


def read_varint(b, i):
    v = b[i] & MASK63
    while b[i] & CONT:
        i += 1
        v = (v << 6) | (b[i] & MASK63)
    return v, i + 1


def write_varint(v):
    """编码为 varint（首组最高位）。"""
    groups = [v & MASK63]
    v >>= 6
    while v:
        groups.append(v & MASK63)
        v >>= 6
    groups.reverse()
    out = bytearray()
    for g in groups[:-1]:
        out.append(g | CONT)
    out.append(groups[-1])
    return bytes(out)


def decode(et):
    """-> [(start, length, target, depth, lasti)]，单位=指令数。"""
    out = []
    i = 0
    while i < len(et):
        start, i = read_varint(et, i)
        length, i = read_varint(et, i)
        target, i = read_varint(et, i)
        dl, i = read_varint(et, i)
        out.append((start, length, target, dl >> 1, dl & 1))
    return out


def encode(entries):
    out = bytearray()
    for start, length, target, depth, lasti in entries:
        out += write_varint(start)
        out += write_varint(length)
        out += write_varint(target)
        out += write_varint((depth << 1) | (lasti & 1))
    return bytes(out)


def relocate(et, ins_unit, nu_units):
    """插入点 ins_unit（指令数），插入 nu_units 条指令。
    start / target 中 >= ins_unit 的值需 +nu_units；
    length 不变（区间长度不因外部插入而改变）。
    """
    entries = decode(et)
    new = []
    for start, length, target, depth, lasti in entries:
        ns = start + nu_units if start >= ins_unit else start
        nt = target + nu_units if target >= ins_unit else target
        new.append((ns, length, nt, depth, lasti))
    return encode(new), entries, new


if __name__ == "__main__":
    ethex = "c31514432a00c32a20440d03c40c01440d03"
    et = bytes.fromhex(ethex)
    dec = decode(et)
    print("原 entries (start,len,target,depth,lasti):")
    for e in dec:
        print("   ", e, " 字节: start=%d .. end=%d -> target=%d"
              % (e[0] * 2, (e[0] + e[1]) * 2, e[2] * 2))
    nb, old, new = relocate(et, 2, 8)   # showEvent: RESUME@2 之后插 16B = 8 指令
    print("插 8 指令后:")
    for e in new:
        print("   ", e)
    print("新 hex:", nb.hex(" "))
    print("往返一致:", encode(decode(et)) == et)
