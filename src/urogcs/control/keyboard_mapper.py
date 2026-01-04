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
    # POSIX: 正式实现
    # =========================

    @dataclass
    class KeyProfile:
        # 每次按键对 DOF 的增量
        step: float = 0.08
        # 每个 tick 的指数衰减系数（接近 1 表示惯性大）
        decay: float = 0.85

    # 按键语义绑定：
    #   - 这里用小写字母，因为我们在 LinuxKeyboard 里已统一 lower()
    #   - W/S/A/D/Q/E/H/G/R/T/F/V 对应 6DOF
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
        键盘 → 6DOF 的状态机：

        - 内部维护一个 DofCommand（连续态）；
        - 每个 tick：
            1) 先对所有 DOF 做一次指数衰减（模拟“松手减速”）；
            2) 再根据本 tick 的按键集合做增/减；
            3) 最后把 [-1,1] 之外的值 clamp 回来；
        - 调用者负责提供本 tick 的按键集合（Iterable[str]，例如 set({'w','a'})）。
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

        def update(self, pressed: Iterable[str]) -> DofCommand:
            """
            :param pressed: 当前 tick 的按键集合（小写字符串，如 {'w','a'}）。
            :return: 更新后的 DofCommand（内部状态的快照）。
            """
            pressed_set: Set[str] = set(pressed)

            # 1) 衰减
            self._apply_decay()

            # 2) 处理按键增量
            step = self.profile.step
            for k in pressed_set:
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

            # 3) clamp 到 [-1, 1]
            self.cmd.surge = _clamp(self.cmd.surge, -1.0, 1.0)
            self.cmd.sway = _clamp(self.cmd.sway, -1.0, 1.0)
            self.cmd.heave = _clamp(self.cmd.heave, -1.0, 1.0)
            self.cmd.roll = _clamp(self.cmd.roll, -1.0, 1.0)
            self.cmd.pitch = _clamp(self.cmd.pitch, -1.0, 1.0)
            self.cmd.yaw = _clamp(self.cmd.yaw, -1.0, 1.0)

            # 返回一个“快照”，避免外部修改内部状态
            return DofCommand(
                surge=self.cmd.surge,
                sway=self.cmd.sway,
                heave=self.cmd.heave,
                roll=self.cmd.roll,
                pitch=self.cmd.pitch,
                yaw=self.cmd.yaw,
            )
