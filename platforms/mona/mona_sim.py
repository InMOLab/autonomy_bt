"""
MonaSim — BaseSim subclass that activates MONA-specific machinery
(MonaComm bridge, WhyCon UDP listener, real-robot keyboard handler,
wall-clock display) based on a single yaml flag: ``mona.mode``.

The four supported modes (matching the four operation profiles in the
SPACE/MONA workflow) only differ in which external systems are wired up:

    mode             motion(UDP G/STOP)   comm(TCP↔ESP-NOW)   WhyCon UDP
    full_simulation        ✗                    ✗                 ✗
    puppet                 ✓                    ✗                 ✓
    p2p                    ✗                    ✓                 ✗
    offboard               ✓                    ✓                 ✓

The agent dynamics (``max_speed``, ``max_accel`` …) and BT XML are
identical across the four modes — they all simulate the same MONA
robot, with different external systems plugged in.
"""
import json
import socket
import threading

import pygame

from core.utils import config
from platforms.pygame.base_sim import BaseSim
from platforms.pygame.utils_pygame import ResultSaver, generate_positions
from platforms.mona.mona_comm import MonaComm


# Mode → (motion_via_udp, comm_via_tcp, whycon_listener, body_radius)
# body_radius represents the MONA robot's physical footprint and is a
# property of the robot itself — not of the operating mode — so it stays
# the same across all four modes.
_MODE_FLAGS = {
    'full_simulation': (False, False, False, 40),
    'puppet':          (True,  False, True,  40),
    'p2p':             (False, True,  False, 40),
    'offboard':        (True,  True,  True,  40),
}


def get_mode():
    """Return the configured mona.mode (default: full_simulation)."""
    return config.get('mona', {}).get('mode', 'full_simulation')


def get_mode_flags(mode=None):
    """Return (motion_enabled, comm_enabled, whycon_enabled, body_radius)."""
    mode = mode or get_mode()
    if mode not in _MODE_FLAGS:
        raise ValueError(
            f"[MonaSim] Unknown mona.mode='{mode}'. "
            f"Valid: {list(_MODE_FLAGS.keys())}"
        )
    return _MODE_FLAGS[mode]


class MonaSim(BaseSim):
    """BaseSim + wall-clock display + MONA mode wiring."""

    def __init__(self, config):
        super().__init__(config)

        self.mode = get_mode()
        self.motion_enabled, self.comm_enabled, self.whycon_enabled, _ = get_mode_flags(self.mode)

        # ESP32 P2P bridge (only if mode requires it)
        self.mona_comm = MonaComm(config.get("mona", {})) if self.comm_enabled else None

        # ResultSaver
        self.result_saver = ResultSaver(config)
        self.generate_tasks = self._generate_tasks

        self.reset()

        # WhyCon UDP listener (only if mode requires it)
        if self.whycon_enabled:
            threading.Thread(target=self._listen_whycon_udp, daemon=True).start()

    # ─── overridable helpers (subclass scenario can swap Task/Agent classes) ────

    def _task_class(self):
        """
        Resolve the scenario's Task class via ``config['scenario']['environment']``.
        Each MONA-aware scenario lives at ``scenarios/<...>/<name>/`` and must
        provide ``sim/task.py`` with a ``Task`` class.
        """
        import importlib
        env_pkg = config['scenario']['environment']
        return getattr(importlib.import_module(env_pkg + ".sim.task"), "Task")

    def _agent_class(self):
        """Same convention as ``_task_class``: resolve from ``scenario.environment``."""
        import importlib
        env_pkg = config['scenario']['environment']
        return getattr(importlib.import_module(env_pkg + ".sim.agent"), "Agent")

    def _generate_tasks(self, task_quantity=None, task_id_start=0, seed=None):
        Task = self._task_class()
        if task_quantity is None:
            task_quantity = config['tasks']['quantity']
        loc = config['tasks']['locations']
        positions = generate_positions(
            task_quantity,
            loc['x_min'], loc['x_max'], loc['y_min'], loc['y_max'],
            radius=loc['non_overlap_radius'], seed=seed,
        )
        return [Task(idx + task_id_start, p) for idx, p in enumerate(positions)]

    def _generate_agents(self, tasks_info, seed=None):
        Agent = self._agent_class()
        agent_quantity = config['agents']['quantity']
        loc = config['agents']['locations']
        fixed_positions = [tuple(p) for p in config['agents'].get('fixed_positions', [])]
        fixed_angles = config['agents'].get('fixed_angles', [])

        num_fixed = min(len(fixed_positions), agent_quantity)
        num_random = agent_quantity - num_fixed
        if num_random > 0:
            random_positions = generate_positions(
                num_random,
                loc['x_min'], loc['x_max'], loc['y_min'], loc['y_max'],
                radius=loc['non_overlap_radius'], seed=seed,
            )
        else:
            random_positions = []

        positions = fixed_positions[:num_fixed] + list(random_positions)
        agents = []
        for idx, pos in enumerate(positions):
            angle = fixed_angles[idx] if idx < len(fixed_angles) else 0
            agents.append(Agent(idx, pos, tasks_info, rotation=angle))
        return agents

    # ─── BaseSim hooks ──────────────────────────────────────────────────────────

    def reset(self):
        super().reset()
        self.tasks = self._generate_tasks(seed=self.seed)
        self.agents = self._generate_agents(self.tasks, seed=self.seed)
        self.data_records = []

        if self.mona_comm is not None:
            for agent in self.agents:
                agent.mona_comm = self.mona_comm

    def handle_keyboard_events(self):
        # Real-robot modes (puppet/offboard) disable the drag-and-drop and
        # use mouse-click-to-spawn-task instead — dragging an agent makes
        # no sense when WhyCon is the position source.
        if self.motion_enabled or self.whycon_enabled:
            self._handle_events_real_robot_mode()
        else:
            super().handle_keyboard_events()

    def _handle_events_real_robot_mode(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    self.running = False
                elif event.key == pygame.K_p:
                    self._toggle_pause()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not self.agents:
                    continue
                click_pos = pygame.Vector2(event.pos)
                Task = self._task_class()
                new_id = len(self.tasks)
                self.tasks.append(Task(new_id, click_pos))
                print(f"[{self.simulation_time:.2f}] Spawned Task {new_id} at "
                      f"({int(click_pos.x)}, {int(click_pos.y)})")

    # ─── Result saving (default; scenarios can override) ────────────────────────

    def save_results(self):
        if self.save_gif and self.rendering_mode == "Screen":
            self.recording = False
            self.result_saver.save_gif(self.frames)

        if self.save_timewise_result_csv:
            csv_path = self.result_saver.save_to_csv(
                "timewise",
                self.data_records,
                ['time', 'agents_total_distance_moved', 'agents_total_task_amount_done',
                 'remaining_tasks', 'tasks_total_amount_left'],
            )
            self.result_saver.plot_timewise_result(csv_path)

        if self.save_agentwise_result_csv:
            variables = ['agent_id', 'task_amount_done', 'distance_moved']
            agentwise = self.result_saver.get_agentwise_results(self.agents, variables)
            csv_path = self.result_saver.save_to_csv('agentwise', agentwise, variables)
            self.result_saver.plot_boxplot(csv_path, variables[1:])

        if self.save_config_yaml:
            self.result_saver.save_config_yaml()

    def record_timewise_result(self):
        self.data_records.append([
            self.simulation_time,
            sum(agent.distance_moved for agent in self.agents),
            sum(agent.task_amount_done for agent in self.agents),
            sum(1 for task in self.tasks if not task.completed),
            sum(task.amount for task in self.tasks),
        ])

    # ─── WhyCon UDP listener ────────────────────────────────────────────────────

    def _listen_whycon_udp(self):
        udp_port = int(self.config.get("mona", {}).get("udp_port", 9999))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", udp_port))
        print(f"[MonaSim] WhyCon UDP listening on 0.0.0.0:{udp_port}")
        while True:
            try:
                data, _ = sock.recvfrom(2048)
                msg = json.loads(data)
                agent_id = int(msg.get("agent_id", 0))
                x = float(msg["x"])
                y = float(msg["y"])
                yaw = msg.get("yaw", None)
                if 0 <= agent_id < len(self.agents):
                    ag = self.agents[agent_id]
                    if hasattr(ag, "set_position"):
                        ag.set_position(x, y, yaw)
            except Exception as e:
                print(f"[WhyCon UDP Error] {e}")
