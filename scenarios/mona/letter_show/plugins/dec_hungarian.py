"""
DistributedHungarian subclass for the letter_show scenario.

Letter_show runs the auction in two phases:
  - Phase 1 (GRAPE) decides which super-task (= cluster of pixels for
    one letter) each agent belongs to.
  - Phase 2 (this Hungarian, or CBBA) decides which pixel inside
    its super-task each agent goes to.

Phase-2 consensus messages must therefore not bleed across super-task
boundaries — agent X working on super-task 0 should ignore messages
from agent Y who is working on super-task 1, otherwise the candidate
graph and the cost matrix mix tasks from different letters.

The base ``DistributedHungarian`` has no concept of super-tasks, so
this subclass:
  1. Pre-filters ``self.agent.messages_received`` by
     ``assigned_super_task_id`` at the top of ``decide()``.
  2. Drops cross-super-task agents from the candidate set inside
     ``_build_latest_graph``.
  3. Adds defensive guards (``n in candidates`` during BFS,
     ``position is not None`` when rebuilding R) — the message channel
     is briefly swapped between CBBA and GRAPE channels inside
     ``AssignSuperTask``, and incomplete entries can transit through.
  4. Tags outbound broadcasts with ``assigned_super_task_id`` so peers
     can apply the same filter on the receive side.

When ``agent.assigned_super_task_id`` is ``None`` (i.e. running in a
non-letter scenario), the filters degrade to no-ops and the subclass
behaves identically to the base class.
"""
from collections import deque
from plugins.mrta.hungarian.dec_hungarian import DistributedHungarian as _BaseDH


def _scope_match_lenient(my_st_id, their_st_id):
    """For internal candidates: accept peers whose ST is None (their
    broadcast may pre-date Phase-1 convergence). Used inside
    ``_build_latest_graph`` only."""
    return my_st_id is None or their_st_id is None or their_st_id == my_st_id


class DistributedHungarian(_BaseDH):
    # ------------------------------------------------------------------
    # _detect_cluster_changes(): also filter agents_info by super-task
    # scope. Without this filter, cross-ST agents in peers' agents_info
    # bleed into ``perceived_ids`` while ``current_r_ids`` (built from
    # ``self.R`` which **is** scoped) only has same-ST agents. The two
    # sets never match → cluster_change is reported every tick →
    # ``self.assigned_task = None`` every tick → Hungarian's matching
    # is recomputed from scratch each tick and flaps on near-symmetric
    # task layouts (e.g. the "S" letter in letter_show, where tasks 3,
    # 4, 5 lie roughly on a line and agents 3 and 5 oscillate between
    # T3 and T4).
    # ------------------------------------------------------------------
    def _detect_cluster_changes(self, messages):
        current_r_ids = {
            getattr(a, 'agent_id', a.get('agent_id') if isinstance(a, dict) else None)
            for a in self.R
        }
        perceived_ids = {self.agent.agent_id}
        my_st_id = getattr(self.agent, 'assigned_super_task_id', None)

        for a in messages:
            perceived_ids.add(a.get('agent_id'))

        for msg in messages:
            if not msg:
                continue
            for agent in msg.get('agents_info', []):
                aid = getattr(agent, 'agent_id', None)
                if aid is None and isinstance(agent, dict):
                    aid = agent.get('agent_id')
                st_id = getattr(agent, 'assigned_super_task_id', None)
                if st_id is None and isinstance(agent, dict):
                    st_id = agent.get('assigned_super_task_id')

                if aid is not None and _scope_match_lenient(my_st_id, st_id):
                    perceived_ids.add(aid)

        if not current_r_ids.issubset(perceived_ids):
            self.gamma = 0
            return True
        if not perceived_ids.issubset(current_r_ids):
            self.gamma = 0
            return True
        return False

    # ------------------------------------------------------------------
    # decide(): pre-filter messages by super-task scope.
    # NOTE: This filter is **strict** — once we have an ST we reject
    # peers whose broadcast doesn't yet declare an ST. Being too
    # permissive here makes ``_detect_cluster_changes`` flap (peers
    # with None ST drift in/out of the cluster across ticks), which
    # resets ``gamma`` and prevents Hungarian from ever converging.
    # ------------------------------------------------------------------
    def decide(self, blackboard):
        previous_assigned_task_id = self.assigned_task.task_id if self.assigned_task is not None else None

        _local_tasks_info = blackboard.get('local_tasks_info', {})

        my_st_id = getattr(self.agent, 'assigned_super_task_id', None)
        messages = [
            m for m in self.agent.messages_received if m and
            (my_st_id is None or m.get('assigned_super_task_id') == my_st_id)
        ]

        # Handle completed task
        self.assigned_task = _local_tasks_info.get(previous_assigned_task_id)
        if self.assigned_task is None and previous_assigned_task_id is not None:
            self._on_task_completed(previous_assigned_task_id)

        # Continuous monitoring
        if self._detect_cluster_changes(messages):
            self.assigned_task = None
            self._update_visualization()

        # Always build/sync graph
        self._build_latest_graph(messages, _local_tasks_info)

        # Run Hungarian
        assigned_task = self._run_centralized_hungarian()
        self.assigned_task = assigned_task
        self._update_visualization()

        # Broadcast outbound state
        self._update_message()

        return self.assigned_task.task_id if self.assigned_task else None

    # ------------------------------------------------------------------
    # _build_latest_graph(): apply super-task filter to peer candidates,
    # plus a couple of defensive guards.
    # ------------------------------------------------------------------
    def _build_latest_graph(self, messages, local_tasks):
        valid_msgs = [m for m in messages if m and 'agent_id' in m]
        my_st_id = getattr(self.agent, 'assigned_super_task_id', None)

        # 1. Collect candidates
        candidates = {
            self.agent.agent_id: {
                'agent_id': self.agent.agent_id,
                'position': self.agent.position,
            }
        }
        for msg in messages:
            candidates[msg['agent_id']] = {
                'agent_id': msg['agent_id'],
                'position': msg.get('position', None),
            }
        for msg in valid_msgs:
            for agent in msg.get('agents_info', []):
                aid = getattr(agent, 'agent_id', None)
                if aid is None and isinstance(agent, dict):
                    aid = agent.get('agent_id')

                # Filter cross-super-task agents out of the candidate set.
                st_id = getattr(agent, 'assigned_super_task_id', None)
                if st_id is None and isinstance(agent, dict):
                    st_id = agent.get('assigned_super_task_id')

                # First-encountered wins: don't overwrite the agent's own
                # fresh self-entry (or a direct peer broadcast) with the
                # stale view that some other peer's agents_info carries.
                if (aid is not None
                        and aid not in candidates
                        and _scope_match_lenient(my_st_id, st_id)):
                    candidates[aid] = agent

        # 2. Link-state graph reconstruction
        _agent_id = self.agent.agent_id
        my_neighbors = {msg['agent_id'] for msg in messages if 'agent_id' in msg}
        new_global_adj = {_agent_id: my_neighbors}

        for msg in valid_msgs:
            sender_id = msg.get('agent_id')
            if sender_id is None:
                continue
            received_graph = msg.get('adjacency_graph', {})
            for node, neighbors in received_graph.items():
                if node not in new_global_adj:
                    new_global_adj[node] = set(neighbors)
                else:
                    new_global_adj[node].update(neighbors)

        self.global_adjacency = new_global_adj

        # BFS for connected component (defensive: skip nodes not in candidates)
        visited = {_agent_id}
        queue = deque([_agent_id])
        while queue:
            curr = queue.popleft()
            for n in self.global_adjacency.get(curr, set()):
                if n not in visited and n in candidates:
                    visited.add(n)
                    if n in self.global_adjacency:
                        queue.append(n)

        # Update R — drop entries with no position (channel-swap artefact)
        self.R = [
            candidates[aid] for aid in sorted(visited)
            if aid in candidates and candidates[aid].get('position') is not None
        ]
        new_R_ids = visited

        # Update P
        observed_task_ids = {t.task_id for t in local_tasks.values()}
        current_p_map = {
            getattr(t, 'task_id', t.get('task_id') if isinstance(t, dict) else None): t
            for t in self.P
        }
        for t in local_tasks.values():
            current_p_map[t.task_id] = t

        for msg in valid_msgs:
            if msg['agent_id'] not in new_R_ids:
                continue
            for tid in msg.get('completed_tasks', set()):
                if tid not in self.completed_tasks:
                    self.completed_tasks.add(tid)
            for t in msg.get('tasks_info', []):
                tid = getattr(t, 'task_id', t.get('task_id') if isinstance(t, dict) else None)
                if tid is not None and tid not in self.completed_tasks:
                    observed_task_ids.add(tid)
                    current_p_map[tid] = t

        self.P = [t for tid, t in current_p_map.items()
                  if tid in observed_task_ids and tid not in self.completed_tasks]
        self.P.sort(key=lambda t: getattr(t, 'task_id', t.get('task_id') if isinstance(t, dict) else None))

        # Lead-robot selection via γ
        neighbor_gammas = {_agent_id: self.gamma}
        for msg in valid_msgs:
            sender = msg.get('agent_id')
            if sender in visited:
                neighbor_gammas[sender] = msg.get('gamma', 0)
        lead_id = max(neighbor_gammas, key=neighbor_gammas.get)
        lead_gamma = neighbor_gammas[lead_id]
        if lead_id != _agent_id and lead_gamma > self.gamma:
            self.gamma = lead_gamma

    # ------------------------------------------------------------------
    # _update_message(): include our assigned_super_task_id so peers can
    # apply the same scope filter on receive.
    # ------------------------------------------------------------------
    def _update_message(self):
        graph_to_send = self.global_adjacency.copy()
        _agent_id = self.agent.agent_id
        graph_to_send[_agent_id] = {
            msg.get('agent_id') for msg in self.agent.messages_received
            if msg and 'agent_id' in msg
        }

        self.agent.message_to_share = {
            'agent_id': _agent_id,
            'adjacency_graph': graph_to_send,
            'position': self.agent.position,
            'agents_info': self.R,
            'tasks_info': self.P,
            'completed_tasks': self.completed_tasks,
            'assigned_task_id': self.assigned_task.task_id if self.assigned_task else None,
            'assigned_super_task_id': getattr(self.agent, 'assigned_super_task_id', None),
            'gamma': self.gamma,
        }
