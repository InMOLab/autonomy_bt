import os
import re
import yaml
import tempfile
import launch
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable, RegisterEventHandler, TimerAction
from launch.event_handlers import OnProcessStart, OnProcessExit
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
from webots_ros2_driver.webots_launcher import WebotsLauncher
from webots_ros2_driver.webots_controller import WebotsController
from webots_ros2_driver.wait_for_controller_connection import WaitForControllerConnection
from launch_ros.actions import Node


# 월드 파일에서 인식할 로봇 타입 목록
ROBOTS_NAME_LIST = ['Fire_UGV']


def create_namespaced_params_file(robot_name, template_path):
    """로봇 namespace에 맞게 YAML 키를 /{robot_name}/{node_name} 형태로 변환하여 임시 파일로 저장.

    ROS 2에서 --params-file의 YAML 키는 노드의 전체 경로(/namespace/node_name)와
    매칭되기 때문에, namespace를 부여한 경우 키를 namespace 포함 형태로 재작성해야 한다.
    """
    with open(template_path, 'r') as f:
        params = yaml.safe_load(f)

    namespaced = {f'/{robot_name}/{node_name}': node_params for node_name, node_params in params.items()}

    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False, prefix=f'ros2ctrl_{robot_name}_'
    )
    yaml.dump(namespaced, tmp)
    tmp.close()
    return tmp.name


def discover_robots_from_world(world_path):
    """월드 파일에서 Husky 기반 로봇들의 DEF 이름을 추출"""
    robot_names = []
    pattern = re.compile(r'^DEF\s+(\w+)\s+(' + '|'.join(ROBOTS_NAME_LIST) + r')\b', re.MULTILINE)
    
    with open(world_path, 'r') as f:
        content = f.read()
    
    for match in pattern.finditer(content):
        robot_names.append(match.group(1))
    
    return robot_names


def generate_launch_description():
    package_dir = get_package_share_directory('webots_ros2_husky')

    # ✅ 기존 값이 있으면 보존하면서 package_dir을 추가
    prev_extra = os.environ.get('WEBOTS_EXTRA_PROJECT_PATH', '')
    extra_path = package_dir if prev_extra == '' else (package_dir + os.pathsep + prev_extra)

    prev_proj = os.environ.get('WEBOTS_PROJECT_PATH', '')
    proj_path = package_dir if prev_proj == '' else (package_dir + os.pathsep + prev_proj)

    # ✅ Webots가 /tmp world를 열더라도 여기 경로에서 controllers를 찾게 됨
    set_webots_paths = [
        SetEnvironmentVariable('WEBOTS_EXTRA_PROJECT_PATH', extra_path),
        SetEnvironmentVariable('WEBOTS_PROJECT_PATH', proj_path),
    ]

    # debug:=true 시 robot_supervisor, world_supervisor 모두 visualisation topics publish
    debug_arg = DeclareLaunchArgument(
        'debug', default_value='false',
        description='Enable debug visualisation topics (comm_topology, fires in RViz)'
    )
    set_debug_env = SetEnvironmentVariable('DEBUG', LaunchConfiguration('debug'))

    # Start a Webots simulation instance
    world_path = os.path.join(package_dir, 'worlds', 'fire_suppression.wbt')
    webots = WebotsLauncher(world=world_path)

    # 월드 파일에서 로봇 이름 동적 발견
    robot_names = discover_robots_from_world(world_path)
    print(f"[robot_launch] Discovered robots: {robot_names}")

    # Create the robot state publisher
    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': '<robot name=""><link name=""/></robot>'
        }],
    )

    # ROS control spawners
    ros2_control_params = os.path.join(package_dir, 'resource', 'ros2control.yaml')
    controller_manager_timeout = ['--controller-manager-timeout', '50']

    robot_description_path = os.path.join(package_dir, 'resource', 'husky.urdf')

    # ----------------------------------------
    # 로봇별 동적 생성: robot_driver + controller spawners + WaitForControllerConnection
    # 공식 예시처럼 각 로봇마다 독립적인 namespace와 controller_manager를 사용
    # ----------------------------------------
    robot_drivers = []
    ros_control_items = []  # robot_driver → waiting_node 순서 보장을 위한 리스트

    for robot_name in robot_names:
        # namespace를 부여하므로 remapping 소스는 상대 경로(namespace 기준)로 지정
        #
        # webots_ros2_driver는 robot_name이 설정될 때 센서 토픽을
        # '{robot_name}/{device_name}' 형태로 생성한다.
        # namespace=robot_name도 함께 부여하면 이중 네임스페이스가 생기므로
        # (예: /Fire_UGV_1/Fire_UGV_1/scan) 아래 remapping으로 되돌린다.
        mappings = [
            ('diffdrive_controller/cmd_vel', f'/{robot_name}/cmd_vel'),
            ('diffdrive_controller/odom', f'/{robot_name}/odom'),
            (f'{robot_name}/scan', 'scan'),
            (f'{robot_name}/scan/point_cloud', 'scan/point_cloud'),
        ]

        # 각 로봇에 고유 namespace 부여 → /{robot_name}/controller_manager 생성
        # namespace 사용 시 YAML 키가 /{robot_name}/{node_name} 형태여야 파라미터가 적용됨
        namespaced_params = create_namespaced_params_file(robot_name, ros2_control_params)
        robot_driver = WebotsController(
            robot_name=robot_name,
            namespace=robot_name,
            parameters=[
                {'robot_description': robot_description_path,
                 'set_robot_state_publisher': True},
                namespaced_params
            ],
            remappings=mappings
        )
        robot_drivers.append(robot_driver)

        # 각 로봇 전용 spawner: -c 로 해당 로봇의 controller_manager 명시
        joint_state_broadcaster_spawner = Node(
            package='controller_manager',
            executable='spawner',
            output='screen',
            arguments=['joint_state_broadcaster',
                       '-c', f'{robot_name}/controller_manager'] + controller_manager_timeout,
        )
        diffdrive_controller_spawner = Node(
            package='controller_manager',
            executable='spawner',
            output='screen',
            arguments=['diffdrive_controller',
                       '-c', f'{robot_name}/controller_manager'] + controller_manager_timeout,
        )

        # 해당 로봇의 controller_manager가 준비된 후에만 spawner 실행
        waiting_node = WaitForControllerConnection(
            target_driver=robot_driver,
            nodes_to_start=[joint_state_broadcaster_spawner, diffdrive_controller_spawner]
        )

        ros_control_items.append(robot_driver)
        ros_control_items.append(waiting_node)

    # LaunchDescription 구성
    # ros_control_items 안에 robot_driver → waiting_node 쌍이 순서대로 포함됨
    launch_items = [
        debug_arg,
        set_debug_env,
        *set_webots_paths,   # ✅ webots 앞에 들어가야 함
        webots,
        robot_state_publisher,
        *ros_control_items,
    ]

    launch_items.append(
        launch.actions.RegisterEventHandler(
            event_handler=launch.event_handlers.OnProcessExit(
                target_action=webots,
                on_exit=[launch.actions.EmitEvent(event=launch.events.Shutdown())],
            )
        )
    )

    return LaunchDescription(launch_items)
    
if __name__ == '__main__':
    # VSCode 디버깅이나 직접 python3로 실행할 때 작동하는 부분
    from launch import LaunchService

    # 1. LaunchDescription 생성
    ld = generate_launch_description()

    # 2. LaunchService 초기화 및 설명(ld) 포함
    ls = LaunchService()
    ls.include_launch_description(ld)

    # 3. 실행
    ls.run()