# Changelog

Notable changes to autonomy_bt. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Changes before this file was started are in the git history.

## [Unreleased]

### Added

- ROS 2 BT runner: alive signal. Every runner publishes `{agent_id, namespace, type}` every 0.2 s on `bt_runner.alive_topic` (default `/agent/alive`).
- ROS 2 BT viewer: a node shows `node.label` if it is set, else its name. `"\n"` in a label starts a new line.

### Changed

- ROS 2 BT runner: the ROS node is named `/<robot>_<bt_runner.node_name>` (default `bt_runner`, e.g. `/robot_1_bt_runner`) instead of `space_bt_bridge`.
  It stays in the root namespace, so relative topic names are unchanged. The viewer window shows the node name.
- ROS 2 BT viewer: each parent is centred over its children, and the tree shrinks to fit the window.
  Labels shrink their font until they fit the node.
