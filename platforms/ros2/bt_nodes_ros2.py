from core.bt_nodes import Node, Status
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus


class ConditionWithROSTopics(Node):
    def __init__(self, name, agent, msg_types_topics):
        super().__init__(name)
        self.ros = agent.ros_bridge
        self._cache = {}
        for msg_type, topic, key in msg_types_topics:
            self.ros.node.create_subscription(
                msg_type, topic,
                lambda m, k=key: self._cache.__setitem__(k, m),
                1
            )
        # For PA-BT
        self.is_expanded = False
        self.type = "Condition"

    async def run(self, agent, blackboard):
        if not self._cache:
            self.status = Status.RUNNING
        elif self._predicate(agent, blackboard):
            self.status = Status.SUCCESS
        else:
            self.status = Status.FAILURE

        # For PA-BT
        blackboard[self.name] = {'status': self.status, 'is_expanded': self.is_expanded}

        return self.status

    def _predicate(self, agent, blackboard) -> bool: # 내 조건이 만족했는가?"를 판단하는 코드 구현
        raise NotImplementedError

    def set_expanded(self): # For PA-BT
        self.is_expanded = True


class ActionWithROSAction(Node):
    """
    심플 ROS Action 클라이언트 베이스.
      - action_spec: (ActionType, action_name)
      - _fingerprint(): 목표 바뀜 판정 (None이면 실행 불가)
      - _build_goal(): Goal 생성
      - _interpret_result(): 완료 시 SUCCESS/FAILURE 매핑
    """
    def __init__(self, name, agent, action_spec):
        super().__init__(name)
        self.ros = agent.ros_bridge
        action_type, action_name = action_spec
        self.client = ActionClient(self.ros.node, action_type, action_name)

        self._goal_handle = None
        self._result_future = None
        self._phase = 'idle'       # 'idle' -> 'sending' -> 'running'

        # For PA-BT
        self.type = "Action"

    def _build_goal(self, agent, blackboard):
        # 하위 클래스에서 구현
        # Action Request가 보내질 때 실행되는 함수
        raise NotImplementedError

    def _on_running(self, agent, blackboard):
        # 하위 클래스에서 구현
        # Action Request가 한 번 시작되고 나면서 BT가 Tick이 될 때 실행되는 함수
        # 예) ROS Action Server로 요청을 하고 난 이후, 실시간으로 위치가 바뀌는 Target에 대한 정보를 ROS Topic으로 공유
        pass

    def _interpret_result(self, result, agent, blackboard, status_code=None):
        # 기본 매핑: SUCCEEDED → SUCCESS, 그 외 → FAILURE
        # 필요 시 하위 클래스에서 오버라이드
        if status_code == GoalStatus.STATUS_SUCCEEDED:
            return Status.SUCCESS
        return Status.FAILURE


    async def run(self, agent, blackboard):
        # Action Request 송신
        if self._phase == 'idle':
            if not self.client.wait_for_server(timeout_sec=0.0): # 서버가 아직 준비가 안된 상황 고려
                self.status = Status.RUNNING
                return self.status

            goal = self._build_goal(agent, blackboard)
            if goal is None:
                self.status = Status.FAILURE
                return self.status

            self.client.send_goal_async(goal).add_done_callback(self._on_goal_response)
            self._phase = 'sending'
            self.status = Status.RUNNING
            return self.status

        # Action Request를 송신했으나 아직 Acceptance Receipt를 못 받은 상황
        if self._phase == 'sending':
            self.status = Status.RUNNING
            return self.status

        # Action Request를 수신하여 진행되는 도중
        if self._phase == 'running':
            if self._result_future and self._result_future.done():
                try:
                    res = self._result_future.result()   # <- get_result 응답
                    self.status = self._interpret_result(res.result, agent, blackboard, res.status)
                except Exception:
                    # 서버 사망 등으로 future가 exception/cancel된 경우
                    self.status = Status.FAILURE
                self._phase = 'idle'
                return self.status
            # 서버가 도중에 죽었는지 확인
            if not self.client.wait_for_server(timeout_sec=0.0):
                self._phase = 'idle'
                self.status = Status.FAILURE
                return self.status
            self._on_running(agent, blackboard)
            self.status = Status.RUNNING

            return self.status

        self.status = Status.RUNNING
        return self.status

    def _on_goal_response(self, future):
        try:
            self._goal_handle = future.result()
        except Exception:
            # 서버 사망 등으로 goal response를 못 받은 경우
            self._phase = 'idle'
            return
        if not self._goal_handle.accepted:
            self._phase = 'idle'
            return
        self._result_future = self._goal_handle.get_result_async()
        self._phase = 'running'

    # Action Request 취소: BT에서 이것이 반복되면서 nav_action_server에 cancel_goal_async()가 여러 번 호출되면서 불안정해짐.
    # def halt(self):
    #     if self._goal_handle is not None:
    #         self._goal_handle.cancel_goal_async()
    #     self._phase = 'idle'


class ActionWithROSService(Node):
    """
    심플 ROS Service 클라이언트 베이스.
      - service_spec: (SrvType, service_name)
      - _build_request(): 서비스 요청 메시지 생성
      - _interpret_response(): 응답을 SUCCESS/FAILURE로 매핑
    """
    def __init__(self, name, agent, service_spec):
        super().__init__(name)
        self.ros = agent.ros_bridge
        srv_type, srv_name = service_spec
        self.client = self.ros.node.create_client(srv_type, srv_name)

        self._future = None
        self._sent = False

        # For PA-BT
        self.type = "Action"

    def _build_request(self, agent, blackboard):
        # 하위 클래스에서 구현
        raise NotImplementedError

    def _interpret_response(self, response, agent, blackboard):
        # 기본 매핑: 서비스 호출 성공 자체를 SUCCESS로 간주
        # 필요 시 하위 클래스에서 오버라이드
        return Status.SUCCESS

    async def run(self, agent, blackboard):
        # 서비스가 아직 준비 안 되었으면 다음 틱에 재시도
        if not self.client.wait_for_service(timeout_sec=0.0):
            self.status = Status.RUNNING
            return self.status

        # 최초 1회 호출
        if not self._sent:
            req = self._build_request(agent, blackboard)
            if req is None:
                self.status = Status.FAILURE
                return self.status
            self._future = self.client.call_async(req)
            self._sent = True
            self.status = Status.RUNNING
            return self.status

        # 응답 도착 확인
        if self._future and self._future.done():
            resp = self._future.result()
            self.status = self._interpret_response(resp, agent, blackboard)
            self._sent = False
            return self.status

        # 아직 응답 대기 중
        self.status = Status.RUNNING
        return self.status

    def halt(self):
        # 서비스는 취소 개념이 없으므로 플래그만 초기화
        self._sent = False


class ActionWithROSTopic(Node):
    """
    심플 ROS Topic 퍼블리셔 베이스.
      - topic_spec: (MsgType, topic_name)
      - _build_message(): 퍼블리시할 메시지 생성 (None 반환 시 FAILURE)
      - _interpret_publish(): 퍼블리시 결과를 SUCCESS/FAILURE로 매핑
    """
    def __init__(self, name, agent, topic_spec):
        super().__init__(name)
        self.ros = agent.ros_bridge
        msg_type, topic_name = topic_spec
        self._pub = self.ros.node.create_publisher(msg_type, topic_name, 10)

        # For PA-BT
        self.type = "Action"

    def _build_message(self, agent, blackboard):
        # 하위 클래스에서 구현
        # 퍼블리시할 메시지를 반환; None이면 FAILURE
        raise NotImplementedError

    def _interpret_publish(self, msg, agent, blackboard):
        # 기본 매핑: 퍼블리시 성공 자체를 SUCCESS로 간주
        # 필요 시 하위 클래스에서 오버라이드
        return Status.SUCCESS

    async def run(self, agent, blackboard):
        msg = self._build_message(agent, blackboard)
        if msg is None:
            self.status = Status.FAILURE
            return self.status

        self._pub.publish(msg)
        self.status = self._interpret_publish(msg, agent, blackboard)
        return self.status

    def halt(self):
        pass  # 토픽 퍼블리시는 취소 개념이 없음
