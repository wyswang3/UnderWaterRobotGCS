# UnderWaterRobotGCS

`UnderWaterRobotGCS` 是当前项目的 ground control station 仓库。

它的定位很明确：

- 负责 upper-computer side 的 session、protocol、TUI / GUI、diagnostics tooling
- 把 operator input 变成机器人侧可消费的 control intent
- 展示来自机器人侧 authority telemetry 的状态
- 为后续 GUI、ROS2 preview、replay tooling 提供统一客户端基础

它不拥有最终安全裁决权，也不直接驱动推进器。

## 当前阶段 / Current Status

截至当前阶段，这个仓已经不是“协议演示工程”，而是：

- `TUI` 已经成为当前成熟的 teleop primary lane
- `GUI` 已经具备 overview dashboard 和只读状态观察能力
- protocol / session / ACK / telemetry mapping 已形成可持续维护的代码结构
- ROS2 相关能力仍处于 read-only preview / mirror 边界，不接管 control authority

当前还没有完成的部分主要是：

- 更完整的 GUI operator workflow
- 更强的 command result / ack / runtime executed 可视化
- 更明确的 `Auto` gating feedback

## 仓库用途 / What This Repo Is For

这个仓最适合解决下面三类问题：

1. 键盘、按钮和 mode request 怎样变成 wire message
2. GCS 怎样判断 session alive、remote authority state 和 ack result
3. TUI / GUI 怎样把 telemetry 解释成 operator 可以理解的状态

如果你要理解“上位机看到的状态从哪里来”，这里是主入口。

## 当前系统中的位置

```text
TUI / GUI
  -> core service
  -> session client
  -> protocol codec
  -> UDP
  -> OrangePi gateway/gcs_server
  -> GCS Intent SHM
  -> pwm_control_program
```

当前语义边界：

- GCS 发的是 `requested intent`
- 机器人侧返回的是 `actual authority state`
- `Manual / Auto / Failsafe` 的最终成立与否，由车端 runtime 决定

## 当前推荐阅读顺序

如果你是开发者，先按这个顺序读：

1. `src/urogcs/core/service.py`
2. `src/urogcs/session/session_client.py`
3. `src/urogcs/protocol/messages.py`
4. `src/urogcs/protocol/codec.py`
5. `src/urogcs/app/tui/tui_main.py`
6. `src/urogcs/app/gui/main_window.py`
7. `src/urogcs/control/keyboard_mapper.py`

这样会先看到 public API，再看到 protocol/session，再看到 UI。

## 目录结构 / Repository Layout

- `src/urogcs/app/`
  - TUI、GUI、应用入口
- `src/urogcs/core/`
  - 上层统一服务接口
- `src/urogcs/session/`
  - session、handshake、ack
- `src/urogcs/protocol/`
  - wire format、codec、CRC、message type
- `src/urogcs/control/`
  - keyboard / joystick mapping
- `src/urogcs/telemetry/`
  - telemetry model 和 UI mapping
- `src/urogcs/tools/`
  - replay、intent watch、pcap export、preflight
- `tests/`
  - 协议、transport、TUI、telemetry、diagnostics 相关测试

## 当前操作口径 / Current Operator Semantics

当前默认口径是：

- `TUI` 是主控制入口
- `GUI` 是只读 observer lane
- `Manual` 是当前主用模式
- `Auto` 是 gated request，不保证一定切换成功
- `Failsafe` 是远端 authority state，不是上位机自己决定的本地标签

不要把：

- 本地请求模式
- 远端实际模式
- ack 成功
- 运行态真正执行

这四件事混为一谈。

## Quick Start

开发环境下，最直接的启动方式仍然是：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
PYTHONPATH=src python -m urogcs.app.tui.tui_main
```

如果要显式指定 ROV 地址：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
UROGCS_ROV_IP=<OrangePi_IP> PYTHONPATH=src python -m urogcs.app.tui.tui_main
```

当前默认端口：

- ROV: `14550`
- TUI local bind: `14551`
- GUI local bind: `0`

## 当前最值得关注的测试

如果你改的是 protocol、telemetry 或 UI mapping，优先看：

- `tests/test_codec.py`
- `tests/test_transport_udp.py`
- `tests/test_safety_ttl.py`
- `tests/test_nav_diagnostics.py`
- `tests/test_tui_view.py`
- `tests/test_telemetry_viewmodels.py`

## 文档入口 / Docs

这份 README 面向技术开发者。

当前更具体的 operator / protocol 文档在：

- [docs/operator_guide.md](/home/wys/orangepi/UnderWaterRobotGCS/docs/operator_guide.md)
- [docs/protocol.md](/home/wys/orangepi/UnderWaterRobotGCS/docs/protocol.md)
