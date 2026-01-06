# src/urogcs/core/service.py
from __future__ import annotations

"""
urogcs.core.service

GCS 核心服务层：

- 封装 GcsSessionClient（底层 UDP + 协议）；
- 对外暴露“业务友好”的 request_* / send_* 接口，供 TUI / GUI / 算法调用；
- 维护一份精简的 GcsServiceState，给 UI 使用；
- 通过回调把状态与日志抛出，不直接依赖具体前端实现。
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from urogcs.session.session_client import GcsSessionClient
from urogcs.protocol.messages import DofCommand
from urogcs.protocol.wire import WireControlMode


StatusCallback = Callable[[Any], None]
LogCallback = Callable[[str], None]


# =============================================================================
# Config & State
# =============================================================================

@dataclass
class GcsServiceConfig:
    """
    GCS 核心服务配置（与具体前端无关）.

    - rov_ip / rov_port:
        目标 ROV 的 UDP 地址（对应 gcs_server 的监听地址）
    - bind_ip / bind_port:
        本机绑定地址（一般为 0.0.0.0 + 固定端口，便于防火墙配置）
    - poll_hz:
        期望的轮询频率（仅用于估算 recv_timeout_ms；真正调度由上层控制）
    - heartbeat_hz:
        心跳频率（同样由上层循环按节拍调用 send_heartbeat）
    - handshake_timeout_s:
        握手阶段的超时时间
    - recv_timeout_ms:
        socket 接收超时；如为 None 则根据 poll_hz 自动估算。
    """

    rov_ip: str = "192.168.2.24"
    rov_port: int = 14550

    bind_ip: str = "0.0.0.0"
    bind_port: int = 14551

    poll_hz: int = 50
    heartbeat_hz: int = 2
    handshake_timeout_s: float = 2.0

    recv_timeout_ms: Optional[int] = None

    def effective_recv_timeout_ms(self) -> int:
        """
        返回用于底层 UDP socket 的接收超时时间（毫秒）.
        """
        if self.recv_timeout_ms is not None:
            return self.recv_timeout_ms
        # 按 poll_hz 估算一个保守的超时时间（略小于 1 / poll_hz）
        return int(1000 / max(1, self.poll_hz))


@dataclass
class GcsServiceState:
    """
    对 UI 友好的状态快照（提炼自底层 STATUS / SessionState）.

    说明：
      - 这里只保留 UI 当前关心的核心字段；
      - 协议层的完整 StatusTelemetry 仍保存在 last_status_raw，
        工程师需要细节时可以直接取用。
    """

    # 会话 / 链路
    session_established: bool = False
    session_id: Optional[int] = None
    link_alive: bool = False

    # 安全 / 模式
    estop: bool = False
    mode: int = 0  # WireControlMode 的数值，UI 可通过表映射为名称

    # 控制器信息
    active_controller: str = ""
    desired_controller: str = ""

    # 最新一份底层 status（透传给对协议细节感兴趣的上层）
    last_status_raw: Optional[Any] = None


# =============================================================================
# Core Service
# =============================================================================

class GcsService:
    """
    GCS 核心服务（面向前端 / 算法的统一接口）.

    职责：
      - 封装 GcsSessionClient 的生命周期与握手流程；
      - 提供简洁的 request_* / send_* API：
          * request_estop / request_arm / request_mode
          * send_dof / send_heartbeat
      - 维护一份 GcsServiceState，供 UI 渲染使用；
      - 通过回调把 status / log 事件抛给上层。
    """

    def __init__(
        self,
        cfg: GcsServiceConfig,
        on_status: Optional[StatusCallback] = None,
        on_log: Optional[LogCallback] = None,
    ) -> None:
        self.cfg = cfg

        self._cli: Optional[GcsSessionClient] = None
        self._state: GcsServiceState = GcsServiceState()

        # 外部回调
        self._user_on_status = on_status
        self._user_on_log = on_log

        # 内部错误信息，用于握手失败等场景
        self.last_error: str = ""

    # -------------------------------------------------------------------------
    # 属性访问
    # -------------------------------------------------------------------------

    @property
    def state(self) -> GcsServiceState:
        """
        返回当前状态快照.

        注意：当前直接返回内部对象，视为只读使用；若未来需要“快照化”，
        再改成浅拷贝即可。
        """
        return self._state

    @property
    def client(self) -> Optional[GcsSessionClient]:
        """暴露底层 GcsSessionClient（仅用于调试或高级用途）."""
        return self._cli

    @property
    def connected(self) -> bool:
        """会话是否已建立（供 UI 简单判断连通性）."""
        return bool(self._state.session_established and self._cli is not None)

    # -------------------------------------------------------------------------
    # 生命周期管理
    # -------------------------------------------------------------------------

    def start(self) -> bool:
        """
        初始化 GcsSessionClient 并发起握手.

        返回：
          - True: 握手成功，session_established = True；
          - False: 握手失败，可查看 self.last_error。
        """
        if self._cli is not None:
            # 已经启动过，先关闭旧会话
            self.close()

        def _on_status(st: Any) -> None:
            self._handle_status(st)

        def _on_log(msg: str) -> None:
            self._handle_log(msg)

        self._cli = GcsSessionClient(
            rov_addr=(self.cfg.rov_ip, self.cfg.rov_port),
            bind_addr=(self.cfg.bind_ip, self.cfg.bind_port),
            recv_timeout_ms=self.cfg.effective_recv_timeout_ms(),
            on_status=_on_status,
            on_log=_on_log,
        )

        self.last_error = ""
        ok = False
        try:
            ok = self._cli.handshake(timeout_s=self.cfg.handshake_timeout_s)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"[HS] exception: {e}"
            self._handle_log(self.last_error)
            ok = False

        if not ok:
            # 尝试从底层 client 拿一份错误信息
            err = getattr(self._cli, "last_error", "") if self._cli is not None else ""
            if err:
                self.last_error = err
            if not self.last_error:
                self.last_error = "[HS] handshake failed (unknown reason)"
            self._handle_log(self.last_error)

        return ok

    def close(self) -> None:
        """
        关闭底层会话，不抛异常；关闭后状态重置为“未连接”.
        """
        cli, self._cli = self._cli, None
        if cli is not None:
            try:
                cli.close()
            except Exception:  # noqa: BLE001
                pass

        # 会话关闭后，把关键状态重置（保留 last_status_raw 可选）
        self._state.session_established = False
        self._state.link_alive = False

    # -------------------------------------------------------------------------
    # 调度相关（供主循环调用）
    # -------------------------------------------------------------------------

    def poll(self, max_packets: int = 16) -> None:
        """
        轮询接收数据包（非阻塞程度由 GcsSessionClient 的 timeout 决定）.

        建议在 TUI/GUI 主循环中，以 cfg.poll_hz 为基准周期调用。
        """
        if self._cli is None:
            return
        try:
            self._cli.poll(max_packets=max_packets)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[POLL] exception: {e}")

    def send_heartbeat(self, use_session: bool = True, ack_req: bool = False) -> None:
        """
        发送心跳包（供上层按 heartbeat_hz 节拍调用）.
        """
        if self._cli is None:
            return
        try:
            self._cli.send_heartbeat(use_session=use_session, ack_req=ack_req)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[HB] send failed: {e}")

    # -------------------------------------------------------------------------
    # 控制命令接口（供 UI / 算法调用）
    # -------------------------------------------------------------------------

    def request_estop(self, latched: bool, ack_req: bool = True) -> None:
        """
        发送急停请求（真正的锁存 / 安全行为由下位机安全层决定）.

        latched=True  通常表示“请求急停”；
        latched=False 通常表示“请求解除急停”
                      （是否允许解除由下位机安全策略决定）。
        """
        if self._cli is None:
            return
        try:
            self._cli.send_estop(latched, ack_req=ack_req)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[TX] ESTOP failed: {e}")

    def request_arm(self, armed: bool, ack_req: bool = True) -> None:
        """
        发送解锁 / 上锁 请求.

        armed=True  => 请求解锁（ARM）
        armed=False => 请求上锁（DISARM）
        """
        if self._cli is None:
            return
        try:
            # 底层真正发 UDP 报文的是 GcsSessionClient.send_arm()
            self._handle_log(f"[GCS] request_arm enable={int(armed)}")
            self._cli.send_arm(armed, ack_req=ack_req)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[TX] ARM failed: {e}")

    def request_mode(
        self,
        mode: WireControlMode,
        auto_controller: str = "",
        ack_req: bool = True,
    ) -> None:
        """
        发送控制模式切换请求.

        - mode: WireControlMode.Manual / Auto / Failsafe / ...
        - auto_controller: 在 Auto 模式下希望激活的控制器名称
          （如 "mpc" / "rl" 等）。
        """
        if self._cli is None:
            return
        try:
            # 底层目前实现为 send_set_mode()，未来如改名 send_mode() 也可透明替换
            self._cli.send_set_mode(mode, auto_controller=auto_controller, ack_req=ack_req)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[TX] SET_MODE failed: {e}")

    def send_dof(self, cmd: DofCommand, ack_req: bool = False) -> None:
        """
        下发 6DOF 命令（高频接口）.

        - cmd: DofCommand(surge, sway, heave, roll, pitch, yaw)，通常范围 [-1, 1]；
        - 上位机不做最终安全裁剪，只负责表达“控制意图”，
          真正限幅 / 零输出策略由下位机安全层负责。
        """
        if self._cli is None:
            return
        try:
            self._cli.send_set_dof(cmd, ack_req=ack_req)
        except Exception as e:  # noqa: BLE001
            self._handle_log(f"[TX] SET_DOF failed: {e}")

    # -------------------------------------------------------------------------
    # 内部回调处理
    # -------------------------------------------------------------------------

    def _handle_status(self, st: Any) -> None:
        """
        内部 status 回调：

        - 更新 GcsServiceState 中的聚合字段；
        - 把原始 status 保存在 last_status_raw 里；
        - 转发给上层 on_status 回调（如果有）。
        """
        self._state.last_status_raw = st

        # 尝试从 st 上提炼常用字段（全部使用 getattr + 默认值，避免协议变更导致崩溃）
        self._state.session_established = bool(getattr(st, "session_established", False))
        self._state.session_id = getattr(st, "session_id", None)
        self._state.link_alive = bool(getattr(st, "link_alive", False))

        self._state.estop = bool(getattr(st, "estop", False))
        self._state.mode = int(getattr(st, "mode", 0))

        self._state.active_controller = str(getattr(st, "active_controller", "") or "")
        self._state.desired_controller = str(getattr(st, "desired_controller", "") or "")

        if self._user_on_status is not None:
            try:
                self._user_on_status(st)
            except Exception as e:  # noqa: BLE001
                # 不让 UI 回调异常影响底层逻辑
                self._handle_log(f"[CB] on_status raised: {e}")

    def _handle_log(self, msg: str) -> None:
        """
        内部 log 回调：透传给用户回调，如果没有就静默.
        """
        if self._user_on_log is not None:
            try:
                self._user_on_log(msg)
            except Exception:
                # UI 日志回调出错时不再向外抛异常，避免干扰网络层
                pass
