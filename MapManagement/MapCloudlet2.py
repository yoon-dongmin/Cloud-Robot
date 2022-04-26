import sys, os, io, time
from MapManagement.VertexCloudlet import *
import numpy as np
import threading
from MapManagement.MapMOS import MapMOS


class MapCloudlet:
    #AMR,RACK,CARGO,DOOR 초기화 하는 부분
    def __init__(self, mapfile, AMR_LIFT_init, AMR_TOW_init, RACK_TOW_init, RACK_LIFT_init, CARGO_init, Door_init, t_init=0):
        # Mapfile: MOS map data file => map_cloud.txt
        # AMR_LITF_IDS, AMR_TOW_IDs: list of robot IDs
        self.VEL = 0.5  # velocity used to compute collision
        self.Collision_DIST = 0.05

        # Load static_map
        self.static_map = MapMOS(mapfile) 
        self.STATION_LITF_TO_TOW = [21, 22]  # station [LIFT, TOW] TODO: check the value

        # initialize - number
        self.AMR_LIFT_IDs = AMR_LIFT_init.keys()
        self.AMR_TOW_IDs = AMR_TOW_init.keys()
        self.CARGO_IDs = CARGO_init.keys()  # Add ID, if new cargo appears
        self.CARGO_ID_NUM = 0
        self.RACK_TOW_IDs = RACK_TOW_init.keys()  # Add ID, if new rack_tow appears
        self.RACK_LIFT_IDs = RACK_LIFT_init.keys()  # Add ID, if new rack_lift appears
        self.DOOR_IDs = Door_init.keys()
        self.t_init = 0

        # initialize - semantic map data
        # save all object's position : dictionary {ID: {'timestamp':[], 'pos':[], 'vertex':[(vertex,vertex),(vertex,vertex)], 'load_id':[], 'load':0}
        # load_id: 같이 있는 물체들을 list로 ex) AMR_LIFT['load_id']=[[rack, cargo], [], ...], RACK['load_id']=[[robot, cargo], CARGO['load_id']=[[robot, rack'], ..
        # load: 로드가 되면 1

        # initialize robots and plan
        self.AMR_LIFT, self.Path_AMR_LIFT = {}, {}
        for id, vertex in AMR_LIFT_init.items():  # save AMR-LIFT pose
            pos = [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]
            self.AMR_LIFT[id] = {'timestamp': [t_init], 'pos': [pos], 'vertex': [[vertex, vertex]],
                                 'load': [0], 'load_id': [[-1, -1]]}
            self.Path_AMR_LIFT[id] = []  # save AMR-LIFT plan
        self.AMR_TOW, self.Path_AMR_TOW = {}, {}
        for id, vertex in AMR_TOW_init.items():
            # save AMR-TOW pose
            pos = [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]
            self.AMR_TOW[id] = {'timestamp': [t_init], 'pos': [pos], 'vertex': [[vertex, vertex]],
                                'load': [0], 'load_id': [[-1, -1]]}
            self.Path_AMR_TOW[id] = []  # save AMR-TOW plan

        # initialize RACK
        # RACK,CARGO에는 load가 없음
        self.RACK_LIFT, self.RACK_TOW = {}, {}
        for id, vertex in RACK_LIFT_init.items():
            pos = [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]
            self.RACK_LIFT[id] = {'timestamp': [t_init], 'pos': [pos], 'vertex': [[vertex, vertex]],
                                  'load_id': [[-1, -1]]}
        for id, vertex in RACK_TOW_init.items():
            pos = [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]
            self.RACK_TOW[id] = {'timestamp': [t_init], 'pos': [pos], 'vertex': [[vertex, vertex]],
                                 'load_id': [[-1, -1]]}

        # initialize CARGO
        self.CARGO = {}  # save cargo pose
        for id, vertex in CARGO_init.items():
            pos = [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]
            self.CARGO[id] = {'timestamp': [t_init], 'pos': [pos], 'vertex': [[vertex, vertex]],
                              'load_id': [[-1, -1]]}
            '''
            if vertex in list(RACK_LIFT_init.values()):
                RACK_LIFT_init_list = list(RACK_LIFT_init.values())
                vertex_index = RACK_LIFT_init_list.index(vertex)
                RACK_LIFT_id = RACK_LIFT_init.keys()[vertex_index]
                self.CARGO[id]['load_id'] = [[-1, RACK_LIFT_id]]
                self.RACK_LIFT[RACK_LIFT_id] = [[-1, id]]
            elif vertex in list(RACK_TOW_init.values()):
                RACK_TOW_init_list = list(RACK_TOW_init.values())
                vertex_index = RACK_TOW_init_list.index(vertex)
                RACK_TOW_id = RACK_TOW_init.keys()[vertex_index]
                self.CARGO[id]['load_id'] = [[-1, RACK_TOW_id]]
                self.RACK_TOW[RACK_TOW_id] = [[-1, id]]
            '''

        # initialize the door
        self.Door = {}
        for id, val in Door_init.items():
            self.Door[id] = {'timestamp': [t_init], 'status': [0]}  #0 : 닫혀, 1 : 열려져

    
    def update_MOS_robot_info(self, info):  # call this function when robot_information is updated by MOS
        if info.id in self.AMR_LIFT_IDs:#AMR_LIFT일때
            info.vertex = self.convert_pose_to_vertex(info.pos)
            if self.robot_update_rule(self.AMR_LIFT, info):  # if the update rule is satisfied
                self.AMR_LIFT[info.id]['timestamp'].insert(0, info.timestamp)
                self.AMR_LIFT[info.id]['pos'].insert(0,info.pos)
                self.AMR_LIFT[info.id]['vertex'].insert(0,info.vertex)
                self.AMR_LIFT[info.id]['load'].insert(0,info.load)
                #load id update
                # update loaded/unloaded objects 
                if info.load == 1: 
                    if self.AMR_LIFT[info.id]['load'][1] == 1:  # a robot is carrying a rack #이전에 물건을 들고있다.
                        # copy previous state #같은 물건을 들고있다.
                        load_id = self.AMR_LIFT[info.id]['load_id'][0] 
                    else:  # a robot loads a rack, now. #현재 막 물건을 들고있다.
                        load_id = [self.search_obj_at_vertex(self.RACK_LIFT, info.vertex), #RACK,CARGO
                                   self.search_obj_at_vertex(self.CARGO, info.vertex)]
                    # update the lift
                    self.AMR_LIFT[info.id]['load_id'].insert(0,load_id)

                    # update the rack_lift
                    if load_id[0] != -1:  #a robot is carrying a rack  #값이 들어왔을 때
                        id = load_id[0]
                        self.RACK_LIFT[id]['timestamp'].insert(0,info.timestamp)
                        self.RACK_LIFT[id]['pos'].insert(0, info.pos)
                        self.RACK_LIFT[id]['vertex'].insert(0,info.vertex)
                        self.RACK_LIFT[id]['load_id'].insert(0,[info.id, load_id[1]]) #로봇이랑 cargo id

                    # update the state of cargos that a robot is carrying
                    if load_id[1] != -1:
                        id = load_id[1]
                        self.CARGO[id]['timestamp'].insert(0,info.timestamp)
                        self.CARGO[id]['pos'].insert(0,info.pos)
                        self.CARGO[id]['vertex'].insert(0,info.vertex)
                        self.CARGO[id]['load_id'].insert(0,[info.id, load_id[0]]) #로봇이랑 rack id

                #현재는 loadx 직전까지 load한 상태
                elif info.load == 0 and self.AMR_LIFT[info.id]['load'][1] == 1:  # unload the rack now
                    self.AMR_LIFT[info.id]['load_id'].insert(0,[-1, -1]) #아무것도 안든 상태기 때문

                    # rack id and cargo id before unloading
                    # 이전의 rock,cargo id
                    rack_id = self.AMR_LIFT[info.id]['load_id'][1][0]
                    cargo_id = self.AMR_LIFT[info.id]['load_id'][1][1]
                    # update the rack_lift
                    self.RACK_LIFT[rack_id]['timestamp'].insert(0,info.timestamp) 
                    self.RACK_LIFT[rack_id]['pos'].insert(0,info.pos)
                    self.RACK_LIFT[rack_id]['vertex'].insert(0,info.vertex) #현재 vertex로     
                    self.RACK_LIFT[rack_id]['load_id'].insert(0,[-1, cargo_id])  #rack에 있던 cargo는 내려놓지 않아서


                    # update the state of cargos that a robot is carrying
                    if cargo_id != -1:
                        self.CARGO[cargo_id]['timestamp'].insert(0,info.timestamp)
                        self.CARGO[cargo_id]['pos'].insert(0,info.pos)
                        self.CARGO[cargo_id]['vertex'].insert(0,info.vertex)
                        self.CARGO[cargo_id]['load_id'].insert(0,[-1, rack_id]) ##마찬가지로 rack에 있던 cargo는 내려놓지 않아서

                else:
                    self.AMR_LIFT[info.id]['load_id'].insert(0,[-1, -1])

        # update tow
        elif info.id in self.AMR_TOW_IDs: #AMR_TOW일때
            info.vertex = self.convert_pose_to_vertex(info.pos)
            if self.robot_update_rule(self.AMR_TOW, info):  # if the update rule is satisfied
                self.AMR_TOW[info.id]['timestamp'].insert(0,info.timestamp)
                self.AMR_TOW[info.id]['pos'].insert(0,info.pos)
                self.AMR_TOW[info.id]['vertex'].insert(0,info.vertex)
                self.AMR_TOW[info.id]['load'].insert(0,info.load)

                # update loaded/unloaded objects
                if info.load == 1:
                    if self.AMR_TOW[info.id]['load'][1] == 1:  # a robot is carrying a rack
                        # copy previous state
                        load_id = self.AMR_TOW[info.id]['load_id'][0]
                    else:  # a robot loads a rack, now.
                        load_id = [self.search_obj_at_vertex(self.RACK_TOW, info.vertex),
                                   self.search_obj_at_vertex(self.CARGO, info.vertex)]

                    # update the TOW
                    self.AMR_TOW[info.id]['load_id'].insert(0,load_id)

                    # update the rack_TOW
                    if load_id[0] != -1:  # a robot is carrying a rack
                        id = load_id[0]
                        self.RACK_TOW[id]['timestamp'].insert(0,info.timestamp)
                        self.RACK_TOW[id]['pos'].insert(0,info.pos)
                        self.RACK_TOW[id]['vertex'].insert(0,info.vertex)
                        self.RACK_TOW[id]['load_id'].insert(0,[info.id, load_id[1]])

                    # update the state of cargos that a robot is carrying
                    if load_id[1] != -1:
                        id = load_id[1]
                        self.CARGO[id]['timestamp'].insert(0,info.timestamp)
                        self.CARGO[id]['pos'].insert(0,info.pos)
                        self.CARGO[id]['vertex'].insert(0,info.vertex)
                        self.CARGO[id]['load_id'].insert(0,[info.id, load_id[0]])

                elif info.load == 0 and self.AMR_TOW[info.id]['load'][1] == 1:  # unload the rack now
                    self.AMR_TOW[info.id]['load_id'].insert(0,[-1, -1])

                    # rack id and cargo id before unloading
                    rack_id = self.AMR_TOW[info.id]['load_id'][1][0]
                    cargo_id = self.AMR_TOW[info.id]['load_id'][1][1]
                    # update the rack_tow
                    self.RACK_TOW[rack_id]['timestamp'].insert(0,info.timestamp) 
                    self.RACK_TOW[rack_id]['pos'].insert(0,info.pos)
                    self.RACK_TOW[rack_id]['vertex'].insert(0,info.vertex)
                    self.RACK_TOW[rack_id]['load_id'].insert(0,[-1, cargo_id])  # change this state

                    # update the state of cargos that a robot is carrying
                    if cargo_id != -1:
                        self.CARGO[cargo_id]['timestamp'].insert(0,info.timestamp)
                        self.CARGO[cargo_id]['pos'].insert(0,info.pos)
                        self.CARGO[cargo_id]['vertex'].insert(0,info.vertex)
                        self.CARGO[cargo_id]['load_id'].insert(0,[-1, rack_id])

                else:
                    self.AMR_TOW[info.id]['load_id'].insert(0,[-1, -1])

        self.update_NAV_PLAN(info.id)


    #이전값과 다른값이 들어왔을 떄 update
    def robot_update_rule(self, robot, info):  # define the update rule of robot status: return true to update
        return info.vertex != robot[info.id]['vertex'][0] or info.load != robot[info.id]['load']  # or info.status!= robot[info.id]['status'][-1]

    #1층에서 2층에 연결된 door를 update하는 부분
    def update_MOS_door_info(self, info):  # update door_state is updated by MOS #TODO: Check
        if info.status != self.DOOR['status']: 
            self.DOOR['timestamp'].append(info.timestamp) 
            self.DOOR['status'].append(info.status)

    #call부분 함수는 현재 시나리오에 사용되고 있지는 않음
    #Lift하라 했을 때 update하는 부분
    ##왜 여기서는 append? => cargo이기 때문에 뒤에 append해서 추가
    def call_LIFT(self, info):  # call if a human calls AMR-LIFT
        # ADD cargo and rack id
        #사람이 부를떄마다 update
        new_cargo_id = 'CARGO' + str(self.CARGO_ID_NUM)  # TODO: change later\
        self.CARGO_ID_NUM = self.CARGO_ID_NUM + 1 #self.CARGO_ID_NUM 1씩 추가
        # search the rack corresponding to the call
        rack_id = self.search_obj_at_vertex(self.RACK_LIFT, info.vertex) #-없을때 : -1
        rack_pos = self.RACK_LIFT[rack_id]['pos'][0] 
        amr_lift_id = self.RACK_LIFT[rack_id]['load_id'][0][0] #로봇의 첫번째 id
        self.CARGO_IDs.append(new_cargo_id)

        # ADD CARGO
        self.CARGO[new_cargo_id] = {'timestamp': [info.timestamp], 'pos': [rack_pos], 'vertex': [info.vertex],
                                    'load_id': [[-1, rack_id]]}

        # RACK update
        self.RACK_LIFT[rack_id]['timestamp'].append(info.timestamp)
        self.RACK_LIFT[rack_id]['pos'].append(rack_pos)
        self.RACK_LIFT[rack_id]['vertex'].append(info.vertex)
        self.RACK_LIFT[rack_id]['load_id'].append([amr_lift_id, new_cargo_id])

        # update AMR-LIFT
        if amr_lift_id != -1:
            self.AMR_LIFT[amr_lift_id]['timestamp'].append(info.timestamp)
            self.AMR_LIFT[amr_lift_id]['pos'].append(self.AMR_LIFT[amr_lift_id]['pos'][0])
            self.AMR_LIFT[amr_lift_id]['vertex'].append(self.AMR_LIFT[amr_lift_id]['vertex'][0])
            self.AMR_LIFT[amr_lift_id]['load'].append(1)
            self.AMR_LIFT[amr_lift_id]['load_id'].append([rack_id, new_cargo_id])
    #TOW를 불렀을 때 update하는 부분
    ##왜 call_TOW에는 RACk_lift가 들어가는지? => lift해서 tow를 옮기때 사용
    def call_TOW(self, info_call):  # call if a human calls AMR-TOW (cargo was moved from LIFT to TOW)
        # search a rack and cargo located at STATION_LIFT_TO_TOW[0]
        # self.STATION_LITF_TO_TOW??
        cargo_id = self.search_obj_at_vertex(self.CARGO, [self.STATION_LITF_TO_TOW[0], self.STATION_LITF_TO_TOW[0]]) 
        rack_lift_id = self.search_obj_at_vertex(self.RACK_LIFT,
                                                 [self.STATION_LITF_TO_TOW[0], self.STATION_LITF_TO_TOW[0]])
        rack_tow_id = self.search_obj_at_vertex(self.RACK_TOW,
                                                [self.STATION_LITF_TO_TOW[1], self.STATION_LITF_TO_TOW[1]])

        # update the rack_lift
        ##pos[0],[2]가 들어가는 이유
        amr_lift_id = self.RACK_LIFT[rack_lift_id]['load_id'][0][0]
        self.RACK_LIFT[rack_lift_id]['timestamp'].append(info_call.timestamp)
        postmp = self.static_map.VertexPos[self.STATION_LITF_TO_TOW[0]]
        self.RACK_LIFT[rack_lift_id]['pos'].append([postmp[0], postmp[2]]) 
        self.RACK_LIFT[rack_lift_id]['vertex'].append([self.STATION_LITF_TO_TOW[0], self.STATION_LITF_TO_TOW[0]])
        self.RACK_LIFT[rack_lift_id]['load_id'].append([amr_lift_id, -1]) ##cargo_id는 초기화

        # update the AMR_LIFT
        if amr_lift_id != -1:
            self.AMR_LIFT[amr_lift_id]['timestamp'].append(info_call.timestamp)
            self.AMR_LIFT[amr_lift_id]['pos'].append(self.AMR_LIFT[amr_lift_id]['pos'][0])
            self.AMR_LIFT[amr_lift_id]['vertex'].append(self.AMR_LIFT[amr_lift_id]['vertex'][0])
            self.AMR_LIFT[amr_lift_id]['load'].append(1)
            self.AMR_LIFT[amr_lift_id]['load_id'].append([rack_lift_id, -1])

        # update the rack_tow
        amr_tow_id = self.RACK_TOW[rack_tow_id]['load_id'][0][0]
        self.RACK_TOW[rack_tow_id]['timestamp'].append(info_call.timestamp)
        postmp = self.static_map.VertexPos[self.STATION_LITF_TO_TOW[1]]
        self.RACK_TOW[rack_tow_id]['pos'].append([postmp[0], postmp[2]])
        self.RACK_TOW[rack_tow_id]['vertex'].append([self.STATION_LITF_TO_TOW[1], self.STATION_LITF_TO_TOW[1]])
        self.RACK_TOW[rack_tow_id]['load_id'].append([amr_tow_id, cargo_id])

        # update the AMR_TOW
        if amr_tow_id != -1:
            self.AMR_TOW[amr_tow_id]['timestamp'].append(info_call.timestamp)
            self.AMR_TOW[amr_tow_id]['pos'].append(self.AMR_TOW[amr_tow_id]['pos'][0])
            self.AMR_TOW[amr_tow_id]['vertex'].append(self.AMR_TOW[amr_tow_id]['vertex'][0])
            self.AMR_TOW[amr_tow_id]['load'].append(1)
            self.AMR_TOW[amr_tow_id]['load_id'].append([rack_tow_id, cargo_id])

        # update the cargo
        self.CARGO[cargo_id]['timestamp'].append(info_call.timestamp)
        postmp = self.static_map.VertexPos[self.STATION_LITF_TO_TOW[1]]
        self.CARGO[cargo_id]['pos'].append([postmp[0], postmp[2]])
        self.CARGO[cargo_id]['vertex'].append([self.STATION_LITF_TO_TOW[1], self.STATION_LITF_TO_TOW[1]])
        self.CARGO[cargo_id]['load_id'].append([amr_tow_id, rack_tow_id])

    def call_removeCargo(self, info_call): #지금은 사용x
        # search a rack and cargo located at info_call.vertex
        # info_call??
        cargo_id = self.search_obj_at_vertex(self.CARGO, info_call.vertex)
        rack_tow_id = self.search_obj_at_vertex(self.RACK_TOW, info_call.vertex)

        # update the cargo
        self.CARGO.pop(cargo_id)
        self.CARGO_IDs.remove(cargo_id)

        # update the rack_tow
        amr_tow_id = self.RACK_TOW[rack_tow_id]['load_id'][0][0]
        self.RACK_TOW[rack_tow_id]['timestamp'].append(info_call.timestamp)
        self.RACK_TOW[rack_tow_id]['pos'].append(self.RACK_TOW[rack_tow_id]['pos'][0])
        self.RACK_TOW[rack_tow_id]['vertex'].append(self.RACK_TOW[rack_tow_id]['vertex'][0])
        self.RACK_TOW[rack_tow_id]['load_id'].append([amr_tow_id, -1])

        # update the AMR_TOW
        if amr_tow_id != -1:
            self.AMR_TOW[amr_tow_id]['timestamp'].append(info_call.timestamp)
            self.AMR_TOW[amr_tow_id]['pos'].append(self.AMR_TOW[amr_tow_id]['pos'][0])
            self.AMR_TOW[amr_tow_id]['vertex'].append(self.AMR_TOW[amr_tow_id]['vertex'][0])
            self.AMR_TOW[amr_tow_id]['load'].append(1)
            self.AMR_TOW[amr_tow_id]['load_id'].append([rack_tow_id, -1])

    def add_RACK_TOW(self, timestamp, vertex):  # never call
        # ADD a new rack
        new_rack_id = 'RACK' + str(len(self.RACK_TOW_IDs))  # TODO: change later
        self.RACK_TOW_IDs.append(new_rack_id)

        # ADD RACK
        self.RACK_TOW[new_rack_id] = {'timestamp': [timestamp], 'pos': [
            [self.static_map.VertexPos[vertex][0], self.static_map.VertexPos[vertex][2]]], 'vertex': [[vertex, vertex]],
                                      'load_id': [[-1, -1]]}

    #어떤 로봇이 어떤 path인지 정보를 받고 update
    #NC에게 받고 update
    def insert_NAV_PLAN(self, amr_id, path):  # Call when a new path is allocated
        if amr_id in self.AMR_LIFT_IDs:
            self.Path_AMR_LIFT[amr_id] = path.copy()

        elif amr_id in self.AMR_TOW_IDs:
            self.Path_AMR_TOW[amr_id] = path.copy()
    #로봇이 움직일때마다 plan이 잘 따라가는지 보고 이미 지난 vertex는 빼줌
    def update_NAV_PLAN(self, amr_id):  # Update the path that the robot should follow TODO: 지나가도 할 수 있게

        if amr_id in self.AMR_LIFT_IDs:
            if len(self.Path_AMR_LIFT[amr_id]) != 0:
                compare_nodes = [[self.Path_AMR_LIFT[amr_id][0]] * 2] #[[0,0]]

                if len(self.Path_AMR_LIFT[amr_id]) > 1:
                    compare_nodes.append(self.Path_AMR_LIFT[amr_id][0:2]) ##compare_nodes = [[0,0],[0,1],[1,0]]
                    compare_nodes.append([self.Path_AMR_LIFT[amr_id][1], self.Path_AMR_LIFT[amr_id][0]])
                if self.AMR_LIFT[amr_id]['vertex'][0] in compare_nodes:
                    self.Path_AMR_LIFT[amr_id].pop(0) #셋중에 하나 있으면 지움

                # print("call update Nav Plan", amr_id, self.AMR_LIFT[amr_id]['vertex'][-1], compare_nodes)
                # print('path plan ', self.Path_AMR_LIFT[amr_id])
        ##질문
        elif amr_id in self.AMR_TOW_IDs:
            if len(self.Path_AMR_TOW[amr_id]) != 0:
                compare_nodes = [[self.Path_AMR_TOW[amr_id][0]] * 2]
                if len(self.Path_AMR_TOW[amr_id]) > 1:
                    compare_nodes.append(self.Path_AMR_TOW[amr_id][0:2]) ##compare_nodes = [[0,0],[0,1],[1,0]]
                    compare_nodes.append([self.Path_AMR_TOW[amr_id][1], self.Path_AMR_TOW[amr_id][0]])
                if self.AMR_TOW[amr_id]['vertex'][0] in compare_nodes:
                    self.Path_AMR_TOW[amr_id].pop(0)

                # print("call update Nav Plan", self.AMR_LIFT[amr_id]['vertex'][-1], compare_nodes)
    
    #두 로봇의 path를 계산해서 충돌을 예상하는 함수
    #vertex를 continuous한 좌표로 바꿔서 겹치면 colision이 일어나는거
    ##어떤한 방식으로 되는지?
    def detect_collision(self, T):  # return [AMR_id1, AMR_id2] if collision occurs in time T
        delT = 0.02
        trajs = {}
        amr_ids = []
        collision_set = []
        for rid in self.AMR_TOW_IDs:
            trajs[rid] = self.generate_traj_from_plan(self.AMR_TOW[rid]['pos'][0], self.VEL, delT, T,
                                                      self.Path_AMR_TOW[rid])
            # print("trajectory of ", rid, trajs[rid])
            amr_ids.append(rid)
        for rid in self.AMR_LIFT_IDs:
            trajs[rid] = self.generate_traj_from_plan(self.AMR_LIFT[rid]['pos'][0], self.VEL, delT, T,
                                                      self.Path_AMR_LIFT[rid])
            # print("trajectory of ", rid, trajs[rid])
            amr_ids.append(rid)

        for ii in range(0, len(amr_ids)):
            rid1 = amr_ids[ii]
            x1 = np.array(trajs[rid1]['x'])
            y1 = np.array(trajs[rid1]['y'])
            for jj in range(ii + 1, len(amr_ids)):
                rid2 = amr_ids[jj]
                x2 = np.array(trajs[rid2]['x'])
                y2 = np.array(trajs[rid2]['y'])
                for t in range(0, min(len(x1), len(x2))):
                    #모든 시간에대해서 겹치는게 있으면 colision이라 생각
                    if (x1[t] - x2[t]) ** 2 + (y1[t] - y2[t]) ** 2 < self.Collision_DIST ** 2: #self.Collision_DIST = 0.05
                        collision_set.append([rid1, rid2, t * delT]) #행당되는 값을 append
                        break

        return collision_set
    #vertex로 되어있는 부분을 position으로 푸는 함수
    #delT :얼마나 촘촘하게 path를 만들까,T : 얼마나 오랜 기간 볼까
    def generate_traj_from_plan(self, init, vel, delT, T, plan):

        traj  = {'x': [], 'y': []}  # initialize
        t = T  # initialize
        x = init[0]
        y = init[1]
        path = plan.copy()

        while t > 0 and path != []:
            # move one step during delT
            t_left = delT
            while t_left > 0:
                goal_pos = [self.static_map.VertexPos[path[0]][0], self.static_map.VertexPos[path[0]][2]] #처음에 가고있는 vertex
                #두 vertex사이의 거리
                goal_dist = np.sqrt(
                    (goal_pos[0] - x) ** 2 + (goal_pos[1] - y) ** 2)  # distance from the current pos to goal position
                #상대 vertex까지 가는 시간
                t_req = goal_dist / vel

                if delT >= t_req:  # pass the next node in the path
                    path.pop(0) #목표에 도달한거라서 뺴고 다음노드로 표시
                    if path == []:
                        x = goal_pos[0]
                        y = goal_pos[1]
                    t_left = 0
                else:#그면 그쪽을 향해서 이동
                    x = x + (goal_pos[0] - x) / goal_dist * vel * t_left
                    y = y + (goal_pos[1] - y) / goal_dist * vel * t_left

                    t_left = t_left - t_req

            t = t - delT
            traj['x'].append(x)
            traj['y'].append(y)
        # print(traj)
        return traj #continuous한 값으로
    #position을 vertex로 바꾸는 함수
    def convert_pose_to_vertex(self, pose):
        # return two closest vertex from pose, the distance should be less than threshold
        # th = 0.6 << Minimum distance between vertex in map
        th = 0.5
        dist_set = []
        id_set = []
        for id, ver_pose in self.static_map.VertexPos.items():
            id_set.append(id)
            dist_set.append((ver_pose[0] - pose[0]) ** 2 + (ver_pose[2] - pose[1]) ** 2)

        min_dist = min(dist_set)
        min_id = id_set[dist_set.index(min_dist)]
        #th제곱 값보다 작으면 그 위치에 있다고 판단
        if min_dist < th ** 2:
            result = [min_id, min_id]
            return result
        else:
            # parts of dist_set: extract distance from neighbor vertices
            id_set2 = self.static_map.Edge[min_id]
            dist_set2 = [dist_set[id_set2.index(id)] for id in id_set2]
            min_dist2 = min(dist_set2)
            min_id2 = id_set2[dist_set2.index(min_dist2)]
            result = [min_id, min_id2]
            return result
    #어떤 object(kargo나leg)가 그 node에 있는지 없는지 찾아주는 함수
    ##self.RACK_LIFT, info.vertex??
    def search_obj_at_vertex(self, objlist, v):  # objlist: AMR_LIFT, AMR_TOW, ...
        objs = []
        for id, info in objlist.items():  #self.RACK_LIFT, info.vertex
            # if info['vertex'][-1] == v:
            if info['vertex'][0] == v: #v = info.vertex?
                objs.append(id)
        if len(objs) == 1:
            return objs[0]
        elif len(objs) == 0:
            return -1
        else:
            print("Error: there are multiple objects at the vertex", objs)
            return -1

    # 무시
    # Translate internal data into GL format
    def get_RobotPos_GL(self, robot_id):
        if robot_id in self.AMR_TOW_IDs:
            return '{RobotPose {} (vertex {} {})'.format(robot_id, self.AMR_TOW[robot_id]['vertex'][0][0],
                                                         self.AMR_TOW[robot_id]['vertex'][0][1])
        else:
            return '{RobotPose {} (vertex {} {})'.format(robot_id, self.AMR_LIFT[robot_id]['vertex'][0][0],
                                                         self.AMR_LIFT[robot_id]['vertex'][0][1])


if __name__ == "__main__":
    map = MapCloudlet("../data/map.txt")
    # regular_task = threading.Timer(1, map.map_update).start()
    thread = threading.Thread(target=map.map_update)
    thread.start()

    print("done")
    input()
    thread.stop()