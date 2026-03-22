# src/urogcs/control/keyboard_mapper.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Set
import sys

from urogcs.protocol.messages import DofCommand


IS_WINDOWS = sys.platform.startswith("win")


# =========================
# Windows: 空实现，占位
# =========================

if IS_WINDOWS:
    class KeyboardMapper:
        """
        Windows 下占位实现：
        - 不处理键盘输入；
        - 始终返回全零的 DofCommand。

        说明：
        - 真正的键盘 TUI 只在 POSIX (Linux/macOS) 下启用；
        - GCS 仍然可以在 Windows 上运行，但只能做“观测/调参”等。
        """

        def __init__(self, *args, **kwargs) -> None:
            print(
                "[KeyboardMapper] Windows 平台，键盘 TUI 功能未启用，"
                "仅保留 GCS 通信。"
            )

        def update(self, pressed: Iterable[str]) -> DofCommand:
            return DofCommand()

else:
    # =========================
    # POSIX: 正式实现（仅负责 6DOF）
    # =========================

    @dataclass
    class KeyProfile:
        """
        DOF 键盘控制参数：

        step:
            - 每个 tick、每次按键对 DOF 的增量；
            - 结合 decay 可近似看作“加速度”。

        decay:
            - 每个 tick 的指数衰减系数（0~1）；
            - 越接近 1，惯性越大、响应越“肉”，但更平滑。

        max_abs:
            - 单个 DOF 的绝对值上限（归一化范围）；
            - 一般 0.5 或 1.0；
            - 通过 KeyboardMapper(profile=KeyProfile(...)) 可现场调节。
        """
        step: float = 0.08
        decay: float = 0.85
        max_abs: float = 1.0

    # 按键语义绑定：
    #   - 这里用小写字母，因为我们在 LinuxKeyboard 里已统一 lower()
    #   - W/S/A/D/Q/E/H/G/R/T/F/V 对应 6DOF
    #
    #   提示：
    #   - Arm / Disarm / E-Stop / ClearEStop 等“安全相关按键”
    #     不在本文件处理，而是在 TUI 层（例如 tui_main.py）直接转换成
    #     “Arm/Disarm/EStop/ClearEStop 请求”，然后发给网关/香橙派。
    DEFAULT_BINDINGS: Dict[str, str] = {
        "w": "surge+",
        "s": "surge-",

        "a": "sway-",
        "d": "sway+",

        "h": "heave+",
        "g": "heave-",

        "q": "yaw+",
        "e": "yaw-",

        "r": "roll+",
        "t": "roll-",

        "f": "pitch+",
        "v": "pitch-",
    }

    def _clamp(v: float, lo: float, hi: float) -> float:
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v

    class KeyboardMapper:
        """
        键盘 → 6DOF 的状态机（仅负责“连续 DOF”，不处理 arm/estop 等安全逻辑）：

        - 内部维护一个 DofCommand（连续态）；
        - 每个 tick：
            1) 先对所有 DOF 做一次指数衰减（模拟“松手减速”）；
            2) 再根据本 tick 的按键集合做增/减；
            3) 最后把 [-max_abs, max_abs] 之外的值 clamp 回来；
        - 调用者负责提供本 tick 的按键集合（Iterable[str]，例如 set({'w','a'})）。

        注意：
        - 安全相关按键（急停、解急停、解锁/上锁等）应由上层 TUI 直接
          转成“控制请求”发送给香橙派，由 ControlGuard 实现真实的解锁与 failsafe。
        - 当前产品化基线要求“单次只接受一个运动键”，避免组合运动导致
          运动学意图与瞬时功耗都变得不透明；若检测到多个运动键，本层会
          拒绝该 tick 的运动输入并让 DOF 按既有衰减回零。
        """

        def __init__(
            self,
            profile: KeyProfile | None = None,
            bindings: Dict[str, str] | None = None,
        ) -> None:
            self.profile = profile or KeyProfile()
            self.bindings: Dict[str, str] = bindings or dict(DEFAULT_BINDINGS)
            self.cmd: DofCommand = DofCommand()

        def _apply_decay(self) -> None:
            p = self.profile.decay
            self.cmd.surge *= p
            self.cmd.sway *= p
            self.cmd.heave *= p
            self.cmd.roll *= p
            self.cmd.pitch *= p
            self.cmd.yaw *= p

        def reset(self) -> None:
            """
            将内部 DOF 状态归零（例如在重新连接 Session 时调用）。
            """
            self.cmd = DofCommand()

        def motion_keys(self, pressed: Iterable[str]) -> Set[str]:
            """提取当前 tick 中真正属于 6DOF 运动控制的键集合。"""
            return {key for key in set(pressed) if key in self.bindings}

        def update(self, pressed: Iterable[str]) -> DofCommand:
            """
            :param pressed: 当前 tick 的按键集合（小写字符串，如 {'w'}）。
            :return: 更新后的 DofCommand（内部状态的快照）。
            """
            motion_pressed: Set[str] = self.motion_keys(pressed)

            # === 1) 衰减逻辑：只有在“恰好一个 DOF 键按下”时才接受运动输入 ===
            #
            # 直觉：
            #   - 按住单个运动键时：持续“加油门”，不减速；
            #   - 松手后：才慢慢减速回到 0；
            #   - 若出现组合运动键：本 tick 运动输入无效，按衰减回零。
            #
            if len(motion_pressed) != 1:
                self._apply_decay()
                motion_pressed = set()
            # 若恰好有一个运动键，则不做衰减（保留上一 tick 的值，再叠加 step）

            # === 2) 处理本 tick 的按键增量 ===
            step = self.profile.step
            for k in motion_pressed:
                act = self.bindings.get(k)
                if not act:
                    continue

                if act == "surge+":
                    self.cmd.surge += step
                elif act == "surge-":
                    self.cmd.surge -= step
                elif act == "sway+":
                    self.cmd.sway += step
                elif act == "sway-":
                    self.cmd.sway -= step
                elif act == "heave+":
                    self.cmd.heave += step
                elif act == "heave-":
                    self.cmd.heave -= step
                elif act == "roll+":
                    self.cmd.roll += step
                elif act == "roll-":
                    self.cmd.roll -= step
                elif act == "pitch+":
                    self.cmd.pitch += step
                elif act == "pitch-":
                    self.cmd.pitch -= step
                elif act == "yaw+":
                    self.cmd.yaw += step
                elif act == "yaw-":
                    self.cmd.yaw -= step

            # === 3) clamp 到 [-max_abs, max_abs] ===
            max_abs = float(self.profile.max_abs)
            self.cmd.surge = _clamp(self.cmd.surge, -max_abs, max_abs)
            self.cmd.sway  = _clamp(self.cmd.sway,  -max_abs, max_abs)
            self.cmd.heave = _clamp(self.cmd.heave, -max_abs, max_abs)
            self.cmd.roll  = _clamp(self.cmd.roll,  -max_abs, max_abs)
            self.cmd.pitch = _clamp(self.cmd.pitch, -max_abs, max_abs)
            self.cmd.yaw   = _clamp(self.cmd.yaw,   -max_abs, max_abs)

            # 返回一个“快照”，避免外部修改内部状态
            return DofCommand(
                surge=self.cmd.surge,
                sway=self.cmd.sway,
                heave=self.cmd.heave,
                roll=self.cmd.roll,
                pitch=self.cmd.pitch,
                yaw=self.cmd.yaw,
            )
