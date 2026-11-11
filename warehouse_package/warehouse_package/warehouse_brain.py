import rclpy
from rclpy.node import Node


class WarehouseBrain(Node):
    def __init__(self):
        super().__init__('warehouse_brain')
        self.get_logger().info('Warehouse Brain node started')


def main(args=None):
    rclpy.init(args=args)
    node = WarehouseBrain()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
