# -*- coding: utf-8 -*-
"""把网速浮窗注入桌宠 pet.window 字节码（纯 marshal 定点编辑）。

支持两种注入目标：
  --target paint  在 PetWindow.paintEvent 注入 _ns_overlay.draw(painter, self)
  --target frame  在 PetWindow._on_frame 注入 _ns_overlay.ping(self)

插入点统一选在「函数 RETURN 之前」，只重定位跨越插入点的跳转。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pet_scan import (CACHE_ENTRIES, NAMES, R, read_code,  # noqa
                       read_str, skip, walk)
from _pet_exctab import relocate as exctab_relocate  # noqa

LOAD_CONST = 0x64
STORE_NAME = 0x5A
IMPORT_NAME = 0x6C
LOAD_FAST = 0x7C
LOAD_GLOBAL = 0x74
LOAD_METHOD = 0xA0
LOAD_ATTR = 0x6A
PRECALL = 0xA6
CALL = 0xAB
POP_TOP = 0x01
PUSH_NULL = 0x02


def call_method(mod_idx, meth_idx, nargs, args=None):
    """生成 3.11 里「调用 `模块.方法(...)`」的**编译器同款**序列。

    与 CPython 3.11 编译器输出完全一致：
        LOAD_GLOBAL mod_idx*2 + 1     # +1 → 同时压入 NULL
        LOAD_METHOD meth_idx          # 10 个字 cache
        <args...>
        PRECALL nargs
        CALL    nargs
        POP_TOP

    为什么不能用 PUSH_NULL + LOAD_GLOBAL(偶数) + LOAD_FAST：
    那样栈是 [NULL, module, ...]，CALL 会去调 **module 本身**
    （→ TypeError: 'module' object is not callable / 硬崩）。
    LOAD_METHOD 会把它绑定成 `module.method` 并把 self 放在正确位置。
    """
    seq = ins(LOAD_GLOBAL, mod_idx * 2 + 1) + ins(LOAD_METHOD, meth_idx)
    for a in (args or []):
        seq += a
    seq += ins(PRECALL, nargs) + ins(CALL, nargs) + ins(POP_TOP)
    return seq


def call_global(idx, nargs=0, args=None):
    """生成 3.11 里「调用一个全局可调用对象」的序列（无 self 绑定）。

        PUSH_NULL
        LOAD_GLOBAL idx*2      (偶数 → 只压函数，不额外压 NULL)
        <args...>
        PRECALL nargs
        CALL    nargs
        POP_TOP
    """
    seq = ins(PUSH_NULL) + ins(LOAD_GLOBAL, idx * 2)
    for a in (args or []):
        seq += a
    seq += ins(PRECALL, nargs) + ins(CALL, nargs) + ins(POP_TOP)
    return seq

FWD = {
    "POP_JUMP_FORWARD_IF_FALSE", "POP_JUMP_FORWARD_IF_TRUE",
    "POP_JUMP_FORWARD_IF_NONE", "POP_JUMP_FORWARD_IF_NOT_NONE",
    "JUMP_FORWARD", "FOR_ITER", "SEND",
}
BWD = {"JUMP_BACKWARD", "JUMP_BACKWARD_NO_INTERRUPT"}


def ins(op, arg=0):
    """生成 3.11 指令（含必要 EXTENDED_ARG 与 cache 槽）。

    注意：EXTENDED_ARG 本身没有 cache 槽。
    """
    out = b""
    if arg > 0xFF:
        if arg > 0xFFFFFF:
            out += bytes([0x90, (arg >> 24) & 0xFF])
        if arg > 0xFFFF:
            out += bytes([0x90, (arg >> 16) & 0xFF])
        out += bytes([0x90, (arg >> 8) & 0xFF])
        arg = arg & 0xFF
    out += bytes([op, arg & 0xFF]) + b"\x00\x00" * CACHE_ENTRIES.get(
        NAMES[op], 0)
    return out


def split_code(b):
    """遍历 3.11 指令，返回 [(start, op, full_arg)].

    start 是该指令**含 EXTENDED_ARG 前缀**的起始偏移；
    full_arg 已把 EXTENDED_ARG 的高位并入。
    EXTENDED_ARG 本身不外抛（并入后续指令）。
    """
    out = []
    i = 0
    ext = 0
    ext_at = None
    while i < len(b):
        op = b[i]
        arg = b[i + 1] if i + 1 < len(b) else 0
        nm = NAMES[op]
        if nm == "EXTENDED_ARG":
            ext = (ext << 8) | arg
            if ext_at is None:
                ext_at = i
            i += 2
            continue
        full = (ext << 8) | arg if ext else arg
        start = ext_at if ext_at is not None else i
        out.append((start, op, full))
        ext = 0
        ext_at = None
        i += 2 + CACHE_ENTRIES.get(nm, 0) * 2
    return out


def _str_hdr_len(tc_full):
    """返回字段「头部字节数」（类型码 + 长度字段）。tc_full 含 FLAG_REF。"""
    if (tc_full & 0x7F) in (0x7A, 0x5A):
        return 2
    return 5


def _str_with_hdr(tc_full, data):
    """按类型码重建「类型 + 长度 + 数据」字段。

    **必须保留原类型码的 FLAG_REF 位**：带 FLAG_REF 的对象会登记进
    marshal 引用表，被后续 TYPE_REF 引用；丢掉该位会让引用表错位，
    报 ValueError: bad marshal data (invalid reference)。
    """
    base = tc_full & 0x7F
    if base in (0x7A, 0x5A):
        return bytes([tc_full, len(data)]) + data
    return bytes([tc_full]) + struct.pack("<I", len(data)) + data


def enc_str(s):
    try:
        raw = s.encode("ascii")
        if len(raw) < 256:
            return bytes([0x7A, len(raw)]) + raw
        return b"\x61" + struct.pack("<I", len(raw)) + raw
    except UnicodeEncodeError:
        raw = s.encode("utf-8")
        return b"\x75" + struct.pack("<I", len(raw)) + raw


def tup_hdr(n, orig_tc=0x29):
    flag = orig_tc & 0x80
    if n < 256:
        return bytes([0x29 | flag, n])
    return bytes([0x28 | flag]) + struct.pack("<I", n)


def code_hdr(n, orig_tc=0x63):
    return bytes([(orig_tc & 0x7F) | (orig_tc & 0x80)]) \
        + struct.pack("<I", n)


def read_tuple_strs(buf, span):
    s, e = span
    tc = buf[s] & 0x7F
    cnt = buf[s + 1] if tc == 0x29 else struct.unpack_from("<I", buf, s + 1)[0]
    p = s + (2 if tc == 0x29 else 5)
    r = R(buf)
    out = []
    for _ in range(cnt):
        st = p
        r.i = p
        skip(r, 0)
        p = r.i
        out.append(read_str(R(buf), (st, p)))
    return tc, cnt, out


def read_tuple_items(buf, span):
    s, e = span
    tc = buf[s] & 0x7F
    cnt = buf[s + 1] if tc == 0x29 else struct.unpack_from("<I", buf, s + 1)[0]
    p = s + (2 if tc == 0x29 else 5)
    r = R(buf)
    items = []
    for _ in range(cnt):
        st = p
        r.i = p
        skip(r, 0)
        p = r.i
        items.append(bytes(buf[st:p]))
    return tc, cnt, items


class Editor:
    def __init__(self, buf):
        self.buf = bytearray(buf)
        self.ops = []

    def insert(self, off, data):
        self.ops.append((off, "ins", bytes(data)))

    def replace(self, s, e, data):
        self.ops.append((s, "rep", (e, bytes(data))))

    def apply(self):
        for off, kind, pl in sorted(self.ops, key=lambda o: o[0],
                                    reverse=True):
            if kind == "ins":
                self.buf[off:off] = pl
            else:
                e, data = pl
                self.buf[off:e] = data
        return bytes(self.buf)


def reloc(body, tgt, nu, label=""):
    """只重定位跨越插入点的跳转。

    body 为 bytearray，就地修改。off 由 split_code 给出（含 EXTENDED_ARG
    前缀），因此 arg 的**最低字节**位于「最后一条 EXTENDED_ARG/指令」的
    第 2 字节处 —— 即 off + 2*(n_ext) + 1。这里直接重新编码整条指令。
    """
    for off, op, arg in split_code(body):
        nm = NAMES[op]
        if nm in FWD:
            target = off + 2 + arg * 2
        elif nm in BWD:
            target = off + 2 - arg * 2
        else:
            continue
        if (off < tgt) != (target <= tgt):
            new_arg = arg + nu
            # 定位 arg 最低字节：从 off 起跳过 EXTENDED_ARG 对
            p = off
            while NAMES[body[p]] == "EXTENDED_ARG":
                p += 2
            if new_arg > 0xFF:
                print("  !! %s @%d 重定位后 arg=%d 超过 255，需重编码"
                      % (label, off, new_arg))
            body[p + 1] = new_arg & 0xFF
            print("  %s重定位 %s @%d: arg %d -> %d (target %d)"
                  % (label, nm, off, arg, new_arg, target))


def find_entry_off(body):
    """返回 RESUME 之后的偏移（函数入口，每次调用必经）。"""
    for off, op, arg in split_code(body):
        if NAMES[op] == "RESUME":
            return off + 2
    return 2


def find_return_off(body):
    """返回最后一条 RETURN_VALUE 的偏移（仅用于兜底）。"""
    last = None
    for off, op, arg in split_code(body):
        if NAMES[op] == "RETURN_VALUE":
            last = off
    return last


def find_convergence(body, bail="RETURN_VALUE"):
    """返回「汇聚点」：被跳转指向次数最多的那个偏移。

    用于 at_entry=False —— 在函数所有分支合流处注入，此时函数内的
    局部变量（如 paintEvent 的 painter）一定已经初始化。
    找不到任何跳转目标时退回最后一条 RETURN_VALUE 之前。
    """
    from collections import Counter
    cnt = Counter()
    for off, op, arg in split_code(body):
        nm = NAMES[op]
        if nm in FWD:
            cnt[off + 2 + arg * 2] += 1
        elif nm in BWD:
            cnt[off + 2 - arg * 2] += 1
    if not cnt:
        r = find_return_off(body)
        return r if r is not None else len(body)
    best, n = cnt.most_common(1)[0]
    if n < 2:
        r = find_return_off(body)
        return r if r is not None else len(body)
    return best


def inject_method(buf, method_name, call_code, overlay_name="_ns_overlay",
                  at_entry=True, extra_names=()):
    """在 method_name 注入 call_code。

    at_entry=True  → 插到 RESUME 之后（每次调用必执行）
    at_entry=False → 插到最后一条 RETURN_VALUE 之前

    call_code(idx_map) 接收一个 dict：{name: names 索引}。
    可用键：overlay_name（默认 `_ns_overlay`）以及 extra_names 中的每个名字。
    """
    items = walk(buf)
    hit = None
    for qn, f, cs in items:
        if qn.endswith("." + method_name):
            hit = (qn, f, cs)
    if hit is None:
        raise SystemExit("未找到方法 " + method_name)
    qn, f, cs = hit
    print("目标方法:", qn)

    tc, cnt, plist = read_tuple_strs(buf, f["names"])
    ed = Editor(buf)
    want = [overlay_name] + [n for n in extra_names if n not in plist]
    add = [n for n in want if n not in plist]
    if add:
        bo = 2 if tc == 0x29 else 5
        s, e = f["names"]
        ed.replace(s, e, tup_hdr(cnt + len(add), buf[s]) + buf[s + bo:e]
                   + b"".join(enc_str(n) for n in add))
        print("  names %d -> %d (+%s)" % (cnt, cnt + len(add), add))
    all_names = plist + add
    idx_map = {n: all_names.index(n) for n in set(want)}

    src_span = buf[f["code"][0]:f["code"][1]]
    body = bytearray(src_span[5:])
    seq = call_code(idx_map)
    nu = len(seq) // 2
    if at_entry:
        tgt = find_entry_off(body)
        print("  注入点 @%d (RESUME 之后), 插入 %d 单元" % (tgt, nu))
    else:
        tgt = find_convergence(body)
        if tgt is None:
            tgt = len(body)
        print("  注入点 @%d (汇聚点), 插入 %d 单元" % (tgt, nu))
    reloc(body, tgt, nu)
    new_body = bytes(body[:tgt]) + seq + bytes(body[tgt:])
    new_field = code_hdr(len(new_body), src_span[0]) + new_body
    ed.replace(f["code"][0], f["code"][1], new_field)
    print("  co_code %d -> %d" % (len(src_span), len(new_field)))

    # ---- 关键修复 1：抬高 co_stacksize ----
    # 注入的 PUSH_NULL/LOAD_GLOBAL/LOAD_FAST 最坏多压 3 个栈槽；
    # 若原 stacksize 已被占满，超出会破坏内存 → 硬崩溃（无 Python 异常）。
    need = 3
    old_ss = struct.unpack_from("<I", ed.buf, f["stacksize"])[0]
    struct.pack_into("<I", ed.buf, f["stacksize"], old_ss + need)
    print("  co_stacksize %d -> %d" % (old_ss, old_ss + need))

    # ---- 关键修复 2：扩展 co_linetable ----
    # 3.11 的 linetable 以「code unit 数」记录每条 entry 覆盖长度。插入指令
    # 后若覆盖长度 < 新 co_code 长度，CPython 做位置映射时会越界读取 → 崩溃。
    # 注意：linetable 在 marshal 里是**带长度前缀**的 str/bytes 对象，
    # 追加内容必须重建头部并更新长度，否则 marshal 流错位（表现为
    # 「localspluskinds 被读成 str」→ ValueError: bad marshal data）。
    lspan = f["linetable"]
    ltc = buf[lspan[0]]                 # 保留 FLAG_REF
    lbo = _str_hdr_len(ltc)
    ldata = bytes(buf[lspan[0] + lbo:lspan[1]])
    extra = bytearray()
    need = nu + 8                       # 新增单元数 + 余量
    while need > 0:
        d = min(8, need)
        extra.append(0x80 | (15 << 3) | (d - 1))    # kind=15 无位置信息
        need -= d
    if extra:
        newfield = _str_with_hdr(ltc, ldata + bytes(extra))
        ed.replace(lspan[0], lspan[1], newfield)
        print("  co_linetable %d -> %d 字节 (+%d entry, 覆盖 +%d unit)"
              % (len(buf[lspan[0]:lspan[1]]), len(newfield),
                 len(extra), nu + 8))

    # ---- 关键修复 3：重定位 co_exceptiontable ----
    # 3.11 的异常表记录的是**绝对的指令/字节偏移**。插入指令后若不重定位，
    # handler 目标会指向错误位置（甚至越界）→ 一旦抛异常就硬崩（无 traceback）。
    et_span = f["exceptiontable"]
    if et_span[1] > et_span[0]:
        etc = buf[et_span[0]]
        ebo = _str_hdr_len(etc)
        etdata = bytes(buf[et_span[0] + ebo:et_span[1]])
        new_et, old_ent, new_ent = exctab_relocate(etdata, tgt // 2, nu)
        if new_et != etdata:
            newfield = _str_with_hdr(etc, new_et)
            ed.replace(et_span[0], et_span[1], newfield)
            print("  co_exceptiontable 重定位 %d entry: %r -> %r"
                  % (len(old_ent), old_ent, new_ent))
    return ed


def patch_module(buf, alias="_ns_overlay",
                 mod="net_speed_overlay"):
    """模块级：在 RESUME 后插 `import mod as alias`。"""
    r = R(buf)
    r.u8()
    f = read_code(r, 0)
    tc, cnt, nlist = read_tuple_strs(buf, f["names"])
    _, ccnt, citems = read_tuple_items(buf, f["consts"])

    ed = Editor(buf)
    add_names = [n for n in (mod, alias) if n not in nlist]
    if add_names:
        s, e = f["names"]
        bo = 2 if tc == 0x29 else 5
        ed.replace(s, e, tup_hdr(cnt + len(add_names), buf[s])
                   + buf[s + bo:e] + b"".join(enc_str(n)
                                              for n in add_names))
        print("  模块 names %d -> %d" % (cnt, cnt + len(add_names)))

    lvl_idx = none_idx = None
    for i, b in enumerate(citems):
        if b[0] == 0x4E:
            none_idx = i
        if (b[0] & 0x7F) == 0x69 \
                and struct.unpack_from("<i", b, 1)[0] == 0:
            lvl_idx = i
    add_consts = []
    if lvl_idx is None:
        add_consts.append(b"\x69" + struct.pack("<i", 0))
        lvl_idx = ccnt + len(add_consts) - 1
    if none_idx is None:
        add_consts.append(b"\x4E")
        none_idx = ccnt + len(add_consts) - 1
    if add_consts:
        s, e = f["consts"]
        tc2 = buf[s] & 0x7F
        bo = 2 if tc2 == 0x29 else 5
        ed.replace(s, e, tup_hdr(ccnt + len(add_consts), buf[s])
                   + buf[s + bo:e] + b"".join(add_consts))
        print("  模块 consts %d -> %d" % (ccnt, ccnt + len(add_consts)))

    all_names = nlist + add_names
    i_ov = all_names.index(mod)
    i_al = all_names.index(alias)
    # 只做 import：`import net_speed_overlay as _ns_overlay`
    # （不要在模块级调用，模块级调用曾把 module 当函数调导致启动崩溃）
    seq = ins(LOAD_CONST, lvl_idx) + ins(LOAD_CONST, none_idx) \
        + ins(IMPORT_NAME, i_ov) + ins(STORE_NAME, i_al)
    nu = len(seq) // 2

    src_span = buf[f["code"][0]:f["code"][1]]
    mbody = bytearray(src_span[5:])
    ins_at = 2
    for off, op, arg in split_code(mbody):
        if NAMES[op] == "RESUME":
            ins_at = off + 2
            break
    reloc(mbody, ins_at, nu, "模块")
    new_body = bytes(mbody[:ins_at]) + seq + bytes(mbody[ins_at:])
    new_field = code_hdr(len(new_body), src_span[0]) + new_body
    ed.replace(f["code"][0], f["code"][1], new_field)
    print("  模块 co_code 插 import @%d, %d -> %d"
          % (ins_at, len(src_span), len(new_field)))

    # ---- 关键修复：扩展模块级 co_linetable ----
    # 与方法注入同理：插入 nu 个 code unit 后若 linetable 覆盖长度不足，
    # CPython 做位置映射时会越界读取 → 启动即 ACCESS_VIOLATION（无 traceback）。
    # （此前只对方法做了这一步，模块级遗漏，导致补丁后 exe 启动硬崩。）
    lspan = f["linetable"]
    ltc = buf[lspan[0]]
    lbo = _str_hdr_len(ltc)
    ldata = bytes(buf[lspan[0] + lbo:lspan[1]])
    extra = bytearray()
    need = nu + 8
    while need > 0:
        d = min(8, need)
        extra.append(0x80 | (15 << 3) | (d - 1))    # kind=15 无位置信息
        need -= d
    if extra:
        newfield = _str_with_hdr(ltc, ldata + bytes(extra))
        ed.replace(lspan[0], lspan[1], newfield)
        print("  模块 co_linetable %d -> %d 字节 (+%d unit)"
              % (len(buf[lspan[0]:lspan[1]]), len(newfield), nu + 8))

    # ---- 模块级 co_exceptiontable 重定位 ----
    et_span = f["exceptiontable"]
    if et_span[1] > et_span[0]:
        etc = buf[et_span[0]]
        ebo = _str_hdr_len(etc)
        etdata = bytes(buf[et_span[0] + ebo:et_span[1]])
        new_et, old_ent, new_ent = exctab_relocate(etdata, ins_at // 2, nu)
        if new_et != etdata:
            newfield = _str_with_hdr(etc, new_et)
            ed.replace(et_span[0], et_span[1], newfield)
            print("  模块 co_exceptiontable 重定位 %d entry: %r -> %r"
                  % (len(old_ent), old_ent, new_ent))
    return ed


def main():
    target = "paint"
    for a in sys.argv[1:]:
        if a.startswith("--target="):
            target = a.split("=", 1)[1]
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_pet_src", "pet", "window.pyc")
    raw = open(src, "rb").read()
    head, buf = raw[:16], raw[16:]

    print("== step 1: 模块级 import ==")
    buf2 = patch_module(bytes(buf)).apply()
    print("  %d -> %d 字节" % (len(buf), len(buf2)))

    print("== step 2: 方法注入 (target=%s) ==" % target)
    if target == "none":
        buf3 = buf2
        print("  跳过")
    elif target == "nop":
        # 无害注入：压常量再弹出，验证插入本身是否破坏结构
        ed2 = inject_method(
            bytes(buf2), "showEvent",
            lambda m: ins(LOAD_CONST, 0) + ins(POP_TOP),
            overlay_name="__nso_unused__", at_entry=True)
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "paintentry":
        # 诊断：paintEvent **入口**（RESUME 之后）调用 _ns_overlay.draw(painter, self)
        ed2 = inject_method(
            bytes(buf2), "paintEvent",
            lambda m: call_method(
                m["_ns_overlay"], m["draw"], 2,
                [ins(LOAD_FAST, 3), ins(LOAD_FAST, 0)]),
            at_entry=True, extra_names=("draw",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "probe":
        # 诊断：paintEvent 汇聚点调用 _ns_overlay.probe(painter, self)
        ed2 = inject_method(
            bytes(buf2), "paintEvent",
            lambda m: call_method(
                m["_ns_overlay"], m["probe"], 2,
                [ins(LOAD_FAST, 3), ins(LOAD_FAST, 0)]),
            at_entry=False, extra_names=("probe",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "lg":
        # 只测 LOAD_GLOBAL：PUSH_NULL + LOAD_GLOBAL idx*2 + POP_TOP
        ed2 = inject_method(
            bytes(buf2), "showEvent",
            lambda m: ins(PUSH_NULL) + ins(LOAD_GLOBAL, m["_ns_overlay"] * 2)
            + ins(POP_TOP),
            at_entry=True)
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "call0":
        # 测无参调用：PUSH_NULL + LOAD_GLOBAL + PRECALL 0 + CALL 0 + POP_TOP
        ed2 = inject_method(
            bytes(buf2), "showEvent",
            lambda m: call_method(m["_ns_overlay"], m["ping"], 0, []),
            at_entry=True, extra_names=("ping",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "show":
        ed2 = inject_method(
            bytes(buf2), "showEvent",
            lambda m: call_method(
                m["_ns_overlay"], m["ping"], 1, [ins(LOAD_FAST, 0)]),
            at_entry=True, extra_names=("ping",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "frame":
        ed2 = inject_method(
            bytes(buf2), "_on_frame",
            lambda m: call_method(
                m["_ns_overlay"], m["ping"], 1, [ins(LOAD_FAST, 0)]),
            at_entry=True, extra_names=("ping",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    elif target == "tick":
        # 正式方案：_on_frame 每帧 → _ns_overlay.tick(self)
        # （paintEvent 在本桌宠不被调用，故改由 _on_frame 驱动子控件浮层）
        ed2 = inject_method(
            bytes(buf2), "_on_frame",
            lambda m: call_method(
                m["_ns_overlay"], m["tick"], 1, [ins(LOAD_FAST, 0)]),
            at_entry=True, extra_names=("tick",))
        buf3 = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf3)))
    else:
        # paint（正式）：
        #   paintEvent 汇聚点 → _ns_overlay.draw(painter, self)
        #   showEvent 入口    → _ns_overlay.ping(self)   （记录窗口实例）
        ed2 = inject_method(
            bytes(buf2), "paintEvent",
            lambda m: call_method(
                m["_ns_overlay"], m["draw"], 2,
                [ins(LOAD_FAST, 3), ins(LOAD_FAST, 0)]),
            at_entry=False, extra_names=("draw",))
        buf2b = ed2.apply()
        print("  %d -> %d 字节" % (len(buf2), len(buf2b)))
        ed3 = inject_method(
            bytes(buf2b), "showEvent",
            lambda m: call_method(
                m["_ns_overlay"], m["ping"], 1, [ins(LOAD_FAST, 0)]),
            at_entry=True, extra_names=("ping",))
        buf3 = ed3.apply()
        print("  %d -> %d 字节" % (len(buf2b), len(buf3)))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_pet_patched", "pet", "window.pyc")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(head + bytes(buf3))
    print("写出:", out, os.path.getsize(out), "字节")

    import xdis.unmarshal as U
    c = U.load_code(bytes(buf3), 3495)
    print("reload OK  names=%d codelen=%d" % (len(c.co_names),
                                              len(c.co_code)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
