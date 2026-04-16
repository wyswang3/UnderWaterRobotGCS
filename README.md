# UnderWaterRobotGCS

`UnderWaterRobotGCS` 是当前项目的地面站仓库。

它负责：

- 和机器人侧 `gcs_server` 建立 UDP 会话
- 发送模式切换、ARM / DISARM、E-STOP、6DOF 手动控制命令
- 接收并显示来自控制侧权威 telemetry 的状态
- 为 TUI、GUI、协议调试和回放工具提供统一客户端能力

如果你想知道“键盘是怎么变成控制意图的”“GCS 看到的状态从哪里来”“会话和 ACK 是怎么做的”，应该从这个仓开始。

## 1. 当前系统中的位置

当前已验证的 GCS 控制路径是：

```text
GCS TUI / GUI
  -> protocol encode + session client
  -> UDP
  -> OrangePi gateway/gcs_server
  -> GCS Intent SHM
  -> pwm_control_program
```

GCS 不直接驱动推进器，也不拥有最终安全裁决权。

它发送的是“控制意图”，真正的模式门控、输入过期处理、failsafe 和 PWM 输出都在机器人侧完成。

## 2. 仓库结构

- `src/urogcs/app/`
  - 应用入口
  - 当前常用的是 `tui/tui_main.py`
- `src/urogcs/control/`
  - 键盘/手柄映射和本地安全辅助逻辑
- `src/urogcs/core/`
  - 对上层最重要的服务接口，尤其是 `service.py`
- `src/urogcs/protocol/`
  - 协议字段、编码解码、CRC、消息结构
- `src/urogcs/session/`
  - 会话、握手、ACK 相关逻辑
- `src/urogcs/telemetry/`
  - 遥测模型和 UI 映射
- `src/urogcs/transport/`
  - UDP/TCP 传输和录包
- `src/urogcs/tools/`
  - replay、intent 观察、pcap 导出等工具
- `tests/`
  - 协议、传输、TUI 和诊断相关测试

## 3. 当前最值得先看的代码

如果你是开发者，建议按这个顺序看：

1. `src/urogcs/core/service.py`
2. `src/urogcs/session/session_client.py`
3. `src/urogcs/protocol/messages.py`
4. `src/urogcs/protocol/codec.py`
5. `src/urogcs/app/tui/tui_main.py`
6. `src/urogcs/app/tui/tui_loop.py`
7. `src/urogcs/control/keyboard_mapper.py`

这样你会先看见“对外接口”，再看“协议细节”，最后再看“前端怎么用它”。

## 4. 快速启动

开发环境下推荐直接用模块入口，不依赖额外安装器：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
PYTHONPATH=src python -m urogcs.app.tui.tui_main
```

如果要显式指定机器人地址：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
UROGCS_ROV_IP=<OrangePi_IP> PYTHONPATH=src python -m urogcs.app.tui.tui_main
```

当前默认使用：

- ROV 端口：`14550`
- TUI 本地绑定端口：`14551`
- GUI 本地绑定端口：`0`（临时端口，避免与 TUI 抢占同一端口）

这些默认值位于：

- TUI: `src/urogcs/app/tui/tui_env.py`
- GUI: `src/urogcs/app/gui/gui_env.py`

## 5. 当前已验证的使用方式

当前已经明确验证通过的路径是：

- OrangePi 端先启动 `gcs_server`
- OrangePi 端启动 `pwm_control_program`
- GCS 端运行 TUI
- 在 TUI 里执行 `Manual -> clear estop -> arm -> send dof`

这个流程已经证明：

- 握手可以建立
- 命令能被 `gcs_server` 接收
- 控制侧能据此产出 PWM duty 变化
- telemetry 日志能回显运行态

## 6. GCS 的边界

GCS 只负责以下事情：

- 输入表达
- 会话管理
- 协议封装
- 状态展示

GCS 不负责以下事情：

- 低级 PWM 安全保护
- 手动模式之外的最终控制决策
- 导航可信度判断
- 推进器限斜率和硬件保护

这些能力属于机器人侧。

## 7. 对代码学习者的建议

这个仓库很适合作为“系统工程入门案例”，因为它把几个层次拆得比较清楚：

- `protocol/` 解决“包长什么样”
- `session/` 解决“什么时候认为对端在线”
- `core/service.py` 解决“上层到底怎么调用”
- `app/tui/` 解决“用户输入怎么接上”

不要上来就读 UI 代码。先读 `service.py`，再读 `session_client.py`，理解会快很多。

## 8. 测试入口

当前最有代表性的测试包括：

- `tests/test_codec.py`
- `tests/test_transport_udp.py`
- `tests/test_safety_ttl.py`
- `tests/test_nav_diagnostics.py`
- `tests/test_tui_view.py`
- `tests/test_telemetry_viewmodels.py`

如果你改的是协议或状态映射，这些测试比手工点 UI 更有价值。

## 9. 常用辅助工具

`src/urogcs/tools/` 下当前最值得注意的工具有：

- `intent_watch.py`
  - 观察 intent 流
- `replay.py`
  - 回放相关工具
- `pcap_export.py`
  - 把协议数据导出成网络抓包可分析格式

## 10. 当前 README 的使用原则

这份 README 面向技术开发团队和代码学习者，不是操作工说明书。

如果你要看 GCS 当前操作和协议说明，请先读：

- [docs/operator_guide.md](/home/wys/orangepi/UnderWaterRobotGCS/docs/operator_guide.md)
- [docs/protocol.md](/home/wys/orangepi/UnderWaterRobotGCS/docs/protocol.md)
