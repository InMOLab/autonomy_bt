import math
from core.bt_nodes import BTNodeList, Status, Node, Sequence, Fallback, ReactiveSequence, ReactiveFallback
# BT Node List
CUSTOM_ACTION_NODES = [
    'MoveTo',
    'KillTarget',
    'ExecuteTask',
    'Explore'
]

CUSTOM_CONDITION_NODES = [
    'IsNearby',
    'IsTargetClear',
]

# BT Node List
BTNodeList.ACTION_NODES.extend(CUSTOM_ACTION_NODES)
BTNodeList.CONDITION_NODES.extend(CUSTOM_CONDITION_NODES)


from turtlesim.msg import Pose as TPose
from std_srvs.srv import SetBool
from platforms.ros2.bt_nodes_ros2 import ConditionWithROSTopics, ActionWithROSAction, ActionWithROSService


class IsNearby(ConditionWithROSTopics):
    def __init__(self, name, agent, target_pose_topic, threshold=0.1):
        ns = agent.ros_namespace or ""  # 네임스페이스 없으면 루트
        super().__init__(name, agent, [
            (TPose, f"{ns}/pose", 'self'),
            (TPose, target_pose_topic, 'target'),
        ])
        self.threshold = threshold


    def _predicate(self, agent, blackboard):
        cache = self._cache  # 베이스 설계대로 내부 캐시 사용
        if "self" not in cache or "target" not in cache:
            return False

        a = cache["self"]
        b = cache["target"]
        blackboard["target"] = b  # <- target pose 캐시를 블랙보드에 기록 (다른 노드에서 활용 가능)

        thresh = self.threshold
        dist = math.hypot(a.x - b.x, a.y - b.y)
        if dist <= float(thresh):
            result = True
        else:
            result = False
        return result # dist <= float(thresh)

# bt_nodes.py (발췌)
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose

class MoveTo(ActionWithROSAction):
    def __init__(self, name, agent, action, goal_pose_topic):
        ns = agent.ros_namespace or ""  # 네임스페이스 없으면 루트
        super().__init__(name, agent, 
            (NavigateToPose, f"{ns}/{action}")
        )
        # RUNNING일 때 목표를 흘려 보낼 퍼블리셔
        goal_topic = f"{ns}/{goal_pose_topic}" if ns else goal_pose_topic
        self.goal_pub = self.ros.node.create_publisher(PoseStamped, goal_topic, 10)


    # --- helpers ---
    def _get_xy(self, bb):
        tgt = bb.get('target')
        if isinstance(tgt, TPose):
            return tgt.x, tgt.y
        return None


    def _build_goal(self, agent, bb):
        xy = self._get_xy(bb)
        if xy is None:
            return None
        x, y = xy

        ps = PoseStamped()
        ps.header.frame_id = 'map'
        ps.header.stamp = self.ros.node.get_clock().now().to_msg()
        ps.pose.position.x = x
        ps.pose.position.y = y
        ps.pose.orientation.w = 1.0  # yaw = 0

        goal = NavigateToPose.Goal()
        goal.pose = ps
        return goal

    # ★ RUNNING일 때만 최신 목표를 퍼블리시
    def _on_running(self, agent, bb):
        xy = self._get_xy(bb)
        if xy is None: return
        x, y = xy
        ps = PoseStamped()
        ps.header.frame_id = 'map'
        ps.header.stamp = self.ros.node.get_clock().now().to_msg()
        ps.pose.position.x = x; ps.pose.position.y = y
        ps.pose.orientation.w = 1.0
        self.goal_pub.publish(ps)
        return Status.RUNNING



from turtlesim.srv import Kill  # turtlesim 표준 서비스

class KillTarget(ActionWithROSService):
    """
    turtlesim의 /kill 서비스를 호출해 target 거북이를 제거.
    - 기본 대상 이름: 'turtle_target'
    - blackboard['target_name'] 가 있으면 그 값을 사용
    """
    def __init__(self, name, agent):
        # turtlesim의 kill 서비스 이름은 전역 '/kill'
        super().__init__(name, agent, (Kill, '/kill'))

    def _build_request(self, agent, blackboard):
        req = Kill.Request()
        req.name = str('turtle_target')
        return req



class IsTargetClear(ConditionWithROSTopics):
    """
    Post-Condition:
      - /turtle_target/pose 토픽의 '퍼블리셔'가 0개면 SUCCESS (= target이 사라짐)
      - 퍼블리셔가 있으면 FAILURE
    """
    def __init__(self, name, agent, pose_topic="/turtle_target/pose"):
        # 구독 없이 그래프 조회만 할 것이라 구독 목록 비움
        super().__init__(name, agent, msg_types_topics=[])
        # _cache 비어있으면 RUNNING이므로 더미 플래그로 즉시 판정
        self._cache["ready"] = True
        self.pose_topic = pose_topic

    def _predicate(self, agent, blackboard) -> bool:
        # 퍼블리셔 목록만 확인 (구독자 존재 여부와 무관)
        pubs = self.ros.node.get_publishers_info_by_topic(self.pose_topic)
        target_gone = (len(pubs) == 0)

        if target_gone:
            # 타깃이 사라졌다면 블랙보드의 target도 정리
            blackboard["target"] = None

        return target_gone


