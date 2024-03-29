"""
Node for kettle management.

Uses the wrapper class made in moveitapi. 

Service Clients:
  + delay (botrista_interfaces/DelayTime) - Delay timer

Action Servers:
  + pick_kettle (botrista_interfaces/Emptyaction) - pick up the kettle
  + place_kettle (botrista_interfaces/Emptyaction) - place the kettle
  + pour_kettle (botrista_interfaces/Emptyaction) - pour water from the kettle

Action Clients:
  + pour_action (botrista_interfaces/PourAction) - Action for pouring in a spiral motion
  + grasp_process (botrista_interfaces/GraspProcess) - Action for detectinig and grasping an object
"""


import rclpy
from rclpy.node import Node
import tf2_geometry_msgs
from tf2_ros import Buffer, TransformListener
from moveit_wrapper.moveitapi import MoveItApi
from moveit_wrapper.grasp_planner import GraspPlan, GraspPlanner
from geometry_msgs.msg import Pose, Point, Quaternion, TransformStamped, Transform, Vector3
from std_msgs.msg import Header
from rclpy.callback_groups import ReentrantCallbackGroup
from franka_msgs.action import Grasp
from rclpy.time import Time
from franka_msgs.msg import GraspEpsilon
from rclpy.callback_groups import ReentrantCallbackGroup
from botrista_interfaces.action import EmptyAction, GraspProcess, PourAction
from rclpy.action import ActionServer, ActionClient
from botrista_interfaces.srv import DelayTime
import numpy as np


class Kettle(Node):

    def __init__(self):
        super().__init__("kettle")

        self.kettle_actual_place = TransformStamped()
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.moveit_api = MoveItApi(
            self, "panda_link0", "panda_hand_tcp", "panda_manipulator", "/franka/joint_states")
        self.grasp_planner = GraspPlanner(
            self.moveit_api, "panda_gripper/grasp")

        self.delay_client = self.create_client(
            DelayTime, "delay", callback_group=ReentrantCallbackGroup()
        )
        self.pick_kettle_client = ActionServer(self,
                                               EmptyAction,
                                               "pick_kettle",
                                               self.pick_kettle_cb,
                                               callback_group=ReentrantCallbackGroup())
        self.place_kettle_client = ActionServer(self,
                                                EmptyAction,
                                                "place_kettle",
                                                self.place_kettle_cb,
                                                callback_group=ReentrantCallbackGroup())
        self.pour_kettle_server = ActionServer(self,
                                               EmptyAction,
                                               "pour_kettle",
                                               self.pour_kettle_cb,
                                               callback_group=ReentrantCallbackGroup())
        self.grasp_process = ActionClient(self,
                                          GraspProcess,
                                          'grasp_process',
                                          callback_group=ReentrantCallbackGroup())

        self.pour_kettle = ActionClient(self,
                                        PourAction,
                                        'pour_action',
                                        callback_group=ReentrantCallbackGroup())

        while not self.delay_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().warn("Waiting for delay service")

        self.observe_pose = Pose(
            position=Point(x=0.0, y=0.0, z=0.40),
            orientation=Quaternion(x=1.0, y=0.0, z=0.0, w=0.0)
        )

        # grasp points in handle frame
        self.approach_pose = Pose(
            position=Point(x=0.0, y=0.0, z=-0.10),
            orientation=Quaternion())
        self.grasp_pose = Pose(
            position=Point(x=0.03, y=0.0, z=0.0),
            orientation=Quaternion())
        self.retreat_pose = Pose(
            position=Point(x=0.03, y=0.0, z=-0.10),
            orientation=Quaternion())

    async def pick_kettle_cb(self, goal_handle):
        """Grab the kettle from its stand."""
        # home the panda
        await self.moveit_api.plan_joint_async(
            ["panda_joint1", "panda_joint2", "panda_joint3",
                "panda_joint4", "panda_joint5", "panda_joint6", "panda_joint7"],
            [0.0, -np.pi / 4.0, 0.0, -3*np.pi / 4.0, 0.0, np.pi / 2.0, np.pi / 4.0],
            execute=True
        )

        # TFs
        # pour_over_tag
        try:
            tf = self.buffer.lookup_transform(
                "panda_link0", "filtered_kettle_tag", Time())

        except Exception as e:
            self.get_logger().error("No transform found")
            return

        observe_pose = tf2_geometry_msgs.do_transform_pose(
            self.observe_pose, tf)

        refinement_pose = Pose(
            position=Point(x=0.0, y=0.0, z=-0.15),
            orientation=Quaternion())

        goal_msg = GraspProcess.Goal(
            observe_pose=observe_pose,
            refinement_pose=refinement_pose,
            approach_pose=self.approach_pose,
            grasp_pose=self.grasp_pose,
            width=0.03,
            force=50.0,
            speed=0.05,
            epsilon=GraspEpsilon(inner=0.01, outer=0.01),
            retreat_pose=self.retreat_pose,
            object=1
        )

        self.get_logger().warn("MADE GRASP PROCESS GOAL")

        goal = await self.grasp_process.send_goal_async(goal_msg)
        res = await goal.get_result_async()
        self.kettle_actual_place = res.result.actual_grasp_pose
        goal_handle.succeed()
        return EmptyAction.Result()

    async def place_kettle_cb(self, goal_handle):
        """Place the kettle on its stand."""
        approach_pose = Pose(
            position=Point(x=0.0, y=0.0, z=-0.1),
            orientation=Quaternion()
        )

        grasp_pose = Pose(
            position=Point(x=0.0, y=0.0, z=-0.02),
            orientation=Quaternion()
        )

        retreat_pose = Pose(
            position=Point(x=0.0, y=0.0, z=-0.1),
            orientation=Quaternion()
        )

        approach_pose = tf2_geometry_msgs.do_transform_pose(
            approach_pose, self.kettle_actual_place)
        grasp_pose = tf2_geometry_msgs.do_transform_pose(
            grasp_pose, self.kettle_actual_place)
        retreat_pose = tf2_geometry_msgs.do_transform_pose(
            retreat_pose, self.kettle_actual_place)

        grasp_plan = GraspPlan(
            approach_pose=approach_pose,
            grasp_pose=grasp_pose,
            grasp_command=Grasp.Goal(
                width=0.04,  # open the gripper wider to release the kettle
                force=50.0,
                speed=0.2,
            ),
            retreat_pose=approach_pose,
            reset_load=True
        )

        await self.grasp_planner.execute_grasp_plan(grasp_plan)
        goal_handle.succeed()
        return EmptyAction.Result()

    async def pour_kettle_cb(self, goal_handle):
        """
        Pour the kettle using the spiral pour.

        Args:
            goal_handle (EmptyAction.Goal) -- goal of the pour action

        Returns:
            EmptyAction.Result -- Result of the action
        """
        try:
            pot_top_tf = self.buffer.lookup_transform(
                "panda_link0", "pot_top", Time())
        except Exception as e:
            self.get_logger().error("No transform found")
            return

        tf = TransformStamped(
            header=Header(
                frame_id="panda_link0",
                stamp=self.get_clock().now().to_msg()
            ),
            transform=Transform(
                translation=Vector3(x=-0.23, y=0.0, z=0.02),
                rotation=Quaternion()
            )
        )

        approach_pose = Pose(
            position=Point(x=-0.01, y=0.0, z=0.20),
            orientation=Quaternion(
                x=1.0, y=0.0, z=0.0, w=0.0)
        )

        pour_pose = Pose(
            position=Point(x=0.01, y=-0.005, z=0.17),
            orientation=Quaternion(
                x=0.9452608, y=0.0, z=-0.3150869, w=-0.0848662)
        )
        # transform to spout
        approach_pose = tf2_geometry_msgs.do_transform_pose(
            approach_pose, tf)
        pour_pose = tf2_geometry_msgs.do_transform_pose(pour_pose, tf)

        # transform to pot_top
        approach_pose = tf2_geometry_msgs.do_transform_pose(
            approach_pose, pot_top_tf)
        pour_pose = tf2_geometry_msgs.do_transform_pose(pour_pose, pot_top_tf)

        # Pour 1
        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )

        result = await self.moveit_api.plan_async(
            point=pour_pose.position,
            orientation=pour_pose.orientation,
            execute=True
        )

        goal_msg = PourAction.Goal(
            num_points=100,
            spiral_radius=0.02,
            num_loops=2.0,
            start_outside=True,
            pour_frame="panda_hand_tcp",
        )
        result = await self.pour_kettle.send_goal_async(goal_msg)
        res = await result.get_result_async()

        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )
        await self.delay_client.call_async(DelayTime.Request(time=1.0))

        # Pour 2
        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )

        result = await self.moveit_api.plan_async(
            point=pour_pose.position,
            orientation=pour_pose.orientation,
            execute=True
        )

        goal_msg = PourAction.Goal(
            num_points=100,
            spiral_radius=0.02,
            num_loops=2.0,
            start_outside=False,
            pour_frame="panda_hand_tcp",
        )
        result = await self.pour_kettle.send_goal_async(goal_msg)
        res = await result.get_result_async()

        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )
        await self.delay_client.call_async(DelayTime.Request(time=1.0))

        # Pour 3
        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )

        result = await self.moveit_api.plan_async(
            point=pour_pose.position,
            orientation=pour_pose.orientation,
            execute=True
        )

        goal_msg = PourAction.Goal(
            num_points=100,
            spiral_radius=0.02,
            num_loops=2.0,
            start_outside=False,
            pour_frame="panda_hand_tcp",
        )
        result = await self.pour_kettle.send_goal_async(goal_msg)
        res = await result.get_result_async()

        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )
        await self.delay_client.call_async(DelayTime.Request(time=1.0))

        # Pour 4
        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )

        result = await self.moveit_api.plan_async(
            point=pour_pose.position,
            orientation=pour_pose.orientation,
            execute=True
        )

        goal_msg = PourAction.Goal(
            num_points=100,
            spiral_radius=0.02,
            num_loops=2.0,
            start_outside=False,
            pour_frame="panda_hand_tcp",
        )
        result = await self.pour_kettle.send_goal_async(goal_msg)
        res = await result.get_result_async()

        result = await self.moveit_api.plan_async(
            point=approach_pose.position,
            orientation=approach_pose.orientation,
            execute=True
        )

        goal_handle.succeed()
        return EmptyAction.Result()


def kettle_entry(args=None):
    rclpy.init(args=args)
    kettle = Kettle()
    rclpy.spin(kettle)
    rclpy.shutdown()
