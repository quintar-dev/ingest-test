import logging
import json
import os
from urllib.request import urlopen
import json
import numpy as np
from scipy.spatial import distance
import math
from scipy.interpolate import interp1d
from scipy.optimize import curve_fit
import pandas as pd
import logging
import shutil
from datetime import datetime
import warnings
import time
import pika
import argparse
import sys

from azure.data.tables import TableClient
from azure.data.tables import UpdateMode
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.storage.filedatalake import FileSystemClient
from azure.core.exceptions import HttpResponseError

Log_Format = "%(levelname)s %(asctime)s - %(message)s"
logging.basicConfig(stream = sys.stdout, format = Log_Format, level = "INFO")
logger = logging.getLogger()


def getParams():
    with open("manifest.json", "r") as f:
        data = json.load(f)
    
    blob_service_client = BlobServiceClient.from_connection_string(data["CONFIG_CONNECTION_STRING"])
    container_client = blob_service_client.get_container_client(data['CONFIG_JSON_CONTAINER_NAME'])
    blob_client = container_client.get_blob_client(data["JSON_FILE_PATH"])
    streamdownloader = blob_client.download_blob()
    jsonData = json.loads(streamdownloader.readall())
    sportData = jsonData['sportData']
    
    params = {"WRITE_CONNECTION_STRING" : data["WRITE_CONNECTION_STRING"],
              "LIVE_SIMULATOR" : data["LIVE_SIMULATOR"],
              "SIM_PARAMS" : data["SIM_PARAMS"],
              "LOG_LEVEL" : data["LOG_LEVEL"],
              "LEAGUE_ID" : sportData['lid'],
              "GAME_ID" : sportData['gid'],
              "SHOT_TRAIL_PARAMS" : sportData['shotTrails'],
              "PRE_GAME_ID" : sportData['preGID']}

    return params


class liveInfo:
    def __init__(self, gameID, quarter, leagueID):
        self.gameID = gameID
        urlInfo = str(str(self.gameID) + "_" + str(quarter))
        self.url = "http://data.nba.com/data/10s/v2015/json/mobile_teams/" + leagueID + "/2021/scores/pbp/" + urlInfo + "_pbp.json"
        # self.url = "http://data.nba.com/data/10s/v2015/json/mobile_teams/nba/2021/scores/pbp/0022101103_1_pbp.json"
        logging.info(self.url)
        while True:
            try:
                c = urlopen(self.url)
                break
            except:
                logging.info("WAITING FOR QUARTER TO START")
                time.sleep(120)
                # continue

    def getData(self, evtID, de):
        while (True):
            response = urlopen(self.url)
            spbpData = json.loads(response.read())["g"]
            period = spbpData["p"]
            self.nextURL = spbpData["next"]
            if "pla" in spbpData:
                newData = [evt for evt in spbpData["pla"] if int(evt["evt"]) > evtID]
            else:
                newData = []
            if newData != []:
                break
            else:
                logging.info("WAITING FOR NEW DATA")

        numEvts = len(newData)

        self.events = []
        self.tids = []
        if numEvts > 0:
            for event in newData:
                if len(self.tids) == 0:
                    if event["tid"] != 0:
                        if (event["tid"]) != int(event["oftid"]):
                            self.tids.append(event["tid"])
                            self.tids.append(event["oftid"])
                evtID = event["evt"]
                de = event["de"].lower()
                relData = {"gid": self.gameID, "eid": evtID, "pe": period, "tid": event["tid"], "pid": event["pid"],
                           "epid": event["epid"], "opid": event["opid"], "tr": event["cl"], "x": event["locX"],
                           "y": event["locY"], "de": de}
                # logging.info("RELDATAT")
                # logging.info(relData)
                self.events.append(relData)
                if de == "end period":
                    break
            # logging.info(self.events)
        return evtID, period, de.lower()


class shotInfo:  ## Get SHOTS, SCORING
    def __init__(self, game_ID, hTeam, shotTrailParams):
        self.game_ID = game_ID
        self.hTeam = hTeam
        self.shotTrailParams = shotTrailParams
        logging.info("SHOT INFO CONSTRUCTOR")

    def func(self, x, a, b, c):
        return a * x ** 2 + b * x + c

    def heights(self, maxH):
        diff = 0
        max_point = round(len(self.z_pts) * 0.5)
        self.z_pts[-1] = 100.0

        maxVal = maxH
        maxDiff = maxVal - 100.0
        self.z_pts[max_point] = maxVal
        diff = maxVal - self.z_pts[0]
        for i in range(1, max_point):
            self.z_pts[i] = round((self.z_pts[i - 1] + (diff / max_point)), 2)
        for i in range(max_point + 1, len(self.z_pts)):
            self.z_pts[i] = round((self.z_pts[i - 1] - ((maxDiff) / ((len(self.z_pts) - max_point) - 1))), 2)

        x = list(range(0, len(self.z_pts)))
        params, _ = curve_fit(self.func, x, self.z_pts)
        a, b, c = params[0], params[1], params[2]
        for i in x:
            self.z_pts[i] = round(((a * i ** 2) + (b * i) + c), 2)

        hDiff = 100.0 - self.z_pts[-1]
        for i in range(0, len(self.z_pts)):
            self.z_pts[i] += hDiff
            self.z_pts[i] = round(self.z_pts[i], 2)

    def getTrace(self, pid, leagueID):
        pc_url = "http://data.nba.com/data/10s/v2015/json/mobile_teams/" + leagueID + "/2021/players/playercard_" + str(
            pid) + "_02.json"
        response = urlopen(pc_url)
        playerData = json.loads(response.read())
        
        offset = self.shotTrailParams['startHeightOffset']
        height = (int(playerData["pl"]["ht"].split("-")[0]) * 10) + math.floor(
            (float(playerData["pl"]["ht"].split("-")[1]) / 12) * 10) + offset

        if self.st == "ft":
            p1 = (0, self.pen, height)
        else:
            p1 = (self.x, self.y, height)
        p2 = (self.p[0], self.p[1], 100)
        dist_points = (p1[0], p1[1])
        origin = (self.p[0], self.p[1])

        num_points = self.shotTrailParams['numPoints']

        self.x_pts = []
        self.y_pts = []
        self.z_pts = []

        t = 0.0;
        delta_t = float(1.0) / float(num_points)

        for ipoint in range(0, num_points + 1):
            x = self.p[0]
            y = self.p[1] - 430.0
            z = 100
            xi = round((x + (t * float(p1[0]))), 2)
            yi = round((y + (t * float(p1[1]))), 2)
            zi = 0.0
            self.x_pts.append(xi)
            self.y_pts.append(yi)
            self.z_pts.append(zi)
            t += delta_t
        self.z_pts[-1] = float(p1[2])
        self.x_pts.reverse()
        self.y_pts.reverse()
        self.z_pts.reverse()
        if self.st == "ft":
            maxH = self.shotTrailParams['apex_ft']
        elif self.st == "fg":
            maxH = self.shotTrailParams['apex_2pt']
        elif self.st == "3pt":
            maxH = self.shotTrailParams['apex_3pt']
        self.heights(maxH)
        ynp = np.array(self.y_pts)
        xnp = np.array(self.x_pts)
        if self.tName == self.hTeam.lower():  # 'mia':
            ynp = np.multiply(ynp, -1.0)
            xnp = np.multiply(xnp, -1.0)
        self.x_pts = xnp.tolist()
        self.y_pts = ynp.tolist()
        combList = self.y_pts + self.x_pts + self.z_pts
        combList = np.divide(combList, 10.0)
        combList = np.around(combList, 3)
        self.trace = combList.tolist()
        self.xy_pts = [self.y_pts[0], self.x_pts[0]]

    def getEvtData(self, tids, qData, shots, points, assists, blocks, rebounds, steals, leagueID):
        shots = []
        self.qData = qData
        for evt in self.qData:
            if evt["tid"] == tids[0]:
                tid = tids[1]
            else:
                tid = tids[0]
            if ("shot:" in evt["de"]) or ("free throw" in evt["de"]):
                if "missed" in evt["de"]:
                    ma = 0
                else:
                    ma = 1
                if "3pt" in evt["de"]:
                    self.st = "3pt"
                elif "free throw" in evt["de"]:
                    self.st = "ft"
                else:
                    self.st = "fg"

                self.x = float(evt['x'])
                self.y = float(evt['y'])
                self.tName = evt["de"].split('[')[1][0:3]
                self.p = [0.0, 12.5]
                self.pen = 150.0

                self.getTrace(evt["pid"], leagueID)
                event = {"gid": self.game_ID, "eid": evt["eid"], "pe": evt["pe"], "tid": evt["tid"], "pid": evt["pid"],
                         "tr": evt["tr"], "ma": ma, "st": self.st, "x": self.xy_pts[0], "y": self.xy_pts[1],
                         "trace": self.trace}
                if ma == 1:
                    point = int((evt["de"].split("(")[1]).split(" ")[0])
                    points[evt["tid"]][evt["pid"]] = point
                    if "assist" in evt["de"]:
                        assist = int((((evt["de"].split("assist:")[1]).split("("))[1]).replace(" ast)", ""))
                        assists[evt["tid"]][int(evt["epid"])] = assist
                shots.append(event)
            if "rebound" in evt["de"]:
                #logging.info(evt["de"])
                #logging.info(evt["pid"])
                if evt["pid"] in rebounds[evt["tid"]]:
                    rebounds[evt["tid"]][evt["pid"]] += 1
                else:
                    rebounds[evt["tid"]][evt["pid"]] = 1
            if "block" in evt["de"]:
                block = int((evt["de"].split("(")[1]).split(" ")[0])
                blocks[tid][evt["opid"]] = block
            if "steal" in evt["de"]:
                steal = int((evt["de"].split("(")[1]).split(" ")[0])
                steals[tid][evt["opid"]] = steal
        return shots, points, assists, blocks, rebounds, steals

    def leaderBoard(self, tids, points, assists, blocks, rebounds, steals, leagueID):
        leaderboardData = []
        cats = ["PTS", "AST", "BLK", "REB", "STL"]
        for tid in tids:
            teamLeaders = []
            points[tid].pop(0, None)
            assists[tid].pop(0, None)
            blocks[tid].pop(0, None)
            rebounds[tid].pop(0, None)
            steals[tid].pop(0, None)
            inArr = [points[tid], assists[tid], blocks[tid], rebounds[tid], steals[tid]]
            for i in range(0, 5):
                if (len(inArr[i]) >= 1) and (int(max(inArr[i], key=inArr[i].get)) != 0):
                    pid = max(inArr[i], key=inArr[i].get)
                    scr = int(inArr[i][max(inArr[i], key=inArr[i].get)])
                    pidStr = str(pid)
                    pc_url = "http://data.nba.com/data/10s/v2015/json/mobile_teams/" + leagueID + "/2021/players/playercard_" + pidStr + "_02.json"
                    # logging.info(pc_url)
                    # pc_url = "http://data.nba.com/data/10s/v2015/json/mobile_teams/nba/2021/players/playercard_1628378_02.json"
                    response = urlopen(pc_url)
                    playerData = json.loads(response.read())
                    # playerData = {"pl": {"ln": "Parsons", "fn": "Jim"}}
                    pl_hs = "https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/" + str(
                        pid) + ".png"
                    leader = {"cat": cats[i], "fn": playerData["pl"]["fn"], "sn": playerData["pl"]["ln"],
                              "pid": int(pid), "scr": scr, "hs": pl_hs}
                else:
                    pid = 0
                    scr = 0
                    leader = {"cat": cats[i], "fn": "N/A", "sn": "N/A", "pid": pid, "scr": scr, "hs": ""}
                teamLeaders.append(leader)
            leaderboardData.append({"tid": tid, "teamLeaders": teamLeaders})
        return leaderboardData

    def getPlayerName(leagueID, gameID):
        pc_url = "http://data.nba.com/data/5s/v2015/json/mobile_teams/" + leagueID.lower() + "/2021/scores/gamedetail/" + gameID + ".json"
        response = urlopen(pc_url)
        playerNames = json.loads(response.read())
        visitorPlayerDict = {}
        homePlayerDict = {}
        for player in playerNames:
            visitorPlayerDict[player['vls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']
            homePlayerDict[player['hls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']

        return homePlayerDict, visitorPlayerDict


class dataOutput:
    def __init__(self):
        logging.info("Data Writing!")
        
    def writeTable(self, gameData, connection_string, gameID):
        shots = gameData["shots"]
        leaders = gameData["leaderboard"]
        #logging.info(gameData)
        operations = []
        for shot in shots:
            #logging.info(shot)
            shot['PartitionKey'] = str(gameID)
            shot['RowKey'] = str(shot['eid'])
            shot['trace'] = "".join(str(shot['trace']))
            operations.append(("upsert", shot))

        with TableClient.from_connection_string(connection_string, table_name="GameChronicle") as table:
            try:
                logging.info("WRITING TO TABLE")
                try:
                    for i in range(0, len(operations), 100):
                        operation = list(operations[i:i + 100])
                        lastTask = operation[-1]
                        # logging.info(f'LAST TASK = {lastTask}')
                        # logging.info(operations[99])
                        table.submit_transaction(operation)
                    logging.info("SUBMIT TRANSACTION PASSED")
                except Exception as e:
                    logging.info("SUBMIT TRANSACTION FAILED")
                    lenOp = len(operations)
                    logging.info(f"LENGTH OF OPERATIONS = {lenOp}")
                    logging.info(f"EXCEPTION : {e}")

            except:
                updateStatus = 0
                return ("Failed to add/update game chronicles")

        for team in leaders:
            if team:
                for leader in team['teamLeaders']:
                    logging.info(leader)
                    leader['PartitionKey'] = str(gameID)
                    leader['RowKey'] = str(team['tid']) + '_' + leader['cat']  # + '_' + str(eid)
                    if leader:
                        with TableClient.from_connection_string(connection_string, table_name="LeaderBoard") as table:
                            try:
                                # add new entity if it does not exist. update if the entity exists
                                createdEntity = table.upsert_entity(mode=UpdateMode.MERGE, entity=leader)
                                # logging.info(createdEntity)
                                # Return http response
                                updateStatus = 1
                            except HttpResponseError:
                                updateStatus = 0
                                return ("Failed to add/update game leaders")
                    else:
                        return ("Failed to add/update game leaders")
        return len(shots)



    def pub2Queue(self, jsonData, gameID):
        credentials = pika.PlainCredentials('quintar', 'quintar123')
        parameters = pika.ConnectionParameters('20.231.253.196', 5672, '/', credentials)
        parameters = pika.ConnectionParameters('20.232.3.112', 5672, '/', credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        channel.exchange_declare(exchange='tq6_exchange', exchange_type='fanout')
        channel.queue_declare(queue='testq6', arguments={'x-message-ttl' : 30000})
        message = json.dumps(jsonData)

        channel.basic_publish(exchange='tq6_exchange', routing_key=str(gameID), body=message)
        logging.info(" [x] Sent %r" % message)
        connection.close()


def main():
    logging.info('######################################################################################')
    logging.info('NBA DATA INGEST PIPELINE INITIATED!!!')
    params = getParams()
    logging.info(f'USING PARAMETERS : {params}')
    WRITE_CONNECTION_STRING = params["WRITE_CONNECTION_STRING"]
    leagueID = params['LEAGUE_ID']
    gameID = params['GAME_ID']
    evtID = 0
    opObj = dataOutput()

    if params['LIVE_SIMULATOR'] == 0:
        logging.info("RUNNING IN LIVE MODE!!")
        with TableClient.from_connection_string(WRITE_CONNECTION_STRING, table_name="Game") as table:
            try:
                logging.info("FETCHING GAME DETAILS")
                gamesFilter = f"PartitionKey eq '{gameID}'"
                gameEntity = table.query_entities(query_filter=gamesFilter)
                count = 0
                for entity in gameEntity:
                    count += 1
                    entity.pop("RowKey", None)
                    entity.pop("PartitionKey", None)
                    gameDetails = entity
                tids = [gameDetails["hid"], gameDetails["vid"]]
                hTid = gameDetails["hid"]
            except:
                return (f"Failed to get games data")

        try:
            with TableClient.from_connection_string(WRITE_CONNECTION_STRING, table_name="Team") as table:
                teams = []
                teamFilter = f"PartitionKey eq 'nba' and RowKey eq '{hTid}'"
                teamEntities = table.query_entities(query_filter=teamFilter)
                for teamEntity in teamEntities:
                    hTeam = teamEntity["ab"]
                logging.info(f'HOME TEAM : {hTeam}')
        except:
            return (f"Failed to get home team data")

        try:
            evtCount = 0
            quarter = 1
            de = "start period"
            gameOn = True
            shots = []

            points = {tids[0]: {}, tids[1]: {}}
            assists = {tids[0]: {}, tids[1]: {}}
            blocks = {tids[0]: {}, tids[1]: {}}
            rebounds = {tids[0]: {}, tids[1]: {}}
            steals = {tids[0]: {}, tids[1]: {}}
            logging.info("INIT SHOT_INFO CLASS????")
            logging.info(f'GAME ID : {gameID}')
            shotInfoObj = shotInfo(gameID, hTeam, params['SHOT_TRAIL_PARAMS'])
            quarter = 1
            evtID = 0
            period = 1
            de = "start period"
            numEvts = 0
            logging.info(de)
        except:
            return (f"Failed to get shot leaderboard data")
        for i in range(0, 2160):
            try:
                gameStatus = "GAMEON = " + str(gameOn)
                liObj = liveInfo(gameID, quarter, leagueID)
                evtID, period, de = liObj.getData(evtID, de)
                logging.info(f"DESCRIPTION : {de}")
                nxtUrl = liObj.nextURL

                shots, points, assists, blocks, rebounds, steals = shotInfoObj.getEvtData(tids, liObj.events, shots,
                                                                                          points, assists, blocks,
                                                                                          rebounds, steals,
                                                                                          leagueID)
                leaders = shotInfoObj.leaderBoard(tids, points, assists, blocks, rebounds, steals, leagueID)
                printStr = "DESCRIPTION : " + de.lower()
                evtIDstr = "EVENT ID = " + str(evtID)
                logging.info(printStr)
                logging.info(evtIDstr)
                json_data = {"shots": shots, "leaderboard": leaders}
                lenShots = len(shots)
                logging.info(f"LENGTH OF SHOTS = {lenShots}")
                if len(shots) > 0:
                    logging.info("WRITING NOW!!!!!!")
                    # pub2Queue(json_data, gameID)
                    evtCount += opObj.writeTable(json_data, WRITE_CONNECTION_STRING, gameID)
                logging.info(gameStatus)
                if (de.lower() == "end period" and period != 4):
                    logging.info("CHANGE PERIOD")
                    quarter += 1
                lastEvt = "LAST EVENT = " + str(evtID)
                logging.info(lastEvt)
                if (period == 4 and de.lower() == "end period"):
                    gameOn = False
                    break
                time.sleep(1)
            except:
                time.sleep(5)

        return f'Game Chronicles Data uploaded. No. of Events = {evtCount}'


if __name__ == "__main__":
    main()