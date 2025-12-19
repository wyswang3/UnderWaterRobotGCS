

---

```md
# GCS ↔ ROV 通信协议规范  
# GCS ↔ ROV Communication Protocol Specification

> Version: v0-gcs-foundation  
> Transport: UDP  
> Reliability: Application-layer (Session + ACK + CRC)  

---

## 1. 设计目标 / Design Goals

### 中文

本协议用于 **上位机（GCS）与水下机器人（ROV）之间的实时控制与状态通信**，设计目标如下：

- 在 **UDP** 之上提供工程可用的可靠性
- 支持实时控制（低延迟、高频）
- 支持状态遥测（Telemetry）
- 明确区分 **控制意图（Intent）** 与 **执行逻辑**
- 适用于真实水下实验，而非仅仿真

### English

This protocol defines the **communication interface between a Ground Control Station (GCS) and an underwater ROV**, with the following goals:

- Provide practical reliability on top of **UDP**
- Support low-latency, high-rate control commands
- Support periodic telemetry feedback
- Clearly separate **control intent** from actuation
- Suitable for real-world underwater experiments

---

## 2. 总体架构 / Overall Architecture

```

GCS (Python)
├─ Session Client
├─ Protocol Codec
├─ UDP Transport
│
│  (UDP packets)
▼
ROV (OrangePi / C++)
├─ comm_gcs Session Server
├─ Control Intent Adapter
├─ Controller / Allocator
└─ STM32 Thruster Driver

```

- **GCS 是客户端（Client）**
- **ROV 是会话服务器（Session Server）**
- 所有控制命令均基于 Session ID

---

## 3. 字节序与 CRC / Endianness & CRC

### 字节序 / Endianness

- **Host Endian（实际为 Little Endian）**
- Python 实现中使用 `<`（little-endian）
- C++ 实现直接使用结构体内存布局

> ⚠️ 当前协议假设 ARM64 / x86_64，小端系统

### CRC 校验 / CRC Check

- 使用 **CRC32C (Castagnoli)**
- 多项式：`0x1EDC6F41`（反射形式 `0x82F63B78`）
- 两处 CRC：
  - Header CRC（header_crc32c）
  - Payload CRC（payload_crc32c）

---

## 4. 数据包总结构 / Packet Structure

### 4.1 Packet Layout

```

┌──────────────────────────┐
│ PacketHeader (40 bytes)  │
├──────────────────────────┤
│ Payload (0 ~ 1024 bytes) │
└──────────────────────────┘

````

---

## 5. PacketHeader 定义 / PacketHeader Definition

### 5.1 C++ 定义（参考）

```cpp
struct PacketHeader {
    uint32_t magic;
    uint16_t version;
    uint8_t  msg_type;
    uint8_t  reserved0;
    uint16_t flags;
    uint16_t reserved1;
    uint32_t seq;
    uint64_t session_id;
    uint32_t payload_len;
    uint32_t send_time_ms;
    uint32_t header_crc32c;
    uint32_t payload_crc32c;
};
````

### 5.2 字段说明 / Field Description

| 字段             | 类型  | 说明                 |
| -------------- | --- | ------------------ |
| magic          | u32 | 魔数，固定              |
| version        | u16 | 协议版本               |
| msg_type       | u8  | 消息类型               |
| flags          | u16 | ACK / 控制标志         |
| seq            | u32 | 序列号                |
| session_id     | u64 | 会话 ID              |
| payload_len    | u32 | 负载长度               |
| send_time_ms   | u32 | 发送时间（steady clock） |
| header_crc32c  | u32 | Header CRC         |
| payload_crc32c | u32 | Payload CRC        |

---

## 6. 消息类型 / Message Types

### 6.1 枚举定义 / Enumeration

| MsgType         | 值   | 方向        | 说明       |
| --------------- | --- | --------- | -------- |
| CONNECT_REQ     | 1   | GCS → ROV | 会话请求     |
| CONNECT_ACK     | 2   | ROV → GCS | 会话确认     |
| CONNECT_CONFIRM | 3   | GCS → ROV | 会话确认完成   |
| HEARTBEAT       | 4   | 双向        | 心跳       |
| SET_MODE        | 10  | GCS → ROV | 切换控制模式   |
| SET_DOF_CMD     | 11  | GCS → ROV | 6-DOF 控制 |
| ESTOP           | 12  | GCS → ROV | 急停       |
| STATUS          | 20  | ROV → GCS | 状态遥测     |
| ACK             | 250 | 双向        | 确认帧      |

---

## 7. 会话机制 / Session Mechanism

### 7.1 会话流程 / Handshake Flow

```
GCS → CONNECT_REQ (gcs_nonce)
ROV → CONNECT_ACK (session_id, rov_nonce)
GCS → CONNECT_CONFIRM (rov_nonce_echo)
```

* session_id 由 ROV 生成
* 会话成功后：

  * ROV: established = true
  * GCS: 保存 session_id

### 7.2 会话规则 / Rules

* **控制命令必须携带正确 session_id**
* seq 必须严格递增（≤ 上一次将被拒绝）
* HEARTBEAT 允许 session_id = 0（可选）

---

## 8. ACK 机制 / ACK Mechanism

### 8.1 Flags

| Flag         | 含义     |
| ------------ | ------ |
| FLAG_ACK_REQ | 请求 ACK |
| FLAG_IS_ACK  | ACK 包  |

### 8.2 AckPayload

```cpp
struct AckPayload {
    uint32_t ack_seq;
    uint16_t ack_code;
    uint16_t reason;
};
```

### 8.3 AckCode

| Code            | 含义       |
| --------------- | -------- |
| OK              | 成功       |
| BAD_FORMAT      | 格式错误     |
| CRC_FAIL        | CRC 校验失败 |
| INVALID_SESSION | 会话错误     |
| SEQ_OLD_OR_DUP  | 序列号重复    |
| NOT_SUPPORTED   | 不支持      |

---

## 9. 控制命令 / Control Commands

### 9.1 SET_DOF_CMD

* Payload: `float[6]`
* 顺序：

  ```
  surge, sway, heave, roll, pitch, yaw
  ```
* 取值范围：`[-1.0, 1.0]`
* 高频发送，**默认不请求 ACK**

### 9.2 SET_MODE

* Manual / Auto / Failsafe
* Auto 模式可指定控制器名称（字符串）

### 9.3 ESTOP

* enable = 1：急停
* enable = 0：解除急停
* **最高优先级**

---

## 10. STATUS 遥测 / STATUS Telemetry

### 10.1 C++ 结构

```cpp
struct StatusTelemetry {
    uint8_t session_established;
    uint8_t link_alive;
    uint8_t estop;
    uint8_t reserved0;

    uint8_t mode;
    uint8_t reserved1;
    uint16_t reserved2;

    char active_controller[16];
    char desired_controller[16];

    uint32_t consecutive_failures;
    uint32_t auto_fail_limit;

    uint64_t t_ns;
};
```

### 10.2 语义说明

* session_established：会话状态
* link_alive：链路健康
* estop：急停状态
* mode：当前控制模式
* controller：当前/期望控制器
* t_ns：ROV 本地时间戳

---

## 11. 安全设计 / Safety Design

### 中文

* 会话丢失 → 自动进入 failsafe
* 命令过期（TTL）→ 丢弃
* 急停优先级最高
* GCS 不直接控制推进器

### English

* Session loss triggers failsafe
* Expired commands are rejected
* ESTOP overrides everything
* GCS never drives thrusters directly

---

## 12. 向后兼容 / Compatibility

* Header 预留字段支持扩展
* 新消息类型不影响旧实现
* 建议保持 wire struct ABI 不变

---

## 13. 参考实现 / Reference Implementations

* C++: `comm_gcs::session::GcsSession`
* Python: `urogcs.session.session_client`
* CRC: `crc32c.cpp / crc32c.py`

---

**End of Protocol Specification**

```

---