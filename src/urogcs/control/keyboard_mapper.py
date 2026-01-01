# src/urogcs/control/keyboard_mapper.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Set, Optional

import sys
import select
import termios
import tty

from urogcs.protocol.messages import DofCommand


IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    # ===== Windows 平台：提供一个“空实现”的 KeyboardMapper =====
    from urogcs.protocol.messages import DofCommand

    class KeyboardMapper:
        def __init__(self, *args, **kwargs):
            print(
                "[KeyboardMapper] 检测到 Windows 平台："
                "终端键盘控制(termios)不可用，键盘输入功能已禁用，只保留 GCS 通信。"
            )

        # 下面这个方法名，需要和你原来在 tui_main.py 里调用的一致
        # 比如 tui_main 里是 mapper.read_once(now_ns)，那这里也写 read_once
        # 比如是 mapper.poll(now_ns)，那就写 poll
        def read_once(self, now_ns: int):
            """
            Windows 下不处理键盘输入：
            - 返回 None，表示“没有新指令”，主循环只负责收发网络包即可。
            - 如果你原来期望返回 DofCommand，也可以返回一个全零的 DofCommand()。
            """
            return None

        # 如果原实现还有别的对外方法（例如 reset / dump_state），按需加空实现
        # def reset(self):
        #     pass

else:
    # ===== 非 Windows 平台：保留你原来的完整实现 =====
    import termios
    import tty
    import select
    # ... 这里以下就是你现在 keyboard_mapper.py 的原始代码内容 ...
    # 原来的 KeyboardMapper 类、内部逻辑全部缩进到这个 else 下面
@dataclass
class KeyProfile:
    step: float = 0.08
    decay: float = 0.85


DEFAULT_BINDINGS: Dict[str, str] = {
    "w": "surge+",
    "s": "surge-",
    "a": "sway-",
    "d": "sway+",
    "r": "heave+",
    "f": "heave-",
    "q": "yaw-",
    "e": "yaw+",
    "j": "roll-",
    "l": "roll+",
    "i": "pitch+",
    "k": "pitch-",
}


@dataclass
class KeyEvent:
    key: str


class _StdinPoller:
    """Non-blocking single-char poller for Linux TUI."""
    def __init__(self) -> None:
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)

    def close(self) -> None:
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def poll(self) -> Optional[str]:
        r, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not r:
            return None
        return sys.stdin.read(1)


class KeyboardMapper:
    """
    Stateful mapper: keeps last command and updates with key presses.

    Two roles for current integration:
    1) poll(): non-blocking key event source (Linux stdin)
    2) update(pressed): mapping pressed keys -> DofCommand
    """
    def __init__(self, profile: KeyProfile | None = None, bindings: Dict[str, str] | None = None) -> None:
        self.profile = profile or KeyProfile()
        self.bindings = bindings or dict(DEFAULT_BINDINGS)
        self.cmd = DofCommand()
        self._poller: Optional[_StdinPoller] = None

    # --------- input layer ---------
    def poll(self) -> Optional[KeyEvent]:
        """
        Non-blocking poll.
        Returns KeyEvent(key=...) or None.
        """
        if self._poller is None:
            self._poller = _StdinPoller()
        ch = self._poller.poll()
        if ch is None:
            return None
        # Normalize: lower-case for bindings
        if ch == "\x1b":  # ESC
            return KeyEvent(key="esc")
        if ch == "\n" or ch == "\r":
            return KeyEvent(key="enter")
        return KeyEvent(key=ch.lower())

    def close(self) -> None:
        """Restore terminal state."""
        if self._poller is not None:
            self._poller.close()
            self._poller = None

    # --------- mapping layer ---------
    def _apply_decay(self) -> None:
        p = self.profile.decay
        self.cmd.surge *= p
        self.cmd.sway *= p
        self.cmd.heave *= p
        self.cmd.roll *= p
        self.cmd.pitch *= p
        self.cmd.yaw *= p

    def update(self, pressed: Iterable[str]) -> DofCommand:
        pressed_set: Set[str] = set(pressed)
        self._apply_decay()
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

        self.cmd.clamp(-1.0, 1.0)
        return DofCommand(
            surge=self.cmd.surge,
            sway=self.cmd.sway,
            heave=self.cmd.heave,
            roll=self.cmd.roll,
            pitch=self.cmd.pitch,
            yaw=self.cmd.yaw,
        )
