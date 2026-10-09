# -*- coding: utf-8 -*-
"""桌宠脚底网速显示 —— 由字节码注入挂载（子控件方案）。

挂载点：
    pet.window 模块级 : import net_speed_overlay as _ns_overlay
    PetWindow._on_frame: _ns_overlay.tick(self)     # 每帧调用（已验证可靠）

为什么不用 paintEvent：
    实测本桌宠运行期 PetWindow.paintEvent **不会被调用**（画面由子控件/视频面
    独立渲染），故注入 paintEvent 无效果。_on_frame 每帧必调，改由此驱动。

做法：
    在桌宠窗口内挂一个透明子 QWidget，每帧按 psutil 采样的上下行速率：
      - 【下载】速率 < MIN_SHOW_BPS → 隐藏
      - 否则显示在人物脚底下方（留 GAP_BELOW_FOOT 缝隙），绘制 ↑/↓ 文本
      - 位置用指数插值平滑跟随（EASE），避免脚部逐帧抖动导致跳变
    子控件自行 paintEvent，不干扰桌宠自身渲染；所有异常一律吞掉。

调参入口：改下方「可调参数」区，重启桌宠即可生效（无需重新打补丁）。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

# ---- 可调参数 ------------------------------------------------------
MIN_SHOW_BPS = 30 * 1024         # 仅当【下载】速率 > 此值才显示
SAMPLE_INTERVAL = 0.5            # 采样节流（秒）
SMOOTH = 3                       # 滑动平均窗口
FONT_PT = 7.0                    # 字号（小一号，便于整条塞进脚底下方）
GAP_BELOW_FOOT = 2               # 胶囊顶边距脚底像素（留出缝隙）
BOTTOM_MARGIN = 1                # 胶囊底边距窗口底边像素（防溢出被裁）
WIDGET_PAD = 0                   # 子控件与胶囊同尺寸（不再外扩）
EASE = 0.42                      # 位置插值系数（越小越顺滑、越大越跟手）

COL_UP = (0xF5, 0x9E, 0x0B)      # 上传：琥珀
COL_DOWN = (0x25, 0x63, 0xEB)    # 下载：蓝
COL_BG = (12, 14, 20, 170)
COL_BORDER = (255, 255, 255, 46)

_ST = {
    "t": 0.0,
    "last": None,
    "up": 0.0,
    "down": 0.0,
    "win": [],
    "psutil": None,
    "tried": False,
    "widget": None,
    "pet": None,
    "n": 0,
}


def _log(msg):
    """自检日志（无缓冲直写）。异常吞掉。"""
    try:
        p = os.path.join(os.environ.get("LOCALAPPDATA", "."),
                         "dsh-pet-standalone-webm", "nso-final.log")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.write(fd, ("%d %s\n" % (os.getpid(), msg)).encode("utf-8"))
        os.close(fd)
    except Exception:
        pass


def _get_psutil():
    if not _ST["tried"]:
        _ST["tried"] = True
        try:
            import psutil
            _ST["psutil"] = psutil
        except Exception:
            _ST["psutil"] = None
    return _ST["psutil"]


# ---- 采样 ----------------------------------------------------------
def _sample():
    ps = _get_psutil()
    if ps is None:
        return 0.0, 0.0
    now = time.monotonic()
    if _ST["t"] and (now - _ST["t"]) < SAMPLE_INTERVAL:
        return _ST["up"], _ST["down"]
    try:
        io = ps.net_io_counters()
    except Exception:
        return _ST["up"], _ST["down"]
    prev, prev_t = _ST["last"], _ST["t"]
    _ST["last"] = (io.bytes_sent, io.bytes_recv)
    _ST["t"] = now
    if prev is None or not prev_t:
        return 0.0, 0.0
    dt = now - prev_t
    if dt <= 0.01:
        return _ST["up"], _ST["down"]
    up = max(0.0, (io.bytes_sent - prev[0]) / dt)
    down = max(0.0, (io.bytes_recv - prev[1]) / dt)
    w = _ST["win"]
    w.append((up, down))
    if len(w) > SMOOTH:
        del w[0]
    _ST["up"] = sum(a for a, _ in w) / len(w)
    _ST["down"] = sum(b for _, b in w) / len(w)
    return _ST["up"], _ST["down"]


def _num(v):
    if v >= 1000:
        return "%.0f" % v
    if v >= 100:
        return "%.1f" % v
    return "%.2f" % v


def fmt_speed(bps):
    if not bps or bps <= 0:
        return "0", "B/s"
    if bps >= 1024 ** 3:
        return _num(bps / 1024 ** 3), "GB/s"
    if bps >= 1024 ** 2:
        return _num(bps / 1024 ** 2), "MB/s"
    if bps >= 1024:
        return _num(bps / 1024), "KB/s"
    return "%.0f" % bps, "B/s"


# ---- 子控件 --------------------------------------------------------
class _Overlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._up = 0.0
        self._down = 0.0

    def set_rates(self, up, down):
        if up != self._up or down != self._down:
            self._up, self._down = up, down
            self.update()

    def paintEvent(self, _ev):
        try:
            p = QPainter(self)
            _paint(p, self.width(), self.height(), self._up, self._down)
            p.end()
        except Exception:
            pass


def _ensure_widget(pet):
    w = _ST["widget"]
    try:
        if w is not None and w.parent() is pet:
            return w
    except Exception:
        pass
    w = _Overlay(pet)
    _ST["widget"] = w
    w.show()
    return w


# 胶囊内边距（水平 / 垂直）—— 尺寸计算与绘制共用，必须一致
PAD_X, PAD_Y = 6, 0


def _metrics(up, down):
    """返回 (w_up, w_sep, w_dn, fm)。字体与 tick/_paint 共用，避免错位。"""
    from PySide6.QtGui import QFontMetrics
    font = QFont()
    font.setPointSizeF(FONT_PT)
    font.setBold(True)
    fm = QFontMetrics(font)
    us, uu = fmt_speed(up)
    ds, du = fmt_speed(down)
    return (fm.horizontalAdvance("\u2191 %s %s" % (us, uu)),
            fm.horizontalAdvance("   "),
            fm.horizontalAdvance("\u2193 %s %s" % (ds, du)),
            fm)


def _capsule_size(up, down):
    """胶囊整体尺寸（= 子控件尺寸）。"""
    w_up, w_sep, w_dn, fm = _metrics(up, down)
    return (int(w_up + w_sep + w_dn + PAD_X * 2),
            int(fm.height() + PAD_Y * 2 + 2))

def _paint(painter, w, h, up, down):
    w_up, w_sep, w_dn, fm = _metrics(up, down)
    us, uu = fmt_speed(up)
    ds, du = fmt_speed(down)
    up_txt = "\u2191 %s %s" % (us, uu)
    dn_txt = "\u2193 %s %s" % (ds, du)

    font = QFont()
    font.setPointSizeF(FONT_PT)
    font.setBold(True)
    painter.setFont(font)

    pad_x, pad_y = PAD_X, PAD_Y
    tw = w_up + w_sep + w_dn + pad_x * 2
    thh = fm.height() + pad_y * 2

    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 子控件与胶囊同尺寸；仍居中以免浮点误差导致偏移
    ox = (w - tw) / 2.0
    oy = (h - thh) / 2.0
    r = thh / 2.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(*COL_BG))
    painter.drawRoundedRect(QRectF(ox, oy, tw, thh), r, r)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(*COL_BORDER), 1.0))
    painter.drawRoundedRect(QRectF(ox + 0.5, oy + 0.5, tw - 1, thh - 1),
                            (thh - 1) / 2.0, (thh - 1) / 2.0)

    ty = oy + pad_y + fm.ascent()
    painter.setPen(QColor(*COL_UP))
    painter.drawText(int(round(ox + pad_x)), int(round(ty)), up_txt)
    painter.setPen(QColor(*COL_DOWN))
    painter.drawText(int(round(ox + pad_x + w_up + w_sep)),
                     int(round(ty)), dn_txt)


def _foot_local(pet):
    """返回 (cx, bottom_y)（窗口局部逻辑坐标）。"""
    try:
        rect = pet.character_local_region()
    except Exception:
        return None
    if rect is None or rect.isEmpty():
        return None
    return float(rect.center().x()), float(rect.bottom())


def tick(pet):
    """由 PetWindow._on_frame 每帧调用。异常一律吞掉。"""
    try:
        if pet is None:
            return
        _ST["pet"] = pet
        _ST["n"] += 1
        up, down = _sample()
        widget = _ensure_widget(pet)
        if down < MIN_SHOW_BPS:          # 仅看下载速率
            if widget.isVisible():
                widget.hide()
            return
        anchor = _foot_local(pet)
        if anchor is None:
            return
        cx, by = anchor
        w, h = _capsule_size(up, down)

        pw, ph = pet.width(), pet.height()

        # 水平：以脚底为中心，钳制在窗口内
        tx = int(cx - w / 2.0)
        tx = max(0, min(tx, pw - w))

        # 垂直：胶囊顶边贴脚底下方，保留 GAP_BELOW_FOOT 缝隙
        ty = int(by + GAP_BELOW_FOOT)
        # 若下方放不下（脚底太靠窗口下沿），则整体上移到窗口内底部
        if ty + h > ph - BOTTOM_MARGIN:
            ty = ph - BOTTOM_MARGIN - h
        ty = max(0, ty)

        # ---- 丝滑跟随：指数趋近目标位置（每帧向目标靠近 EASE 比例）----
        # 位置与尺寸分开处理：尺寸立即生效（否则文字会拉伸变形），
        # 位置用插值平滑，消除脚部动画带来的逐帧抖动。
        cur_w, cur_h = widget.width(), widget.height()
        if cur_w <= 0 or cur_h <= 0:
            widget.setGeometry(tx, ty, w, h)          # 首帧直接就位
        else:
            cx0, cy0 = widget.x(), widget.y()
            nx = tx if abs(tx - cx0) < 0.6 else cx0 + (tx - cx0) * EASE
            ny = ty if abs(ty - cy0) < 0.6 else cy0 + (ty - cy0) * EASE
            widget.setGeometry(int(round(nx)), int(round(ny)), w, h)

        widget.set_rates(up, down)
        if not widget.isVisible():
            widget.show()
        widget.raise_()
    except Exception as e:
        if _ST["n"] < 5:
            _log("tick EXC %r" % (e,))


def ping(pet=None):
    """兼容旧挂载点：等同于 tick。"""
    if pet is not None:
        tick(pet)


def draw(*a, **k):
    """兼容旧挂载点（paintEvent 不触发时不会被调用）。"""
    pass


def probe(*a, **k):
    pass
