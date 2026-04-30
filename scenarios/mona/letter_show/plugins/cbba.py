"""
CBBA subclass for the letter_show scenario.

Adds a single defensive guard inside ``update_time_stamp``: when a
peer message arrives without a ``message_received_time_stamp`` field
(can happen briefly while the message channel is being swapped between
the regular CBBA channel and the super-task GRAPE channel inside
``AssignSuperTask``), the global merge would crash on the missing
key. We just skip those messages — the next round will pick them up.

No other change vs the global CBBA. If letter_show stops swapping
message channels, this subclass becomes redundant.
"""
import time
from plugins.mrta.cbba.cbba import CBBA as _BaseCBBA
from platforms.pygame.utils_pygame import merge_dicts


class CBBA(_BaseCBBA):
    def update_time_stamp(self):
        # For neighbour agents: stamp them with current time
        current_timestamp = int(time.time())
        for other_agent in self.agent.messages_received:
            self.s[other_agent.get('agent_id')] = current_timestamp

        # For two-hop neighbours: merge their views
        max_timestamp = {}
        for other_agent_message in self.agent.messages_received:
            time_stamp = other_agent_message.get("message_received_time_stamp")
            if time_stamp is None:    # ← letter_show-specific: tolerate missing field
                continue
            max_timestamp = merge_dicts(max_timestamp, time_stamp)

        self.s = merge_dicts(self.s, max_timestamp)
