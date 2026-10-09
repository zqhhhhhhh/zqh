# DshPet 桌宠 · 脚底网速显示补丁

给 DeepSeek Harness 的桌宠 `dsh-pet-standalone-webm`（作者 merzlin，官方 v4.2.1）
在**人物脚底**加一行实时网速显示。

## 效果

![效果](docs/安装包验证_脚底网速.png)

- 显示条件：**下载速率 > 30 KB/s** 才出现，低于阈值自动隐藏
- 格式：`↑ 上行  ↓ 下行`，单位自动 B / KB / MB / GB
- 位置：紧贴人物脚底下方（留 2px 缝隙），随走动平滑跟随
- 颜色：上行琥珀 `#F59E0B`，下行蓝 `#2563EB`
- 尺寸：160×15 px（7pt 字）

## 原理

桌宠是 PyInstaller onedir 打包的 Python 3.11 程序。补丁**直接改其字节码**，
不使用任何外部注入框架：

1. 解析 exe 内嵌的 **PYZ**，取出 `pet.window` 模块的 marshal 字节码
2. 在模块级插入 `import net_speed_overlay as _ns_overlay`
3. 在 `PetWindow._on_frame` 入口插入 `_ns_overlay.tick(self)`
4. 重算 `co_linetable` / `co_exceptiontable` / `co_stacksize` / 跳转偏移
5. 重新压缩写回 PYZ，同步 CArchive 的 `clen/ulen`，逐字节补零保持原长度

运行时由 `net_speed_overlay.py` 在桌宠窗口内挂一个透明子 QWidget 绘制胶囊。
用 `psutil.net_io_counters()` 采样，3 点滑动平均。

### 为什么不用 paintEvent

实测本桌宠运行期 `PetWindow.paintEvent` **不会被调用**（画面由子控件/视频面
独立渲染）。`_on_frame` 每帧必调，故由它驱动。

## 目录

| 路径 | 说明 |
|---|---|
| `net_speed_overlay.py` | **核心**。运行时覆盖层，也是唯一需要调参的文件 |
| `inject/` | 字节码注入工具链 |
| `packaging/` | 安装包生成与验证工具链 |
| `assets/` | 原图标、已换图标的 SFX 模块、SFX 脚本 |
| `binaries/patched/` | 已打补丁的主程序（可直接替换到安装目录使用） |
| `binaries/original/` | 原始未打补丁的主程序（还原用） |
| `docs/` | 效果截图、开发日志 |

## 二进制文件说明

`binaries/original/dsh-pet-standalone-webm.exe`
　原始 v4.2.1 主程序，md5 `a77de512bae71297`

`binaries/patched/dsh-pet-standalone-webm.exe`
　已打补丁，md5 `ca6a06ceb6ba0615`（与原始**长度完全相同**，仅 PYZ 内字节不同）

**手动使用**：把 `patched` 版覆盖到安装目录 `%LOCALAPPDATA%\Programs\dsh-pet-standalone-webm\`，
再把 `net_speed_overlay.py` 放到该目录的 `_internal\` 下，重启桌宠即可。

> 130 MB 的完整安装包未上传（超 GitHub 单文件 100 MB 限制）。
> 需要时按下方「重新生成安装包」自行构建。

## 调参

编辑 `net_speed_overlay.py` 顶部参数区，重启桌宠生效：

```python
MIN_SHOW_BPS   = 30 * 1024   # 显示阈值（字节/秒），只看下行
FONT_PT        = 7.0         # 字号
GAP_BELOW_FOOT = 2           # 与脚部的缝隙（像素）
COL_UP         = (0xF5, 0x9E, 0x0B)   # 上行色
COL_DOWN       = (0x25, 0x63, 0xEB)   # 下行色
EASE           = 0.42        # 位置插值系数
```

⚠️ 桌宠窗口仅 320×195，脚底距下沿只有约 16 px。
`FONT_PT` 调到 8 以上胶囊会被窗口底边裁掉。

## 重新生成

### 1. 打补丁

需要 **xdis**（建议单独 venv）：

```bash
pip install xdis
python inject/_pet_extract.py                       # 从原始 exe 导出模块到 _pet_src/
python inject/_pet_inject.py --target=tick          # 注入，产出 _pet_patched/pet/window.pyc
python _pet_repack.py                               # 写回 exe（脚本内 EXE 常量需指向原始 exe）
```

`_pet_repack.py` 的 `EXE` 常量默认指向本机备份路径，按需修改。

校验（用 3.11 嵌入解释器逐 code object 验 linetable）：

```bash
python inject/_pet_deep311.py
```

### 2. 生成安装包

需要 **WinRAR**（提供 `Rar.exe`）：

```bash
python packaging/_build_pkg.py        # 组装 _pkg/（自动排除 *.prev）
python packaging/_set_sfx_icon.py <原安装包.exe> <Default64.SFX> _sfx64_custom.SFX
python packaging/_make_sfx.py         # 产出 SFX 自解压安装包
python packaging/_verify_sfx.py       # 解压比对校验
python packaging/_test_sfx.py         # 端到端：安装到真实位置并验证
```

`_sfx64_custom.SFX` 已在本仓库 `assets/` 中提供，可直接复用，无需重跑换图标。

## 技术要点（踩坑记录）

完整记录见 `docs/`。

### 三个会导致启动即崩（ACCESS_VIOLATION，无 traceback）的坑

1. **`co_exceptiontable` 必须重定位**
　CPython 3.11 格式：每条 4 个 varint `start, length, target, ((depth<<1)|lasti)`，
　varint **首组为最高位**（大端式），单位是**指令条数**（2 字节）。
　插入指令后，`start`/`target` ≥ 插入点的值要 `+nu_units`。

2. **`co_linetable` 覆盖必须 ≥ `co_code` 长度**
　方法级和**模块级**都不能漏。补 kind=15（无位置信息）字节：
　`0x80 | (15<<3) | (len-1)`。

3. **3.11 方法调用约定**
　必须用编译器同款序列：
　```
　LOAD_GLOBAL (mod_idx*2 + 1)   # 奇数才同时压入 NULL
　LOAD_METHOD (meth_idx)        # 10 字 cache
　<args>
　PRECALL n ; CALL n ; POP_TOP
　```
　写成 `PUSH_NULL + LOAD_GLOBAL(偶数) + LOAD_FAST(self)` 会让 `CALL`
　去调 **module 本身**，报 `'module' object is not callable` 或直接硬崩。

### SFX 安装包换图标

`Rar.exe` 5.50 **不支持 `-iicon`**（那是 WinRAR GUI 功能）。做法是
**先给 SFX 模块换图标，再用 `-sfx<模块>` 打包**：

- 不能直接改最终 SFX —— `SFX = [PE 模块][RAR 数据]`，RAR 数据位置由模块大小决定，
  改 PE 会让偏移失配导致包损坏
- 资源语言实际是 **2052**（简中），`UpdateResourceW` 删除时 lang 必须精确匹配，
  用 0 会报 `WinError 87`；用 `EnumResourceLanguagesW` 拿真值
- ctypes 调 `UpdateResourceW`：`lpType`/`lpName` 用 `c_void_p`，
  `lpData` 用 `create_string_buffer` + `cast` 且保持引用
- `FreeLibrary` 必须设 `argtypes=[HMODULE]`，否则 64 位指针溢出

## 免责

本项目仅对**本地已安装的第三方软件**做字节码级修改，供个人使用。
原程序版权归其作者 **merzlin** 所有。请勿分发原程序本体。
