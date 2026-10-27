import argparse
import time
import subprocess
import threading
import sys
import os
import ctypes
from ctypes import wintypes
import re
import json

# Redirect stdout and stderr to a log file if running without a console (pythonw.exe)
_project_dir = os.path.dirname(os.path.abspath(__file__))
if sys.stdout is None:
    try:
        sys.stdout = open(os.path.join(_project_dir, "lgtv-trigger.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.path.join(_project_dir, "lgtv-trigger.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

# Add virtual environment site-packages to sys.path so we can run directly with the base pythonw.exe
_venv_site_packages = os.path.join(_project_dir, ".venv", "Lib", "site-packages")
if os.path.exists(_venv_site_packages) and _venv_site_packages not in sys.path:
    sys.path.insert(0, _venv_site_packages)

from pynput import mouse, keyboard
try:
    from pynput.keyboard._win32 import SystemHook
except ImportError:
    SystemHook = None

# ==========================================
# (Display State listener has been removed based on user request)
# ==========================================

# ==========================================
# Remote Streaming Detector (Sunshine / Parsec)
# ==========================================
class RemoteStreamingDetector:
    """Detects active remote streaming sessions by polling Sunshine and Parsec log files."""

    class _LogWatcher:
        def __init__(self, name, log_path, connect_re, disconnect_re, restart_marker=None):
            self.name = name
            self.log_path = log_path
            self.connect_re = connect_re
            self.disconnect_re = disconnect_re
            self.restart_marker = restart_marker
            self.pos = 0
            self.clients = 0

    def __init__(self):
        self._lock = threading.Lock()

        # Sunshine log path
        sunshine_log = os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "Sunshine", "config", "sunshine.log"
        )
        # Parsec log path (prefer ProgramData, fallback to AppData)
        parsec_log = os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            "Parsec", "log.txt"
        )
        if not os.path.exists(parsec_log):
            parsec_log = os.path.expandvars(r"%appdata%\Parsec\log.txt")

        self._watchers = [
            self._LogWatcher(
                "Sunshine", sunshine_log,
                re.compile(r"CLIENT CONNECTED"),
                re.compile(r"CLIENT DISCONNECTED"),
            ),
            self._LogWatcher(
                "Parsec", parsec_log,
                re.compile(r"\w+#\d+ connected\."),
                re.compile(r"\w+#\d+ disconnected\."),
                restart_marker="===== Parsec: Started =====",
            ),
        ]

        # Read existing logs to determine current streaming state
        for w in self._watchers:
            self._init_watcher(w)

        # Print initialization status
        for w in self._watchers:
            if os.path.exists(w.log_path):
                print(f"Remote streaming detector: {w.name} log found, {w.clients} active client(s)")
            else:
                print(f"Remote streaming detector: {w.name} log not found, skipping")
        sys.stdout.flush()

    def _init_watcher(self, w):
        """Read existing log content to determine current streaming state."""
        if not os.path.exists(w.log_path):
            return
        try:
            with open(w.log_path, 'rb') as f:
                data = f.read()
                w.pos = f.tell()
            content = data.decode('utf-8', errors='ignore')
            # For logs with restart markers, only count events after the last restart
            if w.restart_marker:
                idx = content.rfind(w.restart_marker)
                if idx >= 0:
                    content = content[idx:]
            connects = len(w.connect_re.findall(content))
            disconnects = len(w.disconnect_re.findall(content))
            w.clients = max(0, connects - disconnects)
        except Exception as e:
            print(f"Warning: Failed to read {w.name} log: {e}", file=sys.stderr)
            sys.stderr.flush()

    @property
    def is_streaming(self):
        """Returns True if any remote streaming session is currently active."""
        with self._lock:
            return any(w.clients > 0 for w in self._watchers)

    def poll(self):
        """Check for new log entries. Should be called periodically (e.g. every second)."""
        for w in self._watchers:
            self._poll_watcher(w)

    def _poll_watcher(self, w):
        if not os.path.exists(w.log_path):
            return
        try:
            file_size = os.path.getsize(w.log_path)
            if file_size < w.pos:
                # Log was rotated or truncated, reset
                w.pos = 0
                with self._lock:
                    w.clients = 0
            if file_size == w.pos:
                return  # No new data
            with open(w.log_path, 'rb') as f:
                f.seek(w.pos)
                new_data = f.read()
                w.pos = f.tell()
            new_content = new_data.decode('utf-8', errors='ignore')
            with self._lock:
                old_clients = w.clients
                for line in new_content.splitlines():
                    if w.restart_marker and w.restart_marker in line:
                        w.clients = 0
                    elif w.connect_re.search(line):
                        w.clients += 1
                    elif w.disconnect_re.search(line):
                        w.clients = max(0, w.clients - 1)
                new_clients = w.clients
            if new_clients != old_clients:
                if new_clients > 0:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {w.name}: client connected ({new_clients} active). Remote input will be ignored.")
                else:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {w.name}: all clients disconnected. Local input resumed.")
                sys.stdout.flush()
        except Exception:
            pass


import ctypes
from ctypes import wintypes

# Windows API for SystemEventListener
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
wtsapi32 = ctypes.windll.wtsapi32

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = wintypes.LPARAM
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]

WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]

class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

GUID_CONSOLE_DISPLAY_STATE = GUID(0x6fe69556, 0x704a, 0x47a0, (0x8f, 0x24, 0xc2, 0x8d, 0x93, 0x6f, 0xda, 0x47))

class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_byte * 1)]

class SystemEventListener:
    def __init__(self, controller):
        self.controller = controller
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == 0x0218: # WM_POWERBROADCAST
                if wparam == 0x8013: # PBT_POWERSETTINGCHANGE
                    lpdata = lparam
                    # Read the GUID (first 4 bytes = Data1) directly from lpdata
                    guid_data1 = ctypes.cast(lpdata, ctypes.POINTER(wintypes.DWORD)).contents.value
                    if guid_data1 == GUID_CONSOLE_DISPLAY_STATE.Data1:
                        # Data field is at fixed offset: GUID(16) + DataLength(4) = 20 bytes
                        state = ctypes.cast(lpdata + 20, ctypes.POINTER(wintypes.DWORD)).contents.value
                        # state: 0=Off, 1=On, 2=Dimmed
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Display state changed: {state} ({'Off' if state == 0 else 'On' if state == 1 else 'Dimmed'})")
                        sys.stdout.flush()
                        if state == 0: # Display Off
                            self.controller._run_lgtv("off")
            elif msg == 0x02B1: # WM_WTSSESSION_CHANGE
                if wparam == 0x7: # WTS_SESSION_LOCK
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Session LOCKED (Win+L). Turning off TV.")
                    sys.stdout.flush()
                    self.controller._run_lgtv("off")
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_cb = WNDPROC(wndproc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = wndproc_cb
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "SystemEventListenerClass"
        
        user32.RegisterClassExW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "SystemEventListener", 0, 0, 0, 0, 0, 0, None, wc.hInstance, None)
        
        user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        user32.RegisterPowerSettingNotification.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), wintypes.DWORD]
        user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0)
        
        wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
        wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        wtsapi32.WTSRegisterSessionNotification(hwnd, 0)

        self.wndproc_cb = wndproc_cb # Keep reference
        
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    parser = argparse.ArgumentParser(description="Wake LGTV via specific key combos (Win+Shift+W / Mouse Middle).")
    parser.add_argument("--cooldown", type=int, default=10, help="Cooldown in seconds between triggers (default: 10)")
    parser.add_argument("--verbose", action="store_true", help="Print debug messages")
    parser.add_argument("--timeout", type=int, help="Deprecated: Idle timeout in seconds (ignored)")
    parser.add_argument("--wake-now", action="store_true", help="Execute the wake flow immediately and exit")
    args = parser.parse_args()

    class WakeController:
        def __init__(self, cooldown, verbose, remote_detector=None):
            self.cooldown = cooldown
            self.verbose = verbose
            self.remote_detector = remote_detector
            self.lock = threading.Lock()
            self.last_trigger_time = 0.0
            self._triggering = False
            self.vol_delta = 0
            self.vol_timer = None

        def _run_lgtv(self, lgtv_args):
            """Run an lgtv command and return (success, stdout_str)."""
            cmd = f"lgtv {lgtv_args}"
            try:
                creationflags = 0x08000000 if sys.platform == "win32" else 0
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    creationflags=creationflags, timeout=15
                )
                stdout = result.stdout.strip() if result.stdout else ""
                if result.stderr and result.stderr.strip():
                    print(f"  lgtv {lgtv_args} stderr: {result.stderr.strip()}", file=sys.stderr)
                return result.returncode == 0, stdout
            except subprocess.TimeoutExpired:
                print(f"  lgtv {lgtv_args}: timed out", file=sys.stderr)
                return False, ""
            except Exception as e:
                print(f"  lgtv {lgtv_args}: failed ({e})", file=sys.stderr)
                return False, ""

        def _get_power_status(self):
            """Query TV power status. Returns 'on', 'off', or None on error."""
            ok, output = self._run_lgtv("power-status")
            if ok and output:
                try:
                    data = json.loads(output)
                    return data.get("power")
                except (json.JSONDecodeError, KeyError):
                    pass
            return None

        def _do_wake(self, explicit):
            """Execute the LGTV wake flow: check status -> ON -> poll -> switch input."""
            source_str = "Explicit (User Input)" if explicit else "Implicit (Display ON)"
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Wake triggered [{source_str}]. Checking TV power status...")
            sys.stdout.flush()

            # Step 1: Check current power status
            status = self._get_power_status()
            print(f"  Power status: {status}")
            sys.stdout.flush()

            if status == "on":
                if not explicit:
                    print(f"  TV is already on and trigger was implicit. Ignoring to avoid interrupting TV usage.")
                    sys.stdout.flush()
                    return
                # Already on, just ensure correct input
                print(f"  TV is already on. Explicit trigger received. Switching input to HDMI_1...")
                sys.stdout.flush()
                ok, out = self._run_lgtv("input HDMI_1")
                if ok:
                    print(f"  Input switched to HDMI_1 successfully.")
                else:
                    print(f"  Failed to switch input.", file=sys.stderr)
                sys.stdout.flush()
                return

            # Step 2: TV is off (or unknown), send ON command
            print(f"  TV is off. Sending wake-on-LAN...")
            sys.stdout.flush()
            self._run_lgtv("on")

            # Step 3: Poll until TV is on (max 30 seconds, check every 2 seconds)
            poll_interval = 2
            max_wait = 30
            elapsed = 0
            tv_on = False

            while elapsed < max_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval
                status = self._get_power_status()
                print(f"  Polling power status ({elapsed}s/{max_wait}s): {status}")
                sys.stdout.flush()
                if status == "on":
                    tv_on = True
                    break

            if not tv_on:
                print(f"  TV did not turn on within {max_wait}s. Giving up.", file=sys.stderr)
                sys.stderr.flush()
                return

            # Step 4: TV is on, switch input to HDMI_1
            print(f"  TV is on! Switching input to HDMI_1...")
            sys.stdout.flush()
            ok, out = self._run_lgtv("input HDMI_1")
            if ok:
                print(f"  Input switched to HDMI_1 successfully.")
            else:
                print(f"  Failed to switch input.", file=sys.stderr)
            sys.stdout.flush()

        def trigger_wake(self, explicit=False):
            """Called on wake key combos. Fires with cooldown and remote-streaming guard."""
            # Skip if a remote streaming session is active
            if self.remote_detector and self.remote_detector.is_streaming:
                if self.verbose:
                    print(f"  Wake suppressed: remote streaming session active.")
                    sys.stdout.flush()
                return

            with self.lock:
                now = time.time()
                # Skip if already in progress
                if self._triggering:
                    if self.verbose:
                        print(f"  Wake suppressed: already in progress.")
                        sys.stdout.flush()
                    return
                # Skip if in cooldown
                if (now - self.last_trigger_time) < self.cooldown:
                    remaining = self.cooldown - (now - self.last_trigger_time)
                    if self.verbose:
                        print(f"  Wake suppressed: cooldown ({remaining:.0f}s remaining).")
                        sys.stdout.flush()
                    return
                self._triggering = True
                self.last_trigger_time = now

            # Run wake flow in background thread
            def run():
                try:
                    self._do_wake(explicit)
                finally:
                    with self.lock:
                        self._triggering = False
            threading.Thread(target=run, daemon=True).start()

        def adjust_volume(self, action):
            """Adjust Soundbar volume (up, down) with 100ms batching."""
            if self.remote_detector and self.remote_detector.is_streaming:
                if self.verbose:
                    print(f"  Volume suppressed: remote streaming session active.")
                    sys.stdout.flush()
                return

            with self.lock:
                self.vol_delta += 1 if action == "up" else -1
                if self.vol_timer is None:
                    self.vol_timer = threading.Timer(0.1, self._flush_volume)
                    self.vol_timer.start()

        def _flush_volume(self):
            with self.lock:
                delta = self.vol_delta
                self.vol_delta = 0
                self.vol_timer = None

            if delta == 0:
                return

            action = "up" if delta > 0 else "down"
            step = abs(delta)

            def run():
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Batched volume: {action.upper()} {step} (Routing to Soundbar)")
                sys.stdout.flush()
                import socket
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.5)
                        s.connect(('127.0.0.1', 9105))
                        s.sendall(f"{action} {step}".encode())
                except Exception as e:
                    print(f"  Failed to route volume to Soundbar: {e}", file=sys.stderr)
            threading.Thread(target=run, daemon=True).start()

        def run_forever(self):
            """Main loop: polls remote streaming detector."""
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] LGTV Wake Controller started.")
            print(f"  Wake triggers: Win+Shift+W (keyboard), Mouse Middle Button")
            print(f"  Sleep triggers: Display Off, Session Lock (Win+L)")
            print(f"  Volume control: Keyboard Volume Scroll -> Soundbar")
            print(f"  Cooldown: {self.cooldown}s between triggers")
            sys.stdout.flush()

            sys_listener = SystemEventListener(self)
            sys_listener.start()

            while True:
                time.sleep(1.0)
                if self.remote_detector:
                    self.remote_detector.poll()

    remote_detector = RemoteStreamingDetector()

    controller = WakeController(
        cooldown=args.cooldown,
        verbose=args.verbose,
        remote_detector=remote_detector
    )

    if args.wake_now:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Executing immediate wake flow (--wake-now).")
        sys.stdout.flush()
        controller._do_wake(explicit=True)
        return

    # ----------------------------------------------------
    # Keyboard & Mouse Listeners (pynput)
    # ----------------------------------------------------
    pressed_keys = set()

    def on_click(x, y, button, pressed):
        if button == mouse.Button.middle and pressed:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Wake trigger: Mouse Middle Button")
            sys.stdout.flush()
            controller.trigger_wake(explicit=True)

    def on_press(key):
        pressed_keys.add(key)
        # Win+Shift+W triggers wake
        if (key == keyboard.KeyCode.from_char('W') or key == keyboard.KeyCode.from_char('w')):
            has_win = keyboard.Key.cmd in pressed_keys or keyboard.Key.cmd_l in pressed_keys or keyboard.Key.cmd_r in pressed_keys
            has_shift = keyboard.Key.shift in pressed_keys or keyboard.Key.shift_l in pressed_keys or keyboard.Key.shift_r in pressed_keys
            if has_win and has_shift:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Wake trigger: Win+Shift+W")
                sys.stdout.flush()
                controller.trigger_wake(explicit=True)

    def on_release(key):
        pressed_keys.discard(key)

    def win32_event_filter(msg, data):
        # 256 = WM_KEYDOWN, 260 = WM_SYSKEYDOWN
        VK_VOLUME_DOWN = 0xAE
        VK_VOLUME_UP = 0xAF

        if data.vkCode in (VK_VOLUME_UP, VK_VOLUME_DOWN):
            if msg == 256 or msg == 260:
                action = "up" if data.vkCode == VK_VOLUME_UP else "down"
                controller.adjust_volume(action)
            # Suppress the event completely from Windows
            if SystemHook:
                raise SystemHook.SuppressException()
        return True

    mouse_listener = mouse.Listener(on_click=on_click)
    keyboard_listener = keyboard.Listener(
        on_press=on_press, 
        on_release=on_release,
        win32_event_filter=win32_event_filter
    )

    mouse_listener.daemon = True
    keyboard_listener.daemon = True

    try:
        mouse_listener.start()
        print("Mouse input hook started.")
        sys.stdout.flush()
    except Exception as e:
        print(f"Warning: Mouse input hook failed to start ({e}). This is expected if running as a Windows service.", file=sys.stderr)
        sys.stderr.flush()

    try:
        keyboard_listener.start()
        print("Keyboard input hook started.")
        sys.stdout.flush()
    except Exception as e:
        print(f"Warning: Keyboard input hook failed to start ({e}). This is expected if running as a Windows service.", file=sys.stderr)
        sys.stderr.flush()

    try:
        controller.run_forever()
    except KeyboardInterrupt:
        print("\nExiting script.")
        sys.stdout.flush()

if __name__ == "__main__":
    main()

