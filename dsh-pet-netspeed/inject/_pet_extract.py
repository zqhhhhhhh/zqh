# -*- coding: utf-8 -*-
"""从桌宠 exe 的 PYZ 中导出 pet 包字节码。

结构：PYZ = b'PYZ\\x00' + pyc_magic(4) + toc_pos(4) + <压缩模块数据>
TOC 位于文件绝对偏移 pyz_start + toc_pos，是 marshal 序列化的列表：
    [ (name:str, typecode:int, offset:int, stored_len:int), ... ]
offset 相对 pyz_start；typecode 3 = marshal 代码对象（未压缩），
0 = 原始数据（zip 压缩）。
"""
import marshal
import os
import sys
import zlib

EXE = (r"C:\Users\EDY\AppData\Local\Programs"
       r"\dsh-pet-standalone-webm\dsh-pet-standalone-webm.exe")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pet_src")


def load_toc(data):
    pyz = data.find(b"PYZ\x00")
    if pyz < 0:
        raise SystemExit("PYZ 未找到")
    toc_pos = int.from_bytes(data[pyz + 8:pyz + 12], "big")
    raw = data[pyz + toc_pos:]
    toc = marshal.loads(raw)
    return pyz, toc


def main():
    data = open(EXE, "rb").read()
    pyz, toc = load_toc(data)
    print(f"PYZ @ {pyz}  模块数 {len(toc)}")
    print("样例:", [t[0] for t in toc[:8]])
    tops = sorted({t[0].split(".")[0] for t in toc})
    print("顶层包:", ", ".join(tops))

    pet = [t for t in toc if t[0] == "pet" or t[0].startswith("pet.")]
    print(f"\npet 模块（{len(pet)}）:")
    print("字段样例:", pet[:3])
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for item in pet:
        name = item[0]
        typ, off, clen = item[1]
        body = data[pyz + off:pyz + off + clen]
        if typ == 0:
            try:
                body = zlib.decompress(body)
            except Exception:
                pass
        dst = os.path.join(OUT, name.replace(".", os.sep) + ".pyc")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(body)
        ok += 1
        print(f"  {name:34s} typ={typ} {clen:>7}B")
    print("导出:", ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
