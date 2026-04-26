#!/usr/bin/env python3
"""
World Supervisor
- Fire / Target / Base 등 world object를 관리
- 동적으로 object spawn/remove 지원
- pose publish
"""

from controller import Supervisor
import json
import math
import os
import random
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Point
from std_srvs.srv import Empty
from std_msgs.msg import UInt8, String  # ✅ UInt8 추가 (Target status용)
from std_msgs.msg import UInt16MultiArray  # Target을 Summary 형태로 전달하기 위해 추가
from std_msgs.msg import Float64MultiArray  # Custom fire spawn용
from builtin_interfaces.msg import Duration
from visualization_msgs.msg import Marker, MarkerArray
from ament_index_python.packages import get_package_share_directory


# -----------------------------
# Object Category 정의
# -----------------------------
class ObjectCategory:
    FIRE = "Fire"
    BASE = "Base"


# PROTO 템플릿 (spawn 시 사용)
PROTO_TEMPLATES = {
  ObjectCategory.FIRE: """
DEF {def_name} Fire {{
  translation {x} {y} {z}
  radius {radius}
}}
"""
}


# -----------------------------
# util
# -----------------------------
def axis_angle_to_quaternion(axis_x, axis_y, axis_z, angle):
    """axis-angle -> quaternion 변환"""
    norm = math.sqrt(axis_x * axis_x + axis_y * axis_y + axis_z * axis_z)
    if norm < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    axis_x, axis_y, axis_z = axis_x / norm, axis_y / norm, axis_z / norm
    sin_half = math.sin(angle * 0.5)
    return (axis_x * sin_half, axis_y * sin_half, axis_z * sin_half, math.cos(angle * 0.5))


# -----------------------------
# 동적 Object 관리 클래스
# -----------------------------
class DynamicObjectManager:
    def __init__(self, supervisor: Supervisor, category: str, def_prefix: str):
        """카테고리별(Webots DEF prefix 기반) 객체 spawn/remove를 관리"""
        self.supervisor = supervisor
        self.category = category
        self.def_prefix = def_prefix
        self.active_objects = {}
        self.next_index = 1

    # 월드에 이미 존재하는 객체를 찾아서 목록에 등록 (초기화 시 실행)
    def scan_existing_objects(self):
        """월드에 이미 존재하는 객체(DEF prefix 매칭)를 스캔"""
        root = self.supervisor.getRoot()
        children_field = root.getField("children")
        children_count = children_field.getCount()

        max_found_index = 0
        for i in range(children_count):
            child_node = children_field.getMFNode(i)
            if child_node is None:
                continue

            def_name = child_node.getDef()
            if def_name and def_name.startswith(self.def_prefix):
                try:
                    index_str = def_name[len(self.def_prefix):]
                    index = int(index_str)
                    self.active_objects[def_name] = child_node
                    max_found_index = max(max_found_index, index)
                except ValueError:
                    pass
        
        self.next_index = max_found_index + 1   # 다음 인덱스 설정 -> 겹치지 않도록 (Fire_1,2,3이 있는 상태에서 2가 없어져도 spawn시 Fire_4로 생성되도록)
        return list(self.active_objects.keys())

    # 새로운 객체를 월드에 생성 (PROTO 템플릿 사용)
    def spawn_object(self, position_x: float, position_y: float, position_z: float, **kwargs) -> str:
        """PROTO 템플릿을 사용해 객체를 동적으로 생성"""
        def_name = f"{self.def_prefix}{self.next_index}"
        self.next_index += 1

        template = PROTO_TEMPLATES.get(self.category)
        if template is None:
            return None

        try:
            proto_string = template.format(
                def_name=def_name,
                x=position_x,
                y=position_y,
                z=position_z,
                **kwargs
            )
        except KeyError as e:
            print(f"Error formatting template: Missing key {e}")
            return None

        root = self.supervisor.getRoot()
        children_field = root.getField("children")
        children_field.importMFNodeFromString(-1, proto_string)

        new_node = self.supervisor.getFromDef(def_name)
        if new_node:
            self.active_objects[def_name] = new_node
            return def_name
        return None

    def remove_object(self, def_name: str) -> bool:
        """객체를 월드에서 제거"""
        if def_name not in self.active_objects:
            return False
        webots_node = self.active_objects[def_name]
        if webots_node:
            webots_node.remove()
        del self.active_objects[def_name]
        return True

    def get_active_object_names(self):
        """현재 active 상태인 DEF 리스트 반환"""
        return list(self.active_objects.keys())

    def get_webots_node(self, def_name: str):
        """DEF에 해당하는 Webots node 반환"""
        return self.active_objects.get(def_name)


# -----------------------------
# ROS Node
# -----------------------------
class WorldSupervisor(Node):
    def __init__(self, supervisor: Supervisor):
        """WorldSupervisor 초기화 및 publisher/service 구성"""
        super().__init__("world_supervisor")

        self.supervisor = supervisor
        self.timestep = int(self.supervisor.getBasicTimeStep())

        # 월드 파일 경로를 기준으로 icons 폴더 경로 저장
        # Webots ROS2에서는 월드 파일이 /tmp에 복사되므로 패키지 경로 사용
        try:
            pkg_share = get_package_share_directory("webots_ros2_husky")
            self.icons_dir = os.path.join(pkg_share, "worlds", "icons")
        except Exception:
            # fallback: 기존 방식
            world_path = self.supervisor.getWorldPath()
            self.icons_dir = os.path.join(os.path.dirname(world_path), "icons")

        self.frame_id = "world" #"webots_world"
        self.publish_rate = 30.0  # 20.0

        self.fire_manager = DynamicObjectManager(supervisor, ObjectCategory.FIRE, "Fire_")

        self.base_node = None
        self.base_def_name = "Base"

        self._scan_initial_objects()

        self.fire_list_publisher = self.create_publisher(String, "/world/fire/list", 1)
        self.debug = os.environ.get('DEBUG', 'false').lower() == 'true'
        if self.debug:
            self.fire_markers_publisher = self.create_publisher(MarkerArray, "/world/visualisation/fires", 1)
            self.get_logger().info("Debug mode ON: publishing /world/visualisation/fires")
        self.base_publisher = None

        self._create_initial_publishers()

        self.fire_total_spawned = len(self.fire_manager.get_active_object_names())
        self.fire_summary_publishers = self.create_publisher(UInt16MultiArray, "/world/fire/summary", 1)  # Fire Summary

        # ===== Fire 자동 스폰 및 확산 설정 =====
        self.fire_auto_spawn_enabled = True      # 자동 스폰 활성화 여부
        self.fire_auto_spawn_interval = 20.0     # 자동 스폰 간격 (초)
        self.fire_spawn_range = 20.0             # 스폰 가능 범위 (+/-)
        self.fire_max_count = 100                 # 최대 Fire 개수 제한

        self.fire_spread_enabled = True          # 확산 활성화 여부
        self.fire_spread_interval = 5.0         # 확산 시도 간격 (초)
        self.fire_spread_probability = 0.8       # 확산 확률 (0.0 ~ 1.0)
        self.fire_spread_distance_min = 2.0      # 확산 최소 거리
        self.fire_spread_distance_max = 5.0      # 확산 최대 거리

        self.fire_radius_growth_enabled = True   # 반경 성장 활성화 여부
        self.fire_radius_growth_interval = 10.0   # 반경 성장 적용 간격 (초)
        self.fire_radius_growth_rate = 0.0      # 초당 반경 증가량 (m/s) # TODO: 0 이상 설정하면 Comm topology가 불안정한 모습임. 이유확인 필요 2026.02.25 (Inmo Jang)
        self.fire_radius_max = 5.0               # 반경 최대값 (m)

        self._create_spawn_services()

        # Fire 자동 스폰 타이머
        if self.fire_auto_spawn_enabled:
            self.fire_auto_spawn_timer = self.create_timer(self.fire_auto_spawn_interval, self._auto_spawn_fire)
            self.get_logger().info(f"Fire auto spawn enabled: every {self.fire_auto_spawn_interval}s")

        # Fire 확산 타이머
        if self.fire_spread_enabled:
            self.fire_spread_timer = self.create_timer(self.fire_spread_interval, self._spread_fire_from_existing)
            self.get_logger().info(f"Fire spread enabled: every {self.fire_spread_interval}s, prob={self.fire_spread_probability}")

        # Fire 반경 성장 타이머
        if self.fire_radius_growth_enabled:
            self.fire_radius_growth_timer = self.create_timer(self.fire_radius_growth_interval, self._grow_fire_radius)
            self.get_logger().info(f"Fire radius growth enabled: every {self.fire_radius_growth_interval}s, rate={self.fire_radius_growth_rate}m/s, max={self.fire_radius_max}m")

        self.last_publish_time = self.get_clock().now()
        self.get_logger().info("WorldSupervisor ready")

    # 프로그램 시작 시 월드에 미리 배치된 객체들을 인식
    def _scan_initial_objects(self):
        """월드 초기 객체(Fire/Base) 스캔"""
        self.fire_manager.scan_existing_objects()
        self.base_node = self.supervisor.getFromDef(self.base_def_name)

    # 인식된 초기 객체들에 대해 Publisher 및 상태 초기화 수행
    def _create_initial_publishers(self):
        """초기 존재하는 객체들에 대한 publisher 생성"""
        if self.base_node:
            self.base_publisher = self.create_publisher(PoseStamped, "/world/base/pose", 1)

    def _create_spawn_services(self):   # 직접 터미널에서 호출하는 방식으로 구현
        """spawn 서비스 및 topic 구독 생성"""
        self.create_service(Empty, "/world/fire/spawn", self._handle_spawn_fire)
        # Fire 지정 생성 / x, y, radius
        self.create_subscription(Float64MultiArray, "/world/fire/spawn_custom", self._handle_spawn_fire_custom, 1)
        # Fire suppress / fire_id를 String으로 받음
        self.create_subscription(String, "/world/fire/suppress", self._handle_suppress_fire, 1)
        # Fire radius 감소 / fire_id를 String으로 받음
        self.create_subscription(String, "/world/fire/reduce", self._handle_reduce_fire, 1)

    def _handle_spawn_fire(self, request, response):
        """Fire를 랜덤 위치/크기로 생성"""
        range_limit = 12.5  # +/-12.5
        rand_x = round(random.uniform(-range_limit, range_limit), 2)
        rand_y = round(random.uniform(-range_limit, range_limit), 2)
        default_z = 0.0

        rand_radius = round(random.uniform(0.5, 3.0), 2)

        def_name = self.fire_manager.spawn_object(rand_x, rand_y, default_z, radius=rand_radius)

        if def_name:
            self.get_logger().info(f"Spawned {def_name} at ({rand_x}, {rand_y}) with radius {rand_radius}")
            self.fire_total_spawned += 1
        else:
            self.get_logger().error("Failed to spawn Fire")

        return response

    def _handle_spawn_fire_custom(self, msg):
        """Fire를 지정된 위치/크기로 생성 / msg.data = [x, y, radius]"""
        if len(msg.data) < 3:
            self.get_logger().error("spawn_custom requires [x, y, radius]")
            return

        x, y, radius = msg.data[0], msg.data[1], msg.data[2]
        def_name = self.fire_manager.spawn_object(x, y, 0.0, radius=radius)

        if def_name:
            self.get_logger().info(f"Spawned {def_name} at ({x}, {y}) with radius {radius}")
            self.fire_total_spawned += 1
        else:
            self.get_logger().error("Failed to spawn Fire")

    def _handle_spawn_target(self, request, response):
        """Target을 랜덤 위치에 생성"""
        range_limit = 10.0
        rand_x = round(random.uniform(-range_limit, range_limit), 2)
        rand_y = round(random.uniform(-range_limit, range_limit), 2)
        default_z = 0.03
        
        # Spawn new target (Always Unchecked=0, Red)
        icon_path = os.path.join(self.icons_dir, "target_unchecked.png") # Red
        def_name = self.target_manager.spawn_object(rand_x, rand_y, default_z, texture_url=icon_path)

        if def_name:
            self._create_target_publisher(def_name)

            # target의 status/pub/service 생성
            self.target_status[def_name] = 0
            self._create_target_status_publisher(def_name)
            self._create_check_service_for_target(def_name)

            # complete 서비스 생성
            self._create_complete_service_for_target(def_name)

            self.get_logger().info(f"Spawned {def_name}")
        return response

    def _handle_spawn_target_custom(self, msg):
        """Target을 지정된 위치에 생성 / msg.data = [x, y]"""
        if len(msg.data) < 2:
            self.get_logger().error("spawn_custom requires [x, y]")
            return

        x, y = msg.data[0], msg.data[1]
        default_z = 0.03

        # Spawn new target (Always Unchecked=0, Red)
        icon_path = os.path.join(self.icons_dir, "target_unchecked.png") # Red
        def_name = self.target_manager.spawn_object(x, y, default_z, texture_url=icon_path)

        if def_name:
            self._create_target_publisher(def_name)

            # target의 status/pub/service 생성
            self.target_status[def_name] = 0
            self._create_target_status_publisher(def_name)
            self._create_check_service_for_target(def_name)

            # complete 서비스 생성
            self._create_complete_service_for_target(def_name)

            self.get_logger().info(f"Spawned {def_name} at ({x}, {y})")

    # ===== Fire 자동 스폰 =====
    def _auto_spawn_fire(self):
        """랜덤 위치에 Fire 자동 생성"""
        current_count = len(self.fire_manager.get_active_object_names())
        if current_count >= self.fire_max_count:  # 최대 개수 제한
            self.get_logger().info(f"Fire count ({current_count}) reached max ({self.fire_max_count}), skipping auto spawn")
            return

        rand_x = round(random.uniform(-self.fire_spawn_range, self.fire_spawn_range), 2)
        rand_y = round(random.uniform(-self.fire_spawn_range, self.fire_spawn_range), 2)
        rand_radius = round(random.uniform(0.5, 2.5), 2)

        def_name = self.fire_manager.spawn_object(rand_x, rand_y, 0.0, radius=rand_radius)
        if def_name:
            self.fire_total_spawned += 1
            self.get_logger().info(f"[Auto] Spawned {def_name} at ({rand_x}, {rand_y}) radius={rand_radius}")

    # ===== Fire 확산 =====
    def _spread_fire_from_existing(self):
        """기존 Fire 주변으로 확산"""
        current_count = len(self.fire_manager.get_active_object_names())
        if current_count >= self.fire_max_count:
            self.get_logger().debug(f"Fire count ({current_count}) reached max, skipping spread")
            return

        active_fires = list(self.fire_manager.active_objects.keys())
        if not active_fires:
            return

        # 랜덤하게 하나의 Fire 선택하여 확산 시도
        source_fire = random.choice(active_fires)
        if random.random() > self.fire_spread_probability:
            self.get_logger().debug(f"Spread skipped (prob check failed) for {source_fire}")
            return

        node = self.fire_manager.get_webots_node(source_fire)
        if not node:
            return

        pos = node.getField("translation").getSFVec3f()
        
        # 확산 방향 및 거리 계산
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(self.fire_spread_distance_min, self.fire_spread_distance_max)
        new_x = round(pos[0] + distance * math.cos(angle), 2)
        new_y = round(pos[1] + distance * math.sin(angle), 2)

        # 맵 범위 체크
        if abs(new_x) > self.fire_spawn_range or abs(new_y) > self.fire_spawn_range:
            self.get_logger().debug(f"Spread position ({new_x}, {new_y}) out of range, skipping")
            return

        # 기존 Fire와 너무 가까운지 체크 (겹침 방지)
        for other_name in active_fires:
            other_node = self.fire_manager.get_webots_node(other_name)
            if other_node:
                other_pos = other_node.getField("translation").getSFVec3f()
                dist = math.sqrt((new_x - other_pos[0])**2 + (new_y - other_pos[1])**2)
                if dist < 2.0:  # 최소 2m 간격
                    self.get_logger().debug(f"Too close to {other_name}, skipping spread")
                    return

        # 새 Fire 생성 (소스 Fire보다 약간 작게)
        source_radius = self._read_fire_radius(node)
        new_radius = round(random.uniform(0.5, max(0.5, source_radius * 0.8)), 2)

        def_name = self.fire_manager.spawn_object(new_x, new_y, 0.0, radius=new_radius)
        if def_name:
            self.fire_total_spawned += 1
            self.get_logger().info(f"[Spread] {source_fire} -> {def_name} at ({new_x}, {new_y}) radius={new_radius}")

    # ===== Fire 반경 성장 =====
    def _grow_fire_radius(self):
        """모든 활성 Fire의 radius를 growth_rate만큼 증가 (fire_radius_max 상한)"""
        growth = self.fire_radius_growth_rate * self.fire_radius_growth_interval
        for def_name in list(self.fire_manager.active_objects.keys()):
            node = self.fire_manager.get_webots_node(def_name)
            if not node:
                continue
            current_radius = self._read_fire_radius(node)
            if current_radius >= self.fire_radius_max:
                continue
            new_radius = round(min(current_radius + growth, self.fire_radius_max), 3)
            node.getField("radius").setSFFloat(new_radius)

    def _handle_suppress_fire(self, msg):
        """suppress 토픽을 구독하여 해당 fire_id를 제거"""
        fire_id = msg.data.strip()
        
        if not isinstance(fire_id, str) or not fire_id.startswith("Fire_"):
            self.get_logger().warn(f"Invalid fire_id: {fire_id}")
            return
        
        success = self.fire_manager.remove_object(fire_id)
        if success:
            self.get_logger().info(f"{fire_id} suppressed")
        else:
            self.get_logger().warn(f"Failed to suppress {fire_id}: not found")

    def _handle_reduce_fire(self, msg):
        """reduce 토픽을 구독하여 해당 fire_id의 radius를 0.1 감소. radius <= 0이면 제거"""
        fire_id = msg.data.strip()

        if not isinstance(fire_id, str) or not fire_id.startswith("Fire_"):
            self.get_logger().warn(f"Invalid fire_id: {fire_id}")
            return

        node = self.fire_manager.get_webots_node(fire_id)
        if not node:
            self.get_logger().warn(f"Failed to reduce {fire_id}: not found")
            return

        current_radius = self._read_fire_radius(node)
        new_radius = round(current_radius - 0.1, 2)

        if new_radius <= 0.0:
            self.fire_manager.remove_object(fire_id)
            self.get_logger().info(f"{fire_id} extinguished (radius -> 0)")
        else:
            node.getField("radius").setSFFloat(new_radius)
            self.get_logger().info(f"{fire_id} reduced: {current_radius:.2f} -> {new_radius:.2f}")

    def _read_fire_radius(self, webots_node):
        """Webots Fire PROTO node에서 radius 필드를 읽음"""
        try:
            radius_field = webots_node.getField("radius")
            if radius_field:
                return radius_field.getSFFloat()
        except Exception:
            pass
        return 2.0

    def _read_pose(self, webots_node):
        """Webots node의 translation/rotation을 PoseStamped로 변환"""
        trans = webots_node.getField("translation").getSFVec3f()
        rot = webots_node.getField("rotation").getSFRotation()
        quat = axis_angle_to_quaternion(rot[0], rot[1], rot[2], rot[3])
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.pose.position.x = trans[0]
        msg.pose.position.y = trans[1]
        msg.pose.position.z = trans[2]
        msg.pose.orientation.x = quat[0]
        msg.pose.orientation.y = quat[1]
        msg.pose.orientation.z = quat[2]
        msg.pose.orientation.w = quat[3]
        return msg

    def _publish_fire_summary(self):
        """모든 Fire의 상태를 UInt16MultiArray로 요약하여 퍼블리시"""
        active_fires = len(self.fire_manager.get_active_object_names())
        total_fires = int(self.fire_total_spawned)
        suppressed = max(0, total_fires - active_fires)

        msg = UInt16MultiArray()
        msg.data = [total_fires, int(active_fires), int(suppressed)]
        self.fire_summary_publishers.publish(msg)

    def publish_if_needed(self):
        """publish_rate에 맞춰 pose/radius/status를 주기적으로 publish"""
        now = self.get_clock().now()
        if (now - self.last_publish_time).nanoseconds < 1e9 / self.publish_rate:
            return
        self.last_publish_time = now

        self._publish_fire_list()
        if self.debug:
            self._publish_fire_markers()

        if self.base_node and self.base_publisher:
            self.base_publisher.publish(self._read_pose(self.base_node))

        self._publish_fire_summary()

    def _publish_fire_list(self):
        """모든 활성 Fire 정보를 JSON 리스트로 /world/fire/list에 퍼블리시"""
        fire_list = []
        for def_name in self.fire_manager.get_active_object_names():
            node = self.fire_manager.get_webots_node(def_name)
            if not node:
                continue
            trans = node.getField("translation").getSFVec3f()
            radius = self._read_fire_radius(node)
            fire_list.append({
                "task_id": def_name,
                "x": float(trans[0]),
                "y": float(trans[1]),
                "z": float(trans[2]),
                "radius": float(radius),
            })
        msg = String()
        msg.data = json.dumps(fire_list)
        self.fire_list_publisher.publish(msg)

    def _publish_fire_markers(self):
        """활성 Fire를 SPHERE MarkerArray로 /world/visualisation/fires에 publish"""
        marker_array = MarkerArray()
        stamp = self.get_clock().now().to_msg()

        for idx, def_name in enumerate(self.fire_manager.get_active_object_names()):
            node = self.fire_manager.get_webots_node(def_name)
            if not node:
                continue
            trans = node.getField("translation").getSFVec3f()
            radius = self._read_fire_radius(node)

            marker = Marker()
            marker.header.stamp = stamp
            marker.header.frame_id = "world"
            marker.ns = "fires"
            marker.id = idx
            marker.type = Marker.SPHERE
            marker.action = Marker.ADD
            marker.pose.position.x = float(trans[0])
            marker.pose.position.y = float(trans[1])
            marker.pose.position.z = float(trans[2])
            marker.pose.orientation.w = 1.0
            diameter = float(radius) * 2.0
            marker.scale.x = diameter
            marker.scale.y = diameter
            marker.scale.z = diameter
            marker.color.r = 1.0
            marker.color.g = 0.0
            marker.color.b = 0.0
            marker.color.a = 0.5  # 반투명
            marker.lifetime = Duration(sec=2, nanosec=0)  # 2초간 미갱신 시 자동 소멸
            marker_array.markers.append(marker)

        self.fire_markers_publisher.publish(marker_array)


def main():
    """Webots step 루프에서 ROS spin + publish를 수행"""
    supervisor = Supervisor()
    rclpy.init()
    node = WorldSupervisor(supervisor)
    try:
        while supervisor.step(node.timestep) != -1:
            rclpy.spin_once(node, timeout_sec=0.0)
            node.publish_if_needed()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
