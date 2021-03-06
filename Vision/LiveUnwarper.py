#!/usr/bin/env python3
import glob

import copy

import cv2
import imutils
import numpy as np
import paho.mqtt.client as mqtt
import random
import math
import traceback
import time

import Vision.CamerasUnwarper
import Vision.firebase_interaction as fbi
from Vision import Gridify
from Vision.Finder import RobotFinder
from pathfinding.graph import getInstructionsFromGrid, is_bad

global robot_moving
robot_moving = False
global robot_rotating
robot_rotating = False
global global_robot_pos
global_robot_pos = None
global robot_angle
robot_angle = None
global robot_direction
robot_direction = None
global robot_target
robot_target = None
global expected_end_angle
expected_end_angle = None
global insts
insts = []
global square_length
square_length = None
global goal_pos
goal_pos = None
global search_graph
search_graph = None
global path
path = None
global cell_length
cell_length = 33
global shift_amount
shift_amount = 1
global reached_goal
reached_goal = False
global up_left_down_right
up_left_down_right = [None for i in range(8)]
global current_goal_number
current_goal_number = 0
global initial_dist_to_target
initial_dist_to_target = None
global connected
connected = False
global stopping_distance
stopping_distance = 16
global bad_node_ranges
bad_node_ranges = [((0, 100), (99, 124)), ((100, 320), (93, 130)), ((154, 182), (0, 93)),
                   ((98, 127), (124, 230))]  # Camera boundaires
bad_node_ranges += [((193, 245), (184, 236)), ((1, 32), (186, 230))]  # Overexposure as under light
bad_node_ranges = [((x1 - (stopping_distance * 1.5), x2 + (stopping_distance * 1.5)),
                    (y1 - (stopping_distance * 1.5), y2 + (stopping_distance * 1.5)))
                   for ((x1, x2), (y1, y2)) in bad_node_ranges]
global final_turn
final_turn = False
global start_graph
start_graph = None
global new_plant_goal
new_plant_goal = True
global plant_pos
plant_pos = None
global home
home = None
global going_home
going_home = False

# QA vars
global start_pos
start_pos = None
global original_goal
original_goal = None


def set_res(cap, x, y):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(x))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(y))
    return str(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), str(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))


def on_connect(client, userdata, flags, rc):
    global connected
    connected = True
    print("connected")
    client.subscribe("finish-instruction")
    client.subscribe("battery-update")
    client.subscribe("ping-pong")
    client.subscribe("navigate-start")


def on_disconnect(client, userdata, rc):
    global connected
    connected = False


def check_on_path(graph, to, frm_dec):
    print(1)
    try:
        global path
        global insts

    except Exception as e:
        print(e.message, e.args)
        sys.exit()
        raise


def count_diff_target(start_pos, robot_pos, robot_target):
    f = open("Vision/QAResults/diff_target.txt", "a")
    try:
        f.write(
            "%s %s %s (%s,%s)\n" % (
                start_pos, robot_pos, robot_target, robot_pos[0] - robot_target[0], robot_pos[1] - robot_target[1]))
        f.close()
    except:
        f.close()


def convert_orientation_inst_to_rotation(next_inst):
    global expected_end_angle
    if next_inst == "u":
        expected_end_angle = 0
    elif next_inst == "r":
        expected_end_angle = 90
    elif next_inst == "d":
        expected_end_angle = 180
    elif next_inst == "l":
        expected_end_angle = 270
    angle_to_turn = (expected_end_angle - robot_angle) % 360
    if angle_to_turn > 180:
        angle_to_turn -= 360
    next_inst = "r,%s" % round(angle_to_turn)
    return next_inst


def find_robot_dist_to_target(robot_pos, robot_target):
    global robot_direction
    dist_to_target = None
    # up
    if robot_direction == 0:
        dist_to_target = robot_pos[1] - robot_target[1]
    # right
    elif robot_direction == 1:
        dist_to_target = robot_target[0] - robot_pos[0]
    # down
    elif robot_direction == 2:
        dist_to_target = robot_target[1] - robot_pos[1]
    # left
    elif robot_direction == 3:
        dist_to_target = robot_pos[0] - robot_target[0]
    return dist_to_target


def burrow_out_graph(graph, frm):
    escape = False
    visited = []
    stack = [list(frm)]
    while not escape:
        curr_node = stack.pop(0)
        if graph[curr_node[1]][curr_node[0]] == 0:
            start_x = min(frm[0], curr_node[0])
            end_x = max(frm[0], curr_node[0])
            start_y = min(frm[1], curr_node[1])
            end_y = max(frm[1], curr_node[1])
            for y in range(start_y, end_y + 1):
                graph[y][end_x] = 0
            for x in range(start_x, end_x + 1):
                graph[end_y][x] = 0
            escape = True
            break
        else:
            visited.append(curr_node)
            deltas = [[0, -1], [-1, 0], [0, 1], [1, 0]]
            for delta in deltas:
                new_node = copy.copy(curr_node)
                new_node[0] -= delta[0]
                new_node[1] -= delta[1]
                if new_node[1] >= 0 and new_node[1] < len(graph) and new_node[0] >= 0 and \
                        new_node[0] < len(graph[0]) and new_node not in visited and new_node not in stack:
                    stack.append(new_node)
        if len(stack) == 0:
            print("NO ESCAPE!")
            break
    return graph


def find_closest_goal():
    global up_left_down_right
    global current_goal_number
    global goal_pos
    global global_robot_pos
    if global_robot_pos is not None and goal_pos in up_left_down_right:
        current_goal_number = 0
        new_plant_goal_pos = None
        goal_dist = float('inf')
        for i in range(len(up_left_down_right)):
            if up_left_down_right[i] is not None:
                local_goal_dist = math.sqrt(
                    (up_left_down_right[i][0] - global_robot_pos[0]) ** 2 + (
                            up_left_down_right[i][1] - global_robot_pos[1]) ** 2)
                if local_goal_dist < goal_dist:
                    current_goal_number = i
                    goal_dist = local_goal_dist
                    new_plant_goal_pos = up_left_down_right[i]
        if new_plant_goal_pos is not None:
            goal_pos = new_plant_goal_pos


def on_message(client, userdata, msg):
    global robot_moving
    global robot_rotating
    global robot_angle
    global expected_end_angle
    global robot_direction
    global robot_target
    global global_robot_pos
    global search_graph
    global goal_pos
    global path
    global insts
    global start_pos
    global original_goal
    global reached_goal
    global current_goal_number
    global initial_dist_to_target
    global final_turn
    global new_plant_goal
    global stopping_distance
    global plant_pos
    global home
    global going_home
    try:
        if msg.topic == "navigate-start":
            if msg.payload.decode() == "home":
                print("GOT HOME")
                goal_pos = home
                going_home = True
            else:
                goal_pos = tuple([float(i) for i in msg.payload.decode().split(",")])
                img_dims = [321, 231]
                goal_pos = [round(goal_pos[i] * img_dims[i]) for i in range(0, 2)]
                plant_pos = goal_pos
                new_plant_goal = True
                print("SET COORDINATE %s" % str(goal_pos))
        elif msg.topic == "finish-instruction":
            robot_was_moving = robot_moving
            robot_was_rotating = robot_rotating
            robot_moving = False
            robot_rotating = False
            if goal_pos is not None:
                # print("DISTANCE TO GOAL IS %s" % math.sqrt(
                #    (goal_pos[0] - global_robot_pos[0]) ** 2 + (goal_pos[1] - global_robot_pos[1]) ** 2))
                if math.sqrt((goal_pos[0] - global_robot_pos[0]) ** 2 + (goal_pos[1] - global_robot_pos[1]) ** 2) < 15:
                    insts = []
                    path = None
                    goal_pos = None
                    initial_dist_to_target = None
                    if going_home:
                        going_home = False
                        client.publish("navigate-finish", "DONE", qos=2)
                    else:
                        x = plant_pos[0] - global_robot_pos[0]
                        y = global_robot_pos[1] - plant_pos[1]
                        angle_to_turn = math.degrees(math.atan2(x, y))
                        angle_to_turn = (angle_to_turn - robot_angle) % 360
                        if angle_to_turn > 180:
                            angle_to_turn -= 360
                        print("TOLD TO FINAL TURN - r,%s" % round(angle_to_turn))
                        print("ROBOT ANGLE IS: %s, GOAL POS IS: %s, ROBOT POS IS: %s" % (
                            robot_angle, goal_pos, global_robot_pos))
                        robot_was_rotating = True
                        client.publish("start-instruction", "r,%s" % round(angle_to_turn), qos=2)
                        final_turn = True
                    return
            if robot_was_moving:
                initial_dist_to_target = None
                count_diff_target(start_pos, global_robot_pos, original_goal)
                closest = float('inf')
                # print(insts)
                grid_robot_pos = tuple([i / shift_amount for i in global_robot_pos])
                # print("SHAPE: (%s, %s)" % (len(search_graph), len(search_graph[0])))
                for node in path:
                    x, y = node.pos
                    # Add 0.5 as we want robot to be in centre of each square
                    if math.sqrt((x + 0.5 - grid_robot_pos[0]) ** 2 + (y + 0.5 - grid_robot_pos[1]) ** 2) < closest:
                        closest = abs(x - grid_robot_pos[0]) + abs(y - grid_robot_pos[1])
                # print(str(grid_robot_pos))
                # print("CLOSEST IS %s" % closest)
                frm = tuple([round(i) for i in grid_robot_pos])
                if closest > 6:
                    find_closest_goal()
                    if search_graph[frm[1]][frm[0]] == 1:
                        search_graph = burrow_out_graph(search_graph, frm)
                    if going_home and search_graph[goal_pos[1]][goal_pos[0]] == 1:
                        search_graph = burrow_out_graph(search_graph, goal_pos)
                    _, path, _, insts = getInstructionsFromGrid(search_graph, target=goal_pos, start=frm,
                                                                upside_down=True, bad_node_ranges=bad_node_ranges)

            if robot_was_rotating:
                time.sleep(1)
                angle_to_turn = (expected_end_angle - robot_angle) % 360
                if angle_to_turn > 180:
                    angle_to_turn -= 360
                if abs(round(angle_to_turn)) > 5:
                    robot_rotating = True
                    print("TOLD TO TURN %s" % round(angle_to_turn))
                    # print(insts)
                    client.publish("start-instruction", "%s,%s" % ("r", round(angle_to_turn)), qos=2)
                    return

            if final_turn:
                final_turn = False
                print("FINISHED FINAL TURN")
                client.publish("navigate-finish", "DONE", qos=2)
                # client.publish("close-navigate", "", qos=2)
                '''
                current_goal_number += 1
                while current_goal_number < 3 and up_left_down_right[current_goal_number] is None:
                    current_goal_number += 1
                if current_goal_number == 4:
                    reached_goal = True
                else:
                    print("SET GOAL TO %s" % current_goal_number)
                    goal_pos = up_left_down_right[current_goal_number]
                '''
                return

            # robot_direction = 0 if facing south, 1 if facing west, 2 if facing north, 3 if facing east
            robot_direction = round((int(robot_angle) % 360) / 90) % 4
            if len(insts) != 0:
                got_valid_inst = False
                next_inst = insts.pop(0)
                while not got_valid_inst:
                    if type(next_inst) is not tuple:
                        next_inst = convert_orientation_inst_to_rotation(next_inst)
                        if abs(int(next_inst.split(",")[1])) > 5:
                            robot_rotating = True
                            print("1. TOLD TO DO %s" % str(next_inst))
                            # print(insts)
                            client.publish("start-instruction", next_inst, qos=2)
                            got_valid_inst = True
                        else:
                            next_inst = insts.pop(0)
                    else:
                        if next_inst[0] == "m":
                            # print("pos: %s, square_length: %s" % (str(global_robot_pos), str(square_length)))
                            distance = next_inst[1] * square_length
                            robot_target = list(global_robot_pos)
                            # up
                            if robot_direction == 0:
                                robot_target[1] -= distance
                            # right
                            if robot_direction == 1:
                                robot_target[0] += distance
                            # down
                            if robot_direction == 2:
                                robot_target[1] += distance
                            # left
                            if robot_direction == 3:
                                robot_target[0] -= distance
                            robot_target = tuple(robot_target)
                            dist_to_target = find_robot_dist_to_target(global_robot_pos, robot_target)
                            if dist_to_target < 16:
                                next_inst = list(next_inst)
                                next_inst.append("%.2f" % ((dist_to_target / 2) / stopping_distance))
                                next_inst = tuple(next_inst)
                            robot_moving = True
                        if next_inst[0] == "r":
                            expected_end_angle = robot_angle + next_inst[1]
                            robot_rotating = True
                        start_pos = global_robot_pos
                        original_goal = robot_target
                        print("2. TOLD TO DO %s" % str(next_inst))
                        # print(insts)
                        if len(next_inst) == 2:
                            client.publish("start-instruction", "%s,%s" % next_inst, qos=2)
                        elif len(next_inst) == 3:
                            client.publish("start-instruction", "%s,%s,%s" % next_inst, qos=2)
                        got_valid_inst = True
                # print("INSTRUCTIONS REMAINING %s" % str(insts))

    except:
        print("Error")
        traceback.print_exc()
        sys.exit()
    if (msg.topic == "battery-update"):
        print("sending battery update to firebase")
        # decode status and send it to db using fbi method
        new_battery_status = msg.payload.decode()
        fbi.update_battery_status_in_db(new_battery_status)


print("ON MESSAGE FINISHED")


class Unwarper:

    def __init__(self):
        # Note for cameras 3 and 4 we use the calibration matrices of camera 1, this is because the calibration matrix
        # produced for it actually performed better than those trained for cameras 3 and 4
        self.mtxs = np.load("Vision/mtxs.npy")
        self.mtxs[2] = self.mtxs[0]
        self.mtxs[3] = self.mtxs[0]
        self.dists = np.load("Vision/dists.npy")
        self.dists[2] = self.dists[0]
        self.dists[3] = self.dists[0]
        self.H_c1_and_c2 = np.load("Vision/H_c1_and_c2.npy")
        self.stitcher = Stitcher()
        self.errors = self.where_error(
            [(np.load("Vision/lhs_adj_errors.npy"), [125, 7]), (np.load("Vision/rhs_adj_errors.npy"), [104, 140])])
        self.robot_finder = RobotFinder()

        self.mqtt = mqtt.Client("PathCommunicator")
        self.mqtt.on_connect = on_connect
        self.mqtt.on_disconnect = on_disconnect
        self.mqtt.on_message = on_message
        self.mqtt.connect("129.215.3.65")
        self.mqtt.loop_start()
        self.overhead_image = None
        self.overlap_area = None

        # TESTING VARIABLES
        self.visibility = []

    def get_overhead_image(self):
        return self.overhead_image

    # Give a numpy array of erroneous pixels, return the location of pixels adjacent to them
    # error_descriptions is a list of tuples, the first element of each tuple should be another tuple in the format
    # output by np.where, the second argument of each tuple should be a list containing [y,x] where each corresponds to the
    # arguments in np.where(arr[y:i,x:j==some_condition)

    def where_error(self, error_descritpions):
        # Find the locations of the errors in the image
        errors = []
        if type(error_descritpions) != list:
            error_descritpions = list(error_descritpions)
        for error_descritpion in error_descritpions:
            relative_y_pos = error_descritpion[1][0]
            relative_x_pos = error_descritpion[1][1]
            error_array = error_descritpion[0]
            for i in range(0, error_array[0].shape[0], 3):
                errors.append((int(error_array[0][i]) + relative_y_pos, int(error_array[1][i]) + relative_x_pos))
        # Create a list of the pixels adjacent to the errors
        adjacent_to_error = []
        for error in errors:
            for i in [error[0] - 1, error[0] + 1]:
                for j in [error[1] - 1, error[1] + 1]:
                    if (i, j) not in errors and (i, j) not in adjacent_to_error:
                        adjacent_to_error.append((i, j))
        errors += adjacent_to_error
        # Convert the errors and pixels adjacent back into a list of coordinates we can use to address them by index
        x_errors = []
        y_errors = []
        z_errors = []
        for error in errors:
            for z in range(0, 3):
                x_errors.append(error[0])
                y_errors.append(error[1])
                z_errors.append(z)
        return np.array(x_errors), np.array(y_errors), np.array(z_errors)

    # Take CCTV view and unwarp each camera, returning result, if only_camera is set to 0,1,2, or 3, it will unwarp only
    # the respective camera
    def unwarp_image(self, original_img, only_camera=None):
        if only_camera is not None:

            img = Vision.CamerasUnwarper.getImgRegionByCameraNo(original_img, only_camera)

            h, w = img.shape[:2]
            newcameramtx, _ = cv2.getOptimalNewCameraMatrix(self.mtxs[only_camera - 1], self.dists[only_camera - 1],
                                                            (w, h), 1,
                                                            (w, h))
            dst = cv2.undistort(img, self.mtxs[only_camera - 1], self.dists[only_camera - 1], None, newcameramtx)
            return dst
            # cv2.imshow("origin", img)
            # cv2.imshow("processed", img_thresh)
            # cv2.waitKey(1)
        else:
            for camera_no in range(0, 4):
                img = Vision.CamerasUnwarper.getImgRegionByCameraNo(original_img, camera_no + 1)
                h, w = img.shape[:2]
                newcameramtx, _ = cv2.getOptimalNewCameraMatrix(self.mtxs[camera_no], self.dists[camera_no], (w, h), 1,
                                                                (w, h))
                dst = cv2.undistort(img, self.mtxs[camera_no], self.dists[camera_no], None, newcameramtx)
                if camera_no == 0:
                    dsts = dst
                elif camera_no == 1:
                    dsts = np.concatenate((dsts, dst), axis=1)
                elif camera_no == 2:
                    dsts2 = dst
                elif camera_no == 3:
                    dsts2 = np.concatenate((dsts2, dst), axis=1)
                    dsts = np.concatenate((dsts, dsts2), axis=0)
            return dsts

    def determine_new_path(self, graph, to, frm):
        global insts
        global path
        global robot_rotating
        global robot_moving
        global robot_target
        global stopping_distance
        if goal_pos is not None:
            find_closest_goal()
            if graph[frm[1]][frm[0]] == 1:
                graph = burrow_out_graph(graph, frm)
            if going_home and graph[to[1]][to[0]] == 1:
                graph = burrow_out_graph(graph, goal_pos)
            _, path, _, insts = getInstructionsFromGrid(graph, target=goal_pos, start=frm, upside_down=True,
                                                        bad_node_ranges=bad_node_ranges)
            if not robot_rotating and not robot_moving and insts != []:
                next_inst = insts.pop(0)
                next_inst = convert_orientation_inst_to_rotation(next_inst)
                if abs(int(next_inst.split(",")[1])) > 5:
                    print("3. TOLD TO DO %s" % str(next_inst))
                    # print(insts)
                    self.mqtt.publish("start-instruction", next_inst, qos=2)
                    robot_rotating = True
                else:
                    next_inst = insts.pop(0)
                    distance = next_inst[1] * square_length
                    robot_target = list(global_robot_pos)
                    # up
                    if robot_direction == 0:
                        robot_target[1] -= distance
                    # right
                    if robot_direction == 1:
                        robot_target[0] += distance
                    # down
                    if robot_direction == 2:
                        robot_target[1] += distance
                    # left
                    if robot_direction == 3:
                        robot_target[0] -= distance
                    robot_target = tuple(robot_target)
                    robot_moving = True
                    dist_to_target = find_robot_dist_to_target(global_robot_pos, robot_target)
                    if dist_to_target is not None:
                        if dist_to_target < 16:
                            next_inst = list(next_inst)
                            next_inst.append("%.2f" % ((dist_to_target / 2) / stopping_distance))
                            next_inst = tuple(next_inst)
                        print("4. TOLD TO DO %s" % str(next_inst))
                        # print(insts)
                        if len(next_inst) == 2:
                            self.mqtt.publish("start-instruction", "%s,%s" % next_inst, qos=2)
                        elif len(next_inst) == 3:
                            self.mqtt.publish("start-instruction", "%s,%s,%s" % next_inst, qos=2)

    def check_robot_at_target(self, robot_pos, local_robot_angle):
        global robot_target
        global robot_moving
        global robot_direction
        global robot_rotating
        global square_length
        global insts
        global path
        global initial_dist_to_target
        # Check if robot at target
        if robot_moving and robot_pos[0] is not None and robot_pos[1] is not None and robot_direction is not None:
            dist_to_target = find_robot_dist_to_target(robot_pos, robot_target)
            if initial_dist_to_target is None:
                initial_dist_to_target = dist_to_target
                # if initial_dist_to_target < stopping_distance:
                #    print("WILL GO %s" % stopping_distance)
                # else:
                #    print("WILL GO %s" % (initial_dist_to_target / 2))
            # print("DIST TO TARGET IS %s" % dist_to_target)
            if (initial_dist_to_target >= stopping_distance and dist_to_target < stopping_distance) or (
                    initial_dist_to_target < stopping_distance and dist_to_target < (initial_dist_to_target / 2)):
                self.mqtt.publish("start-instruction", "s", qos=2)
        # Check if robot deviated from path
        if robot_moving and robot_pos[0] is not None and robot_pos[1] is not None and local_robot_angle is not None:
            closest = float('inf')
            grid_robot_pos = tuple([i / shift_amount for i in robot_pos])
            for node in path:
                x, y = node.pos
                # Add 0.5 as we want robot to be in centre of each square
                if math.sqrt((x + 0.5 - grid_robot_pos[0]) ** 2 + (y + 0.5 - grid_robot_pos[1]) ** 2) < closest:
                    closest = math.sqrt((x + 0.5 - grid_robot_pos[0]) ** 2 + (y + 0.5 - grid_robot_pos[1]) ** 2)
            if closest > 6 and not is_bad(tuple([round(i) for i in grid_robot_pos]), bad_node_ranges):
                self.mqtt.publish("start-instruction", "s", qos=2)

    def set_random_target(self, robot_pos):
        global goal_pos
        global search_graph
        # possible_goals = [(x, y) for x in range(30, len(search_graph[0])) for y in range(30, len(search_graph))]
        possible_goals = [(136, 44), (166, 209), (45, 179), (286, 75), (277, 194), (209, 158), (41, 109)]
        goal_pos = random.choice(possible_goals)
        self.determine_new_path(search_graph, goal_pos, tuple([round(i) for i in robot_pos]))

    def count_visibility(self, visible):
        if visible:
            self.visibility.append(1)
        else:
            self.visibility.append(0)
        if len(self.visibility) == 100:
            count = sum(self.visibility)
            # Writes out of the last 100 frames the number of times how many of them the spot was visible
            f = open("Vision/QAResults/spot_visibility_count_out_of_100.txt", "a")
            try:
                f.write("%s\n" % count)
                f.close()
            except:
                f.close()
            self.visibility = []

    def find_path(self, graph, to, frm_dec):
        global insts
        global path
        global search_graph
        global global_robot_pos
        if frm_dec[0] is not None:
            if path is None and robot_angle is not None and not reached_goal:
                self.determine_new_path(graph, to, tuple([round(i) for i in frm_dec]))

    def find_nearest_free_cells(self, search_graphs, robot_pos):
        global up_left_down_right
        global current_goal_number
        global goal_pos
        global reached_goal
        delta = [[0, -1], [-1, -1], [-1, 0], [-1, 1], [0, 1], [1, 1], [1, 0], [1, -1]]
        up_left_down_right = [list(goal_pos) for x in range(len(delta))]
        found = [False for x in range(len(delta))]
        while not all(found):
            for i in range(len(found)):
                if not found[i]:
                    up_left_down_right[i][0] += delta[i][0]
                    up_left_down_right[i][1] += delta[i][1]
                    # If out of bounds there is no empty square to the left/right/up/down of the goal
                    if up_left_down_right[i][1] < 0 or up_left_down_right[i][1] >= len(search_graph) or \
                            up_left_down_right[i][0] < 0 or up_left_down_right[i][0] >= len(search_graph[0]):
                        up_left_down_right[i] = None
                        found[i] = True
                    else:
                        local_goal = tuple(up_left_down_right[i])
                        if math.sqrt((local_goal[0] - goal_pos[0]) ** 2 + (local_goal[1] - goal_pos[1]) ** 2) > 40:
                            up_left_down_right[i] = None
                            found[i] = True
                        # If the cell is empty then this is the closest we can reach to the left/right/up/down of the goal
                        elif search_graph[local_goal[1]][local_goal[0]] == 0:
                            find_closest_goal()
                            if search_graphs[i][robot_pos[1]][robot_pos[0]] == 1:
                                search_graphs[i] = burrow_out_graph(search_graphs[i], robot_pos)
                            if going_home and search_graphs[i][to[1]][to[0]] == 1:
                                search_graphs[i] = burrow_out_graph(search_graphs[i], local_goal)
                            _, path, _, _ = getInstructionsFromGrid(search_graphs[i], target=local_goal,
                                                                    start=robot_pos,
                                                                    upside_down=True, bad_node_ranges=bad_node_ranges)
                            if path is not None:
                                up_left_down_right[i] = tuple(up_left_down_right[i])
                                found[i] = True
                            else:
                                up_left_down_right[i] = None
                                found[i] = True
        current_goal_number = 0
        new_plant_goal_pos = None
        goal_dist = float('inf')
        for i in range(len(up_left_down_right)):
            if up_left_down_right[i] is not None:
                local_goal_dist = math.sqrt(
                    (up_left_down_right[i][0] - robot_pos[0]) ** 2 + (up_left_down_right[i][1] - robot_pos[1]) ** 2)
                if local_goal_dist < goal_dist:
                    current_goal_number = i
                    goal_dist = local_goal_dist
                    new_plant_goal_pos = up_left_down_right[i]
        if new_plant_goal_pos is not None:
            goal_pos = new_plant_goal_pos
            print("FOUND SIDES AT %s" % str(up_left_down_right))
        if goal_pos is None and current_goal_number == len(up_left_down_right) - 1:
            reached_goal = True

    # Unwarp all 4 cameras and merge them into a single image in real time

    def live_unwarp(self):
        try:
            global goal_pos
            global search_graph
            global global_robot_pos
            global robot_angle
            global new_plant_goal
            global start_graph
            global home
            count = 6
            # goal_pos = (272, 34) #UNCOMMENT FOR TESTING ONLY
            cam = cv2.VideoCapture(0)
            set_res(cam, 1920, 1080)
            i = 1
            visible = 0
            global square_length
            square_length = shift_amount
            first_iteration = True
            first_robot_seen = True
            start_thresh_merged_img = None
            while True:  # not reached_goal:
                _, img = cam.read()
                if i > 20:
                    # unwarp_img = self.unwarp_image(img)
                    merged_img = self.stitch_one_two_three_and_four(img)
                    self.overhead_image = merged_img
                    thresh_merged_img = self.stitch_one_two_three_and_four(img, thresh=True)
                    if merged_img is not None:
                        cv2.imshow('1. raw', cv2.resize(img, (0, 0), fx=0.33, fy=0.33))
                        # cv2.imshow('1.5. unwarped', cv2.resize(unwarp_img, (0, 0), fx=0.5, fy=0.5))
                        cv2.imshow('2. merged', merged_img)
                        robot_pos_dec, local_robot_angle = self.robot_finder.find_robot(merged_img)
                        if local_robot_angle is not None:
                            robot_angle = local_robot_angle
                        if robot_pos_dec[0] is not None and robot_pos_dec[1] is not None:
                            global_robot_pos = robot_pos_dec
                            if home is None:
                                home = tuple([round(i) for i in robot_pos_dec])
                                print("HOME IS %s" % str(home))
                        if global_robot_pos is not None:
                            lower_i = max(round(global_robot_pos[1] - 24), 0)
                            upper_i = round(global_robot_pos[1] + 24)
                            lower_j = max(round(global_robot_pos[0] - 24), 0)
                            upper_j = round(global_robot_pos[0] + 24)
                            thresh_merged_img[lower_i:upper_i, lower_j:upper_j, :] = np.zeros(
                                thresh_merged_img[lower_i:upper_i, lower_j:upper_j, :].shape, dtype=np.uint8)
                            if first_robot_seen:
                                start_thresh_merged_img = copy.deepcopy(thresh_merged_img)
                                first_robot_seen = False

                        if start_thresh_merged_img is not None:
                            thresh_merged_img = start_thresh_merged_img + thresh_merged_img
                            thresh_merged_img[thresh_merged_img > 255] = 255
                        cv2.imshow('3. edges', thresh_merged_img)
                        object_graph = Gridify.convert_thresh_to_map(thresh_merged_img, shift_amount=shift_amount,
                                                                     cell_length=cell_length,
                                                                     visualize=True)
                        search_graph = Gridify.convert_thresh_to_map(thresh_merged_img, shift_amount=shift_amount,
                                                                     cell_length=cell_length)
                        search_graph_copy = Gridify.convert_thresh_to_map(thresh_merged_img, shift_amount=shift_amount,
                                                                          cell_length=cell_length)
                        if robot_pos_dec[0] is not None and robot_pos_dec[1] is not None:
                            if new_plant_goal and not first_iteration and goal_pos is not None:
                                search_graphs = [
                                    Gridify.convert_thresh_to_map(thresh_merged_img, shift_amount=shift_amount,
                                                                  cell_length=cell_length) for x in range(8)]
                                self.find_nearest_free_cells(search_graphs,
                                                             tuple([round(i / shift_amount) for i in robot_pos_dec]))
                                if up_left_down_right[current_goal_number] is not None:
                                    new_plant_goal = False
                        self.count_visibility(robot_pos_dec[0] is not None)
                        self.check_robot_at_target(robot_pos_dec, local_robot_angle)
                        if robot_pos_dec[0] is not None:
                            robot_pos_dec = tuple([i / shift_amount for i in robot_pos_dec])
                            robot_pos = tuple([round(i) for i in robot_pos_dec])

                            object_graph[robot_pos[1] - 3:robot_pos[1] + 3,
                            robot_pos[0] - 3:robot_pos[0] + 3] = np.array(
                                [0, 0, 255], dtype=np.uint8)
                            object_graph[robot_pos[1], robot_pos[0]] = np.array([0, 0, 0], dtype=np.uint8)
                            self.find_path(search_graph, goal_pos, robot_pos_dec)

                        cv2.imshow("4. object graph", np.array(search_graph_copy, dtype=np.uint8) * 255)
                        if path is not None:
                            for node in path:
                                x, y = node.pos
                                object_graph[y][x] = np.array([255, 0, 0], dtype=np.uint8)
                            if path is not None:
                                if len(path) != 0:
                                    object_graph[y][x] = np.array([0, 255, 0], dtype=np.uint8)
                        cv2.imshow('5. navigation graph', object_graph)  # cv2.resize(object_graph, (0, 0), fx=6, fy=6))
                        if cv2.waitKey(1) == 48:
                            cv2.imwrite("Vision/record_output/%s.jpg" % count, merged_img)
                            count += 1
                        if first_iteration:
                            fbi.start_script(self)
                            first_iteration = False
                i += 1
        except:
            if connected:
                self.mqtt.publish("ping-pong", "crashed", qos=2)
            traceback.print_exc()

    def static_unwarp(self, photo_path="Vision/Calibrated Pictures/*.jpg"):
        images = glob.glob(photo_path)

        for fname in images:
            img = cv2.imread(fname)
            unwarp_img = self.unwarp_image(img)
            merged_img = self.stitch_one_two_three_and_four(img)
            thresh_merged_img = self.stitch_one_two_three_and_four(img, thresh=True)
            grid = Gridify.convert_thresh_to_map(thresh_merged_img)
            if merged_img is not None:
                cv2.imshow('1. raw', cv2.resize(img, (0, 0), fx=0.33, fy=0.33))
                cv2.imshow('2. unwarped', cv2.resize(unwarp_img, (0, 0), fx=0.5, fy=0.5))
                cv2.imshow('3. merged', merged_img)
                cv2.imshow('4. edges', thresh_merged_img)
                cv2.waitKey()

    def camera_one_segment(self, original_img):
        unwarped_camera = self.unwarp_image(original_img, 1)
        x_lower_bound = 360
        x_upper_bound = 540
        y_lower_bound = 120
        y_upper_bound = 255
        segment = unwarped_camera[y_lower_bound:y_upper_bound, x_lower_bound:x_upper_bound]
        return segment

    def camera_two_segment(self, original_img):
        unwarped_camera = self.unwarp_image(original_img, 2)
        x_lower_bound = 25
        x_upper_bound = 400
        y_lower_bound = 200
        y_upper_bound = 390
        segment = unwarped_camera[y_lower_bound:y_upper_bound, x_lower_bound:x_upper_bound]
        return segment

    def stitch_one_and_two(self, img, thresh=False):
        img_1 = self.camera_one_segment(img)
        img_2 = self.camera_two_segment(img)
        new_img = self.stitcher.stitch((img_1, img_2), self.H_c1_and_c2, thresh=thresh)
        return new_img

    def camera_three_segment(self, original_img):
        unwarped_camera = self.unwarp_image(original_img, 3)
        x_lower_bound = 379
        x_upper_bound = 492
        y_lower_bound = 90
        y_upper_bound = 210
        segment = unwarped_camera[y_lower_bound:y_upper_bound, x_lower_bound:x_upper_bound]
        return segment

    def camera_four_segment(self, original_img):
        unwarped_camera = self.unwarp_image(original_img, 4)
        x_lower_bound = 275
        x_upper_bound = 505
        y_lower_bound = 78
        y_upper_bound = 211
        segment = unwarped_camera[y_lower_bound:y_upper_bound, x_lower_bound:x_upper_bound]
        return segment

    def stich_three_and_four(self, img, thresh=False):
        img_1 = self.camera_three_segment(img)
        img_2 = self.camera_four_segment(img)
        img_2 = cv2.resize(img_2, (0, 0), fx=0.903846154, fy=0.903846154)
        if thresh:
            img_1 = cv2.cvtColor(cv2.Canny(img_1, 100, 255), cv2.COLOR_GRAY2RGB)
            img_2 = cv2.cvtColor(cv2.Canny(img_2, 100, 255), cv2.COLOR_GRAY2RGB)
        img_1 = np.concatenate(
            (np.zeros((img_2.shape[0] - img_1.shape[0], img_1.shape[1], 3), dtype=np.uint8), img_1), axis=0)
        new_img = np.concatenate((img_1, img_2), axis=1)
        return new_img

    def stitch_one_two_three_and_four(self, img, thresh=False):
        # Get the top of the image
        img_1 = self.stitch_one_and_two(img, thresh=thresh)
        # Take a portion of top image to line walls up with bottom one
        img_1 = img_1[:, 13:326, :]
        # Get the bottom of the image
        img_2 = self.stich_three_and_four(img, thresh=thresh)
        # Add to the width of top image to make it the same width as the bottom one
        img_1 = np.concatenate(
            (img_1, np.zeros((img_1.shape[0], img_2.shape[1] - img_1.shape[1], 3), dtype=np.uint8)), axis=1)
        # Overlap between top and bottom image, so we say we want the bottom one to overlap the top one by 45 pixels
        amount_to_move_bottom_img_up = 45
        # Create a copy of the bottom image with it aligned to its desired new position, set space which top image will take up as black
        img_2_merge_canvas = np.zeros(
            (img_1.shape[0] + img_2.shape[0] - amount_to_move_bottom_img_up, img_2.shape[1], 3), dtype=np.uint8)
        img_2_merge_canvas[img_1.shape[0] - amount_to_move_bottom_img_up:
                           img_1.shape[0] + img_2.shape[0] - amount_to_move_bottom_img_up, :, :] = img_2
        # Add to the top image space for the non-overlapping part of the bottom image
        img_1 = np.concatenate(
            (img_1, np.zeros((img_2.shape[0] - amount_to_move_bottom_img_up, img_1.shape[1], 3), dtype=np.uint8)),
            axis=0)
        # For all pixels in the top image that will be overlapped by the bottom image, we set their value to 0
        if not thresh or self.overlap_area is None:
            self.overlap_area = np.where(img_2_merge_canvas != [0, 0, 0])
            if thresh:
                print("WARNING: self.overlap_area undefined, this is likely due to not merging the colour image first")
        img_1[self.overlap_area] = np.zeros(img_1.shape, dtype=np.uint8)[self.overlap_area]
        # New top and bottom image are then the same size, and each respective pixel is black in one image, and the desired colour
        # in the other, meaning we can just add the matrices values and return the result for our merged image
        img_1 += img_2_merge_canvas

        if thresh:
            # Canny edge detection detects the edge of the images as edges, which can lead to false positives for objects
            # in the vision system. To get around this we recorded the errenous pixels positions in one frame. We then marked
            # all adjacent pixels to this errenous pixtures as well (as the errors can move around slightly). self.errors
            # lists the positions of all these pixels, and we set them to black to get rid of the false positives.
            img_1[self.errors] = np.uint8(0)
            # There were a few pixels that were still errenously white after the postprocessing above, so we manual
            # set these to black
            img_1[132, 67] = np.array([0, 0, 0], dtype=np.uint8)
            img_1[133, 87] = np.array([0, 0, 0], dtype=np.uint8)
            img_1[134, 88] = np.array([0, 0, 0], dtype=np.uint8)

        return img_1


# The stitcher class is a varitation of the one found in the tutorial here https://www.pyimagesearch.com/2016/01/11/opencv-panorama-stitching/

class Stitcher:
    def __init__(self):
        # determine if we are using OpenCV v3.X
        self.isv3 = imutils.is_cv3()

    def find_h(self, images, ratio=0.75, reprojThresh=4.0):
        (imageB, imageA) = images
        # unpack the images, then detect keypoints and extract
        # local invariant descriptors from them
        (kpsA, featuresA) = self.detectAndDescribe(imageA)
        (kpsB, featuresB) = self.detectAndDescribe(imageB)

        # match features between the two images
        M = self.matchKeypoints(kpsA, kpsB,
                                featuresA, featuresB, ratio, reprojThresh)

        # if the match is None, then there aren't enough matched
        # keypoints to create a panorama
        if M is None:
            return None, None
        # otherwise, apply a perspective warp to stitch the images
        # together
        (matches, H, status) = M

        if H is None:
            return None, None

        return (self.stitch(images, H), H)

    def stitch(self, images, H, thresh=False):
        (imageB, imageA) = images

        result = cv2.warpPerspective(imageA, H,
                                     (imageA.shape[1] + imageB.shape[1], imageA.shape[0]))

        if thresh:
            result = cv2.cvtColor(cv2.Canny(result, 100, 255), cv2.COLOR_GRAY2RGB)
            imageB = cv2.cvtColor(cv2.Canny(imageB, 100, 255), cv2.COLOR_GRAY2RGB)

        result[0:imageB.shape[0], 0:imageB.shape[1]] = imageB

        # return the stitched image
        return result

    def detectAndDescribe(self, image):
        # convert the image to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # check to see if we are using OpenCV 3.X
        if self.isv3:
            # detect and extract features from the image
            descriptor = cv2.xfeatures2d.SIFT_create()
            (kps, features) = descriptor.detectAndCompute(image, None)

        # otherwise, we are using OpenCV 2.4.X
        else:
            # detect keypoints in the image
            detector = cv2.FeatureDetector_create("SIFT")
            kps = detector.detect(gray)

            # extract features from the image
            extractor = cv2.DescriptorExtractor_create("SIFT")
            (kps, features) = extractor.compute(gray, kps)

        # convert the keypoints from KeyPoint objects to NumPy
        # arrays
        kps = np.float32([kp.pt for kp in kps])

        # return a tuple of keypoints and features
        return (kps, features)

    def matchKeypoints(self, kpsA, kpsB, featuresA, featuresB,
                       ratio, reprojThresh):
        # compute the raw matches and initialize the list of actual
        # matches
        matcher = cv2.DescriptorMatcher_create("BruteForce")
        rawMatches = matcher.knnMatch(featuresA, featuresB, 2)
        matches = []

        # loop over the raw matches
        for m in rawMatches:
            # ensure the distance is within a certain ratio of each
            # other (i.e. Lowe's ratio test)
            if len(m) == 2 and m[0].distance < m[1].distance * ratio:
                matches.append((m[0].trainIdx, m[0].queryIdx))
        # computing a homography requires at least 4 matches
        if len(matches) > 4:
            # construct the two sets of points
            ptsA = np.float32([kpsA[i] for (_, i) in matches])
            ptsB = np.float32([kpsB[i] for (i, _) in matches])

            # compute the homography between the two sets of points
            (H, status) = cv2.findHomography(ptsA, ptsB, cv2.RANSAC,
                                             reprojThresh)

            # return the matches along with the homograpy matrix
            # and status of each matched point
            return (matches, H, status)

        # otherwise, no homograpy could be computed
        return None

    def drawMatches(self, imageA, imageB, kpsA, kpsB, matches, status):
        # initialize the output visualization image
        (hA, wA) = imageA.shape[:2]
        (hB, wB) = imageB.shape[:2]
        vis = np.zeros((max(hA, hB), wA + wB, 3), dtype="uint8")
        vis[0:hA, 0:wA] = imageA
        vis[0:hB, wA:] = imageB

        # loop over the matches
        for ((trainIdx, queryIdx), s) in zip(matches, status):
            # only process the match if the keypoint was successfully
            # matched
            if s == 1:
                # draw the match
                ptA = (int(kpsA[queryIdx][0]), int(kpsA[queryIdx][1]))
                ptB = (int(kpsB[trainIdx][0]) + wA, int(kpsB[trainIdx][1]))
                cv2.line(vis, ptA, ptB, (0, 255, 0), 1)

        # return the visualization
        return vis
