"""
Common BT nodes used across both pygame and ros2 platforms.
"""
from core.bt_nodes import *
import importlib
from core.utils import config

# Load decision-making class lazily: only if 'decision_making.plugin' is set in config.
_dm_plugin_path = config.get('decision_making', {}).get('plugin') if config else None
if _dm_plugin_path:
    _module_path, _class_name = _dm_plugin_path.rsplit('.', 1)
    decision_making_class = getattr(importlib.import_module(_module_path), _class_name)
else:
    decision_making_class = None

# Register in BTNodeList
BTNodeList.ACTION_NODES.extend(['AssignTask'])


class AssignTask(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._decide)
        if decision_making_class is None:
            raise RuntimeError("[AssignTask] 'decision_making.plugin' is not set in config.")
        if not getattr(agent, 'decision_maker', None):
            agent.decision_maker = decision_making_class(agent)

    def _decide(self, agent, blackboard):
        if not getattr(agent, 'decision_maker', None):
            agent.decision_maker = decision_making_class(agent)
        assigned_task_id = agent.decision_maker.decide(blackboard)
        agent.assigned_task_id = assigned_task_id  # mirrored for pygame rendering / CSV / external readers
        blackboard['assigned_task_id'] = assigned_task_id
        if assigned_task_id is None:
            return Status.FAILURE
        else:
            return Status.SUCCESS
