"""
MonaAgent — BaseAgent extended with the rotation-shim controller and
optional MONA real-robot interfaces (UDP motion + TCP/ESP-NOW peer comm).

Composition (set via yaml + sim.py, driven by ``mona.mode``):
    - motion-enabled mode (puppet / offboard) + matching agent_id in mona.robots
        → self._mona (MonaClient) is created; follow() sends UDP G commands
          and update() skips physics. Position arrives via set_position()
          from a WhyCon UDP listener.
    - comm-enabled mode (p2p / offboard)
        → sim.py assigns agent.mona_comm = MonaComm(...). update()
          compresses CBBA broadcasts and forwards them through mona_comm;
          received peer messages are decoded into self.messages_received,
          replacing the in-process P2P loop.

Either, both, or neither of these can be active per mode.
The rotation shim is always on (no yaml flag): full_simulation also uses it
so simulated MONA dynamics match the real robot's rotate-then-move profile.
"""
import math
import time
import pygame
from typing import Optional

from core.utils import config
from platforms.pygame.base_agent import BaseAgent
from platforms.mona.mona_client import MonaClient


# Module-level config (re-derived to avoid coupling to base_agent's locals)
_sampling_time = 1.0 / config['simulation']['sampling_freq']
_agent_track_size = config['simulation']['agent_track_size']
_agent_approaching_to_target_radius = config['agents']['target_approaching_radius']

# Rotation shim threshold (radians, ~2.9°)
_ALIGN_THRESHOLD = 0.05

# WhyCon noise filter (pixels). Movement smaller than this is ignored when
# accumulating distance_moved.
_WHYCON_NOISE_THRESHOLD = 1.0

# CBBA bid compression — used by offboard mode to fit within ESP-NOW 250B.
_BID_SCALE_FACTOR = float(config.get('mona', {}).get('bid_scale_factor', 1000.0))
_TIMESTAMP_OFFSET = int(time.time())


def _is_numeric_key(key) -> bool:
    try:
        int(key)
        return True
    except (ValueError, TypeError):
        return False


class MonaAgent(BaseAgent):
    """BaseAgent + rotation shim + optional MONA real-robot/comm interfaces.

    Visualisation knobs:
        task_colors: scenario-provided dict for `update_color()`. Keys are
            assigned_task_id values; default colour is dark grey when missing.
        body_radius: when >0, `draw()` adds a body outline circle (used by
            puppet/offboard to make the real-robot footprint visible).
    """

    def __init__(self, agent_id, position, tasks_info, rotation=0,
                 task_colors=None, body_radius=None):
        super().__init__(agent_id, position, tasks_info)
        self.rotation = float(rotation)
        self.work_rate = config['agents']['work_rate']

        # Rotation shim state
        self._rotation_shim_aligned = True
        self._movement_commanded = False

        # MONA UDP motion client (puppet/offboard)
        self._mona: Optional[MonaClient] = None
        self.is_real_robot = False
        self._position_initialized = False

        # P2P comm (offboard/p2p) — set externally by sim.py
        self.mona_comm = None
        self._cfg_comm_radius = self.communication_radius
        self._vis_keep_sec = 0.1
        self._last_peer_ids = set()
        self._last_peer_toa = 0.0

        # Visualisation: body_radius represents the MONA robot's physical
        # footprint in simulator pixels. Resolution order:
        #   1. explicit kwarg (rare; for tests)
        #   2. yaml ``agents.body_radius`` (recommended — depends on
        #      WhyCode camera calibration: pixels-per-meter)
        #   3. mode default from `_MODE_FLAGS` (fallback)
        self._task_colors = task_colors or {}
        if body_radius is None:
            body_radius = config.get('agents', {}).get('body_radius')
        if body_radius is None:
            from platforms.mona.mona_sim import get_mode_flags
            _, _, _, body_radius = get_mode_flags()
        self.body_radius = int(body_radius)

        self._init_robot_connection()

    # ==================== Robot Connection ====================

    def _init_robot_connection(self):
        """
        Set up the UDP motion client only when ``mona.mode`` is one of the
        motion-enabled modes (puppet / offboard) and this agent_id has a
        matching entry in ``mona.robots``. p2p / full_simulation modes
        keep motion simulated (no UDP commands sent).
        """
        from platforms.mona.mona_sim import get_mode_flags
        motion_enabled, _, _, _ = get_mode_flags()
        if not motion_enabled:
            return

        mona_cfg = config.get('mona', {})
        robot_cfg = self._find_robot_config(mona_cfg)
        if robot_cfg is None:
            return

        self.is_real_robot = True
        self._mona = MonaClient(
            host=robot_cfg.get('host', '127.0.0.1'),
            port=robot_cfg.get('port', 8080),
            px_to_mm=mona_cfg.get('px_to_mm', 1.0),
            distance_scale=mona_cfg.get('distance_scale', 1.0),
        )
        print(f"[MonaAgent {self.agent_id}] Connected to {robot_cfg.get('host')}:{robot_cfg.get('port')}")

    def _find_robot_config(self, mona_cfg: dict):
        for robot in mona_cfg.get('robots', []):
            if int(robot.get('agent_id', -1)) == self.agent_id:
                return robot
        return None

    def _is_robot_connected(self) -> bool:
        return self.is_real_robot and self._mona is not None and self._mona.is_connected

    # ==================== Position (external injection) ====================

    def set_position(self, x: float, y: float, yaw: float = None):
        """
        Update position from external sensor (e.g., WhyCon UDP listener).
        First call seeds the position; subsequent calls accumulate distance_moved
        only when the move exceeds the noise threshold.
        """
        if not self._position_initialized:
            self.position.x = float(x)
            self.position.y = float(y)
            if yaw is not None:
                self.rotation = float(yaw)
            self._position_initialized = True
            return

        old_pos = pygame.Vector2(self.position.x, self.position.y)
        self.position.x = float(x)
        self.position.y = float(y)
        if yaw is not None:
            self.rotation = float(yaw)

        if self.is_real_robot:
            distance = (self.position - old_pos).length()
            if distance > _WHYCON_NOISE_THRESHOLD:
                self.distance_moved += distance

    # ==================== Movement ====================

    def follow(self, target):
        """
        Real robot: send G command via UDP.
        Simulation: rotation-shim controller (rotate-in-place then drive straight).
        """
        self._movement_commanded = True

        if self._is_robot_connected():
            self._mona.send_g_to(
                current_position=(self.position.x, self.position.y),
                current_heading=self.rotation,
                target_position=(float(target[0]), float(target[1])),
            )
            return

        self._follow_rotation_shim(target)

    def _follow_rotation_shim(self, target):
        target_vec = target if isinstance(target, pygame.Vector2) else pygame.Vector2(target)
        desired = target_vec - self.position
        d = desired.length()

        if d == 0:
            self._rotation_shim_aligned = True
            return

        desired_angle = math.atan2(desired.y, desired.x)
        angle_diff = desired_angle - self.rotation
        while angle_diff > math.pi:
            angle_diff -= 2 * math.pi
        while angle_diff < -math.pi:
            angle_diff += 2 * math.pi

        if abs(angle_diff) > _ALIGN_THRESHOLD:
            # Phase 1: rotate in place; hard-brake any residual velocity.
            self._rotation_shim_aligned = False
            rot_step = math.copysign(min(abs(angle_diff), self.max_angular_speed), angle_diff)
            self.rotation += rot_step * _sampling_time
            self.velocity = pygame.Vector2(0, 0)
            self.acceleration = pygame.Vector2(0, 0)
            return

        # Phase 2: aligned → drive forward, lock heading to target direction.
        self._rotation_shim_aligned = True
        self.rotation = desired_angle
        if d < _agent_approaching_to_target_radius:
            speed = self.max_speed * (d / _agent_approaching_to_target_radius)
        else:
            speed = self.max_speed
        forward = pygame.Vector2(math.cos(self.rotation), math.sin(self.rotation))
        desired_vel = forward * speed
        steer = self.limit(desired_vel - self.velocity, self.max_accel)
        self.applyForce(steer)

    def stop(self):
        """
        Stop the agent. Real robot: send STOP UDP. Always: zero velocity and
        leave rotation as-is (no atan2(0,0) drift, since update() never runs
        the velocity-derived rotation update for MonaAgent).
        """
        if self._is_robot_connected():
            self._mona.send_stop()
        self.velocity = pygame.Vector2(0, 0)
        self.acceleration = pygame.Vector2(0, 0)
        self._movement_commanded = True  # mark this tick as "intentional stop"

    # ==================== Update Loop ====================

    def update(self):
        if self._is_robot_connected():
            # Real robot: physics is handled by the robot itself; position arrives
            # via set_position(). Issue STOP whenever no task is assigned.
            if self.assigned_task_id is None:
                self._mona.send_stop()
            self._sync_p2p()
            self._movement_commanded = False
            return

        # ── Simulation mode ────────────────────────────────────────────────
        # Deceleration when no movement was commanded this tick (idle).
        if not self._movement_commanded:
            v_len = self.velocity.length()
            if v_len > 0:
                if v_len <= self.max_accel * _sampling_time:
                    self.velocity = pygame.Vector2(0, 0)
                else:
                    brake = -self.velocity.normalize() * self.max_accel
                    self.velocity += brake * _sampling_time

        # Standard velocity → position integration.
        self.velocity += self.acceleration * _sampling_time
        self.velocity = self.limit(self.velocity, self.max_speed)
        self.position += self.velocity * _sampling_time
        self.acceleration *= 0

        self.distance_moved += self.velocity.length() * _sampling_time
        self.memory_location.append((self.position.x, self.position.y))
        if len(self.memory_location) > _agent_track_size:
            self.memory_location.pop(0)

        # Rotation update is intentionally skipped — the shim manages rotation
        # directly inside follow(). When idle, rotation stays put (no drift).

        self._sync_p2p()
        self._movement_commanded = False

    # ==================== P2P (ESP32 bridge) ====================

    def _sync_p2p(self):
        """Push compressed CBBA broadcast to ESP32 and pull peer messages back."""
        mc = self.mona_comm
        if mc is None:
            return
        compressed = self._build_compressed_cbba_message()
        mc.set_message(self, msg_override=compressed)
        self._receive_p2p_messages()

    def _build_compressed_cbba_message(self) -> dict:
        """Compress CBBA fields to fit ESP-NOW 250B payload limit."""
        original = getattr(self, "message_to_share", {}) or {}
        if not original:
            return {}

        y_dict = original.get('winning_bids', {}) or {}
        z_dict = original.get('winning_agents', {}) or {}

        compressed_y = {}
        compressed_z = {}
        for task in self.tasks_info:
            if task.completed:
                continue
            tid = task.task_id
            val_y = y_dict.get(tid, y_dict.get(str(tid)))
            if val_y is not None and float(val_y) > 0:
                compressed_y[tid] = int(round(float(val_y) * _BID_SCALE_FACTOR))
            val_z = z_dict.get(tid, z_dict.get(str(tid)))
            if val_z is not None and val_z != -1:
                compressed_z[tid] = int(val_z)

        s_data = original.get('message_received_time_stamp', {}) or {}
        compressed_s = {}
        for ag_id, ts in s_data.items():
            if isinstance(ts, (int, float)):
                compressed_s[ag_id] = int(ts) - _TIMESTAMP_OFFSET

        return {
            "id": int(self.agent_id),
            "y": compressed_y,
            "z": compressed_z,
            "s": compressed_s,
        }

    def _receive_p2p_messages(self):
        """Pull peer messages from MonaComm, decompress, and update neighbour state."""
        mc = self.mona_comm
        if mc is None:
            return

        now = time.time()
        peer_ids = set()
        self.reset_messages_received()

        monitor = mc.get_message(self.agent_id)
        if isinstance(monitor, dict):
            recv = monitor.get("received_messages") or {}
            for _, v in recv.items():
                if not (isinstance(v, dict) and "y" in v):
                    continue
                restored = self._decompress_peer_message(v)
                sender_id = restored.get("agent_id")
                if sender_id is None:
                    continue
                if not self._peer_in_range(int(sender_id)):
                    continue
                self.receive_message(restored)
                try:
                    peer_ids.add(int(sender_id))
                except (ValueError, TypeError):
                    pass

        if peer_ids:
            self._last_peer_ids, self._last_peer_toa = peer_ids, now

        if self._last_peer_ids and (now - self._last_peer_toa) < self._vis_keep_sec:
            visual_peer_ids = self._last_peer_ids
        else:
            visual_peer_ids = set()

        all_agents = self.agents_info or []
        if self._cfg_comm_radius > 0:
            radius_sq = self._cfg_comm_radius ** 2
            self.agents_nearby = [
                ag for ag in all_agents
                if ag.agent_id in visual_peer_ids
                and ag.agent_id != self.agent_id
                and (self.position - ag.position).length_squared() <= radius_sq
            ]
        else:
            self.agents_nearby = [
                ag for ag in all_agents
                if ag.agent_id in visual_peer_ids and ag.agent_id != self.agent_id
            ]

        if self.agents_nearby:
            observed = max((self.position - ag.position).length() for ag in self.agents_nearby)
            cap = self._cfg_comm_radius or 0
            self.communication_radius = min(observed, cap) if cap > 0 else observed
        else:
            self.communication_radius = 0

    def _peer_in_range(self, sender_id: int) -> bool:
        if self._cfg_comm_radius <= 0:
            return True
        sender = next(
            (ag for ag in (self.agents_info or []) if ag.agent_id == sender_id),
            None,
        )
        if sender is None:
            return True
        return (self.position - sender.position).length_squared() <= self._cfg_comm_radius ** 2

    def _decompress_peer_message(self, v: dict) -> dict:
        restored = {"agent_id": v.get("id", v.get("agent_id"))}

        # Winning bids
        y_raw = v.get("y", {})
        if isinstance(y_raw, list):
            restored["winning_bids"] = {
                i: (val / _BID_SCALE_FACTOR)
                for i, val in enumerate(y_raw)
                if isinstance(val, (int, float)) and val > 0
            }
        elif isinstance(y_raw, dict):
            restored["winning_bids"] = {
                int(tid): (val / _BID_SCALE_FACTOR)
                for tid, val in y_raw.items()
                if isinstance(val, (int, float)) and _is_numeric_key(tid)
            }
        else:
            restored["winning_bids"] = {}

        # Winning agents
        z_raw = v.get("z", {})
        if isinstance(z_raw, list):
            restored["winning_agents"] = {
                i: val
                for i, val in enumerate(z_raw)
                if isinstance(val, (int, float)) and val != -1
            }
        elif isinstance(z_raw, dict):
            restored["winning_agents"] = {
                int(tid): val
                for tid, val in z_raw.items()
                if isinstance(val, (int, float)) and _is_numeric_key(tid)
            }
        else:
            restored["winning_agents"] = {}

        # Time stamps
        s_raw = v.get("s", {})
        if isinstance(s_raw, dict):
            restored["message_received_time_stamp"] = {
                str(ag_id): (int(ts) + _TIMESTAMP_OFFSET)
                for ag_id, ts in s_raw.items()
                if isinstance(ts, (int, float)) and _is_numeric_key(ag_id)
            }
        else:
            restored["message_received_time_stamp"] = {}

        return restored

    # ==================== Visualisation ====================

    def draw(self, screen):
        """Draw the agent: optional body outline (when body_radius > 0) +
        a heading triangle coloured by the assigned task."""
        if self.body_radius > 0:
            pygame.draw.circle(
                screen, (0, 0, 0),
                (int(self.position.x), int(self.position.y)),
                self.body_radius, width=4,
            )

        size = 10
        angle = self.rotation
        p1 = pygame.Vector2(self.position.x + size * math.cos(angle),
                            self.position.y + size * math.sin(angle))
        p2 = pygame.Vector2(self.position.x + size * math.cos(angle + 2.5),
                            self.position.y + size * math.sin(angle + 2.5))
        p3 = pygame.Vector2(self.position.x + size * math.cos(angle - 2.5),
                            self.position.y + size * math.sin(angle - 2.5))
        self.update_color()
        pygame.draw.polygon(screen, self.color, [p1, p2, p3])

    def update_color(self):
        self.color = self._task_colors.get(self.assigned_task_id, (20, 20, 20))
