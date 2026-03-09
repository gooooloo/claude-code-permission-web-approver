#!/usr/bin/env python3
"""
Windows console input helper for Claude Code WebUI.

Sends text to a Windows console process by attaching to its console
and writing keyboard input records via WriteConsoleInputW.

This runs as a separate subprocess to avoid disrupting the server's
own console. On Linux/macOS this file is unused (tmux is used instead).

Usage: python win_send_keys.py <target_pid> <text>
"""

import ctypes
import ctypes.wintypes as wt
import sys


def send_keys(target_pid, text):
    """Attach to target console and write text as keyboard input."""
    kernel32 = ctypes.windll.kernel32

    # Detach from current console
    kernel32.FreeConsole()

    # Attach to target process's console
    if not kernel32.AttachConsole(target_pid):
        error = ctypes.get_last_error()
        print(f"AttachConsole failed for PID {target_pid}: error {error}", file=sys.stderr)
        return False

    try:
        # Get console input handle
        STD_INPUT_HANDLE = ctypes.c_ulong(-10 & 0xFFFFFFFF)
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if handle == ctypes.c_void_p(-1).value:
            print("GetStdHandle failed", file=sys.stderr)
            return False

        KEY_EVENT = 0x0001

        class KEY_EVENT_RECORD(ctypes.Structure):
            _fields_ = [
                ("bKeyDown", wt.BOOL),
                ("wRepeatCount", wt.WORD),
                ("wVirtualKeyCode", wt.WORD),
                ("wVirtualScanCode", wt.WORD),
                ("uChar", ctypes.c_wchar),
                ("dwControlKeyState", wt.DWORD),
            ]

        class INPUT_RECORD_Event(ctypes.Union):
            _fields_ = [
                ("KeyEvent", KEY_EVENT_RECORD),
                ("_padding", ctypes.c_byte * 16),  # Union padding
            ]

        class INPUT_RECORD(ctypes.Structure):
            _fields_ = [
                ("EventType", wt.WORD),
                ("_padding", wt.WORD),
                ("Event", INPUT_RECORD_Event),
            ]

        # Build input records: key down + key up for each character
        full_text = text + "\r"  # Add Enter
        records = []
        for ch in full_text:
            # Key down
            rec_down = INPUT_RECORD()
            rec_down.EventType = KEY_EVENT
            rec_down.Event.KeyEvent.bKeyDown = True
            rec_down.Event.KeyEvent.wRepeatCount = 1
            rec_down.Event.KeyEvent.wVirtualKeyCode = 0
            rec_down.Event.KeyEvent.wVirtualScanCode = 0
            rec_down.Event.KeyEvent.uChar = ch
            rec_down.Event.KeyEvent.dwControlKeyState = 0
            records.append(rec_down)

            # Key up
            rec_up = INPUT_RECORD()
            rec_up.EventType = KEY_EVENT
            rec_up.Event.KeyEvent.bKeyDown = False
            rec_up.Event.KeyEvent.wRepeatCount = 1
            rec_up.Event.KeyEvent.wVirtualKeyCode = 0
            rec_up.Event.KeyEvent.wVirtualScanCode = 0
            rec_up.Event.KeyEvent.uChar = ch
            rec_up.Event.KeyEvent.dwControlKeyState = 0
            records.append(rec_up)

        # Write all records at once
        arr = (INPUT_RECORD * len(records))(*records)
        written = wt.DWORD()
        success = kernel32.WriteConsoleInputW(
            handle, arr, len(records), ctypes.byref(written)
        )

        if not success:
            error = ctypes.get_last_error()
            print(f"WriteConsoleInputW failed: error {error}", file=sys.stderr)
            return False

        return written.value > 0

    finally:
        # Always detach from target console
        kernel32.FreeConsole()


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <target_pid> <text>", file=sys.stderr)
        sys.exit(1)

    target_pid = int(sys.argv[1])
    text = sys.argv[2]

    if send_keys(target_pid, text):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
