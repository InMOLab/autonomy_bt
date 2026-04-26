import os
import importlib
import pygame
from platforms.ros2.agent import Agent
from core.bt_nodes import Status
from core.utils import optional_import

class BTRunner:
    def __init__(self, config):
        self.config = config
        self.bt_viz_cfg = config['bt_runner'].get('bt_visualiser', {})
        self.bt_tick_rate = config['bt_runner']['bt_tick_rate']
        pygame.init()
        if self.bt_viz_cfg.get('enabled', False):
            os.environ['SDL_VIDEO_WINDOW_POS'] = "0,30"  # top-left corner
            self.screen_height = self.bt_viz_cfg.get('screen_height',500)
            self.screen_width = self.bt_viz_cfg.get('screen_width',500)
            self.screen = pygame.display.set_mode((self.screen_width, self.screen_height), pygame.RESIZABLE)
            self.background_color = (224, 224, 224)
            from .bt_visualiser import BTViewer
            self.bt_visualiser = BTViewer(
                direction=self.bt_viz_cfg.get('direction', 'Vertical')
            )
        self.clock = pygame.time.Clock()

        # Load PPA library dynamically from config
        ppa_module_path = config.get('scenario', {}).get('ppa_module')
        if ppa_module_path:
            ppa_mod = importlib.import_module(ppa_module_path)
            self._load_library = ppa_mod.load_library
            self._expand_behavior_tree = ppa_mod.expand_behavior_tree
            self._find_failed_conditions = ppa_mod.find_failed_conditions
        else:
            self._load_library = None
            self._expand_behavior_tree = None
            self._find_failed_conditions = None

        ppa_library_path = config['scenario'].get('ppa_library_path')
        self.ppa_library = self._load_library(ppa_library_path) if self._load_library else None

        # Load agent_mixin (replace_agent_BT) dynamically
        agent_mixin_mod = optional_import('plugins.mission_autonomy.agent_mixin')
        self._replace_agent_BT = getattr(agent_mixin_mod, 'replace_agent_BT', None) if agent_mixin_mod else None

        # Initialise
        self.reset()


    def reset(self):
        # Initialization
        self.running = True
        self.paused = False
        self.agent = None

        ros_namespace = self.config['agent'].get('namespaces', [])

        # Initialize agent
        self.agent = Agent(ros_namespace)

        # Provide global info and create BT
        scenario_path = self.config['scenario'].get('environment').replace('.', '/')
        # Project root: 3 levels up from platforms/ros2/bt_runner.py
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        behavior_tree_xml = f"{project_root}/{scenario_path}/{self.config['agent']['behavior_tree_xml']}"
        self.agent.create_behavior_tree(str(behavior_tree_xml))


    async def step(self):
        # Main bt_runner loop logic
        if self._replace_agent_BT:
            self._replace_agent_BT(self.agent)
        result = await self.agent.run_tree()
        if result == Status.FAILURE and self._find_failed_conditions and self._expand_behavior_tree:
            failed_conditions = self._find_failed_conditions(self.agent.blackboard)
            for failed_condition in failed_conditions:
                self.agent.tree = self._expand_behavior_tree(self.agent.tree, failed_condition, self.ppa_library, self.agent)
        self.clock.tick(self.bt_tick_rate)


    def close(self):
        pass

    def render(self):
        if self.bt_viz_cfg.get('enabled', False):
            self.bt_visualiser.render_tree(self.screen, self.agent.tree)

            if self.paused:
                font = pygame.font.Font(None, 48)
                text = font.render("Paused", True, (255, 0, 0))
                self.screen.blit(text, (10, 10))

            pygame.display.flip()


    def handle_keyboard_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
                    self.running = False
                elif event.key == pygame.K_p:
                    self.paused = not self.paused
