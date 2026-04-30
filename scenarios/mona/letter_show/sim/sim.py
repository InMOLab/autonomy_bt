"""
letter_show Sim.

Extensions over MonaSim:
  * SuperTask construction from yaml (``super_tasks.groups``) — a
    SuperTask is a visual + logical cluster of pixel-tasks that
    together form one letter (or sub-region of one).
  * Battery initialisation per agent (yaml ``agents.fixed_batteries``
    or random 40~90 %) and per-tick battery recording.
  * Replace-on-arrival generation: once every agent reaches its
    assigned task and a configurable wall-clock delay elapses, the
    current task list is **replaced in-place** with the next
    generation's positions/amounts (the next letter). Each agent's
    decision-maker state is reset so the next round of GRAPE/CBBA
    starts fresh.
  * Battery time-series CSV + two PNG graphs (battery vs distance
    moved, battery vs wall clock) saved with the rest of the results.

Real-robot mode wiring (UDP G commands, WhyCon listener, ESP-NOW P2P
relay) is inherited from MonaSim — driven by ``mona.mode``.
"""
from collections import Counter

import pygame

from core.utils import config
from platforms.mona.mona_sim import MonaSim
from platforms.pygame.utils_pygame import generate_positions
from scenarios.mona.letter_show.sim.task import Task
from scenarios.mona.letter_show.sim.super_task import SuperTask, size_for_count


# Visual style per super-task index: (draw_shape, color). Member tasks of
# each super-task pick up the corresponding visual.
_ST_TASK_VISUAL = {
    0: ('square', (30, 100, 220)),   # ST_0 → blue square
    1: ('circle', (220, 50, 50)),    # ST_1 → red circle
}


def _setup_agent_groups(agents, super_tasks):
    """Inject super-task references into each agent (all agents see all super tasks)."""
    for agent in agents:
        agent.super_tasks_info = super_tasks
        agent.super_task_message_to_share = {}
        agent.super_task_messages_received = []


def _generate_super_tasks(tasks):
    """Build SuperTask objects from yaml's ``super_tasks.groups``."""
    groups = config.get('super_tasks', {}).get('groups', [])

    # Parse all groups first to compute a shared (max) size — keeps all
    # super-task overlay rectangles the same size regardless of n_members.
    parsed = []
    for grp in groups:
        if isinstance(grp, dict):
            indices = grp.get('tasks', [])
            max_agents = grp.get('max_agents', None)
        else:
            indices = grp
            max_agents = None
        member_tasks = [tasks[i] for i in indices if i < len(tasks)]
        parsed.append((indices, max_agents, member_tasks))

    shared_size = max(size_for_count(len(m)) for _, _, m in parsed if m) if parsed else None

    super_tasks = []
    for st_id, (indices, max_agents, member_tasks) in enumerate(parsed):
        if member_tasks:
            super_tasks.append(SuperTask(
                st_id, member_tasks, max_agents=max_agents, size=shared_size,
            ))
            shape, color = _ST_TASK_VISUAL.get(st_id, ('circle', (100, 100, 100)))
            for t in member_tasks:
                t.draw_shape = shape
                t.color = color
    return super_tasks


class Sim(MonaSim):
    """letter_show extends MonaSim with super-task wiring + replace-on-arrive.

    ``Task`` / ``Agent`` are resolved dynamically by ``MonaSim._task_class``
    / ``_agent_class`` from ``config.scenario.environment``, so no override
    is needed here.
    """

    # ── generate_tasks override: support fixed_positions/amounts override ─────
    def _generate_tasks(self, task_quantity=None, task_id_start=0, seed=None,
                       fixed_positions_override=None, fixed_amounts_override=None):
        if task_quantity is None:
            task_quantity = config['tasks']['quantity']
        loc = config['tasks']['locations']
        fixed_positions = fixed_positions_override if fixed_positions_override is not None \
            else config['tasks'].get('fixed_positions', [])
        fixed_positions = [tuple(p) for p in fixed_positions]

        num_fixed = min(len(fixed_positions), task_quantity)
        num_random = task_quantity - num_fixed
        if num_random > 0:
            random_positions = generate_positions(
                num_random,
                loc['x_min'], loc['x_max'], loc['y_min'], loc['y_max'],
                radius=loc['non_overlap_radius'], seed=seed,
            )
        else:
            random_positions = []

        positions = fixed_positions[:num_fixed] + list(random_positions)
        tasks = [Task(idx + task_id_start, pos) for idx, pos in enumerate(positions)]

        if fixed_amounts_override is not None:
            for idx, t in enumerate(tasks):
                if idx < len(fixed_amounts_override):
                    t.amount = float(fixed_amounts_override[idx])
                    t.radius = t.amount / config['simulation']['task_visualisation_factor']
        return tasks

    # ── generate_agents override: per-agent battery seeding ───────────────────
    def _generate_agents(self, tasks_info, seed=None):
        Agent = self._agent_class()
        agent_quantity = config['agents']['quantity']
        loc = config['agents']['locations']
        fixed_positions = [tuple(p) for p in config['agents'].get('fixed_positions', [])]
        fixed_angles = config['agents'].get('fixed_angles', [])
        fixed_batteries = config['agents'].get('fixed_batteries', [])

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
            initial_battery = fixed_batteries[idx] if idx < len(fixed_batteries) else None
            battery_seed = (seed * 1000 + idx) if seed is not None else None
            agents.append(Agent(idx, pos, tasks_info, rotation=angle,
                                seed=battery_seed, initial_battery=initial_battery))
        return agents

    # ── reset(): wire super-tasks + battery log + arrive-then-delay state ────
    def reset(self):
        super().reset()
        # super().reset() already populated self.tasks / self.agents.
        self.super_tasks = _generate_super_tasks(self.tasks)
        _setup_agent_groups(self.agents, self.super_tasks)

        self.battery_records = {agent.agent_id: [] for agent in self.agents}

        # Replace-on-arrival generation state
        self._all_arrived_wall = None
        dyn = config.get('tasks', {}).get('dynamic_task_generation', {})
        self._completion_delay = dyn.get('delay_seconds', 1.0)
        self._arrive_threshold = config.get('tasks', {}).get('threshold_done_by_arrival', 1.0)

    # ── all_agents_arrived: same condition that IsArrivedAtTarget BT uses ────
    def _all_agents_arrived(self):
        if not self.agents:
            return False
        for agent in self.agents:
            task_id = agent.assigned_task_id
            if task_id is None:
                return False
            task = next((t for t in agent.tasks_info if t.task_id == task_id), None)
            if task is None:
                return False
            dist = (pygame.Vector2(task.position) - agent.position).length()
            if dist >= task.radius + self._arrive_threshold:
                return False
        return True

    # ── generate_tasks_if_needed override: replace on arrive + delay ─────────
    def generate_tasks_if_needed(self):
        if self.generation_count >= self.max_generations:
            return

        if not self._all_agents_arrived():
            self._all_arrived_wall = None
            return

        # All agents arrived — start (or continue) the dwell timer.
        if self._all_arrived_wall is None:
            self._all_arrived_wall = self.wall_clock_elapsed
        if self.wall_clock_elapsed - self._all_arrived_wall < self._completion_delay:
            return

        # Pick this generation's positions / amounts.
        seed = self.seed + self.generation_count + 1 if self.seed is not None else None
        dyn = config.get('tasks', {}).get('dynamic_task_generation', {})
        gens_cfg = dyn.get('generations', None)
        if gens_cfg and self.generation_count < len(gens_cfg):
            gen_cfg = gens_cfg[self.generation_count]
            dyn_positions = gen_cfg.get('fixed_positions', None)
            dyn_amounts = gen_cfg.get('fixed_amounts', None)
        else:
            dyn_positions = dyn.get('fixed_positions', None)
            dyn_amounts = dyn.get('fixed_amounts', None)

        new_tasks = self._generate_tasks(
            task_quantity=self.tasks_per_generation,
            task_id_start=0,
            seed=seed,
            fixed_positions_override=dyn_positions,
            fixed_amounts_override=dyn_amounts,
        )

        # Replace tasks in-place (agents share the same list reference).
        self.tasks.clear()
        self.tasks.extend(new_tasks)
        self.generation_count += 1
        self._all_arrived_wall = None

        # Rebuild super tasks against the new task objects + reset agent state.
        self.super_tasks = _generate_super_tasks(self.tasks)
        _setup_agent_groups(self.agents, self.super_tasks)
        for agent in self.agents:
            agent.task_amount_done = 0.0
            agent.assigned_task_id = None
            agent.planned_tasks = []
            agent.blackboard = {}
            # Reset heading. MonaAgent.update() removes the velocity-based
            # rotation drift that BaseAgent has, so without this an agent's
            # heading from the previous letter persists into the next one.
            # On near-collinear layouts (e.g. the 'S' letter, where T3-T4-T5
            # lie roughly on a line and a3/a5 see near-equal Hungarian costs
            # to T3 and T4), that residual heading sends each agent into a
            # long re-orientation arc — Hungarian re-runs every tick during
            # the rotation, the matching flips on each cost-tie reversal,
            # and the agents chatter without ever translating.
            agent.rotation = 0.0
            self._reset_agent_decision_maker(agent)

        if self.rendering_mode != "None":
            print(f"[{self.simulation_time:.2f}] Replaced with {self.tasks_per_generation} "
                  f"new tasks (Generation {self.generation_count}). Agents reset.")

    def _reset_agent_decision_maker(self, agent):
        """Walk the BT and call ``decision_maker.__init__(agent)`` to reset state.
        Used after replacing the task set so phase-2 algorithms (CBBA / Hungarian)
        start fresh."""
        def walk(node):
            if hasattr(node, 'decision_maker'):
                try:
                    node.decision_maker.__init__(agent)
                except Exception:
                    pass
            if hasattr(node, 'children'):
                for child in node.children:
                    walk(child)
        if hasattr(agent, 'tree') and agent.tree is not None:
            walk(agent.tree)

    # ── draw_tasks override: super-task overlays under regular tasks ─────────
    def draw_tasks(self):
        for st in self.super_tasks:
            st.draw(self.screen)
            st.draw_id(self.screen)
        super().draw_tasks()

    # ── draw_agents_info override: add a battery bar next to each agent ──────
    def draw_agents_info(self):
        super().draw_agents_info()
        if self.rendering_options.get('agent_battery'):
            self._draw_battery_overlay()

    def _draw_battery_overlay(self):
        """Vertical battery bar (HP-bar style) to the left of each agent.

        letter_show is currently the only scenario with `agent.battery`, so
        this lives here rather than on `MonaSim`. Other mona scenarios are
        unaffected even when the rendering option is left enabled — the
        method skips agents whose `battery` attribute is missing/None.
        """
        if not self.agents:
            return

        BAR_W, BAR_H, GAP = 5, 35, 6

        if not hasattr(self, '_battery_font') or self._battery_font is None:
            self._battery_font = pygame.font.SysFont(None, 14)

        for agent in self.agents:
            battery = getattr(agent, 'battery', None)
            if battery is None:
                continue

            # Anchor to the agent's body footprint (puppet/offboard) or fall
            # back to a default offset when body_radius is unset/0.
            anchor = int(getattr(agent, 'body_radius', 0)) or 40

            bar_x = int(agent.position.x) - anchor - GAP - BAR_W
            bar_y = int(agent.position.y) - BAR_H // 2

            bg_rect = pygame.Rect(bar_x, bar_y, BAR_W, BAR_H)
            pygame.draw.rect(self.screen, (190, 190, 190), bg_rect)

            ratio = max(0.0, min(1.0, battery / 100.0))
            fill_h = int(BAR_H * ratio)
            fill_y = bar_y + (BAR_H - fill_h)
            if ratio > 0.5:
                bar_color = (50, 200, 50)
            elif ratio > 0.2:
                bar_color = (230, 180, 0)
            else:
                bar_color = (220, 50, 50)
            if fill_h > 0:
                pygame.draw.rect(self.screen, bar_color,
                                 pygame.Rect(bar_x, fill_y, BAR_W, fill_h))
            pygame.draw.rect(self.screen, (80, 80, 80), bg_rect, 1)

            pct_surf = self._battery_font.render(f'{int(battery)}%', True, (30, 30, 30))
            pct_rect = pct_surf.get_rect(centerx=bar_x + BAR_W // 2, bottom=bar_y - 2)
            self.screen.blit(pct_surf, pct_rect)

    # ── record_timewise_result override: include battery + wall_clock ────────
    def record_timewise_result(self):
        agents_total_distance_moved = sum(agent.distance_moved for agent in self.agents)
        agents_total_task_amount_done = sum(agent.task_amount_done for agent in self.agents)
        remaining_tasks = sum(1 for t in self.tasks if not t.completed)
        tasks_total_amount_left = sum(t.amount for t in self.tasks)

        self.data_records.append([
            self.simulation_time,
            self.wall_clock_elapsed,
            agents_total_distance_moved,
            agents_total_task_amount_done,
            remaining_tasks,
            tasks_total_amount_left,
        ])

        for agent in self.agents:
            self.battery_records[agent.agent_id].append(
                (self.wall_clock_elapsed, agent.distance_moved, agent.battery)
            )

    # ── save_results override: timewise CSV header includes wall_clock; add battery graphs ──
    def save_results(self):
        if self.save_gif and self.rendering_mode == "Screen":
            self.recording = False
            self.result_saver.save_gif(self.frames)

        if self.save_timewise_result_csv:
            csv_path = self.result_saver.save_to_csv(
                "timewise",
                self.data_records,
                ['time', 'wall_clock', 'agents_total_distance_moved',
                 'agents_total_task_amount_done', 'remaining_tasks',
                 'tasks_total_amount_left'],
            )
            self.result_saver.plot_timewise_result(csv_path)

        if self.save_agentwise_result_csv:
            variables = ['agent_id', 'task_amount_done', 'distance_moved']
            agentwise = self.result_saver.get_agentwise_results(self.agents, variables)
            csv_path = self.result_saver.save_to_csv('agentwise', agentwise, variables)
            self.result_saver.plot_boxplot(csv_path, variables[1:])

        if self.save_timewise_result_csv and self.battery_records:
            self._plot_battery_graphs()

        if self.save_config_yaml:
            self.result_saver.save_config_yaml()

    def _plot_battery_graphs(self):
        # Lazy import — pulls in matplotlib only if the user actually saves results.
        import matplotlib.pyplot as plt
        import pandas as pd

        colors = plt.cm.tab10.colors
        base = self.result_saver.result_file_path.rsplit('.', 1)[0]

        rows = []
        for agent in self.agents:
            for (wall_clock, distance_moved, battery) in self.battery_records.get(agent.agent_id, []):
                rows.append({
                    'agent_id': agent.agent_id,
                    'wall_clock': wall_clock,
                    'distance_moved': distance_moved,
                    'battery': battery,
                })

        csv_path = base + '_battery.csv'
        df = pd.DataFrame(rows, columns=['agent_id', 'wall_clock', 'distance_moved', 'battery'])
        df.to_csv(csv_path, index=False)
        print(f"[Battery] Saved: {csv_path}")

        # Battery vs distance moved
        fig1, ax1 = plt.subplots(figsize=(10, 5))
        for i, agent in enumerate(self.agents):
            agent_df = df[df['agent_id'] == agent.agent_id]
            if agent_df.empty:
                continue
            ax1.plot(agent_df['distance_moved'], agent_df['battery'],
                     color=colors[i % len(colors)], label=f'Agent {agent.agent_id}')
        ax1.set_xlabel('Distance Moved (px)')
        ax1.set_ylabel('Battery (%)')
        ax1.set_title('Battery vs Distance Moved')
        ax1.set_ylim(0, 105)
        ax1.legend(loc='upper right', fontsize=8)
        ax1.grid(True)
        fig1.tight_layout()
        path1 = base + '_battery_vs_distance.png'
        fig1.savefig(path1)
        plt.close(fig1)
        print(f"[Battery] Saved: {path1}")

        # Battery vs wall-clock time
        fig2, ax2 = plt.subplots(figsize=(10, 5))
        for i, agent in enumerate(self.agents):
            agent_df = df[df['agent_id'] == agent.agent_id]
            if agent_df.empty:
                continue
            ax2.plot(agent_df['wall_clock'], agent_df['battery'],
                     color=colors[i % len(colors)], label=f'Agent {agent.agent_id}')
        ax2.set_xlabel('Wall Clock Time (s)')
        ax2.set_ylabel('Battery (%)')
        ax2.set_title('Battery vs Wall Clock Time')
        ax2.set_ylim(0, 105)
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True)
        fig2.tight_layout()
        path2 = base + '_battery_vs_time.png'
        fig2.savefig(path2)
        plt.close(fig2)
        print(f"[Battery] Saved: {path2}")
