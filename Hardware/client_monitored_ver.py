import movement_monitored_ver
import paho.mqtt.client as mqtt
import sys
import ev3dev.ev3 as ev3
import math
import time

def onConnect(client,userdata,flags,rc):
    print("connected with result code %i" % rc)
    client.subscribe("instructions")
    client.subscribe("pos")
    ev3.Sound.speak("connected")

def onMessage(client,userdata,msg):
    try:
        print("Received message with payload:%s "%(msg.payload.decode()))

        if msg.topic=="start-instruction":
            # single instruction:
            # - face direction, start moving, stop moving, or rotate
            instruction_to_follow = msg.payload.decode().strip()
            follow_one_instruction(instruction_to_follow)
    except:
        # catch any errors to stop alertless crashing
        print("Error")
        print(sys.exc_info()[0])
        sys.exit()
        raise

def follow_one_instruction(instruction_as_string):
    print("about to follow instruction: %s"%instruction_as_string)
    if currently_moving:
        # stop (moving) instruction
        if instruction_as_string=='s':
            currently_moving = False
            movement_controller.stop()
            ask_for_next_inst(movement_controller.angle)
        else:
            print("useless instruction: %s"%instruction_as_string)
    else:
        # fresh instruction / not a stop instruction

        # absolute turn instructions ( first inst received)
        if instruction_as_string=='u':
            movement_controller.absolute_turn(0)
        elif instruction_as_string=='r':
            movement_controller.absolute_turn(90)
        elif instruction_as_string=='d':
            movement_controller.absolute_turn(180)
        elif instruction_as_string=='l':
            movement_controller.absolute_turn(270)

        # movement / relative turn instructions (subsequent insts)
        else:
            # tuple received is either 'u','d','l','r', or 
            # in form (r,[degrees]), or (m,[squares])
            # note the number of squares is unused for the main navigation
            (inst_type,inst_val) = tuple(instruction_as_string.split(","))
            if inst_type=='m':
                currently_moving=True
                movement_controller.forward_forever()
            elif inst_type=='r':
                currently_moving = True
                movement_controller.relative_turn(inst_val)
                ask_for_next_inst(movement_controller.angle)
            else:
                print("received a malformed instruction!: %s"%instruction_as_string)

def ask_for_next_inst(current_angle):
    client.publish("finish-instruction",str(current_angle))

# set up client & client functions
global client
client=mqtt.Client("ev3")
client.on_connect=onConnect
client.on_message=onMessage

# if this is true, robot is waiting for a stop instruction from vision
global currently_moving
currently_moving = False

# movement object, with initial angle of 0
global movement_controller
movement_controller = movement_monitored_ver.Movement(0)

#connect client and make it wait for inputs
client.connect("129.215.202.200")
client.loop_forever()

################
# robot has three states: 
# -- moving - waiting to be told to stop
# -- rotating - using gyro to track whether it's finished
# -- waiting - ready to receive a fresh instruction
################