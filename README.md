好，这里我直接给你一份**可以原样放进 `UnderWaterRobotGCS/README.md` 的正式版 README**。
风格我按 **工程 + 科研双用途** 来写，既不花哨，也经得起长期维护和别人阅读。

你可以 **直接整体复制**，后续我们再逐步细化。

---

```md
# 🌊 UnderWaterRobotGCS

**Ground Control Station (GCS)** for the UnderWaterRobot system.

This repository implements a **ground-side control and monitoring system** for an underwater ROV, designed to communicate with an OrangePi + STM32 onboard control stack via a **custom UDP protocol with session, ACK, and safety guarantees**.

The project is intended for:
- real-world pool / open-water experiments,
- long-duration operation,
- reproducible research and algorithm integration (MPC / RL / teleop).

---

## ✨ Key Features

- ✅ **Reliable UDP protocol**
  - CRC32C (Castagnoli)
  - Session-based handshake
  - Monotonic sequence numbers
  - Optional ACK & deduplication

- 🎮 **Teleoperation**
  - Keyboard control (6-DOF body command)
  - Extensible to gamepad / joystick
  - Manual / Auto / Failsafe mode switching

- 🛑 **Safety mechanisms**
  - Emergency stop (ESTOP)
  - TTL-based command expiry
  - Session loss detection
  - Link-alive monitoring

- 📡 **Telemetry**
  - Vehicle status feedback
  - Mode / controller state
  - Failure counters
  - Timestamped status frames

- 🧪 **Engineering & Research ready**
  - Packet recording & replay
  - Protocol-level testing
  - Clear separation of transport / protocol / control logic

---

## 📁 Project Structure

```

UnderWaterRobotGCS/
├── configs/                  # Runtime configuration files
│   ├── gcs_default.yaml
│   └── profiles/
│       ├── pool_test.yaml
│       └── open_water.yaml
│
├── docs/                     # Documentation
│   ├── operator_guide.md     # How to operate the GCS
│   ├── protocol.md           # Wire protocol specification
│   └── screenshots/
│
├── scripts/                  # Helper scripts
│   ├── run_gui.ps1
│   ├── run_tui.ps1
│   └── build_installer.ps1
│
├── src/urogcs/
│   ├── app/                  # Entry points
│   │   ├── cli_main.py
│   │   ├── tui_main.py
│   │   └── gui_main.py
│   │
│   ├── control/              # Input & safety logic
│   │   ├── keyboard_mapper.py
│   │   ├── gamepad_mapper.py
│   │   ├── safety.py
│   │   └── profiles/
│   │
│   ├── protocol/             # Wire protocol implementation
│   │   ├── messages.py
│   │   ├── codec.py
│   │   ├── crc32c.py
│   │   └── framing.py
│   │
│   ├── session/              # Session & handshake
│   │   └── session_client.py
│   │
│   ├── telemetry/            # Telemetry models & UI mapping
│   │   ├── model.py
│   │   ├── alarms.py
│   │   └── ui_viewmodels.py
│   │
│   ├── transport/            # Communication layer
│   │   ├── udp_link.py
│   │   ├── tcp_link.py
│   │   └── recorder.py
│   │
│   └── tools/                # Debug & analysis tools
│       ├── replay.py
│       └── pcap_export.py
│
└── tests/                    # Unit & integration tests
├── test_codec.py
├── test_transport_udp.py
└── test_safety_ttl.py

```

---

## 🧠 System Architecture

High-level data flow:

```

Keyboard / Gamepad
↓
GCS Control Layer
↓
Protocol Encoder (CRC, Session, Seq)
↓
UDP Transport
↓
OrangePi comm_gcs
↓
ControlIntent
↓
Controller (Manual / Auto)
↓
Thruster Allocation
↓
STM32 PWM → Thrusters

````

The GCS **does not directly control motors**.  
It issues **intent-level commands**, leaving actuation, allocation, and low-level safety to the vehicle.

---

## 🚀 Getting Started

### 1️⃣ Install (development)

```bash
git clone https://github.com/wyswang3/UnderWaterRobotGCS.git
cd UnderWaterRobotGCS
pip install -e .
````

### 2️⃣ Run TUI (keyboard teleop)

```bash
python -m urogcs.app.tui_main
```

or on Windows:

```powershell
scripts\run_tui.ps1
```

### 3️⃣ Typical workflow

1. Start vehicle-side `comm_gcs` on OrangePi
2. Launch GCS
3. Handshake establishes session
4. Switch to **Manual mode**
5. Teleoperate using keyboard
6. Monitor telemetry & link status
7. Use ESTOP if needed

---

## 🧪 Research Usage

This GCS is designed to integrate with:

* MPC controllers
* Reinforcement Learning policies
* External autonomy modules

Recommended approach:

* Use `SET_DOF_CMD` as low-level interface
* Add higher-level commands (e.g. velocity / wrench) **without modifying transport or session logic**
* Record packets for offline learning & replay

---

## 🔒 Safety Philosophy

* Loss of session → vehicle enters failsafe
* Stale commands → automatically rejected
* ESTOP always has priority
* GCS is **not trusted** for low-level safety

This separation is intentional and critical for real underwater experiments.

---

## 📌 Versioning

* `v0-gcs-foundation`
  Initial stable GCS architecture: protocol, session, teleop, telemetry.

Future versions will extend UI and autonomy interfaces **without breaking protocol compatibility**.

---

## 📄 License

TBD (to be decided according to project needs).

---

## 🤝 Acknowledgements

This project is part of a larger **UnderWaterRobot** control and navigation system, including:

* OrangePi onboard computer
* STM32 thruster controller
* IMU / DVL / USBL navigation stack

```

---


```
