from launch import LaunchDescription
from launch_ros.actions import Node, SetRemap, SetParameter
from launch_ros.substitutions import FindPackageShare
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.substitutions import (
    PathJoinSubstitution,
    LaunchConfiguration,
    EqualsSubstitution
)
from launch.conditions import IfCondition


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'hardware_type',
            default_value='real',
            description='whether to use fake or real hardware'
        ),
        DeclareLaunchArgument(
            'bag_playback',
            default_value='false',
            description='whether to configure the system to use bag time'
        ),
        SetParameter(
            name="use_sim_time",
            value=True,
            condition=IfCondition(
                EqualsSubstitution(
                    left=LaunchConfiguration('bag_playback'),
                    right='true'
                )
            )
        ),
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare("botrista"),
                "launch",
                "realsense.launch.py"
            ])
        ),
        IncludeLaunchDescription(
            PathJoinSubstitution([
                FindPackageShare("botrista"),
                "launch",
                "open_franka.launch.xml"
            ]),
            launch_arguments={
                'hardware_type': LaunchConfiguration('hardware_type')
            }.items(),
        ),
        Node(
            package="botrista",
            executable="pouring"
        )
    ])