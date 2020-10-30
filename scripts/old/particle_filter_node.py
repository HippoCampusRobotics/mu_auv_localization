#!/usr/bin/env python
import particle_class
import numpy as np

from pyquaternion import Quaternion
import rospy
import tf

from geometry_msgs.msg import Pose, PoseArray, PoseStamped
from apriltag_ros.msg import AprilTagDetectionArray
from apriltag_ros.msg import AprilTagDetection
from visualization_msgs.msg import Marker, MarkerArray
from mavros_msgs.srv import SetMode
from numpy import genfromtxt
import os

NUM_P = 100
PART_DIM = 3  # x, y, z
x_range = (0, 3)
y_range = (0, 2)
z_range = (0, 1.5)
# cov_mat = 1.5
# cov_mat = 0.05
cov_mat = 0.05
old_yaw = 0
# set_mode_srv = rospy.ServiceProxy('mavros/set_mode', SetMode)
# res = set_mode_srv(0, " OFFBOARD")

# /home/hippoc/.ros
# /home/hippoc/catkin_ws/src/localisation/scripts
# print os.getcwd()
path_to_calibration = '../ros_catkin_ws/src/localisation/scripts'  # on hippoc-companion
# path_to_calibration = '../scripts'  # on computer
# path_to_calibration = '../catkin_ws/src/localisation/scripts'    # on hippoc
tags = genfromtxt(path_to_calibration + '/calibration.csv', delimiter=',')

tags = tags[:, 0:4]
# tags[:, 1] += 0.08  # to shift x-value according to gantry origin
# tags[:,2] += 0.02  # to shift y-value according to gantry origin
# print(tags)
rviz = False


def yaw_pitch_roll_to_quat(yaw, pitch, roll):
    cy = np.cos(yaw * 0.5)
    sy = np.sin(yaw * 0.5)
    cp = np.cos(pitch * 0.5)
    sp = np.sin(pitch * 0.5)
    cr = np.cos(roll * 0.5)
    sr = np.sin(roll * 0.5)
    return (Quaternion(x=cy * cp * sr - sy * sp * cr, y=sy * cp * sr + cy * sp * cr, z=sy * cp * cr - cy * sp * sr,
                       w=cy * cp * cr + sy * sp * sr))


def callback(msg, tmp_list):
    """"""
    global old_yaw
    [particle_filter, publisher_position, publisher_mavros, publisher_particles, broadcaster,
     publisher_marker] = tmp_list

    # particle filter algorithm
    particle_filter.predict()  # move particles

    # get length of message
    num_meas = len(msg.detections)
    orientation_yaw_pitch_roll = np.zeros((num_meas, 3))

    # if new measurement: update particles
    if num_meas >= 1:
        measurements = np.zeros((num_meas, 1 + PART_DIM))
        # get data from topic /tag_detection

        if rviz:
            markerArray = MarkerArray()

        for i, tag in enumerate(msg.detections):
            tag_id = int(tag.id[0])
            distance = np.array(([tag.pose.pose.pose.position.x,
                                  tag.pose.pose.pose.position.y,
                                  tag.pose.pose.pose.position.z]))
            measurements[i, 0] = np.linalg.norm(distance)
            tmpquat = Quaternion(w=tag.pose.pose.pose.orientation.w,
                                 x=tag.pose.pose.pose.orientation.x,
                                 y=tag.pose.pose.pose.orientation.y,
                                 z=tag.pose.pose.pose.orientation.z)

            orientation_yaw_pitch_roll[i, :] = tmpquat.inverse.yaw_pitch_roll
            index = np.where(tags[:, 0] == tag_id)

            measurements[i, 1:4] = tags[index, 1:4]
            # print(measurements[i, 1:4])
            if rviz:
                marker = Marker()
                marker.header.frame_id = "global_tank"
                marker.id = i
                marker.type = marker.SPHERE
                marker.action = marker.ADD
                marker.scale.x = measurements[i, 0] * 2  # r*2 of distance to camera from tag_14
                marker.scale.y = measurements[i, 0] * 2
                marker.scale.z = measurements[i, 0] * 2
                marker.color.g = 1
                marker.color.a = 0.1  # transparency
                marker.pose.orientation.w = 1.0
                marker.pose.position.x = tags[index, 1][0]  # x
                marker.pose.position.y = tags[index, 2][0]  # y
                marker.pose.position.z = tags[index, 3][0]  # z
                markerArray.markers.append(marker)

        if rviz:
            # print(len(markerArray.markers))
            publisher_marker.publish(markerArray)
            # print(index)
        particle_filter.update(measurements)
        yaw = np.mean(orientation_yaw_pitch_roll[:, 0])
        pitch = np.mean(orientation_yaw_pitch_roll[:, 1])
        roll = np.mean(orientation_yaw_pitch_roll[:, 2])
    else:
        yaw = old_yaw
    old_yaw = yaw
    # print "reale messungen: " + str(measurements)

    print("Angle yaw:", yaw * 180 / np.pi)
    estimated_orientation = yaw_pitch_roll_to_quat(-(yaw - np.pi / 2), 0, 0)
    # estimated_orientation = yaw_pitch_roll_to_quat(yaw, 0, 0)#evtl wrong
    # calculate position as mean of particle positions
    estimated_position = particle_filter.get_position_estimate()

    # [mm]
    x_mean_ned = estimated_position[0] * 1000  # global Tank Coordinate System(NED)
    y_mean_ned = estimated_position[1] * 1000
    z_mean_ned = estimated_position[2] * 1000

    # publish estimated_pose [m] in mavros to /mavros/vision_pose/pose
    # this pose needs to be in ENU
    mavros_position = PoseStamped()
    mavros_position.header.stamp = rospy.Time.now()
    mavros_position.header.frame_id = "map"
    mavros_position.pose.position.x = y_mean_ned / 1000  # NED Coordinate to ENU(ROS)
    mavros_position.pose.position.y = x_mean_ned / 1000
    mavros_position.pose.position.z = - z_mean_ned / 1000

    mavros_position.pose.orientation.w = estimated_orientation.w
    mavros_position.pose.orientation.x = estimated_orientation.x
    mavros_position.pose.orientation.y = estimated_orientation.y
    mavros_position.pose.orientation.z = estimated_orientation.z

    # publish estimated_pose [m]
    position = PoseStamped()
    position.header.stamp = rospy.Time.now()
    position.header.frame_id = "global_tank"  # ned
    position.pose.position.x = x_mean_ned / 1000
    position.pose.position.y = y_mean_ned / 1000
    position.pose.position.z = z_mean_ned / 1000
    estimated_orientation = yaw_pitch_roll_to_quat(yaw, 0, 0)
    position.pose.orientation.w = estimated_orientation.w
    position.pose.orientation.x = estimated_orientation.x
    position.pose.orientation.y = estimated_orientation.y
    position.pose.orientation.z = estimated_orientation.z
    publisher_position.publish(position)

    # yaw = 0 / 180.0 * np.pi
    # tmp = yaw_pitch_roll_to_quat(-(yaw-np.pi/2), 0, 0)
    # print(tmp)
    # mavros_position.pose.orientation.w = tmp.w
    # mavros_position.pose.orientation.x = tmp.x
    # mavros_position.pose.orientation.y = tmp.y
    # mavros_position.pose.orientation.z = tmp.z
    publisher_mavros.publish(mavros_position)

    # For Debugging
    # mavros_position = PoseStamped()
    # mavros_position.header.stamp = rospy.Time.now()
    # mavros_position.header.frame_id = "map"
    # mavros_position.pose.position.x = 1.0 + np.random.normal(0, 0.01)
    # mavros_position.pose.position.y = 2.0 + np.random.normal(0, 0.01)
    # mavros_position.pose.position.z = 3.0 + np.random.normal(0, 0.01)
    #
    # mavros_position.pose.orientation.w = 1.0
    # mavros_position.pose.orientation.x = 2.0
    # mavros_position.pose.orientation.y = 3.0
    # mavros_position.pose.orientation.z = 4.0

    # publisher_mavros.publish(mavros_position)

    """
    # publish transform
    broadcaster.sendTransform((estimated_position[0], estimated_position[1], estimated_position[2]),
                              (1.0, 0, 0, 0),
                              rospy.Time.now(),
                              "TestPose",
                              "world")
    """

    if rviz:
        # publish particles as PoseArray
        pose_array = PoseArray()
        pose_array.header.stamp = rospy.Time.now()
        pose_array.header.frame_id = "global_tank"
        # for i in range(num_meas):
        #     print(orientation_yaw_pitch_roll[i, 0] * 180 / np.pi, orientation_yaw_pitch_roll[i, 1] * 180 / np.pi,
        #           orientation_yaw_pitch_roll[i, 2] * 180 / np.pi)
        print("done")
        for i in range(particle_filter.NUM_P):
            pose = Pose()
            pose.position.x = particle_filter.particles[i, 0]
            pose.position.y = particle_filter.particles[i, 1]
            pose.position.z = particle_filter.particles[i, 2]
            # pose.orientation.x =
            # pose.orientation.y =
            # pose.orientation.z =
            # pose.orientation.w =
            pose_array.poses.append(pose)

        publisher_particles.publish(pose_array)
        # add spheres to rviz

        # print pose_array


def main():
    rospy.init_node('particle_filter_node')

    particle_filter = particle_class.ParticleFilter(NUM_P, PART_DIM, x_range, y_range, z_range, cov_mat)

    publisher_position = rospy.Publisher('estimated_pose_particle', PoseStamped, queue_size=1)
    publisher_mavros = rospy.Publisher('/mavros/vision_pose/pose', PoseStamped, queue_size=1)
    publisher_particles = rospy.Publisher('particle_poses', PoseArray, queue_size=1)
    publisher_marker = rospy.Publisher('Sphere', MarkerArray, queue_size=1)
    broadcaster = tf.TransformBroadcaster()

    rospy.Subscriber("/tag_detections", AprilTagDetectionArray, callback,
                     [particle_filter, publisher_position, publisher_mavros, publisher_particles, broadcaster,
                      publisher_marker], queue_size=1)

    while not rospy.is_shutdown():
        pass


if __name__ == '__main__':
    main()
