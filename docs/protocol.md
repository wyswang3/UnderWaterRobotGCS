# GCS 端口、会话与控制接口说明
# GCS Port, Session, and Control Interface Guide

> Audience:
> GCS developers, UI developers, protocol maintainers, and integration engineers.
>
> Purpose:
> Make the current Python GCS implementation, wire contract, runtime operation modes,
> and next upgrade direction explicit and aligned with code.

---

## 1. 文档范围 / Scope

本文档描述的是 **`UnderWaterRobotGCS` 当前代码真实实现**，重点覆盖：

- GCS 当前在系统中的角色
- 默认端口与 bind 策略
- TUI / GUI / ROS2 preview 三条使用 lane
- UDP session + ACK + STATUS 的真实协议实现
- 当前控制模式切换语义
- 上位机开发时应遵守的边界
- 后续升级时建议怎么继续演进

不在本文详述的内容：

- ROV 侧 `gcs_server` / `pwm_control_program` 的内部实现
- 系统级 operator bring-up 总流程
- 控制侧最终安全裁决

---

## 2. 当前系统角色 / Current Role In The System

当前已经验证的 GCS 主链如下：

```text
GCS TUI / GUI
  -> GcsService
  -> GcsSessionClient
  -> UDP
  -> OrangePi gcs_server
  -> GCS Intent SHM
  -> pwm_control_program
```

关键边界：

- GCS 发送的是 **control intent**，不是最终 PWM。
- GCS 可以请求 `Manual / Auto / Failsafe / Arm / Disarm / E-Stop / 6DOF`。
- **最终是否接受** 由 ROV 侧 authority 决定。
- stale、navigation gating、failsafe、PWM safety 都不在 GCS 内部决定。

In short:

- GCS is an intent client and runtime observer.
- The ROV remains the final safety and execution authority.

---

## 3. 当前运行 lane / Current Operation Lanes

### 3.1 TUI primary lane

当前主控制面是 TUI：

- 可握手
- 可发心跳
- 可发 `SET_MODE / ARM / ESTOP / SET_DOF`
- 可实时显示 runtime STATUS
- 支持键盘 teleop

这是当前默认、最成熟、最接近现场控制的 GCS lane。

### 3.2 GUI observer lane

GUI 当前是 **read-only overview dashboard**：

- 默认会建立 UDP session 并读取状态
- 默认使用临时本地端口 `bind_port=0`
- 可以和 TUI 同时运行，避免抢占固定端口
- 当前不承担键盘 teleop 主职责

代码依据：

- `src/urogcs/app/gui/gui_env.py`
- `src/urogcs/app/gui/overview_presenter.py`
- `scripts/run_gui.sh`

GUI current positioning:

- observer first
- control later, only after semantics and safety UX are explicit

### 3.3 ROS2 preview lane

当前接入代码的是 **GUI 的 ROS2 mirror preview** 数据源：

- 仅用于外围镜像观察
- 只消费 `/rov/telemetry` 等 mirror topic
- 不发送控制、不发心跳、不参与最终安全决策

代码依据：

- `src/urogcs/telemetry/ros2_mirror_source.py`

---

## 4. 默认端口与 bind 策略 / Default Ports And Bind Policy

### 4.1 Defaults in code

当前默认值如下：

| 项目 | 默认值 | 位置 |
| --- | --- | --- |
| ROV UDP 目标端口 | `14550` | `tui_env.py` / `gui_env.py` |
| TUI 本地 bind 端口 | `14551` | `tui_env.py` |
| GUI 本地 bind 端口 | `0` | `gui_env.py` |
| TUI poll 频率 | `50 Hz` | `tui_env.py` |
| TUI send 频率 | `20 Hz` | `tui_env.py` |
| Heartbeat | `2 Hz` | `tui_env.py` / `gui_env.py` |

### 4.2 Why GUI uses bind port `0`

GUI 默认使用临时端口是刻意设计：

- TUI 是主控制 lane，使用固定端口便于防火墙与排障
- GUI 是观测 lane，不应与 TUI 抢本地固定端口

因此：

- `TUI -> bind_port=14551`
- `GUI -> bind_port=0`

### 4.3 Environment variables

常用环境变量：

- `UROGCS_ROV_IP`
- `UROGCS_ROV_PORT`
- `UROGCS_BIND_IP`
- `UROGCS_BIND_PORT`
- `UROGCS_GUI_BIND_IP`
- `UROGCS_GUI_BIND_PORT`
- `UROGCS_SESSION_DEBUG`
- `UROGCS_POLL_HZ`
- `UROGCS_HEARTBEAT_HZ`
- `UROGCS_HANDSHAKE_TIMEOUT_S`

Debug session logging:

- CLI flag: `--debug-session`
- env: `UROGCS_SESSION_DEBUG=1`

---

## 5. 代码入口 / Key Code Entry Points

推荐开发阅读顺序：

1. `src/urogcs/core/service.py`
2. `src/urogcs/session/session_client.py`
3. `src/urogcs/protocol/wire.py`
4. `src/urogcs/protocol/codec.py`
5. `src/urogcs/protocol/messages.py`
6. `src/urogcs/app/tui/tui_loop.py`
7. `src/urogcs/app/gui/overview_presenter.py`

职责分层如下：

- `GcsService`
  - UI/调用层统一接口
- `GcsSessionClient`
  - UDP + handshake + STATUS/ACK 维护
- `wire.py`
  - 固定枚举、header layout、常量
- `codec.py`
  - 编解码与 CRC
- `messages.py`
  - 上层 payload model 与 runtime helper

---

## 6. 会话机制 / Session Mechanism

### 6.1 握手流程

当前真实实现是三步握手：

```text
GCS -> CONNECT_REQ(gcs_nonce)
ROV -> CONNECT_ACK(gcs_nonce_echo, rov_nonce, ...)
GCS -> CONNECT_CONFIRM(rov_nonce_echo)
```

建立后：

- GCS 保存 `session_id`
- 后续控制命令都带该 `session_id`
- `STATUS.session_established=1` 作为运行态确认信号之一

### 6.2 Session rules

- `session_id` 由 ROV 生成
- 命令使用严格递增的 `seq`
- `HEARTBEAT` 可以带当前 session，也可以不带
- GCS 端把 `session_established` 与 `session_id` 维护在 `GcsServiceState`

### 6.3 Why GCS has both handshake state and STATUS state

原因是当前 UI 需要区分两层事实：

1. 本地 UDP/session 是否已经握手成功
2. ROV runtime 是否已经通过 `STATUS` 回报“会话建立且链路活着”

所以开发时不要把：

- local handshake success
- remote runtime healthy

当成同一个概念。

---

## 7. Packet Header 与基础协议 / Packet Header And Wire Basics

### 7.1 Header layout

当前 Python 端与 C++ 对齐的 `PacketHeader` 大小是 **48 bytes**：

```cpp
u32 magic
u16 version
u8  msg_type
u8  reserved0
u16 flags
u16 reserved1
u32 seq
u64 session_id
u32 payload_len
u32 ack_seq
u32 send_time_ms
u32 reserved2
u32 header_crc32c
u32 payload_crc32c
```

Python 实现位置：

- `src/urogcs/protocol/wire.py`

### 7.2 Endianness

当前 Python codec 使用 little-endian：

- `struct.Struct("<...")`

文档口径上应理解为：

- current contract assumes little-endian Linux hosts

### 7.3 CRC

当前协议使用 **CRC32C**，同时校验：

- header CRC
- payload CRC

实现位置：

- `src/urogcs/protocol/crc32c.py`
- `src/urogcs/protocol/codec.py`

---

## 8. 当前消息类型 / Current Message Types

真实枚举见 `wire.py`：

| MsgType | 数值 | 方向 | 说明 |
| --- | --- | --- | --- |
| `CONNECT_REQ` | `1` | GCS -> ROV | 握手请求 |
| `CONNECT_ACK` | `2` | ROV -> GCS | 握手确认 |
| `CONNECT_CONFIRM` | `3` | GCS -> ROV | 握手完成确认 |
| `HEARTBEAT` | `10` | 双向 | 心跳 |
| `SET_MODE` | `20` | GCS -> ROV | 模式请求 |
| `SET_DOF_CMD` | `21` | GCS -> ROV | 高频 6DOF 命令 |
| `ESTOP` | `22` | GCS -> ROV | 急停请求 |
| `ARM` | `23` | GCS -> ROV | Arm/Disarm 请求 |
| `STATUS` | `40` | ROV -> GCS | 状态遥测 |
| `ACK` | `250` | 双向 | 确认包 |

### 8.1 Flags

当前只使用两类 flag：

- `ACK_REQ`
- `IS_ACK`

---

## 9. 控制命令与 ACK 策略 / Command Semantics And ACK Policy

### 9.1 `SET_DOF_CMD`

- payload: `float[6]`
- 顺序：
  - `surge, sway, heave, roll, pitch, yaw`
- 范围通常是 `[-1.0, 1.0]`
- 默认 **不请求 ACK**

原因：

- 高频 teleop 不应被 ACK 流量放大

### 9.2 `SET_MODE`

- mode: `Manual / Auto / Failsafe`
- `Auto` 还可带 `auto_controller` 字符串
- 当前 TUI 发 `Auto` 时默认 controller name 为空串
- 默认请求 ACK

重要语义：

- GCS 发的是 **mode request**
- remote runtime 才决定是否真正进入该 mode

### 9.3 `ESTOP`

- `enable=1`：请求急停
- `enable=0`：请求解除急停
- 默认请求 ACK

注意：

- GCS 可以请求 clear estop
- 但 remote side 可能因为安全前提不满足而不接受

### 9.4 `ARM`

- `armed=True`：请求解锁
- `armed=False`：请求上锁
- 默认请求 ACK

### 9.5 ACK policy summary

| 命令 | 默认 ACK |
| --- | --- |
| `SET_DOF_CMD` | No |
| `SET_MODE` | Yes |
| `ESTOP` | Yes |
| `ARM` | Yes |

这意味着 UI/日志里应明确区分：

1. packet sent
2. ACK received
3. runtime STATUS 真的反映出状态变化

ACK 不等价于 mode/arm/runtime 已经真正生效。

---

## 10. 控制模式语义 / Control Mode Semantics

### 10.1 Wire enum

当前 `WireControlMode`：

- `Unknown = 0`
- `Manual = 1`
- `Auto = 2`
- `Failsafe = 3`

### 10.2 Local requested mode vs remote actual mode

当前 TUI/UI 里存在两个层次：

- `local_mode`
  - 本地最近一次请求的模式
- `remote_mode`
  - 远端 STATUS 当前报告的实际模式

因此开发时必须接受下面这种情况：

- local request is `Auto`
- remote status remains `Manual` or `Failsafe`

这通常不是 GCS bug，而是 remote side 拒绝了切换请求。

### 10.3 Current mode switching expectations

#### Manual

当前主操作模式。

适合：

- teleop
- bring-up
- bench 验证
- 最小联调

#### Auto

当前只能理解为 **request Auto / hold-controller lane**，不是完整任务自治。

只有在 remote side 满足前提时才可能真正进入：

- navigation trusted
- mode preconditions satisfied
- controller available

如果这些条件不满足，GCS 应继续把 remote-reported mode 当成真相。

#### Failsafe

可由：

- remote side 主动进入
- GCS 显式请求进入

但一旦 remote runtime 已经处于 failsafe，恢复路径仍要看 remote safety policy。

---

## 11. TUI 当前真实操作语义 / Actual TUI Behavior

代码位置：

- `src/urogcs/app/tui/tui_loop.py`
- `src/urogcs/app/tui/tui_keys.py`
- `src/urogcs/control/keyboard_mapper.py`

### 11.1 Current discrete keys

| 键位 | 当前语义 |
| --- | --- |
| `space` | toggle estop |
| `m` | clear estop + center DOF |
| `,` / `，` | arm |
| `.` / `。` | disarm |
| `1` | request Manual |
| `2` | request Auto |
| `3` | request Failsafe |
| `-` / `_` | throttle down |
| `=` / `+` | throttle up |
| `z` | help |
| `esc` | exit |

### 11.2 Current motion keys

| 键位 | DOF |
| --- | --- |
| `w/s` | surge +/- |
| `a/d` | sway -/+ |
| `h/g` | heave +/- |
| `q/e` | yaw +/- |
| `r/t` | roll +/- |
| `f/v` | pitch +/- |

### 11.3 One-key-only motion rule

当前产品化基线明确要求：

- **一次只接受一个运动键**
- 多个运动键同时按下时，该 tick 的运动输入会被忽略
- DOF 只做衰减回零

原因：

- 减少运动学意图不透明
- 降低瞬时功耗和操作误读

这条规则已经在 `KeyboardMapper` 里实现，不是文档建议，而是代码事实。

### 11.4 Windows behavior

Windows 当前可以运行 GCS，但键盘 teleop 不是正式 lane：

- `KeyboardMapper` 在 Windows 下返回全零 DOF
- 当前 Windows 更适合观测、调试、协议开发

所以不要把 Windows 当前行为宣传成完整 teleop lane。

---

## 12. GUI 当前真实语义 / Actual GUI Behavior

GUI 入口：

- `python -m urogcs.app.gui_main`

常用参数：

- `--no-auto-connect`
- `--telemetry-source udp|ros2`
- `--debug-session`

当前 GUI 是：

- overview dashboard
- status / motion observer
- fault / advisory observer

不是：

- keyboard teleop replacement
- final control console

`overview_presenter.py` 已明确写死当前口径：

- Primary lane: supervisor + GCS TUI teleop
- GUI is read-only status/motion observer

---

## 13. STATUS 遥测语义 / STATUS Telemetry Semantics

### 13.1 Current compatibility strategy

Python 侧 `decode_status()` 当前兼容三种 payload layout：

- legacy
- v1
- v2

这意味着 GCS 当前承担一部分兼容层职责，而不是只接受单一最新版结构。

### 13.2 Current fields used by UI

当前 UI/alarms 重点消费：

- `session_established`
- `link_alive`
- `armed`
- `estop`
- `mode`
- `failsafe_active`
- `nav_valid`
- `nav_state`
- `nav_stale`
- `nav_degraded`
- `nav_fault_code`
- `nav_status_flags`
- `active_controller`
- `desired_controller`
- `command_status`
- `last_fault_code`

### 13.3 Capability display rule

GUI/TUI 当前关于 Motion Info 的显示已按 runtime nav 约束收紧：

- 不是“设备在线 = 导航可用”
- 只有 fresh runtime nav 才允许升级能力显示
- `IMU online` 但 `nav invalid/stale` 时，仍只显示 `Control Only`

代码位置：

- `src/urogcs/telemetry/ui_viewmodels.py`

---

## 14. 开发边界 / Engineering Boundaries

GCS 端当前负责：

- intent expression
- session management
- protocol encode/decode
- runtime status observation
- UI advisory and developer diagnostics

GCS 当前不负责：

- final safety arbitration
- final nav trust decision
- final mode acceptance
- PWM protection
- ROS2 safety authority

如果某个 GCS 改动试图把这些 authority 拉到上位机，方向就是错的。

---

## 15. 后续升级建议 / Recommended Next Upgrade Direction

### 15.1 Near-term

优先继续收口：

1. 明确 `local request` 与 `remote actual` 的 UI 表达
2. 继续强化 command sent / ack / runtime executed 三层可观测性
3. 让 GUI 在不接管控制 authority 的前提下复用更多 TUI runtime guidance
4. 稳住 ROS2 mirror 的只读边界

### 15.2 Medium-term

可以考虑推进：

1. Auto controller name 的明确 UI 入口
2. 更清晰的 command result timeline
3. MotorTest 协议接入
4. 更显式的 mode switch precondition hint

### 15.3 Explicit non-goals for now

当前不应提前承诺：

- GUI 直接替代 TUI 成为主控制面
- 在 ROS2 上发送控制权威命令
- 把 GCS 变成最终安全决策层
- 把 Auto 描述成完整自主导航/任务层

---

## 16. Quick Reference

### Developer commands

TUI:

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_tui.sh
```

TUI with session debug:

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_tui.sh --debug-session
```

GUI:

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_gui.sh
```

GUI with ROS2 preview:

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
PYTHONPATH=src python -m urogcs.app.gui_main --telemetry-source ros2 --no-auto-connect
```

### Key reminder

- TUI is the current control lane.
- GUI is the current observer lane.
- GCS requests modes; ROV decides actual runtime mode.
