import pytest
import rclpy
from warehouse_package.warehouse_brain import WarehouseBrain


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def test_node_starts_with_expected_name(ros_context):
    node = WarehouseBrain()
    try:
        assert node.get_name() == 'warehouse_brain'
    finally:
        node.destroy_node()
