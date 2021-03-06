import movement_monitored_ver
import paho.mqtt.client as mqtt
import sys
import ev3dev.ev3 as ev3
import math
import time
from threading import Timer
import ips
import traceback
global currently_moving
global client
global movement_controller

def onConnect(client,userdata,flags,rc):
    print("connected with result code %i" % rc)
    client.subscribe("start-instruction")
    client.subscribe("pi-start-instruction")
    client.subscribe("arm")
    client.subscribe("ping-pong")
    client.subscribe("sonar-creeping")

    ###garbage###
    ev3.Sound.speak("EDEN")
    #############

def on_disconnect(client,userdata,rc):
    print("DISCONNECTED FROM MQTT")
    ev3.sound.speak("disconnected")
    # we've disconnected so tell the robot to stop
    follow_one_instruction("s")

def onMessage(client,userdata,msg):
    try:
        if msg.topic=="start-instruction":
            # single instruction:
            # - start moving, stop moving, or rotate
            instruction_to_follow = msg.payload.decode().strip()
            follow_one_instruction(instruction_to_follow)
        if msg.topic=="arm":
            movement_controller.arm_to_pos(float(msg.payload.decode()))
        if msg.topic=="ping-pong":
            pl = msg.payload.decode()
            if pl=="pong":
                global received_pong
                print("pong")
                # update global var received_pong for check_for_pong()
                received_pong = True
            elif pl=="crashed":
                print("vision system says it's dead")
                on_vision_death()
            else:
                print("useless pong: %s"%pl)
        if msg.topic=="sonar-creeping":
            print("creeping")
            sonar_based_creeping()
            print("crept")
            ev3.Sound.speak("woooosshhhhhhhhhhhh")
            time.sleep(3)
            follow_one_instruction("-m",self_stop=True)
            #movement_controller.arm_to_pos(-50)
            client.publish("plant-watered","done",qos=2)
            print("finished end sequence!")
        if msg.topic=="pi-start-instruction":
            instruction_to_follow = msg.payload.decode().strip()
            follow_one_instruction(instruction_to_follow, local = True)

    except:
        # catch any errors to stop alertless crashing
        print("Error")
        traceback.print_exc()
        sys.exit()
        
# special sonar method to get very close to something
def detect_pot(prev_sonar_vals, prev_min_sonar_pos):

    # we will only act if local sys hasn't told us to stop
    if not detect_pot_interrupted:    

        new_sonar_vals = movement_controller.sonar_value()

        # first compare previous smallest sonar val with it's new val
        # if this val was <50 and is now >1000 we're probably too close
        if prev_sonar_vals[prev_min_sonar_pos] <50 and new_sonar_vals[prev_min_sonar_pos] > 1000:
            # the old closest sonar is likely now too close, we've reached the pot!
    
            # stop moving and signal we've arrived
            follow_one_instruction("s", local=True)
        else:
            # not met success condition, so just keep measuring, and send an update
            # to local system about which val was smallest and what it was

            new_min_sonar_val = find_pos_of_min_val(new_sonar_vals)

            ### publish pos of val and it's val

            # check again in 0.1 seconds
            Timer(0.1,detect_pot,[new_sonar_vals, new_min_sonar_val]).start()

def find_pos_of_min_val(list_of_vals):
    if len(list_of_vals)<2:
        return 0
    else:
        min_pos = 0
        min_val = list_of_vals[0]

        for i in range(1,len(list_of_vals)):
            if list_of_vals[i]<min_val:
                min_val = list_of_vals[i]
                min_pos = i
        
        return min_pos

# generic instruction following
def follow_one_instruction(instruction_as_string, self_stop=False, local=False):
    print("about to follow instruction: %s"%instruction_as_string)
    global currently_moving
    global currently_pinging
    global polling_sonar

    if currently_moving:
        # stop (moving) instruction
        if instruction_as_string=='s':
            # not moving, pinging, or checking sonar  anymore
            currently_moving = False
            currently_pinging = -1
            polling_sonar = False
            movement_controller.stop()
            if not self_stop:
                #request next instruction in path only when stopped 
                # by vision system - not on a self-stop
                ask_for_next_inst(local)
        else:
            print("useless instruction: %s"%instruction_as_string)
    else:
        # fresh instructions

        if instruction_as_string == 's':
            # received a stop when we're already stopped!
            pass
        # movement / relative turn instructions (subsequent insts)
        else:
            # in form (r,[degrees],[target dir]), or ([-]m,[squares]) 
            # or ([-]m,[squares],[speed_modifier]) or (rc,[dir])

            # note the number of squares is unused for the main navigation
            inst = instruction_as_string.split(",")
            inst_type = inst[0]

            if inst_type=='m':

                # default speed is 1000, but this can be scaled
                speed_modifier = 1
                # some move instructions don't have a modifer, in this case
                # default value of 1 is kept
                if len(inst)==3:
                    speed_modifier = float(inst[2])

                currently_moving=True
                # 0 represents active pinging with 0 pings missed so far
                #currently_pinging = 0
                # start listening for pongs
                #check_for_pong()

                # start checking sonar regularly while we're moving
                # only used by overhead system
                if not local:
                    polling_sonar = True
                    poll_sonar()

                movement_controller.forward_forever(speed_modifier)

                # start checking sonar regularly while we're moving
                #polling_sonar = True
                #poll_sonar_mainthread()
            elif inst_type =='-m':
                # we must reverse! reverses for 1 second, with warning
                # no sonars when we're reversing
                print("about to reverse")
                currently_moving = True
                # audible_warning_mp3()
                movement_controller.forward_forever(0.2, reverse =True)
                time.sleep(1)
                movement_controller.stop()
                currently_moving = False
                print("finished reverse")
            elif inst_type =='r':
                currently_moving=True
                movement_controller.relative_turn(int(inst[1]))
                ask_for_next_inst(local)
            elif inst_type == 'rc':
                # begins a slow turn either left or right. Will not stop until receives s
                currently_moving=True
                movement_controller.start_slow_turn(inst[1],float(inst[2]))
            elif inst_type == 'rt':
                # turns for a specified number of seconds
                # (rt,[dir],[time])
                currently_moving = True
                movement_controller.do_timed_turn(inst[1],int(inst[2]))
                ask_for_next_inst(local)

            else:
                print("received a malformed instruction!: %s"%instruction_as_string)

def check_for_pong():
    global received_pong
    global currently_pinging
    # if this is -1, pinging is not active anymore, due to a stop instruction being sent
    # it must have been sent by vision since when we send one we don't initiate another ping
    # i.e. this means we successfully stopped under normal operation
    if currently_pinging>=0:
        if received_pong:
            #reset missed ping count, and send the next ping
            currently_pinging = 0
            received_pong = False
            Timer(1,check_for_pong).start()
        else:
            #a pong has not been sent in time!
            currently_pinging+=1

            if currently_pinging==5:
                # stop the robot due to x missed pongs.
                # pings will now stop, and currently_pinging will be set to -1
                print("five pings! stopping!")
                follow_one_instruction("s",True)
            else:
                # we've acknowledged the missed pong, but keep trying 
                print("%s missed pongs"%currently_pinging)
                received_pong=False
                Timer(1,check_for_pong).start()

#called when vision system tells us explicitely it's dead. Instead of
# waiting for next pong check, we just stop immediately
def on_vision_death():
    # stop pinging process, now even when next pong isn't received,
    # check_for_pong() does nothing. This is because robot stopping
    # has already been sorted here.
    follow_one_instruction("s",True)

def poll_sonar():
    if polling_sonar:
        if min(movement_controller.sonar_value())<=80:
            # robot too close to a wall!

            print("SONAR SAYS STOP~~~")
            # this stops robot, but still asks
            # for next instruction
            follow_one_instruction("s")
        else:
            Timer(0.3,poll_sonar).start()

def poll_sonar_mainthread():
    while polling_sonar:
        if movement_controller.sonar_value()<=80:
            print("SONAR SAYS STOP~~~")
            follow_one_instruction("s")
            
            #follow_one_instruction should make polling_sonar false
            # but break just in case
            break
        else:
            time.sleep(0.2)

# this method slowly moves forward towards a plant pot, ensuring the centre
# sonar has the smallest value of the three
def sonar_based_creeping():
    print("~~starting to creep~~")
    # continue until centre sonar is close enough to pot, or until side sonars are very very
    # close to the pot (as a failsafe)

    sonar_vals = movement_controller.sonar_value()
    min_sonar_vals = -1
    prev_sonar_vals = []
    print("inital vals: %s"%sonar_vals)
    while not sonar_closeness_check(min_sonar_vals,sonar_vals,prev_sonar_vals):
        print("\n-----------\n")

        # compare sonar values
        prev_sonar_vals = sonar_vals
        left_val_larger, right_val_larger, sonar_vals = get_sonar_comparisons()
        min_sonar_vals = update_mins(min_sonar_vals,sonar_vals,prev_sonar_vals)

        # if at least one of the side sonars has a smaller value, we must turn
        if not left_val_larger or not right_val_larger:
            face_plant_by_sonar(left_val_larger,right_val_larger,min_sonar_vals,sonar_vals,prev_sonar_vals)
        
        # now we are facing plant, move forward until this stops being true, or we get
        # too close to the pot
        print("FORWARD---")
        movement_controller.forward_forever(0.2)

        while left_val_larger and right_val_larger \
            and not sonar_closeness_check(min_sonar_vals, sonar_vals):
            time.sleep(0.2)
            prev_sonar_vals = sonar_vals
            left_val_larger, right_val_larger, sonar_vals = get_sonar_comparisons()
            min_sonar_vals = update_mins(min_sonar_vals,sonar_vals,prev_sonar_vals)
        
        # stop robot and either continue or finish if we're close enough
        print("STOP\n")
        movement_controller.stop()

def sonar_closeness_check(min_vals,new_vals,prev_vals=[]):
    if min_vals == -1:
        return (new_vals[1]<60 or new_vals[1]>1000 \
            or new_vals[0] < 10 or new_vals[2] < 10)
    else:
        return  min_vals[1]<50 and (new_vals[1]<100 or new_vals[1]>1000 \
            or new_vals[0] < 10 or new_vals[2] < 10)

def update_mins(current_mins, new_vals, prev_vals):
    if current_mins == -1:
        return new_vals

    print("mins: %s \t vals: %s"%(current_mins, new_vals))

    length = min(len(current_mins),len(new_vals),len(prev_vals))
    new_mins = []

    for i in range(0,length):
        # update min if new val is less than current min and consistent with most recent vals
        if new_vals[i]<current_mins[i] and prev_vals!= [] and abs(new_vals[i]-prev_vals[i])<15:
            new_mins.append(new_vals[i])
        else:
            new_mins.append(current_mins[i])

    return new_mins



# returns whether left sonar is larger than middle, and same with right sonar
def get_sonar_comparisons():
    sonar_vals = movement_controller.sonar_value()
    left_val_larger = sonar_vals[0]>sonar_vals[1]
    right_val_larger = sonar_vals[2]>sonar_vals[1]
    return left_val_larger, right_val_larger, sonar_vals

def remove_big_vals(sonar_vals):
    new_sonar_vals = []
    for val in sonar_vals:
        if val>1500:
            new_sonar_vals.append(0)
        else:
            new_sonar_vals.append(val)
    return new_sonar_vals

# turns left if needed, until sonars agree, then does the same turning right
def face_plant_by_sonar(left_val_larger,right_val_larger, min_sonar_vals, sonar_vals, prev_sonar_vals):
    # first do lefts
    if not left_val_larger:
        print("LEFT---")
        movement_controller.start_slow_turn('l')

        while not left_val_larger and not sonar_closeness_check(min_sonar_vals,sonar_vals):
            time.sleep(0.2)
            prev_sonar_vals = sonar_vals
            left_val_larger,right_val_larger,sonar_vals = get_sonar_comparisons()
            min_sonar_vals = update_mins(min_sonar_vals, sonar_vals,prev_sonar_vals)

        print("STOP\n")
        movement_controller.stop()

    # then do rights
    elif not right_val_larger:
        print("RIGHT---")
        movement_controller.start_slow_turn('r')   

        while not right_val_larger and not sonar_closeness_check(min_sonar_vals, sonar_vals):
            time.sleep(0.2)
            prev_sonar_vals = sonar_vals
            left_val_larger,right_val_larger,sonar_vals = get_sonar_comparisons()
            min_sonar_vals = update_mins(min_sonar_vals, sonar_vals,prev_sonar_vals)

        print("STOP\n")
        movement_controller.stop()

    return min_sonar_vals


#= DEPRECATED - Now we just listen for pongs, we don't send pings =
def send_ping():
    print("ping")

    try:
        client.publish("ping-pong","ping",qos=2)
    except:
        print("couldn't publish ping :(")
    
    #in x seconds check for the pong
    Timer(1,check_for_pong).start()

def ask_for_next_inst(local=False):
    global currently_moving
    currently_moving = False
    print("about to send finish-instruction \t local: %s"%local)
    if local:
        client.publish("pi-finish-instruction","done",qos=2)
    else:
        client.publish("finish-instruction","",qos=2)
    print("instruction sent!")

def audible_warning_mp3():
    if currently_moving:
        ev3.Sound.speak("Vehicle reversing")
        Timer(2,audible_warning_mp3).start()

def read_battery_status(client):
    # this file contains the current battery voltage
    voltage_file = open("/sys/class/power_supply/legoev3-battery/voltage_now","r")
    # convert reading into string of decimal number
    voltage_level = str(int(voltage_file.readline())/1000000)
    voltage_file.close()
    client.publish("battery-update",voltage_level,qos=2)
    print("sent battery update")
    # starts a threading.Timer object which calls this method again in 300 seconds
    Timer(300,read_battery_status,[client]).start()

# set up client & client functions
client=mqtt.Client("ev3")
client.on_connect=onConnect
client.on_message=onMessage

# if this is true, robot is either turning or moving forever
currently_moving = False

# tracks whether vision system has responded to the current ping
received_pong=False
# -1 means pinging is not active, [0..) means pinging is active, and counts num missed pings in a row
currently_pinging = -1

# movement object, controls motors, sonar, and gyro
movement_controller = movement_monitored_ver.Movement()

# tracks whether we should be checking for sonar input
polling_sonar = False

# tracks whether we should be running the special local sonar checks
detect_pot_interrupted = False

#connect client and make it wait for inputs
client.connect(ips.ip)
read_battery_status(client) # battery reading thread is started here

client.loop_forever()

################
# robot has three states:
# -- moving - waiting to be told to stop
# -- rotating - using gyro to track whether it's finished
# -- waiting - ready to receive a fresh instruction
################
