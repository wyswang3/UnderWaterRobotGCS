# 上位机（GCS）操作与开发对照指南
# GCS Operator And Developer-Oriented Guide

> Audience:
> operators, bring-up engineers, and GCS developers who need the real current behavior.
>
> Goal:
> describe how to launch the current GCS, how to switch modes correctly,
> and how to interpret what the UI is telling you.

---

## 1. 先理解当前产品形态 / Understand The Current Product Shape First

当前 GCS 不是“一个统一 GUI 控制台”，而是两条 lane：

1. **TUI**
   - 当前主控制面
   - 当前主 teleop lane
   - 支持键盘控制、模式切换、arm/disarm、estop
2. **GUI**
   - 当前只读 overview dashboard
   - 主要用于状态观察、Motion Info、Fault Summary、advisory

Therefore:

- 想真实控制机器人，用 TUI
- 想同时观察状态，可并行开 GUI

---

## 2. 默认网络与端口 / Default Network And Ports

默认值：

- ROV IP：`192.168.2.24`
- ROV 端口：`14550`
- TUI bind 端口：`14551`
- GUI bind 端口：`0`（ephemeral）

为什么 GUI 是 `0`：

- 避免和 TUI 抢固定本地端口
- 允许 GUI 与 TUI 同时运行

环境变量覆盖：

- `UROGCS_ROV_IP`
- `UROGCS_ROV_PORT`
- `UROGCS_BIND_PORT`
- `UROGCS_GUI_BIND_PORT`

---

## 3. 启动前检查 / Preflight Checklist

### 3.1 网络

先确认操作员电脑和 OrangePi 在同一局域网：

```bash
ping <OrangePi_IP>
```

若 ping 不通，不要继续排查 GCS UI，先修网络。

### 3.2 ROV 侧准备

ROV 侧至少应有：

- `gcs_server`
- `pwm_control_program`

如果你只看得到 GCS 握手成功，但没有 STATUS，很可能是通信面活着、运行态还没真正起来。

---

## 4. 启动方式 / Launch Paths

### 4.1 TUI

推荐：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_tui.sh
```

需要显式开启 session debug：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_tui.sh --debug-session
```

### 4.2 GUI

推荐：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
bash scripts/run_gui.sh
```

GUI 默认是 observer lane。若只想本地开界面但先不握手：

```bash
cd /home/wys/orangepi/UnderWaterRobotGCS
PYTHONPATH=src python -m urogcs.app.gui_main --no-auto-connect
```

### 4.3 Windows note

Windows 当前不是正式键盘 teleop lane：

- 可以做最小观测和协议开发
- 不要把它当成完整 TUI teleop 替代

---

## 5. 握手成功后你应该看到什么 / What Success Looks Like

正常握手日志大致如下：

```text
[HS] sent CONNECT_REQ
[HS] got CONNECT_ACK ...
[HS] sent CONNECT_CONFIRM
```

TUI 启动成功后应看到：

- `handshake OK`
- `session_id=...`
- HUD 开始刷新

此时还要继续看两件事：

1. `session_established`
2. `link_alive`

握手成功不等于控制链已经健康。

---

## 6. 当前实际操作顺序 / Current Correct Operation Order

当前建议顺序不是“随便按键”，而是：

1. 建立会话
2. 确认 STATUS 在刷新
3. 如有需要，先 clear estop
4. arm
5. 先保持 `Manual`
6. 小幅单键 teleop
7. 再考虑是否请求 `Auto`

一句话版：

> handshake -> status alive -> clear estop -> arm -> Manual small motion -> then evaluate Auto

---

## 7. 模式切换 / Control Mode Switching

### 7.1 当前模式键

TUI 当前不是旧文档里的 `M` 切模式，而是：

- `1` -> request `Manual`
- `2` -> request `Auto`
- `3` -> request `Failsafe`

### 7.2 很重要：本地请求不等于远端已切换

GCS 有两个概念：

- local requested mode
- remote actual mode

你按下 `2` 只是请求 `Auto`。

如果远端 STATUS 仍显示：

- `Manual`
- `Failsafe`

说明 remote side 没接受切换。

### 7.3 为什么 Auto 可能不生效

常见原因：

- 导航不可信
- nav stale / degraded / invalid
- controller 不可用
- arm / estop / mode 前提不满足

因此当前开发和操作口径都应是：

- `Auto` is request-based
- remote runtime mode is authoritative

---

## 8. Arm / Disarm / E-Stop / Clear E-Stop

当前 TUI 离散控制键：

| 键位 | 语义 |
| --- | --- |
| `space` | toggle E-Stop |
| `m` | clear estop + center DOF |
| `,` / `，` | Arm |
| `.` / `。` | Disarm |

注意：

- `space` 是 toggle，不是“按住有效”
- `m` 会同时请求 clear estop，并把本地 DOF 清零
- clear estop 请求不代表 remote 一定立即解除

所以操作上不要只看“按过键了”，要看远端 STATUS 是否真的变化。

---

## 9. 当前键盘 teleop 真实映射 / Actual Keyboard Teleop Mapping

### 9.1 Motion keys

| 键位 | 轴 |
| --- | --- |
| `w/s` | surge +/- |
| `a/d` | sway -/+ |
| `h/g` | heave +/- |
| `q/e` | yaw +/- |
| `r/t` | roll +/- |
| `f/v` | pitch +/- |

### 9.2 Throttle

| 键位 | 动作 |
| --- | --- |
| `-` / `_` | throttle down |
| `=` / `+` | throttle up |

### 9.3 One-key-only rule

当前实现不是自由组合运动，而是：

- 一次只接受一个运动键
- 多个运动键同时按下会被忽略
- 系统按衰减逻辑回零

这是刻意设计，不是 bug。

原因：

- 降低误操作
- 减少运动学含义不透明
- 降低瞬时功耗风险

---

## 10. GUI 该怎么看 / How To Read The GUI Correctly

GUI 当前应被理解为：

- `Connection`：会话与链路状态
- `Devices`：IMU / DVL 观察状态
- `Motion Info`：当前 runtime nav 允许展示到什么层级
- `Control`：armed / mode / failsafe / controller
- `Command`：最近命令与 ACK/runtime 状态
- `Fault Summary`：告警与建议动作

关键提醒：

- GUI 当前不是主控输入面
- GUI footer 已明确写明：primary lane is TUI teleop

---

## 11. 如何理解 Motion Info / How To Read Motion Info

当前 GUI/TUI 不再把“设备在线”直接显示成“完整导航可用”。

显示逻辑是：

- `Control Only`
  - 只有最小状态可依赖
- `Attitude Feedback`
  - IMU 在线且 runtime nav 允许
- `Relative Nav`
  - IMU + DVL 在线且 fresh/valid/not degraded

所以如果你看到：

- IMU/DVL online
- 但 Motion Info 仍是 `Control Only`

这并不必然是 GUI 错了，可能是 runtime nav 当前 stale/invalid。

---

## 12. 常见误判 / Common Misreadings

### 12.1 “我按了 Auto，为什么还在 Manual？”

因为 GCS 只发 request，remote 可能拒绝。

### 12.2 “握手成功了，为什么机器人还不动？”

检查顺序：

1. STATUS 是否在刷新
2. remote 是否 armed
3. remote estop 是否清除
4. 当前 remote mode 是什么
5. failsafe 是否激活

### 12.3 “我同时按两个方向，为什么没反应？”

因为当前 teleop 明确只接受一个运动键。

### 12.4 “Windows 上为什么没法像 Linux 一样键盘飞？”

因为当前 Windows lane 不是正式 keyboard teleop implementation。

---

## 13. 给开发者的升级建议 / Upgrade Notes For Developers

当前 GCS 继续升级时，建议遵守以下顺序：

1. 先稳住 TUI 主控制 lane
2. 把 sent / ack / runtime executed 三层状态表达得更清楚
3. 让 GUI 复用更多运行态 guidance，但不提前接管控制 authority
4. 只把 ROS2 用在只读 mirror / diagnostics
5. Auto controller 选择、MotorTest 等功能在协议明确后再加

当前不建议做的事：

- 把 GUI 直接宣传成主控面
- 在 ROS2 上发送控制 authority
- 让 GCS 承担最终安全裁决

---

## 14. 当前最短提醒 / Short Reminder

> Use TUI to control, use GUI to observe, trust remote STATUS over local wishes, and treat Auto as a gated request rather than a guaranteed state change.
