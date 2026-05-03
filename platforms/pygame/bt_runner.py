import os

from platforms.pygame.base_agent import BaseAgent
from platforms.pygame.utils_pygame import snapshot_message


class BTRunner:
    def __init__(self, config):
        self.config = config
        self.agents = None

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
        # Freeze peer-message view at tick start so all agents see the same snapshot — the sequential loop below would otherwise cascade (agent N+1 reading agent N's just-updated message).
        BaseAgent._tick_message_snapshot = {
            agent.agent_id: snapshot_message(agent.message_to_share)
            for agent in self.agents
        }
        for agent in self.agents:
            await agent.run_tree()

    def close(self):
        if self.agent and hasattr(self.agent, 'tree'):
            self.agent.halt_tree()
