# First-Claimed Greedy

This plugin implements the **First-Claimed Greedy** algorithm, a decentralised task allocation approach where each agent selects a task based on local information and resolves conflicts with neighbours using timestamps.

## How It Works

Every tick, each agent:

1. **Checks task availability**: Looks up its currently assigned task in `local_tasks_info`. If no tasks are visible nearby, it broadcasts a null claim and returns.
2. **Conflict resolution (assigned task)**: If the agent already holds a claim, it checks whether any neighbour claimed the same task *earlier*. If so, the agent yields — clears the claim and resets its stored timestamp for that task.
3. **Re-evaluates candidates every tick**: Filters all visible tasks by conflict resolution. Any task already claimed by a neighbour with an earlier timestamp is excluded. When an agent yields a task during filtering, its stored timestamp for that task is also cleared.
4. **Selects the best candidate**: From the remaining conflict-free candidates, picks a task according to the configured `mode`.
5. **Records claim time**: On first claim of a task, records `time.time()` as its `time_stamp`. Subsequent ticks keep the original timestamp, ensuring temporal priority is preserved.
6. **Broadcasts claim**: Shares `agent_id`, `assigned_task_id`, and `time_stamp` with neighbours via `message_to_share`.

### Conflict Resolution Rule

| Condition | Action |
|-----------|--------|
| Neighbour’s `time_stamp` < my `time_stamp` | Yield: clear claim and reset `my_claim_time[task_id]` |
| Neighbour’s `time_stamp` is `None` | Yield conservatively |
| My `time_stamp` ≤ neighbour’s `time_stamp` | Keep claim |
| No neighbour claims the same task | Keep claim |

Yielding resets the stored timestamp so the agent can re-compete if the winning neighbour later releases the task.



## Parameters Example

```yaml
decision_making:
  plugin: plugins.mrta.greedy.greedy.FirstClaimGreedy
  FirstClaimGreedy:
    mode: MinDist  # Options: Random; MinDist; MaxUtil
    weight_factor_cost: 10000.0 # Only used for `MaxUtil` mode
```

### Parameter Descriptions

- **`mode`**: 
  This parameter allows you to adjust the logic by which an agent selects a task from local tasks. The options are:
  - **`Random`**: Selects a task randomly.
  - **`MinDist`**: Chooses the task that is closest to the agent.
  - **`MaxUtil`**: Selects the task with the highest utility. The utility is currently calculated as:
    ```
    utility = task.amount - weight_factor_cost * (self.agent.position - task.position).length()
    ```

- **`weight_factor_cost`**: 
  Used in the `MaxUtil` mode to determine the magnitude of `W_FACTOR_COST`. This parameter affects the cost component in the utility calculation.