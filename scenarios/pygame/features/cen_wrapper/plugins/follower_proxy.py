"""Leader-side per-follower snapshot for CentralisationWrapper.

Exposes the same attribute surface as `platforms/pygame/base_agent.BaseAgent`
and `platforms/ros2/agent.Agent` so that decision_makers (CBBA / GRAPE /
Hungarian / Greedy) can read the same `self.agent.<attr>` patterns whether
they're invoked in pure-dec mode (on the follower's own agent) or wrapper
mode (on a leader-side proxy).

The wrapper holds N proxies (one per leader-connected follower) and refreshes
each proxy's `position` and `messages_received` per tick from data received
via broadcast (in pygame sim: copied from the live target agent; in ROS2:
populated from received topic data). The decision_maker attached to each
proxy (via `proxy.decision_maker = decision_making_class(proxy)`, lazily
created by AssignTask on first invocation) carries the per-follower
persistent state — bundle / partition / etc. — across BT ticks.

In a real distributed deployment, this proxy is the abstraction that lets
the leader run the algorithm "as if it were the follower" without ever
touching the follower's memory. In our pygame simulation, the proxy
attributes are copied from the live follower for convenience; the
algorithmic correctness does not depend on this — the same proxy interface
maps directly to received-topic data in ROS2.
"""
import pygame


class FollowerProxy:
    """Per-follower context held on the leader.

    Algorithm-relevant attributes mirror those of a real Agent. Persistent
    state (decision_maker, planned_tasks) is attached lazily.
    """

    def __init__(self, agent_id, position=None):
        self.agent_id = agent_id
        self.position = position if position is not None else pygame.Vector2(0, 0)
        self.messages_received = []
        self.message_to_share = {}
        self.assigned_task_id = None
        self.planned_tasks = []
        # `decision_maker` is attached lazily by AssignTask on first invocation.

    def set_planned_tasks(self, task_list):
        """Mirror the BaseAgent method; stored on the proxy (not propagated to live follower)."""
        self.planned_tasks = task_list
