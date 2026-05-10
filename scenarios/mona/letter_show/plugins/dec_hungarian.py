"""
DistributedHungarian subclass for the letter_show scenario.

The only difference from the base class is super-task scoping:
  - _perceive_world() filters incoming messages to same-ST peers only,
    so the cost matrix never mixes agents/tasks across letter boundaries.
  - _update_message() tags outbound broadcasts with assigned_super_task_id
    so peers can apply the same filter on receive.
"""
from plugins.mrta.hungarian.dec_hungarian import DistributedHungarian as _BaseDH


class DistributedHungarian(_BaseDH):

    def _perceive_world(self, messages, local_tasks):
        my_st_id = getattr(self.agent, 'assigned_super_task_id', None)
        scoped = [
            m for m in messages if m and
            (my_st_id is None or m.get('assigned_super_task_id') == my_st_id)
        ]
        super()._perceive_world(scoped, local_tasks)

    def _update_message(self, local_tasks):
        super()._update_message(local_tasks)
        self.agent.message_to_share['assigned_super_task_id'] = (
            getattr(self.agent, 'assigned_super_task_id', None)
        )
