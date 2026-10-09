# -*- coding: utf-8 -*-
"""从 PE 文件（.exe）提取图标资源，重组成标准 .ico 文件（纯标准库）。

原理：
  RT_GROUP_ICON(14) 描述各尺寸条目（含资源 ID nID），
  RT_ICON(3) 存放各尺寸图像数据；
  .ico 的结构与 GRPICONDIR 几乎一致，只需把 entry 里的 nID
  换成「图像数据在文件中的偏移」。

用法: python _extract_icon.py <src.exe> <out.ico> [group_index]
"""
import struct
import sys


def rva2off(data, secs, rva):
    for name, va, vsz, praw, rsz in secs:
        if va <= rva < va + max(vsz, rsz):
            return rva - va + praw
    raise ValueError("RVA 0x%X 不在任何节内" % rva)


def parse_sections(data, pe):
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    base = pe + 24 + optsz
    secs = []
    for i in range(nsec):
        o = base + i * 40
        name = data[o:o + 8].rstrip(b"\x00").decode("ascii", "ignore")
        vsz, va, rsz, praw = struct.unpack_from("<IIII", data, o + 8)
        secs.append((name, va, vsz, praw, rsz))
    return secs, pe + 24


def walk_res(data, secs, res_rva, res_sz):
    """返回 {type: {name: {lang: (dataRVA, size)}}}"""
    base = rva2off(data, secs, res_rva)
    out = {}

    def read_dir(off, level, path):
        chars, tds, mj, mn, nnamed, nid = struct.unpack_from("<IIHHHH",
                                                             data, off)
        n = nnamed + nid
        for i in range(n):
            eo = off + 16 + i * 8
            nm, od = struct.unpack_from("<II", data, eo)
            is_dir = bool(od & 0x80000000)
            val = od & 0x7FFFFF
            if is_dir:
                read_dir(base + val, level + 1, path + [(nm, val)])
            else:
                doff = base + val
                d_rva, d_sz, cp, rsv = struct.unpack_from("<IIII", data, doff)
                k = path[0][0] if path else 0
                out.setdefault(k, []).append((path[1][0] if len(path) > 1
                                              else 0,
                                              path[2][0] if len(path) > 2
                                              else 0, d_rva, d_sz))

    read_dir(base, 0, [])
    return out


def build_ico(res):
    """res: {type: [(name, lang, rva, size)]}"""
    grp_names = sorted({n for n, l, r, s in res.get(14, [])})
    if not grp_names:
        raise SystemExit("未找到 RT_GROUP_ICON(14)")
    gname = grp_names[0]
    g = [x for x in res[14] if x[0] == gname]
    gname2, glang, grva, gsz = g[0]
    return gname, glang, grva, gsz


def main():
    src, dst = sys.argv[1], sys.argv[2]
    gi = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    data = open(src, "rb").read()

    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\x00\x00":
        raise SystemExit("不是有效 PE 文件")
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    dd = pe + 24 + (96 if magic == 0x10B else 112)
    res_rva, res_sz = struct.unpack_from("<II", data, dd + 2 * 8)
    secs, optoff = parse_sections(data, pe)
    print("PE32" if magic == 0x10B else "PE32+",
          " sections=%d  resRVA=0x%X size=%d" % (len(secs), res_rva, res_sz))

    res = walk_res(data, secs, res_rva, res_sz)
    types = {k: len(v) for k, v in res.items()}
    print("资源类型统计:", sorted(types.items()))

    # RT_GROUP_ICON = 14, RT_ICON = 3
    groups = res.get(14, [])
    if not groups:
        raise SystemExit("无图标组")
    grp_ids = sorted({n for n, l, r, s in groups})
    print("图标组 ID:", grp_ids)
    gname = grp_ids[gi]
    grp = [x for x in groups if x[0] == gname][0]
    _, glang, grva, gsz = grp
    goff = rva2off(data, secs, grva)
    gdata = data[goff:goff + gsz]

    grsv, gtype, gcount = struct.unpack_from("<HHH", gdata, 0)
    print("组: idReserved=%d idType=%d count=%d" % (grsv, gtype, gcount))

    icons = {}
    for n, l, r, s in res.get(3, []):
        off = rva2off(data, secs, r)
        icons.setdefault(n, (off, s))

    entries = []
    for i in range(gcount):
        o = 6 + i * 14
        bw, bh, bcc, brsv, planes, bpp, binsz, nid = struct.unpack_from(
            "<BBBBHHIH", gdata, o)
        if nid not in icons:
            print("  !! 缺 RT_ICON id=%d" % nid)
            continue
        io, isz = icons[nid]
        entries.append(((bw, bh, bcc, brsv, planes, bpp, isz), data[io:io + isz]))
        print("  [%d] %3dx%-3d bpp=%-2d %6d B  (resID=%d)"
              % (i, bw or 256, bh or 256, bpp, isz, nid))

    # 组装 .ico
    hdr = struct.pack("<HHH", 0, 1, len(entries))
    off = 6 + 16 * len(entries)
    dirs = []
    blobs = []
    for (bw, bh, bcc, brsv, planes, bpp, isz), blob in entries:
        dirs.append(struct.pack("<BBBBHHII", bw, bh, bcc, brsv, planes, bpp,
                                len(blob), off))
        blobs.append(blob)
        off += len(blob)
    out = hdr + b"".join(dirs) + b"".join(blobs)
    with open(dst, "wb") as f:
        f.write(out)
    print("写出 %s  %d 张 %d B" % (dst, len(entries), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
