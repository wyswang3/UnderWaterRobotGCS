# src/urogcs/app/tui_keys.py
from __future__ import annotations

import os
import sys
import select
from dataclasses import dataclass
from typing import Optional, Set

from urogcs.protocol.wire import WireControlMode

from urogcs.app.tui.tui_env import IS_POSIX


# =========================
# 离散动作聚合（Python 版 TeleopAction 子集）
# =========================

@dataclass
class DiscreteActions:
    """
    对齐下位机 TeleopAction 的离散键盘语义（精简版）：

      - togg_estop:   E-STOP 请求（对应 C++: TeleopAction::EStop）
      - clear_estop:  解除急停请求（对应 C++: TeleopAction::ClearEStop）
      - arm / disarm: 解锁 / 上锁（',' / '，'；'.' / '。'）
      - exit:         退出 TUI（ESC）
      - help:         帮助 / 打印说明（Z/z）
      - center:       中心化 DOF （对应 C++: TeleopAction::Center）
      - throttle_delta: 全局油门变化量（-1..+1，小步长叠加）
      - mode_req:     模式切换请求（Manual/Auto/Failsafe）

    说明：
      - Ctrl 组合（Ctrl+Space / Ctrl+M）在 Linux 终端中很难稳定识别，
        当前实现采用“无修饰键近似语义”：
          * Space   -> togg_estop（近似 Ctrl+Space）
          * 'm'     -> clear_estop + center（近似 Ctrl+M + 'M'）
      - 单电机测试 (1..8, 0) 暂不在上位机实现（协议未定义），后续可以扩展。
    """
    togg_estop: bool = False
    clear_estop: bool = False

    arm: bool = False
    disarm: bool = False

    exit: bool = False
    help: bool = False
    center: bool = False

    throttle_delta: float = 0.0

    mode_req: Optional[WireControlMode] = None

# =========================
# 键盘读取抽象
# =========================

class BaseKeyboard:
    """抽象键盘读取接口，便于在 Linux / Windows / 非 TTY 环境统一使用。"""

    def __enter__(self) -> "BaseKeyboard":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        pass

    def read_keys_tick(self, max_bytes: int = 32) -> Set[str]:
        """返回本 tick 内读取到的一组按键（已 lower()）。"""
        return set()


class LinuxKeyboard(BaseKeyboard):
    """
    非阻塞 Linux 键盘读取：
      - 仅在 POSIX + TTY 下启用；
      - 使用 termios + tty 设置 cbreak 模式；
      - 使用 select + os.read 读取原始字节；
      - 只解析出“键值集合”，不做语义映射。
    """

    def __init__(self) -> None:
        super().__init__()
        self.enabled = False
        self._orig = None
        self._fd: Optional[int] = None

    def __enter__(self) -> "LinuxKeyboard":
        if not IS_POSIX:
            return self
        if not sys.stdin.isatty():
            return self

        try:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._orig = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self.enabled = True
        except Exception:
            self.enabled = False
        return self

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            import termios

            if self._fd is not None and self._orig is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._orig)
        except Exception:
            pass
        self.enabled = False

    def read_keys_tick(self, max_bytes: int = 32) -> Set[str]:
        keys: Set[str] = set()
        if not self.enabled or self._fd is None:
            return keys

        r, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not r:
            return keys

        try:
            data = os.read(self._fd, max_bytes)
        except Exception:
            return keys

        for b in data:
            if b == 27:
                keys.add("esc")
            elif b in (10, 13):
                keys.add("enter")
            elif b == 32:
                keys.add("space")
            else:
                ch = chr(b)
                if ch.isprintable():
                    keys.add(ch.lower())
        return keys


class DummyKeyboard(BaseKeyboard):
    """
    用于 Windows / 非 TTY 环境：
      - read_keys_tick 始终返回空集合；
      - 仍然实现 BaseKeyboard 接口，方便上层统一使用 with。
    """

    def __init__(self) -> None:
        super().__init__()


def create_keyboard() -> BaseKeyboard:
    """工厂：根据平台返回合适的键盘实现。"""
    if IS_POSIX:
        return LinuxKeyboard()
    return DummyKeyboard()


# =========================
# 离散命令映射（对齐下位机约定）
# =========================

def apply_special_keys(keys: Set[str]) -> DiscreteActions:
    """
    将当前 tick 的键集合映射为离散控制语义，参考下位机 C++：

      - Ctrl + Space : E-STOP            (近似为 Space)
      - Ctrl + M/m   : ClearEStop        (近似为 'm')
      - ',' / '，'   : Arm
      - '.' / '。'   : Disarm
      - 'Z'          : Help
      - 'M'          : Center
      - '=' / '+'    : ThrottleUp
      - '-' / '_'    : ThrottleDown
      - ESC          : Exit

    限制说明：
      - 我们当前的键盘扫描只拿到“字符”，很难区分 Ctrl 组合，因此采用近似：
          * Space   → togg_estop
          * 'm'     → clear_estop + center
      - 模式键 1/2/3 沿用原来的上位机约定（Manual/Auto/Failsafe），
        下位机 Teleop 键盘暂不涉及模式切换。
    """
    act = DiscreteActions()

    # --- 退出 ---
    if "esc" in keys:
        act.exit = True

    # --- E-STOP / ClearEStop / Center ---
    # 近似 C++: Ctrl+Space => EStop
    if "space" in keys:
        act.togg_estop = True

    # 近似 C++: Ctrl+M => ClearEStop, 'M' => Center
    # 这里简化为：按 'm'（小写）同时触发 ClearEStop + Center
    if "m" in keys:
        act.clear_estop = True
        act.center = True

    # --- Arm / Disarm (全角/半角兼容) ---
    # C++: is_comma_key / is_dot_key 处理 ',' / '，'、'.' / '。'
    if "," in keys or "，" in keys:
        act.arm = True
    if "." in keys or "。" in keys:
        act.disarm = True

    # --- Help ---
    # C++: 'Z' => Help，这里键盘统一 lower()，用 'z'
    if "z" in keys:
        act.help = True

    # --- 模式切换（沿用原有上位机逻辑） ---
    if "1" in keys:
        act.mode_req = WireControlMode.Manual
    elif "2" in keys:
        act.mode_req = WireControlMode.Auto
    elif "3" in keys:
        act.mode_req = WireControlMode.Failsafe

    # --- 油门档位（ThrottleUp / ThrottleDown） ---
    # C++:
    #   if (key == '=' || key == '+') return TeleopAction::ThrottleUp;
    #   if (key == '-' || key == '_') return TeleopAction::ThrottleDown;
    if "-" in keys or "_" in keys:
        act.throttle_delta -= 0.1
    if "=" in keys or "+" in keys:
        act.throttle_delta += 0.1

    # 备注：单电机测试 1..8 / 0 在上位机暂时不实现，
    # 待 GCS 协议中定义 MotorTest 消息后再接入。

    return act
# =========================