from core.bt_nodes import *
from core.bt_nodes_common import AssignTask, decision_making_class
import random
from core.utils import config, first_action_or_condition_name

# Register platform-specific nodes in BTNodeList
BTNodeList.ACTION_NODES.extend(['LocalSensingNode', 'DecisionMakingNode', 'GatherLocalInfo'])

# Local Sensing node
class LocalSensingNode(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._local_sensing)

    def _local_sensing(self, agent, blackboard):
        blackboard['local_tasks_info'] = agent.get_tasks_nearby(with_completed_task = False)
        blackboard['local_agents_info'] = agent.local_message_receive()

        return Status.SUCCESS

# Decision-making node
class DecisionMakingNode(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._decide)
        if decision_making_class is None:
            raise RuntimeError("[DecisionMakingNode] 'decision_making.plugin' is not set in config.")
        self.decision_maker = decision_making_class(agent)

    def _decide(self, agent, blackboard):
        assigned_task_id = self.decision_maker.decide(blackboard)
        agent.set_assigned_task_id(assigned_task_id)
        blackboard['assigned_task_id'] = assigned_task_id
        if assigned_task_id is None:
            return Status.FAILURE
        else:
            return Status.SUCCESS

# Local Sensing node
class GatherLocalInfo(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._local_sensing)

    def _local_sensing(self, agent, blackboard):
        blackboard['local_tasks_info'] = {task.task_id: task for task in agent.get_tasks_nearby(with_completed_task=False)}
        blackboard['local_agents_info'] = agent.local_message_receive()

        return Status.SUCCESS



# -- Base Condition Nodes (pygame-specific) --------------------
class _IsNearbyPos(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, position, radius):
        distance = agent.position.distance_to(position)
        if distance < radius:
            agent.reset_movement()
            return Status.SUCCESS
        else:
            return Status.FAILURE

class _IsNearby(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, target, radius):
        distance = agent.position.distance_to(target.position)
        if distance < radius:
            return Status.SUCCESS
        else:
            return Status.FAILURE

class _IsTaskCompleted(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, task_id_key = 'task_id'):
        _task_id = blackboard.get(task_id_key)
        if _task_id is None:
            return Status.RUNNING

        task = agent.tasks_info[_task_id]
        if task.completed is True:
            return Status.SUCCESS
        return Status.FAILURE

class _IsArrivedAtTask(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, task_id_key = 'task_id', arrive_threshold = 10.0):
        _task_id = blackboard.get(task_id_key)
        if _task_id is None:
            raise ValueError(f"[{self.name}] Error: No {task_id_key} found in the blackboard!")

        agent_position = agent.position
        task_position = agent.tasks_info[_task_id].position
        distance = (task_position - agent_position).length()

        if distance < agent.tasks_info[_task_id].radius + arrive_threshold:
            return Status.SUCCESS
        return Status.FAILURE


# -- Base Action Nodes (pygame-specific) --------------------
class _MoveTo(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, target):
        if not target:
            raise ValueError(f"[{self.name}] Error: Target is not defined")
        agent.follow(target.position)
        return Status.RUNNING

class _MoveToPos(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, position):
        agent.follow(position)
        return Status.RUNNING

class _MoveToTask(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, task_id_key = 'task_id'):
        _task_id = blackboard.get(task_id_key)
        if _task_id is None:
            raise ValueError(f"[{self.name}] Error: No {task_id_key} found in the blackboard!")

        task_position = agent.tasks_info[_task_id].position
        agent.follow(task_position)

        return Status.RUNNING

class _ExecuteTask(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, task_id_key = 'task_id'):
        _task_id = blackboard.get(task_id_key)
        if _task_id is None:
            raise ValueError(f"[{self.name}] Error: No {_task_id} found in the blackboard!")

        agent.tasks_info[_task_id].reduce_amount(agent.work_rate)
        agent.update_task_amount_done(agent.work_rate)

        return Status.RUNNING

class _ExecuteTaskWhileFollowing(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)

    def _update(self, agent, blackboard, task_id_key = 'task_id'):
        _task_id = blackboard.get(task_id_key)
        if _task_id is None:
            raise ValueError(f"[{self.name}] Error: No {_task_id} found in the blackboard!")

        agent.tasks_info[_task_id].reduce_amount(agent.work_rate)
        agent.update_task_amount_done(agent.work_rate)

        task_position = agent.tasks_info[_task_id].position
        agent.follow(task_position)

        return Status.RUNNING

class _ExploreArea(SyncAction):
    def __init__(self, name, agent):
        super().__init__(name, self._update)
        self.random_move_time = float('inf')
        self.random_waypoint = (0, 0)

    def _update(self, agent, blackboard, agent_max_random_movement_duration = 1000, exploration_area = {'x_min': 0, 'x_max': 1400, 'y_min': 0, 'y_max': 1000}, sampling_time = 1.0):
        if self.random_move_time > agent_max_random_movement_duration:
            self.random_waypoint = self.get_random_position(exploration_area['x_min'], exploration_area['x_max'], exploration_area['y_min'], exploration_area['y_max'])
            self.random_move_time = 0
        self.random_move_time += sampling_time
        agent.follow(self.random_waypoint)
        return Status.RUNNING

    def get_random_position(self, x_min, x_max, y_min, y_max):
        pos = (random.randint(x_min, x_max),
                random.randint(y_min, y_max))
        return pos

    def halt(self):
        self.random_move_time = float('inf')
