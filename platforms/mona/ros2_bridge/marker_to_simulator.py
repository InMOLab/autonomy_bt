"""
WhyCon → simulator UDP bridge.

Run this as a standalone ROS2 node (NOT imported by sim.py):
    python -m platforms.mona.ros2_bridge.marker_to_simulator

It subscribes to /whycode_node/markers, converts each marker's WhyCon
(camera-frame y, z) coordinate into pygame canvas (x, y) pixels, and
publishes a JSON payload {agent_id, x, y, yaw} via UDP to 127.0.0.1:9999.
The puppet/offboard scenarios spawn a UDP listener on that port and feed
each agent through MonaAgent.set_position().

Requires a ROS2 environment with whycode_interfaces installed; do not
import this module from contexts that don't have rclpy.
"""
import rclpy
from rclpy.node import Node

from socket import socket, AF_INET, SOCK_DGRAM
import json

from whycode_interfaces.msg import MarkerArray


class MarkerListener(Node):
    # ----- Simulator canvas size (px) -----
    SIM_WIDTH_PX = 1260
    SIM_HEIGHT_PX = 660
    # Outer margins (px)
    MARGIN_X = 40
    MARGIN_Y = 40

    # ----- Measured WhyCon ranges (meters) -----
    WHYCON_Y_MAX = 2.14    # left-most
    WHYCON_Y_MIN = -2.185  # right-most
    WHYCON_Z_MAX = 1.125   # top-most
    WHYCON_Z_MIN = -1.085  # bottom-most

    def __init__(self):
        super().__init__('marker_listener')

        self.AX = -self.SIM_WIDTH_PX / (self.WHYCON_Y_MAX - self.WHYCON_Y_MIN)
        self.BX = -self.AX * self.WHYCON_Y_MAX

        self.AY = -self.SIM_HEIGHT_PX / (self.WHYCON_Z_MAX - self.WHYCON_Z_MIN)
        self.BY = -self.AY * self.WHYCON_Z_MAX

        self.CX = self.SIM_WIDTH_PX / 2.0
        self.CY = self.SIM_HEIGHT_PX / 2.0

        # ROS subscription
        self.subscription = self.create_subscription(
            MarkerArray,
            '/whycode_node/markers',
            self.listener_callback,
            10,
        )

        # UDP socket → simulator
        self.sock = socket(AF_INET, SOCK_DGRAM)
        self.udp_ip = '127.0.0.1'
        self.udp_port = 9999

        # marker ID → agent_id
        self.marker_to_agent = {
            1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5,
            7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 11,
        }

        self.get_logger().info(
            f"MarkerListener started. Tracking markers: {list(self.marker_to_agent.keys())} "
            f"→ Sending to {self.udp_ip}:{self.udp_port}"
        )

    def listener_callback(self, msg):
        for marker in msg.markers:
            agent_id = self.marker_to_agent.get(marker.id)
            if agent_id is None:
                continue

            # WhyCon coordinates (meters) → simulator (pixels)
            cam_y = float(marker.position.position.y)  # → sim X
            cam_z = float(marker.position.position.z)  # → sim Y
            yaw = -1 * float(marker.rotation.x)         # radians

            sim_x, sim_y = self.convert_to_sim(cam_y, cam_z)

            data = {"agent_id": agent_id, "x": sim_x, "y": sim_y, "yaw": yaw}
            self.sock.sendto(json.dumps(data).encode(), (self.udp_ip, self.udp_port))
            self.get_logger().info(f"Sent: {data}")

    def convert_to_sim(self, y, z):
        """
        WhyCon (y, z) in meters → simulator (x, y) in pixels.
            y = +2.13 (left)  → x = 40,    y = -2.21 (right) → x = 1260
            z = +1.18 (top)   → y = 40,    z = -1.07 (bottom) → y = 660
        """
        x_px = self.AX * y + self.BX
        y_px = self.AY * z + self.BY
        x_px += self.MARGIN_X
        y_px += self.MARGIN_Y
        return x_px, y_px


def main(args=None):
    rclpy.init(args=args)
    node = MarkerListener()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
