#!/usr/bin/env python3
"""
Rescue UGV NavigateToPose Action Server
- Tangential obstacle avoidance: steer perpendicular to nearest obstacle
- INF(개활지) 반영 + 거리 클리핑(<=0.5 -> 0.0, >=12 -> inf)
- angle_increment < 0 인 scan 정규화 (좌/우 뒤집힘 방지)
- angular.z 양수 => 왼쪽 회전 (ROS 표준)
"""

import math
import threading
import time
from typing import Optional, Tuple, List

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from geometry_msgs.msg import TwistStamped, PoseStamped
from sensor_msgs.msg import LaserScan
from nav2_msgs.action import NavigateToPose
from builtin_interfaces.msg import Duration as DurationMsg


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi]"""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def quaternion_to_yaw(q) -> float:
    """Extract yaw from quaternion"""
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class UGVNavServer(Node):
    """
    NavigateToPose Action Server for Rescue UGV
    - Logic: Goal tracking + Tangential obstacle avoidance
    - Robust scan preprocessing:
        * normalize reversed scan (angle_increment < 0)
        * <= 0.5m -> 0.0 (blocked)
        * >= 12m -> inf (open)
    """

    def __init__(self, ns: str = ""):
        ns = (ns or "").strip("/")
        if ns and not ns.startswith("/"):
            ns = "/" + ns
        super().__init__("rescue_ugv_navigate_server", namespace=ns)

        # Declare parameters
        self._declare_parameters()
        self._load_parameters()

        # State
        self._current_pose: Optional[PoseStamped] = None
        self._raw_scan: Optional[LaserScan] = None
        self._active_goal_handle = None
        self._goal_lock = threading.Lock()

        # Processed scan cache (normalized + clipped)
        self._scan_ranges: Optional[List[float]] = None
        self._scan_angle_min: float = 0.0
        self._scan_angle_inc: float = 0.0

        # Callback group for async
        self._cb_group = ReentrantCallbackGroup()

        # Publishers & Subscribers
        self._cmd_pub = self.create_publisher(TwistStamped, "cmd_vel", 10)

        self._pose_sub = self.create_subscription(
            PoseStamped, "pose_world", self._pose_callback, 10,
            callback_group=self._cb_group
        )
        self._scan_sub = self.create_subscription(
            LaserScan, "scan", self._scan_callback, 10,
            callback_group=self._cb_group
        )

        # Action Server
        self._action_server = ActionServer(
            self,
            NavigateToPose,
            "navigate_to_pose",
            execute_callback=self._execute_callback,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            handle_accepted_callback=self._handle_accepted_callback,
            callback_group=self._cb_group
        )

        self.get_logger().info(
            f"UGVNavServer started. "
            f"Namespace: {self.get_namespace()}, Action: navigate_to_pose"
        )

    def _declare_parameters(self):
        # 제어 주기 (Hz)
        self.declare_parameter("control_rate", 30.0)  # 20.0

        # 최대 속도 제한
        self.declare_parameter("max_linear_vel", 1.0)  # 1.0
        self.declare_parameter("max_angular_vel", 0.5)  # 1.0

        # 목표 추종 게인
        self.declare_parameter("k_linear", 0.8)  # 0.5
        self.declare_parameter("k_angular", 0.8)  # 1.0

        # 부드러운 이동 설정
        self.declare_parameter("min_linear_scale", 0.15)
        self.declare_parameter("heading_tolerance", 0.05)

        # Rotation shim 설정 (목적지 방향과 현재 방향이 많이 다를 때 회전 우선)
        self.declare_parameter("rotation_shim_threshold", 0.2)  # 약 11.5도
        
        # 목표 도착 판정
        self.declare_parameter("goal_tolerance", 0.3)

        # 장애물 회피 설정 (Tangential)
        self.declare_parameter("obstacle_distance_slow", 1.0)   # 감속 시작 거리
        self.declare_parameter("obstacle_distance_stop", 1.0)   # 긴급 정지 거리
        self.declare_parameter("front_sector_angle", 45.0)      # 전방 감시 각도 (deg)
        self.declare_parameter("avoidance_gain", 0.5)           # 회피 각속도 (rad/s), tangent 방향으로 회전할 강도

        # Scan preprocessing
        self.declare_parameter("clip_close_dist", 0.5)          # <= 이하면 0.0 처리
        self.declare_parameter("clip_open_dist", 12.0)          # >= 이면 inf 처리

    def _load_parameters(self):
        self.control_rate = float(self.get_parameter("control_rate").value)
        self.max_linear_vel = float(self.get_parameter("max_linear_vel").value)
        self.max_angular_vel = float(self.get_parameter("max_angular_vel").value)
        self.k_linear = float(self.get_parameter("k_linear").value)
        self.k_angular = float(self.get_parameter("k_angular").value)
        self.min_linear_scale = float(self.get_parameter("min_linear_scale").value)
        self.heading_tolerance = float(self.get_parameter("heading_tolerance").value)
        self.goal_tolerance = float(self.get_parameter("goal_tolerance").value)

        self.obstacle_distance_slow = float(self.get_parameter("obstacle_distance_slow").value)
        self.obstacle_distance_stop = float(self.get_parameter("obstacle_distance_stop").value)
        self.front_sector_angle = math.radians(float(self.get_parameter("front_sector_angle").value))
        self.avoidance_gain = float(self.get_parameter("avoidance_gain").value)

        self.clip_close_dist = float(self.get_parameter("clip_close_dist").value)
        self.clip_open_dist = float(self.get_parameter("clip_open_dist").value)

        self.rotation_shim_threshold = float(self.get_parameter("rotation_shim_threshold").value)        


    def _pose_callback(self, msg: PoseStamped):
        self._current_pose = msg

    # ------------------------------------------------------------
    # Scan preprocessing (핵심)
    # ------------------------------------------------------------
    def _scan_callback(self, msg: LaserScan):
        """
        1) angle_increment < 0 이면 scan을 뒤집어 정규화 (angle_min < angle_max, inc > 0)
        2) 거리 클리핑:
           - <= clip_close_dist -> 0.0 (막힘)
           - >= clip_open_dist  -> inf (개활지)
        3) INF는 gap 후보로 포함되도록 유지
        """
        self._raw_scan = msg

        ranges = list(msg.ranges)
        angle_min = float(msg.angle_min)
        angle_inc = float(msg.angle_increment)

        # (A) Normalize reversed scan (so angles increase with index)
        if angle_inc < 0.0:
            ranges.reverse()
            angle_min = float(msg.angle_max)
            angle_inc = -angle_inc

        # (B) Clip ranges as requested
        proc = []
        for r in ranges:
            if not math.isfinite(r):
                # keep INF as INF (open)
                proc.append(float('inf'))
                continue

            rr = float(r)
            if rr <= self.clip_close_dist:
                proc.append(0.0)              # blocked
            elif rr >= self.clip_open_dist:
                proc.append(float('inf'))     # open
            else:
                proc.append(rr)

        self._scan_ranges = proc
        self._scan_angle_min = angle_min
        self._scan_angle_inc = angle_inc

    def _goal_callback(self, goal_request) -> GoalResponse:
        self.get_logger().info(
            f"Received goal: x={goal_request.pose.pose.position.x:.2f}, "
            f"y={goal_request.pose.pose.position.y:.2f}"
        )
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle) -> CancelResponse:
        self.get_logger().info("Goal cancellation requested")
        return CancelResponse.ACCEPT

    def _handle_accepted_callback(self, goal_handle):
        """새 goal 수락 시 기존 goal을 즉시 abort하고 새 goal 실행 (preemption)"""
        with self._goal_lock:
            if self._active_goal_handle is not None and self._active_goal_handle.is_active:
                self.get_logger().info("Preempting current goal with new goal")
                self._active_goal_handle.abort()
            self._active_goal_handle = goal_handle
        goal_handle.execute()

    def _publish_cmd(self, linear: float, angular: float):
        # angular.z > 0 => left turn (as user confirmed)
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "world"
        msg.twist.linear.x = float(linear)
        msg.twist.angular.z = float(angular)
        self._cmd_pub.publish(msg)

    def _stop(self):
        self._publish_cmd(0.0, 0.0)

    # ================= Scan Utilities =================

    def _scan_ready(self) -> bool:
        return self._scan_ranges is not None and self._raw_scan is not None and len(self._scan_ranges) > 0

    def _range_eff(self, r: float) -> float:
        """INF -> clip_open_dist, 그 외 그대로 반환."""
        if math.isfinite(r):
            return r
        return self.clip_open_dist

    def _angle_at(self, idx: float) -> float:
        """idx -> angle (rad), 0 rad = forward"""
        return self._scan_angle_min + idx * self._scan_angle_inc

    def _get_front_min_distance(self) -> float:
        """전방 섹터의 최소 거리 반환 (INF는 clip_open_dist로 간주)"""
        if not self._scan_ready():
            return float('inf')

        min_dist = float('inf')
        for i, r in enumerate(self._scan_ranges):
            if abs(self._angle_at(i)) > self.front_sector_angle:
                continue
            r_eff = self._range_eff(r)
            if r_eff < min_dist:
                min_dist = r_eff
        return min_dist

    def _get_nearest_obstacle_angle(self) -> Optional[float]:
        """전방 섹터에서 가장 가까운 실제 장애물의 각도(robot frame) 반환.
        INF(개활지)는 장애물이 아니므로 제외."""
        if not self._scan_ready():
            return None

        min_r = float('inf')
        min_angle = None
        for i, r in enumerate(self._scan_ranges):
            if r == 0.0 or not math.isfinite(r):
                continue
            angle = self._angle_at(i)
            if abs(angle) > self.front_sector_angle:
                continue
            if r < min_r:
                min_r = r
                min_angle = angle
        return min_angle

    def _compute_obstacle_avoidance(self) -> Tuple[float, float, float]:
        """
        Tangential 장애물 회피.
        가장 가까운 장애물에 수직(접선) 방향으로 조향.
        반환: (front_min, avoidance_angular, danger_level)
        """
        front_min = self._get_front_min_distance()

        if front_min <= self.obstacle_distance_stop:
            danger_level = 1.0
        elif front_min >= self.obstacle_distance_slow:
            danger_level = 0.0
        else:
            danger_level = (self.obstacle_distance_slow - front_min) / (
                self.obstacle_distance_slow - self.obstacle_distance_stop
            )

        if danger_level <= 0.0:
            return front_min, 0.0, 0.0

        nearest_angle = self._get_nearest_obstacle_angle()
        if nearest_angle is None:
            return front_min, 0.0, danger_level

        # 장애물 반대 방향으로 회전
        # nearest_angle > 0 (왼쪽 장애물) → 오른쪽(음수) 회전
        # nearest_angle < 0 (오른쪽 장애물) → 왼쪽(양수) 회전
        avoidance_angular = -math.copysign(self.avoidance_gain, nearest_angle)
        return front_min, avoidance_angular, danger_level

    def _get_full_scan_min_distance(self) -> float:
        """전체 스캔(전방 180°)에서 가장 가까운 실제 장애물까지의 거리.
        INF(개활지)는 장애물이 아니므로 제외."""
        if not self._scan_ready():
            return float('inf')
        min_dist = float('inf')
        for r in self._scan_ranges:
            if r > 0.0 and math.isfinite(r) and r < min_dist:
                min_dist = r
        return min_dist

    def _compute_velocity(self, goal_x: float, goal_y: float) -> Tuple[float, float]:
        if self._current_pose is None:
            return 0.0, 0.0

        px = self._current_pose.pose.position.x
        py = self._current_pose.pose.position.y
        yaw = quaternion_to_yaw(self._current_pose.pose.orientation)

        dx = goal_x - px
        dy = goal_y - py
        distance = math.hypot(dx, dy)

        target_yaw = math.atan2(dy, dx)
        heading_error = normalize_angle(target_yaw - yaw)  # +면 왼쪽

        # Goal tracking용 속도 (RotationShim)
        is_rotating_only = abs(heading_error) > self.rotation_shim_threshold
        goal_angular = clamp(self.k_angular * heading_error, -self.max_angular_vel, self.max_angular_vel)
        if is_rotating_only:
            goal_linear = 0.0
        else:
            heading_factor = max(math.cos(heading_error), 0.0)
            speed_scale = self.min_linear_scale + (1.0 - self.min_linear_scale) * heading_factor
            goal_linear = self.k_linear * distance * speed_scale

        # 장애물 체크
        _, avoidance_angular, danger_level = self._compute_obstacle_avoidance()
        full_scan_min = self._get_full_scan_min_distance()

        # ── 3단계 상태 결정 ──────────────────────────────────────────────────
        if danger_level > 0.0:
            # [1] 전방 ±45° 장애물 감지: 접선 방향으로 제자리 회전 (최우선)
            linear_vel = 0.0
            angular_vel = avoidance_angular
        elif full_scan_min < self.obstacle_distance_slow:
            # [2] 전방에서 벗어났지만 근처에 여전히 장애물 존재 (coast zone):
            #     현재 방향 그대로 직진 → goal 재정렬 없음 (oscillation 방지)
            linear_vel = self.max_linear_vel
            angular_vel = 0.0
        else:
            # [3] 장애물 없음: 일반 RotationShim 내비게이션
            if is_rotating_only:
                linear_vel = 0.0
                angular_vel = goal_angular
            else:
                linear_vel = goal_linear
                angular_vel = goal_angular
        # ────────────────────────────────────────────────────────────────────

        linear_vel = clamp(linear_vel, 0.0, self.max_linear_vel)
        angular_vel = clamp(angular_vel, -self.max_angular_vel, self.max_angular_vel)
        return linear_vel, angular_vel


    async def _execute_callback(self, goal_handle):
        self.get_logger().info("Executing navigation goal...")

        goal_pose = goal_handle.request.pose
        goal_x = goal_pose.pose.position.x
        goal_y = goal_pose.pose.position.y

        start_time = self.get_clock().now()
        sleep_duration = 1.0 / self.control_rate

        result = NavigateToPose.Result()

        try:
            while rclpy.ok():
                if not goal_handle.is_active:
                    # Preempted by a newer goal
                    self._stop()
                    return result

                if goal_handle.is_cancel_requested:
                    self._stop()
                    goal_handle.canceled()
                    return result

                if self._current_pose is None:
                    self.get_logger().warn("Waiting for pose...", throttle_duration_sec=2.0)
                    self._stop()
                    time.sleep(sleep_duration)
                    continue

                if not self._scan_ready():
                    self.get_logger().warn("Waiting for scan...", throttle_duration_sec=2.0)
                    self._stop()
                    time.sleep(sleep_duration)
                    continue

                px = self._current_pose.pose.position.x
                py = self._current_pose.pose.position.y
                distance = math.hypot(goal_x - px, goal_y - py)

                if distance <= self.goal_tolerance:
                    self._stop()
                    goal_handle.succeed()
                    self.get_logger().info(f"Goal reached! Dist: {distance:.3f}m")
                    return result

                linear_vel, angular_vel = self._compute_velocity(goal_x, goal_y)
                self._publish_cmd(linear_vel, angular_vel)

                feedback = NavigateToPose.Feedback()
                feedback.current_pose = self._current_pose
                feedback.distance_remaining = float(distance)

                elapsed = self.get_clock().now() - start_time
                elapsed_sec = elapsed.nanoseconds / 1e9
                feedback.navigation_time = DurationMsg(
                    sec=int(elapsed_sec),
                    nanosec=int((elapsed_sec % 1) * 1e9)
                )
                goal_handle.publish_feedback(feedback)

                time.sleep(sleep_duration)

        except Exception as e:
            self.get_logger().error(f"Navigation error: {e}")
            self._stop()
            if goal_handle.is_active:
                goal_handle.abort()
            return result

        self._stop()
        if goal_handle.is_active:
            goal_handle.abort()
        return result

    def destroy_node(self):
        self._stop()
        self._action_server.destroy()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)

    # 네임스페이스 설정
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ns", type=str, default="/Fire_UGV_2", help="ROS namespace, e.g. /Fire_UGV_1")
    args = parser.parse_args()

    node = UGVNavServer(ns=args.ns)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()