
---

````md
# 上位机（GCS）操作员指南  
# Operator Guide – Ground Control Station (GCS)

> 适用对象：  
> **第一次参与水下实验的操作员 / 新人 / 非核心开发人员**  
>  
> 本文档说明：  
> **如何启动上位机（GCS），让其与香橙派（ROV）成功通信，并通过键盘遥控机器人。**

---

## 0. 系统整体说明（先看）

### 中文说明

当前系统采用 **“上位机 + 香橙派 + STM32”** 三层结构：

- **上位机（GCS）**  
  - 运行在操作员电脑上（Windows / Linux）
  - 负责：键盘输入、控制指令发送、状态显示
- **香橙派（OrangePi）**  
  - 运行在机器人本体上
  - 负责：通信、控制逻辑、安全保护
- **STM32**  
  - 只负责最底层 PWM 输出（推进器）

⚠️ **操作员只需要关心 GCS 和香橙派是否“连通”**

---

## 1. 操作前检查清单（Checklist）

在启动任何程序前，请确认：

### 1.1 硬件

- [ ] 机器人已通电
- [ ] 香橙派已启动（指示灯正常）
- [ ] 网络连接正常（网线 / 交换机 / 路由器）
- [ ] 操作员电脑 与 香橙派 在 **同一局域网**

### 1.2 网络确认（非常重要）

在操作员电脑上执行：

```bash
ping <香橙派IP地址>
````

例如：

```bash
ping 192.168.2.24
```

* 能 ping 通 → 继续
* ping 不通 → **不要启动 GCS，先解决网络**

---

## 2. 启动香橙派端程序（ROV 侧）

> ⚠️ 如果香橙派已配置为“开机自启动”，此步骤可跳过
> ⚠️ 如果不确定，请按以下步骤人工启动

### 2.1 SSH 登录香橙派

当前实验环境默认配置如下（如有变更以负责人通知为准）：

- IP 地址：`192.168.2.24`
- 用户名：`orangepi`
- 密码：`orangepi`

```bash
ssh orangepi@<香橙派IP>(192.168.2.24)
用户名：orangepi
密码：orangepi
```


### 2.2 启动通信与控制程序

进入项目目录，例如：

```bash
cd ~/OrangePi_STM32_for_ROV/build
```

启动主程序（示例）：

```bash
./pwm_control_program/pwm_control_program
```

你应该看到类似输出：

```
[INFO] pwm_control_program starting...
[INFO] comm_gcs listening on UDP port XXXX
```

**此时香橙派已进入“等待上位机连接”状态。**

---

## 3. 启动上位机（GCS）

### 3.1 进入 GCS 项目目录

在操作员电脑上：

```bash
cd UnderWaterRobotGCS
```

### 3.2 启动键盘遥控模式（推荐新人）

#### Windows（PowerShell）

```powershell
scripts\run_tui.ps1
```

#### Linux / macOS

```bash
PYTHONPATH=src python -m urogcs.app.tui.tui_main
```

---

## 4. 建立 GCS ↔ ROV 通信（最关键一步）

### 4.1 正常情况（成功）

启动 GCS 后，你应该看到类似日志：

```
[HS] sent CONNECT_REQ
[HS] CONNECT_ACK ok: session_id=12345678
[HS] sent CONNECT_CONFIRM
```

这表示：

* 上位机 与 香橙派 **已成功建立会话**
* 后续控制命令将被接受

### 4.2 异常情况（失败）

| 现象               | 可能原因     | 处理方式        |
| ---------------- | -------- | ----------- |
| 一直无 CONNECT_ACK  | 网络不通     | 检查 IP / 防火墙 |
| INVALID_SESSION  | 香橙派程序未启动 | 回到第 2 步     |
| CRC / BAD_FORMAT | 版本不匹配    | 联系开发人员      |

---

## 5. 键盘遥控说明（Manual Mode）

### 5.1 切换到手动模式

在 GCS 启动后，默认应为 **Manual 模式**。
如需手动切换，请按（示例）：

```
M
```

屏幕状态应显示：

```
Mode: Manual
```

---

### 5.2 键盘控制映射（默认）

| 键位    | 动作             |
| ----- | -------------- |
| W / S | 前进 / 后退（surge） |
| A / D | 左移 / 右移（sway）  |
| Q / E | 上浮 / 下潜（heave） |
| ← / → | 左转 / 右转（yaw）   |
| ↑ / ↓ | 俯仰（pitch）      |
| Z / C | 横滚（roll）       |

> 所有控制量均为 **归一化 [-1, 1]**，非直接 PWM

---

## 6. 急停（ESTOP）操作（必须记住）

### 6.1 触发急停

按下：

```
SPACE
```

效果：

* 所有推进器立即停止
* ROV 进入安全状态
* 状态栏显示 `ESTOP = ON`

### 6.2 解除急停

再次按：

```
SPACE
```

> ⚠️ 解除急停前，请确认周围安全

---

## 7. 状态监控（Telemetry）

GCS 界面会显示以下关键信息：

* Session 状态（是否连接）
* Link Alive（链路是否健康）
* 当前控制模式
* 急停状态
* 时间戳

如果看到：

```
link_alive = false
```

说明通信异常，应立即停止操作。

---

## 8. 常见错误与处理（新人必看）

### 8.1 机器人不动

检查顺序：

1. 是否已建立 Session
2. 是否处于 Manual 模式
3. 是否触发了 ESTOP
4. 香橙派程序是否仍在运行

### 8.2 有延迟 / 抖动

* 检查网络质量
* 确认没有同时运行多个 GCS 实例
* 关闭视频流等高带宽任务

---

## 9. 操作纪律（非常重要）

* ❌ 不要跳过 ESTOP 测试
* ❌ 不要在通信异常时强行操作
* ❌ 不要直接改动香橙派参数
* ✅ 所有异常第一时间汇报

---

## 10. 一句话总结（给新人）

> **看到 CONNECT 成功 → 切到 Manual → 小幅按键测试 → 随时准备 ESTOP**

---

**End of Operator Guide**

```

---
