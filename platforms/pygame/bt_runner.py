import os
import numpy as np
from scipy.spatial.distance import cdist

from platforms.pygame.base_agent import BaseAgent
from platforms.pygame.utils_pygame import snapshot_message


class BTRunner:
    def __init__(self, config):
        self.config = config
        self.agents = None
        # Freeze peer-message view per tick to simulate parallel execution; default off (cascade is faster for high-contention scenarios like simple/grape).
        self.message_snapshot_enabled = config.get('simulation', {}).get('message_snapshot', False)

    def initialize(self, agents):
        self.agents = agents
        # If agents already have behavior trees (created by Sim), skip BT creation
        if agents and hasattr(agents[0], 'tree') and agents[0].tree is not None:
            return

        # Provide global info and create behavior tree
        for agent in self.agents:
            agent.set_global_info_agents(self.agents)
            scenario_path = self.config['scenario'].get('environment').replace('.', '/')
            # Project root: 3 levels up from platforms/pygame/bt_runner.py
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            behavior_tree_xml = f"{project_root}/{scenario_path}/{self.config['agents']['behavior_tree_xml']}"
            agent.create_behavior_tree(str(behavior_tree_xml))


    async def step(self):
        # Precompute N×N pairwise squared-distance matrix once per tick so `get_agents_nearby` can use a numpy mask instead of N C-method calls per agent.
        n = len(self.agents)
        if n > 0:
            positions = np.array([[a.position.x, a.position.y] for a in self.agents])
            BaseAgent._tick_dist_sq = cdist(positions, positions, 'sqeuclidean')
            BaseAgent._tick_agents = self.agents
            BaseAgent._tick_agent_index = {a.agent_id: i for i, a in enumerate(self.agents)}

        if self.message_snapshot_enabled:
            BaseAgent._tick_message_snapshot = {
                agent.agent_id: snapshot_message(agent.message_to_share)
                for agent in self.agents
            }
        for agent in self.agents:
            await agent.run_tree()

    def close(self):
        if self.agent and hasattr(self.agent, 'tree'):
            self.agent.halt_tree()
