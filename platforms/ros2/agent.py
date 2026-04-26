import pygame
from core.utils import config, optional_import
env_pkg = config.get('scenario').get('environment')
bt_module = optional_import(env_pkg + ".bt_nodes")

from core.bt_constructor import build_behavior_tree
from platforms.ros2.ros_bridge import ROSBridge

class Agent:
    def __init__(self, ros_namespace=None):
        self.blackboard = {}
        self.ros_bridge = ROSBridge.get()
        self.ros_namespace = ros_namespace
        self.type = config['agent'].get('type', None) # agent type 생성

        self.messages_received = []

        # For smooth integration with the SPACE simulator
        self.agent_id = ros_namespace.strip('/') if ros_namespace else "no_id_agent" # agent_id 생성
        self.message_to_share = {} # BT 노드에서 설정하는 임시 속성: 다음 틱에 outbox로 송신할 메시지
        self.position = pygame.math.Vector2(0, 0) # Agent의 현재 위치 (초기값은 (0, 0))


    def create_behavior_tree(self, behavior_tree_xml):
        self.behavior_tree_xml = behavior_tree_xml
        self.tree = build_behavior_tree(self, behavior_tree_xml, env_pkg)

    def _reset_bt_action_node_status(self):
        self.tree.reset()

    async def run_tree(self):
        self._reset_bt_action_node_status()
        return await self.tree.run(self, self.blackboard)

    def reset_messages_received(self):
        self.messages_received = []

    def set_planned_tasks(self, *_):
        pass  # Visualization handled by ROS tools

    def halt_tree(self):
        """트리 전체를 재귀적으로 halt — 종료 시 진행 중인 ROS Action goal 취소에 사용."""
        def _halt(node):
            if hasattr(node, 'children'):
                for child in node.children:
                    _halt(child)
            node.halt()
        _halt(self.tree)
