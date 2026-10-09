# zqh

个人项目备份仓库。

## 项目列表

### dsh-pet-netspeed — DshPet 桌宠「脚底网速显示」补丁

给 DeepSeek Harness 桌宠 `dsh-pet-standalone-webm`（作者 merzlin，官方 v4.2.1）
在人物脚底加一行实时上下行速率，**仅下载速率 > 30 KB/s 时出现**。

![效果](dsh-pet-netspeed/docs/安装包验证_脚底网速.png)

| 内容 | 链接 |
|---|---|
| 说明文档（原理 / 调参 / 重建步骤 / 踩坑） | [dsh-pet-netspeed/README.md](dsh-pet-netspeed/README.md) |
| 核心运行时覆盖层 | [net_speed_overlay.py](dsh-pet-netspeed/net_speed_overlay.py) |
| 字节码注入工具链 | [inject/](dsh-pet-netspeed/inject) |
| 安装包生成工具链 | [packaging/](dsh-pet-netspeed/packaging) |
| 已打补丁主程序 | [binaries/patched/](dsh-pet-netspeed/binaries/patched) |
| 原始未打补丁主程序 | [binaries/original/](dsh-pet-netspeed/binaries/original) |
| 开发日志 | [docs/2026-10-09.md](dsh-pet-netspeed/docs/2026-10-09.md) |

> 130 MB 的完整安装包未上传（超 GitHub 单文件 100 MB 限制），
> 可按说明文档中的命令自行重建。
