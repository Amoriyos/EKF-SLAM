#!/usr/bin/env python
# Python implementation of "ekf_slam"

import rospy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from std_msgs.msg import Float32
from aruco_localization.msg import MarkerMeasurementArray
from math import *
import numpy as np
import tf

class ekf_slam:
    #init functions
    def __init__(self):
        #init stuff
        #get stuff

        self.num_landmarks = 12

        # Estimator stuff
        # x = pn, pe, pd, phi, theta, psi
        self.xhat = np.zeros((9 + 2*self.num_landmarks, 1))
        self.xhat_odom = Odometry()

        # Covariance matrix
        self.P = np.zeros((9 + 2*self.num_landmarks, 9 + 2*self.num_landmarks))
        self.P[9:,9:] = np.eye(2*self.num_landmarks)*9999999.9 # Inf
        self.Q = np.diag([100.0, 10.0]) # meas noise
        # self.Q = np.diag([2.0, 1.0]) # meas noise

        # Measurements stuff
        # Truth
        self.truth_pn = 0.0
        self.truth_pe = 0.0
        self.truth_pd = 0.0
        self.truth_phi = 0.0
        self.truth_theta = 0.0
        self.truth_psi = 0.0
        self.truth_p = 0.0
        self.truth_q = 0.0
        self.truth_r = 0.0
        self.truth_pndot = 0.0
        self.truth_pedot = 0.0
        self.truth_pddot = 0.0
        self.truth_u = 0.0
        self.truth_v = 0.0
        self.truth_w = 0.0
        self.prev_time = 0.0
        self.imu_az = 0.0

        #aruco Stuff
        self.aruco_location = {
        100:[0.0, 0.0, 0.0],
        101:[0.0, -14.5, 5.0],
        102:[5.0, -14.5, 5.0],
        103:[-5.0, -14.5, 5.0],
        104:[0.0, 14.5, 5.0],
        105:[5.0, 14.5, 5.0],
        106:[-5.0, 14.5, 5.0],
        107:[7.0, 0.0, 5.0],
        108:[7.0, -7.5, 5.0],
        109:[7.0, 7.5, 5.0],
        110:[-7.0, 0.0, 5.0],
        111:[-7.0, -7.5, 5.0],
        112:[-7.0, 7.5, 5.0],
        }

        # Number of propagate steps
        self.N = 5

        #Constants
        self.g = 9.8

        # ROS Stuff
        # Init subscribers
        self.truth_sub_ = rospy.Subscriber('/slammer/ground_truth/odometry/NED', Odometry, self.truth_callback)
        self.imu_sub_ = rospy.Subscriber('/slammer/imu/data', Imu, self.imu_callback)
        self.aruco_sub = rospy.Subscriber('/aruco/measurements', MarkerMeasurementArray, self.aruco_meas_callback )

        # Init publishers
        self.estimate_pub_ = rospy.Publisher('/ekf_estimate', Odometry, queue_size=10)

        # # Init Timer
        self.pub_rate_ = 100. #
        self.update_timer_ = rospy.Timer(rospy.Duration(1.0/self.pub_rate_), self.pub_est)


    def propagate(self, dt):
        # Using truth for:
        #           - p (near perfect IMU)
        #           - q (near perfect IMU)
        #           - r (near perfect IMU)
        #           - u
        #           - v
        #           - w

        for _ in range(self.N):
            # Calc trig functions
            sp = sin(self.xhat[6])
            cp = cos(self.xhat[6])
            st = sin(self.xhat[7])
            ct = cos(self.xhat[7])
            tt = tan(self.xhat[7])
            spsi = sin(self.xhat[8])
            cpsi = cos(self.xhat[8])
            # sp = sin(self.truth_phi)
            # cp = cos(self.truth_phi)
            # st = sin(self.truth_theta)
            # ct = cos(self.truth_theta)
            # tt = tan(self.truth_theta)
            # spsi = sin(self.truth_psi)
            # cpsi = cos(self.truth_psi)

            # Calc pos_dot
            lin_vel = np.zeros((3,1))
            lin_vel[0] = self.truth_u
            lin_vel[1] = self.truth_v
            lin_vel[2] = self.truth_w

            pos_rot_mat = np.array([[ct*cpsi, sp*st*cpsi-cp*spsi, cp*st*cpsi+sp*spsi],
                                    [ct*spsi, sp*st*spsi+cp*cpsi, cp*st*spsi-sp*cpsi],
                                    [-st, sp*ct, cp*ct]])

            pos_dot = np.matmul(pos_rot_mat, lin_vel)

            # calc eul dot
            ang_rates = np.zeros((3,1))
            ang_rates[0] = self.truth_p
            ang_rates[1] = self.truth_q
            ang_rates[2] = self.truth_r


            rot_matrix = np.array([[1., sp*tt, cp*tt], [0., cp, -sp], [0., sp/ct, cp/ct]])

            eul_dot = np.matmul(rot_matrix, ang_rates)

            # Calc xdot
            #TODO add other states, or remove states from Jacobian
            xdot = np.zeros((9,1))
            xdot[0] = pos_dot[0]
            xdot[1] = pos_dot[1]
            xdot[2] = pos_dot[2]
            xdot[3] = cp*st*self.imu_az                    # udot
            xdot[4] = -sp*self.imu_az                     # vdot
            xdot[5] = self.g+cp*ct*self.imu_az              # wdot
            xdot[6] = eul_dot[0]
            xdot[7] = eul_dot[1]
            xdot[8] = eul_dot[2]

            self.xhat[0:9] += xdot*dt/float(self.N)

            while self.xhat[8] > np.pi:
                self.xhat[8] -= 2*np.pi
            while self.xhat[8] < -np.pi:
                self.xhat[8] += 2*np.pi

            # A = np.array([[0, 0, 0, 1, 0, 0, 0, 0, 0],
            # [0, 0, 0, 0, 1, 0, 0, 0, 0],
            # [0, 0, 0, 0, 0, 1, 0, 0, 0],
            # [0, 0, 0, 0, 0, 0, -sp*st*self.imu_az, cp*ct*self.imu_az, 0],
            # [0, 0, 0, 0, 0, 0, -cp*self.imu_az, 0, 0],
            # [0, 0, 0, 0, 0, 0, -sp*ct*self.imu_az, -cp*st*self.imu_az, 0],
            # [0, 0, 0, 0, 0, 0, self.truth_q*cp*tt-self.truth_r*sp*tt, (self.truth_q*sp+self.truth_r*cp)/(ct)**2, 0],
            # [0, 0, 0, 0, 0, 0, -self.truth_q*sp-self.truth_r*cp, 0, 0],
            # [0, 0, 0, 0, 0, 0, (self.truth_q*cp-self.truth_r*sp)/ct, -(self.truth_q*sp+self.truth_r*cp)*tt/ct, 0]])

            # self.P = self.P + 1/float(self.N)*(np.matmul(A,self.P)+np.matmul(self.P,A.T))#+np.matmul(G,Q,G.T))
            self.P[0:9,0:9] += np.diag([0.001, 0.001, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.001])

    def update(self):

        # Remember that X correpsonds to East and Y to north

        # Compute Landmark index (0 indexed)
        lndmark = self.aruco_id - 101
        # print "Landmark #", lndmark

        # If never seen before
        if self.xhat[9+2*lndmark] == 0.0:
            # print "Init Landmark"
            # Init location of Landmark
            self.xhat[9+2*lndmark] = self.xhat[0] + self.range*cos(self.bearing_2d + self.xhat[8]) # pn
            self.xhat[10+2*lndmark] = self.xhat[1] + self.range*sin(self.bearing_2d + self.xhat[8]) # pe
            # print "Location:", self.xhat[9+2*lndmark:11+2*lndmark]

        # Compute Delta
        delta_n = self.xhat[9+2*lndmark] - self.xhat[0]
        delta_e = self.xhat[10+2*lndmark] - self.xhat[1]
        delta = np.array([delta_e, delta_n])
        # print "delta", delta

        q = np.matmul(delta.T, delta)
        # print "q", q

        # Compute Zhat
        zhat = np.array([[sqrt(q)],
                        [np.arctan2(delta_e, delta_n)-self.xhat[8]]])
        # print "zhat2", np.arctan2(delta_e, delta_n)-self.xhat[8]

        # Selector Matrix
        # Fxj = np.array([[np.eye(9), np.zeros((9, 2*self.num_landmarks))],
        #     [np.zeros((2, 9+(2*(lndmark)))), np.eye(2), np.zeros((2, 2*self.num_landmarks - 2*lndmark))]])

        Fxj = np.zeros((11, 9 + 2*self.num_landmarks))
        Fxj[0:2,0:2] = np.eye(2)
        Fxj[2,8] = 1.
        Fxj[3:5, 9+(2*lndmark):11+(2*lndmark)] = np.eye(2)
        # print "Fxj", Fxj

        # print "sqrtq", [-sqrt(q)*delta_e[0], -sqrt(q)*delta_n, 0., sqrt(q)*delta_e, sqrt(q)*delta_n]
        littleC = (1/q)*np.array([[-sqrt(q)*delta_n[0], -sqrt(q)*delta_e[0], 0., sqrt(q)*delta_n[0], sqrt(q)*delta_e[0]],
                           [delta_e[0], -delta_n[0], -q, -delta_e[0], delta_n[0]]])
        BigC = np.zeros((2,11))
        BigC[0:2,0:5] = littleC
        # print "BigC", BigC

        C = np.matmul(BigC, Fxj)
        # print "C", C

        # print self.aruco_id, self.xhat[0], self.xhat[1], self.range, self.H
        S = np.matmul(C,np.matmul(self.P,C.T))+self.Q
        self.L = np.matmul(self.P,np.matmul(C.T,np.linalg.inv(S)))

        # wrap the residual
        residual = self.z-zhat
        while residual[1] > np.pi:
            residual[1] -= 2*np.pi
        while residual[1] < -np.pi:
            residual[1] += 2*np.pi
        # print "zhat", zhat
        # print "Residua", residual
        # print "aruco_id", self.aruco_id
        print "Location:", self.xhat[9+2*lndmark:11+2*lndmark]
        print "True Location:", self.aruco_location[self.aruco_id]
        # print "Covariance:", self.P[9+2*lndmark:11+2*lndmark,9+2*lndmark:11+2*lndmark]
        # print "xhat", self.xhat

        dist = residual.T.dot(np.linalg.inv(S)).dot(residual)[0,0]
        # print "dist", dist
        if True: #dist < 9:
            self.xhat = self.xhat + np.matmul(self.L,(residual))
            # print "add", np.matmul(self.L,(residual))[9+2*lndmark:11+2*lndmark]
            # print "Added", np.matmul(self.L,(residual))[8]
            self.P = np.matmul((np.identity(9 + 2*self.num_landmarks)-np.matmul(self.L,C)),self.P)
            pass
        else:
            print "gated a measurement", np.sqrt(dist)

        while self.xhat[8] > np.pi:
            self.xhat[8] -= 2*np.pi
        while self.xhat[8] < -np.pi:
            self.xhat[8] += 2*np.pi

        # print "True measred position N", self.truth_pn + self.range*cos(self.bearing_2d + self.truth_psi) # pn
        # print "True measred position E", self.truth_pe + self.range*sin(self.bearing_2d + self.truth_psi) # pe

    def pub_est(self, event):

        # pack up estimate to ROS msg and publish
        self.xhat_odom.header.stamp = rospy.Time.now()
        self.xhat_odom.pose.pose.position.x = self.xhat[0] # pn
        self.xhat_odom.pose.pose.position.y = self.xhat[1] # pe
        self.xhat_odom.pose.pose.position.z = self.xhat[2] # pd

        quat = tf.transformations.quaternion_from_euler(self.xhat[6].copy(), self.xhat[7].copy(), self.xhat[8].copy())

        self.xhat_odom.pose.pose.orientation.x = quat[0]
        self.xhat_odom.pose.pose.orientation.y = quat[1]
        self.xhat_odom.pose.pose.orientation.z = quat[2]
        self.xhat_odom.pose.pose.orientation.w = quat[3]
        self.xhat_odom.twist.twist.linear.x = self.xhat[3] # u
        self.xhat_odom.twist.twist.linear.y = self.xhat[4] # v
        self.xhat_odom.twist.twist.linear.z = self.xhat[5] # w

        self.estimate_pub_.publish(self.xhat_odom)

    # Callback Functions
    def truth_callback(self, msg):

        time = msg.header.stamp.secs + msg.header.stamp.nsecs*1e-9

        # Map msg to class variables
        self.truth_pn = msg.pose.pose.position.x
        self.truth_pe = msg.pose.pose.position.y
        self.truth_pd = msg.pose.pose.position.z

        quat = (
        msg.pose.pose.orientation.x,
        msg.pose.pose.orientation.y,
        msg.pose.pose.orientation.z,
        msg.pose.pose.orientation.w)
        euler = tf.transformations.euler_from_quaternion(quat)

        self.truth_phi = euler[0]
        self.truth_theta = euler[1]
        self.truth_psi = euler[2]

        self.truth_p = msg.twist.twist.angular.x
        self.truth_q = msg.twist.twist.angular.y
        self.truth_r = msg.twist.twist.angular.z

        self.truth_u = msg.twist.twist.linear.x
        self.truth_v = msg.twist.twist.linear.y
        self.truth_w = msg.twist.twist.linear.z

        if (self.prev_time != 0.0):
            dt = time - self.prev_time
            self.propagate(dt)

        self.prev_time = time

    def imu_callback(self, msg):

        # Map msg to class variables

        # Angular rates
        # self.truth_p = msg.angular_velocity.x
        # self.truth_q = msg.angular_velocity.y
        # self.truth_r = msg.angular_velocity.z
        # self.imu_p = msg.angular_velocity.x
        # self.imu_q = msg.angular_velocity.y
        # self.imu_r = msg.angular_velocity.z

        # Linear accel
        self.imu_ax = msg.linear_acceleration.x
        self.imu_ay = msg.linear_acceleration.y
        self.imu_az = msg.linear_acceleration.z

    def aruco_meas_callback(self, msg):
        if len(msg.poses)>0:
            for i in range (0,len(msg.poses)):
                self.aruco_id = msg.poses[i].aruco_id

                self.aruco_x = msg.poses[i].position.x
                self.aruco_y = msg.poses[i].position.y
                self.aruco_z = msg.poses[i].position.z

                self.aruco_phi = msg.poses[i].euler.x
                self.aruco_theta = msg.poses[i].euler.y
                self.aruco_psi = msg.poses[i].euler.z

                self.range = np.sqrt(self.aruco_x**2 + self.aruco_y**2 + self.aruco_z**2)
                self.bearing_2d = np.arctan2(self.aruco_x,self.aruco_z)#-self.truth_psi
                self.z = np.array([[self.range],[self.bearing_2d]])

                # if not (self.aruco_id == 110 or self.aruco_id == 111 or self.aruco_id == 112 or self.aruco_id == 107 or self.aruco_id == 108 or self.aruco_id == 109):
                # if self.aruco_id == 107 or self.aruco_id == 108 or self.aruco_id == 109:
                print "\nUpdate", self.aruco_id
                # print "range =", self.range
                # print "2D bear =", self.bearing_2d
                self.update()
                # if self.aruco_id == 107 or self.aruco_id == 108:
                #     print "107 Update"
                #     print "range =", self.range
                #     print "2D bear =", self.bearing_2d
                #     self.update()

##############################
#### Main Function to Run ####
##############################
if __name__ == '__main__':
    # Initialize Node
    rospy.init_node('slam_estimator')

    # init path_manager_base object
    estimator = ekf_slam()

    while not rospy.is_shutdown():
        rospy.spin()
