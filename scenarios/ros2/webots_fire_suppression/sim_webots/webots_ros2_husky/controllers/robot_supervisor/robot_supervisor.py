#!/usr/bin/env python3
"""
Robot Supervisor
- Webots world에서 여러 로봇의 translation/rotation을 읽어서
  /{agent_id}/pose_world (PoseStamped) 로 publish

- 로봇간 local communication 중계:
  /{agent_id}/local_comm/outbox (JSON) 를 수집하고
  수신 로봇의 comm_radius 기준으로 이웃만 필터링하여
  /{agent_id}/local_comm/inbox (JSON array) 로 publish

- (debug 모드) communication topology 시각화:
  /world/visualisation/comm_topology (MarkerArray) 로 publish
  robot_launch.py 에서 debug:=true 로 실행 시 활성화

권장:
- 로봇 고유 ID는 DEF 사용 (robot_launch.py도 DEF 기반)
"""

# Webots 월드에서 pose_world를 publish할 로봇 DEF prefix 목록
# robot_launch.py의 ROBOTS_NAME_LIST와 동일하게 유지할 것
ROBOT_DEF_PREFIXES = ["Fire_UGV"]
OUTBOX_TIMEOUT = 0.5  # seconds: 이 시간 이상 outbox 미수신 시 stale로 판정
COMM_RADIUS    = 30.0 # metres: local communication emulation 수신 반경

from controller import Supervisor
import json
import math
import os
import time
import rclpy
from rclpy.node import Node
import tf2_ros
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Point, PoseStamped, TransformStamped
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray


def axis_angle_to_quaternion(axis_x, axis_y, axis_z, angle):
    """axis-angle -> quaternion (x,y,z,w)"""
    norm = math.sqrt(axis_x * axis_x + axis_y * axis_y + axis_z * axis_z)
    if norm < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    axis_x, axis_y, axis_z = axis_x / norm, axis_y / norm, axis_z / norm
    sin_half = math.sin(angle * 0.5)
    return (axis_x * sin_half, axis_y * sin_half, axis_z * sin_half, math.cos(angle * 0.5))


class TrackedRobot:
    def __init__(self, ros_node: Node, wb_node, agent_id: str, frame_id_world: str):
        self.node = ros_node
        self.wb_node = wb_node
        self.agent_id = agent_id
        self.frame_id_world = frame_id_world

        self.translation_field = wb_node.getField("translation")
        self.rotation_field = wb_node.getField("rotation")

        # pose publisher: Webots 월드에서 읽은 pose를 ROS topic으로 publish
        self.pub_pose_world = ros_node.create_publisher(
            PoseStamped, f"/{self.agent_id}/pose_world", 10
        )

        # local comm: 로봇이 broadcast하는 outbox 수신
        self.sub_outbox = ros_node.create_subscription(
            String,
            f"/{self.agent_id}/local_comm/outbox",
            self._on_outbox,
            10
        )

        # local comm: 이웃 정보를 로봇에게 전달하는 inbox 송신
        self.pub_inbox = ros_node.create_publisher(
            String, f"/{self.agent_id}/local_comm/inbox", 10
        )

        self.last_outbox = None       # 최신 outbox dict (None = 아직 수신 전)
        self.last_outbox_time = None  # 마지막 수신 시각 (stale 감지용)

    def _on_outbox(self, msg: String):
        try:
            self.last_outbox = json.loads(msg.data)
            self.last_outbox_time = time.time()
        except json.JSONDecodeError as e:
            self.node.get_logger().warn(f"[{self.agent_id}] outbox JSON parse error: {e}")

    def get_position_2d(self):
        """Webots translation field에서 (x, y) 반환"""
        t = self.translation_field.getSFVec3f()
        return (t[0], t[1])

    def get_position_3d(self):
        """Webots translation field에서 (x, y, z) 반환"""
        t = self.translation_field.getSFVec3f()
        return (t[0], t[1], t[2])

    def publish_world_pose(self):
        t = self.translation_field.getSFVec3f()
        r = self.rotation_field.getSFRotation()
        q = axis_angle_to_quaternion(r[0], r[1], r[2], r[3])

        msg = PoseStamped()
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id_world
        msg.pose.position.x = float(t[0])
        msg.pose.position.y = float(t[1])
        msg.pose.position.z = float(t[2])
        msg.pose.orientation.x = float(q[0])
        msg.pose.orientation.y = float(q[1])
        msg.pose.orientation.z = float(q[2])
        msg.pose.orientation.w = float(q[3])

        self.pub_pose_world.publish(msg)

    def publish_inbox(self, neighbors: list):
        msg = String()
        msg.data = json.dumps(neighbors)
        self.pub_inbox.publish(msg)


class RobotSupervisor:
    def __init__(self):
        self.supervisor = Supervisor()
        self.timestep = int(self.supervisor.getBasicTimeStep())

        rclpy.init(args=None)
        self.node = rclpy.create_node("robot_supervisor")
        self.log = self.node.get_logger()

        self.frame_id_world = "world"

        # Publish static TF so RViz can use "world" as Fixed Frame
        self._tf_static = tf2_ros.StaticTransformBroadcaster(self.node)
        t = TransformStamped()
        t.header.stamp = self.node.get_clock().now().to_msg()
        t.header.frame_id = "world"
        t.child_frame_id = "world_fixed"
        t.transform.rotation.w = 1.0
        self._tf_static.sendTransform(t)

        # Debug mode: enable visualisation topics (set via DEBUG env var)
        self.debug = os.environ.get('DEBUG', 'false').lower() == 'true'
        if self.debug:
            self._pub_comm_topology = self.node.create_publisher(
                MarkerArray, '/world/visualisation/comm_topology', 10
            )
            self._pub_task_assignment = self.node.create_publisher(
                MarkerArray, '/world/visualisation/task_assignment', 10
            )
            self._pub_task_plan = self.node.create_publisher(
                MarkerArray, '/world/visualisation/task_plan', 10
            )
            self._pub_robot_markers = self.node.create_publisher(
                MarkerArray, '/world/visualisation/robots', 10
            )
            self.log.info("Debug mode ON: publishing /world/visualisation/comm_topology, /world/visualisation/task_assignment, /world/visualisation/task_plan, /world/visualisation/robots")

        self.def_prefixes = ROBOT_DEF_PREFIXES

        self.tracked = []
        self._discover_robots_by_def()

        self.log.info("===== robot_supervisor started =====")
        self.log.info(f"Tracked robots (DEF): {[r.agent_id for r in self.tracked]}")

    def _discover_robots_by_def(self):
        root = self.supervisor.getRoot()
        children_field = root.getField("children")

        found = []
        for i in range(children_field.getCount()):
            wb_node = children_field.getMFNode(i)
            if wb_node is None:
                continue

            def_name = wb_node.getDef()
            if not def_name:
                continue

            if any(def_name == p or def_name.startswith(p + "_") or def_name.startswith(p)
                   for p in self.def_prefixes):
                found.append((def_name, wb_node))

        found.sort(key=lambda x: x[0])

        for def_name, wb_node in found:
            try:
                self.tracked.append(
                    TrackedRobot(self.node, wb_node, def_name, self.frame_id_world)
                )
            except Exception as e:
                self.log.warn(f"Failed to track robot DEF='{def_name}': {e}")

    def _is_stale(self, robot) -> bool:
        if robot.last_outbox_time is None:
            return True
        return (time.time() - robot.last_outbox_time) > OUTBOX_TIMEOUT

    def _relay_communications(self):
        """COMM_RADIUS 기준으로 이웃 outbox를 inbox에 전달.
        receiver는 outbox 송신 여부와 무관하게 inbox를 수신한다.
        sender는 stale 감지 시 이웃에서 제외된다.
        """
        # 시각화용: 통신 엣지 집합 (frozenset으로 중복 제거) 및 위치 캐시
        comm_edges = set()
        positions = {}

        for receiver in self.tracked:
            rx, ry = receiver.get_position_2d()

            if self.debug:
                positions[receiver.agent_id] = receiver.get_position_3d()

            neighbors = []
            for sender in self.tracked:
                if sender.agent_id == receiver.agent_id:
                    continue
                if self._is_stale(sender):
                    continue  # stale sender는 이웃에서 제외

                sx, sy = sender.get_position_2d()
                dist = math.sqrt((rx - sx) ** 2 + (ry - sy) ** 2)
                if dist <= COMM_RADIUS:
                    neighbors.append(sender.last_outbox)
                    if self.debug:
                        positions[sender.agent_id] = sender.get_position_3d()
                        comm_edges.add(frozenset([receiver.agent_id, sender.agent_id]))

            receiver.publish_inbox(neighbors)

        if self.debug:
            self._publish_comm_topology(comm_edges, positions)
            self._publish_task_assignment()
            self._publish_task_plan()
            self._publish_robot_markers()

    def _publish_comm_topology(self, edges: set, positions: dict):
        """통신 엣지를 LINE_LIST Marker로 publish"""
        marker = Marker()
        marker.header.stamp = self.node.get_clock().now().to_msg()
        marker.header.frame_id = self.frame_id_world
        marker.ns = "comm_topology"
        marker.id = 0
        marker.type = Marker.LINE_LIST
        marker.action = Marker.ADD
        marker.scale.x = 0.1          # line width (metres)
        marker.color.r = 1.0
        marker.color.g = 1.0
        marker.color.b = 0.0
        marker.color.a = 0.8
        marker.pose.orientation.w = 1.0
        marker.lifetime = Duration(sec=1, nanosec=0)  # auto-expire if updates stop

        for edge in edges:
            ids = list(edge)
            if len(ids) != 2:
                continue
            a_id, b_id = ids[0], ids[1]
            if a_id not in positions or b_id not in positions:
                continue

            ax, ay, az = positions[a_id]
            bx, by, bz = positions[b_id]

            p1 = Point(x=float(ax), y=float(ay), z=float(az))
            p2 = Point(x=float(bx), y=float(by), z=float(bz))
            marker.points.append(p1)
            marker.points.append(p2)

        msg = MarkerArray()
        msg.markers.append(marker)
        self._pub_comm_topology.publish(msg)

    def _publish_task_assignment(self):
        """각 로봇의 outbox에서 assigned_task_id를 읽어 로봇↔Fire 간 LINE으로 publish"""
        marker = Marker()
        marker.header.stamp = self.node.get_clock().now().to_msg()
        marker.header.frame_id = self.frame_id_world
        marker.ns = "task_assignment"
        marker.id = 0
        marker.type = Marker.LINE_LIST
        marker.action = Marker.ADD
        marker.scale.x = 0.12
        marker.color.r = 0.0
        marker.color.g = 1.0
        marker.color.b = 1.0
        marker.color.a = 0.9
        marker.pose.orientation.w = 1.0
        marker.lifetime = Duration(sec=1, nanosec=0)

        for robot in self.tracked:
            if self._is_stale(robot):
                continue
            outbox = robot.last_outbox
            if outbox is None:
                continue
            assigned_task_id = outbox.get('assigned_task_id')
            if not assigned_task_id:
                continue

            fire_node = self.supervisor.getFromDef(assigned_task_id)
            if fire_node is None:
                continue
            fire_t = fire_node.getField("translation").getSFVec3f()
            robot_t = robot.get_position_3d()

            marker.points.append(Point(x=float(robot_t[0]), y=float(robot_t[1]), z=float(robot_t[2])))
            marker.points.append(Point(x=float(fire_t[0]), y=float(fire_t[1]), z=float(fire_t[2])))

        msg = MarkerArray()
        msg.markers.append(marker)
        self._pub_task_assignment.publish(msg)

    def _publish_task_plan(self):
        """각 로봇의 outbox에서 planned_tasks_id를 읽어 로봇 위치부터 순차적으로 LINE_STRIP으로 publish"""
        msg = MarkerArray()
        stamp = self.node.get_clock().now().to_msg()

        for idx, robot in enumerate(self.tracked):
            if self._is_stale(robot):
                continue
            outbox = robot.last_outbox
            if outbox is None:
                continue
            planned_tasks_id = outbox.get('planned_tasks_id')
            if not planned_tasks_id:
                continue

            marker = Marker()
            marker.header.stamp = stamp
            marker.header.frame_id = self.frame_id_world
            marker.ns = "task_plan"
            marker.id = idx
            marker.type = Marker.LINE_STRIP
            marker.action = Marker.ADD
            marker.scale.x = 0.08
            marker.color.r = 1.0
            marker.color.g = 0.5
            marker.color.b = 0.0
            marker.color.a = 0.8
            marker.pose.orientation.w = 1.0
            marker.lifetime = Duration(sec=1, nanosec=0)

            robot_t = robot.get_position_3d()
            marker.points.append(Point(x=float(robot_t[0]), y=float(robot_t[1]), z=float(robot_t[2])))

            for task_id in planned_tasks_id:
                fire_node = self.supervisor.getFromDef(task_id)
                if fire_node is None:
                    break
                fire_t = fire_node.getField("translation").getSFVec3f()
                marker.points.append(Point(x=float(fire_t[0]), y=float(fire_t[1]), z=float(fire_t[2])))

            if len(marker.points) > 1:
                msg.markers.append(marker)

        if msg.markers:
            self._pub_task_plan.publish(msg)

    def _publish_robot_markers(self):
        """각 로봇의 위치·방향을 ARROW Marker로 publish"""
        msg = MarkerArray()
        stamp = self.node.get_clock().now().to_msg()

        for idx, robot in enumerate(self.tracked):
            t = robot.translation_field.getSFVec3f()
            r = robot.rotation_field.getSFRotation()
            q = axis_angle_to_quaternion(r[0], r[1], r[2], r[3])

            marker = Marker()
            marker.header.stamp = stamp
            marker.header.frame_id = self.frame_id_world
            marker.ns = "robots"
            marker.id = idx
            marker.type = Marker.ARROW
            marker.action = Marker.ADD
            marker.pose.position.x = float(t[0])
            marker.pose.position.y = float(t[1])
            marker.pose.position.z = float(t[2])
            marker.pose.orientation.x = float(q[0])
            marker.pose.orientation.y = float(q[1])
            marker.pose.orientation.z = float(q[2])
            marker.pose.orientation.w = float(q[3])
            marker.scale.x = 1.0   # shaft length (metres)
            marker.scale.y = 0.2   # shaft diameter
            marker.scale.z = 0.3   # arrowhead diameter
            marker.color.r = 0.5
            marker.color.g = 1.0
            marker.color.b = 0.2
            marker.color.a = 0.9
            marker.lifetime = Duration(sec=1, nanosec=0)
            msg.markers.append(marker)

        self._pub_robot_markers.publish(msg)

    def run(self):
        while self.supervisor.step(self.timestep) != -1 and rclpy.ok():
            for robot in self.tracked:
                robot.publish_world_pose()

            rclpy.spin_once(self.node, timeout_sec=0.0)
            self._relay_communications()

        self.node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    RobotSupervisor().run()
