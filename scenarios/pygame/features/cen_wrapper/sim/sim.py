"""Sim class for cen_wrapper.

Adds to BaseSim: leader spawn/despawn ('L' key), static-mode auto-termination
(wall-clock stability/timeout), and assignment-CSV output for the 3-way
comparison experiment (pure-dec / wrapper / cen_grape).
"""
import csv
import os
import time
from types import SimpleNamespace

import pygame

from core.utils import config
from platforms.pygame.base_sim import BaseSim
from platforms.pygame.utils_pygame import ResultSaver
from scenarios.pygame.features.cen_wrapper.sim.task import generate_tasks
from scenarios.pygame.features.cen_wrapper.sim.agent import generate_agents


# Subdirectory for static-mode assignment results — comes from yaml's top-level `setup:` key.
SAVE_SUB_DIR = config.get('setup', 'default')


class CustomResultSaver(ResultSaver):
    """Adds the `{case_name}_seed{seed}_{type}.csv` rename used by the cendec experiments."""

    def __init__(self, config):
        super().__init__(config)
        self.case_name = config.get('case_name')
        self.seed = config.get('simulation', {}).get('random_seed')

    def save_to_csv(self, data_type, data, column_names):
        original_csv_path = super().save_to_csv(data_type, data, column_names)
        file_name = f"{self.case_name}_seed{self.seed}_{data_type}.csv"
        new_csv_path = os.path.join(os.path.dirname(original_csv_path), file_name)
        os.rename(original_csv_path, new_csv_path)
        print(f"Saved {file_name} at {new_csv_path}")
        return new_csv_path


class Sim(BaseSim):
    def __init__(self, config):
        super().__init__(config)

        # Set generate_tasks for dynamic task generation hook
        self.generate_tasks = generate_tasks
        self.result_saver = CustomResultSaver(config)

        # Leader management state (toggle via 'L' key)
        self.leader_present = True
        self.removed_leader = None

        self.reset()

    def reset(self):
        super().reset()

        self.tasks = generate_tasks(seed=self.seed)
        self.agents = generate_agents(self.tasks, seed=self.seed)

        self.data_records = []

        # Static-mode termination state (wall-clock based)
        self.static_start_real_time = time.time()
        self.last_signature_change_real_time = None
        self.last_assignment_signature = None

    # ── Result saving ───────────────────────────────────────────────────

    def save_results(self):
        # Save GIF
        if self.save_gif and self.rendering_mode == "Screen":
            self.recording = False
            print("Recording stopped.")
            self.result_saver.save_gif(self.frames)

        # Time series CSV + plot
        if self.save_timewise_result_csv:
            csv_file_path = self.result_saver.save_to_csv(
                "timewise",
                self.data_records,
                ['time', 'agents_total_distance_moved',
                 'agents_total_task_amount_done',
                 'remaining_tasks', 'tasks_total_amount_left'],
            )
            self.result_saver.plot_timewise_result(csv_file_path)

        # Per-agent CSV + boxplot
        if self.save_agentwise_result_csv:
            variables = ['agent_id', 'task_amount_done', 'distance_moved']
            agentwise = self.result_saver.get_agentwise_results(self.agents, variables)
            csv_file_path = self.result_saver.save_to_csv('agentwise', agentwise, variables)
            self.result_saver.plot_boxplot(csv_file_path, variables[1:])

        # Save config copy
        if self.save_config_yaml:
            self.result_saver.save_config_yaml()

    def record_timewise_result(self):
        agents_total_distance_moved = sum(
            agent.distance_moved for agent in self.agents if agent.type != 'Leader'
        )
        agents_total_task_amount_done = sum(
            agent.task_amount_done for agent in self.agents
        )
        remaining_tasks = sum(1 for task in self.tasks if not task.completed)
        tasks_total_amount_left = sum(task.amount for task in self.tasks)

        self.data_records.append([
            self.simulation_time,
            agents_total_distance_moved,
            agents_total_task_amount_done,
            remaining_tasks,
            tasks_total_amount_left,
        ])

    # ── Rendering overrides ─────────────────────────────────────────────

    def draw_agents_info(self):
        super().draw_agents_info()

        if self.rendering_options.get('leader_communication_topology'):
            for agent in self.agents:
                agent.draw_leader_communication_topology(self.screen, self.agents)

        for agent in self.agents:
            if agent.type == 'Leader' and self.rendering_options.get(
                'leader_communication_radius_circle'
            ):
                agent.draw_leader_communication_radius_circle(self.screen)
            if agent.type != 'Leader' and self.rendering_options.get(
                'agent_communication_radius_circle'
            ):
                agent.draw_communication_radius_circle(self.screen)

    # ── Keyboard ───────────────────────────────────────────────────────

    def _handle_extra_keys(self, events):
        """'L' key toggles leader removal/respawn (cen_wrapper-specific)."""
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_l:
                self.toggle_leader()

    def toggle_leader(self):
        if self.leader_present:
            self.remove_leader()
        else:
            self.respawn_leader()

    def remove_leader(self):
        leader_agents = [a for a in self.agents if a.type == 'Leader']
        if leader_agents:
            self.removed_leader = leader_agents[0]
            self.agents = [a for a in self.agents if a.type != 'Leader']
            self.leader_present = False

            for agent in self.agents:
                agent.set_global_info_agents(self.agents)

    def respawn_leader(self):
        if self.removed_leader:
            self.agents.append(self.removed_leader)
            self.leader_present = True

            for agent in self.agents:
                agent.set_global_info_agents(self.agents)

    # ── Static-mode termination ────────────────────────────────────────

    def update_simulation(self):
        super().update_simulation()
        if self.config['simulation'].get('mode', 'dynamic') == 'static':
            self._check_static_termination()

    def _check_static_termination(self):
        """Auto-stop static-mode runs once Follower assignments stabilise (wall-clock)."""
        WARMUP_SEC = 1.0
        STABILITY_SEC = 1.0
        TIMEOUT_SEC = self.config['simulation'].get('static_timeout_sec', 5.0)

        now = time.time()
        elapsed_real = now - self.static_start_real_time

        if elapsed_real > WARMUP_SEC:
            current_signature = []
            all_assigned = True
            for agent in self.agents:
                if agent.type != 'Follower':
                    continue
                task_id = getattr(agent, 'assigned_task_id', None)
                if task_id is None:
                    all_assigned = False
                    self.last_signature_change_real_time = None
                    self.last_assignment_signature = None
                    break
                current_signature.append((agent.agent_id, task_id))

            if all_assigned:
                current_signature = tuple(sorted(current_signature))
                if self.last_assignment_signature == current_signature:
                    stable_duration = now - self.last_signature_change_real_time
                    if stable_duration >= STABILITY_SEC:
                        print(f"[{self.simulation_time:.2f}] Assignments stable for {stable_duration:.1f}s (real). Saving and terminating.")
                        self.save_static_results()
                        self.running = False
                        return
                else:
                    self.last_assignment_signature = current_signature
                    self.last_signature_change_real_time = now

        if elapsed_real > TIMEOUT_SEC:
            print(f"[{self.simulation_time:.2f}] Simulation timed out ({TIMEOUT_SEC:.0f}s real). Saving current assignments and terminating.")
            self.save_static_results()
            self.running = False

    def save_static_results(self):
        """Save static-mode allocation snapshot to `output/assignments/<setup>/`."""
        rows, score_label, algo_type = self._build_static_results_rows()

        case_name = self.config.get('case_name', 'unknown').strip().lower().replace(' ', '_')
        seed = self.config['simulation'].get('random_seed', 0)

        assignments_dir = os.path.join("output/assignments", SAVE_SUB_DIR)
        os.makedirs(assignments_dir, exist_ok=True)
        file_path = os.path.join(assignments_dir, f"{case_name}_{seed}_static_results.csv")

        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Agent_ID', 'Assigned_Task_ID', 'Bundle', 'Distance_to_Task', score_label])
            writer.writerows(rows)

        print(f"[Static Results] Saved: {file_path} (algorithm: {algo_type}, metric: {score_label})")

    def _build_static_results_rows(self):
        """Build per-follower (agent_id, task_id, bundle, path_dist, score) rows + Total row."""
        algo_type = self._detect_algorithm_type()
        score_label = {
            'cbba':      'Expected_Reward_from_Task',
            'sga':       'Expected_Reward_from_Task',
            'hungarian': 'Expected_Reward',
            'grape':     'Utility',
        }.get(algo_type, 'Score')

        rows = []
        total_dist = 0.0
        total_score = 0.0

        for agent in self.agents:
            if agent.type != 'Follower':
                continue
            planned = getattr(agent, 'planned_tasks', [])
            task_id = planned[0].task_id if planned else None
            bundle = [t.task_id for t in planned] if planned else []

            if planned:
                current_pos = agent.position
                agent_path_dist = 0.0
                for task in planned:
                    tpos = pygame.Vector2(task.position)
                    agent_path_dist += current_pos.distance_to(tpos)
                    current_pos = tpos
                total_dist += agent_path_dist
            else:
                agent_path_dist = -1.0

            score = self._compute_agent_score(algo_type, agent, planned)
            total_score += score
            rows.append([agent.agent_id, task_id, bundle, agent_path_dist, score])

        rows.append(['Total', '', '', total_dist, total_score])
        return rows, score_label, algo_type

    def _detect_algorithm_type(self):
        case_name = self.config.get('case_name', '').upper()
        if 'SGA' in case_name:
            return 'sga'
        elif 'CBBA' in case_name:
            return 'cbba'
        elif 'GRAPE' in case_name:
            return 'grape'
        elif 'HUNGARIAN' in case_name:
            return 'hungarian'
        return 'unknown'

    def _compute_agent_score(self, algo_type, agent, planned):
        if not planned:
            return 0.0

        if algo_type in ('cbba', 'sga'):
            from scenarios.pygame.features.cen_wrapper.plugins.sga import SGA
            return SGA.calculate_score_along_path(None, agent, planned)
        elif algo_type == 'hungarian':
            from scenarios.pygame.features.cen_wrapper.plugins.hungarian import Hungarian
            return Hungarian.compute_weight_value(None, agent, planned[0])
        elif algo_type == 'grape':
            from scenarios.pygame.features.cen_wrapper.plugins.cen_grape import CenGRAPE
            partition = {}
            for a in self.agents:
                if a.type == 'Follower':
                    p = getattr(a, 'planned_tasks', [])
                    if p:
                        partition.setdefault(p[0].task_id, set()).add(a.agent_id)
            grape_ctx = SimpleNamespace(partition=partition)
            return CenGRAPE.compute_utility(grape_ctx, agent, planned[0])

        return 0.0
