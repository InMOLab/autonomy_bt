"""
Battery telemetry receiver for the letter_show scenario (puppet mode).

Each MONA robot's Arduino periodically sends a small UDP packet

    {"battery": <pct>, "pulses": <n>}

to a fixed port (default 5005 — see ``mona.battery_listen_port``). The packet
carries no agent id, so the sender is identified by its source IP, matched
against ``mona.robots[].host``. Only the latest ``battery`` percentage per
agent is kept; agents poll it via :meth:`BatteryReceiver.get_battery`. The
``pulses`` field is currently ignored.

``BatteryReceiver`` is a lazily-created singleton (:meth:`get_instance`) so the
listening socket is opened once and shared by every agent — and only in modes
that actually have real robots wired up (``Agent`` only touches it when
``is_real_robot`` is True).
"""
import json
import socket
import threading
from typing import Optional


class BatteryReceiver:
    _instance: Optional['BatteryReceiver'] = None
    _instance_lock = threading.Lock()

    def __init__(self, listen_port: int, ip_to_agent_id: dict):
        self._ip_to_agent_id = dict(ip_to_agent_id)   # {robot_ip: agent_id}
        self._battery_data: dict = {}                  # {agent_id: battery%}
        self._data_lock = threading.Lock()

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", int(listen_port)))
        self._sock.settimeout(0.5)

        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        print(f"[BatteryReceiver] Listening on UDP port {listen_port}")

    # ── Public API ──────────────────────────────────────────────────────────

    def get_battery(self, agent_id: int) -> Optional[float]:
        """Latest battery % for ``agent_id``, or None if nothing received yet."""
        with self._data_lock:
            return self._battery_data.get(agent_id)

    def close(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass

    # ── Background recv loop ────────────────────────────────────────────────

    def _recv_loop(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = json.loads(data.decode("utf-8"))
                batt = float(payload["battery"])
            except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError):
                continue
            agent_id = self._ip_to_agent_id.get(addr[0])
            if agent_id is None:
                continue
            with self._data_lock:
                self._battery_data[agent_id] = batt

    # ── Factory ─────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls, config: dict) -> 'BatteryReceiver':
        """Return the shared singleton, creating it on first call."""
        with cls._instance_lock:
            if cls._instance is None:
                mona_cfg = config.get('mona', {})
                listen_port = int(mona_cfg.get('battery_listen_port', 5005))
                ip_to_agent_id = {
                    robot['host']: int(robot['agent_id'])
                    for robot in mona_cfg.get('robots', [])
                    if 'host' in robot and 'agent_id' in robot
                }
                cls._instance = cls(listen_port, ip_to_agent_id)
            return cls._instance
