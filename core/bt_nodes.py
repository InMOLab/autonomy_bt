from enum import Enum
# BT Node List
class BTNodeList:
    CONTROL_NODES = [
        'Sequence',
        'Fallback',
        'ReactiveSequence',
        'ReactiveFallback',
        'Parallel'
    ]

    ACTION_NODES = [
    ]

    CONDITION_NODES = [
        'AlwaysFailure',
        'AlwaysSuccess',
    ]

    DECORATOR_NODES = [
    ]

# Status enumeration for behavior tree nodes
class Status(Enum):
    SUCCESS = 1
    FAILURE = 2
    RUNNING = 3

# Base class for all behavior tree nodes
class Node:
    def __init__(self, name):
        self.name = name
        self.type = None
        self.status = None

    async def run(self, agent, blackboard):
        raise NotImplementedError

    def halt(self):
        pass

    def reset(self):
        self.status = None
        if hasattr(self, "children"):
            for child in self.children:
                child.reset()


# Sequence node: Runs child nodes in sequence until one fails
class Sequence(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children
        self.current_child_index = 0

    async def run(self, agent, blackboard):
        while self.current_child_index < len(self.children):
            status = await self.children[self.current_child_index].run(agent, blackboard)
            self.status = status

            if status == Status.RUNNING:
                return Status.RUNNING
            elif status == Status.FAILURE:
                self.halt_children()
                self.current_child_index = 0
                return Status.FAILURE
            elif status == Status.SUCCESS:
                self.current_child_index += 1

        self.current_child_index = 0
        self.halt_children()
        return Status.SUCCESS

    def halt_children(self):
        for child in self.children:
            child.halt()

    def halt(self):
        self.current_child_index = 0

class ReactiveSequence(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children

    async def run(self, agent, blackboard):
        for child in self.children:
            status = await child.run(agent, blackboard)
            self.status = status
            if status == Status.FAILURE:
                self.halt_children()
                return Status.FAILURE
            if status == Status.RUNNING:
                return Status.RUNNING
        self.halt_children()
        return Status.SUCCESS

    def halt_children(self):
        for child in self.children:
            child.halt()

# Fallback node: Runs child nodes in sequence until one succeeds
class Fallback(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children
        self.current_child_index = 0

    async def run(self, agent, blackboard):
        while self.current_child_index < len(self.children):
            status = await self.children[self.current_child_index].run(agent, blackboard)
            self.status = status

            if status == Status.RUNNING:
                return Status.RUNNING
            elif status == Status.SUCCESS:
                self.halt_children()
                self.current_child_index = 0
                return Status.SUCCESS
            elif status == Status.FAILURE:
                self.current_child_index += 1

        self.current_child_index = 0
        self.halt_children()
        return Status.FAILURE

    def halt_children(self):
        for child in self.children:
            child.halt()

    def halt(self):
        self.current_child_index = 0

class ReactiveFallback(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children

    async def run(self, agent, blackboard):
        for child in self.children:
            status = await child.run(agent, blackboard)
            self.status = status
            if status == Status.SUCCESS:
                self.halt_children()
                return Status.SUCCESS
            if status == Status.RUNNING:
                return Status.RUNNING

        self.halt_children()
        return Status.FAILURE

    def halt_children(self):
        for child in self.children:
            child.halt()

# Parallel node: Ticks all children sequentially in the same tick and returns by success_count / failure_count
class Parallel(Node):
    def __init__(self, name, children, success_count=None, failure_count=None):
        """
        success_count: number of SUCCESS children required for overall SUCCESS
                       (default: len(children))
        failure_count: number of FAILURE children causing overall FAILURE
                       (default: None → failures alone don't decide FAILURE)
        """
        super().__init__(name)
        self.children = children
        self.success_count = len(children) if success_count is None else success_count
        self.failure_count = failure_count  # None means ignore failures in final decision

    async def run(self, agent, blackboard):
        successes = 0
        failures = 0
        any_running = False

        # Tick all children sequentially within the same tick
        for child in self.children:
            status = await child.run(agent, blackboard)

            if status == Status.SUCCESS:
                successes += 1
            elif status == Status.FAILURE:
                failures += 1
            elif status == Status.RUNNING:
                any_running = True

        # Final decision after evaluating all children
        if successes >= self.success_count:
            self.halt_children()
            self.status = Status.SUCCESS
            return self.status

        if self.failure_count is not None and failures >= self.failure_count:
            self.halt_children()
            self.status = Status.FAILURE
            return self.status

        if any_running:
            self.status = Status.RUNNING
            return self.status

        # All finished, thresholds not satisfied → FAILURE
        self.halt_children()
        self.status = Status.FAILURE
        return self.status

    def halt_children(self):
        for child in self.children:
            child.halt()

    def halt(self):
        self.halt_children()


# Synchronous action node
class SyncAction(Node):
    def __init__(self, name, action):
        super().__init__(name)
        self.action = action
        self.type = "Action"

    async def run(self, agent, blackboard):
        result = self.action(agent, blackboard)
        blackboard[self.name] = result
        self.status = result
        return result

class SyncCondition(Node):
    def __init__(self, name, condition):
        super().__init__(name)
        self.condition = condition
        self.is_expanded = False
        self.type = "Condition"

    async def run(self, agent, blackboard):
        result = self.condition(agent, blackboard)
        blackboard[self.name] = {'status': result, 'is_expanded': self.is_expanded}
        self.status = result
        return result

    def set_expanded(self):
        self.is_expanded = True



# ---- Helper: AlwaysFailure & AlwaysSuccess -----------------------
class AlwaysFailure(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._check)

    def _check(self, agent, blackboard):
        return Status.FAILURE

class AlwaysSuccess(SyncCondition):
    def __init__(self, name, agent):
        super().__init__(name, self._check)

    def _check(self, agent, blackboard):
        return Status.SUCCESS
