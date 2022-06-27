#!/usr/bin/env python
# coding: utf-8

# In[115]:


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
# import pika
# import date
import argparse

# import azure.functions as func
from azure.data.tables import TableClient
from azure.data.tables import UpdateMode
from azure.storage.filedatalake import DataLakeServiceClient
from azure.storage.filedatalake import FileSystemClient
from azure.core.exceptions import HttpResponseError


# In[116]:


# In[118]:


def getParams():
    with open("manifest.json", "r") as f:
        data = json.load(f)
        linkToJson = urlopen(data[0])
        connection_string = data[1]
        liveSimulator = data[2]
    download = linkToJson.download_file()
    dataBytes = download.readall()
    dataStr = dataBytes.decode("utf-8")
    jsonData = json.loads(dataStr)
    shotTrailData = jsonData['sportData']
    preGameID = jsonData['sportData']['preGID']  # for live simulation data
    result = []
    result.append(shotTrailData, liveSimulator, preGameID)
    return result


def logData(data):
    with open("logging_data.json", "w") as f:
        json.dump(data, f)
    logging.info("Wrote data to file")


def logDataToAzureFile(fileName):
    data = json.load(fileName)
    gameID = data["g"]["gid"]
    # accountName =
    # accountKey = "Gs49jwtBv2AaK6MTJnlc2iiqc1yCbZKVliwGveYkjbF+f1mjSukpnUk07RaWkCMqP4VOk5bh+bucVtMdhT3x2g=="
    from azure.storage.fileshare import ShareFileClient
    fileClient = ShareFileClient.from_connection_string(
        conn_str="DefaultEndpointsProtocol=https;AccountName=nbadatalakedev;AccountKey=Gs49jwtBv2AaK6MTJnlc2iiqc1yCbZKVliwGveYkjbF+f1mjSukpnUk07RaWkCMqP4VOk5bh+bucVtMdhT3x2g==;EndpointSuffix=core.windows.net",
        share_name=(gameID + "sportData.json"), file_path="nbadatalakedev/nba/sport-data/")
    with open(fileName, "rb") as source_file:
        fileClient.upload_file(source_file)


# In[119]:
# live simulator data
class getSampleGame:
    def __init__(self, gameID, connection_string, scaleFactor, delTime, erase, ct):
        self.gameID = gameID
        self.connection_string = connection_string
        self.scaleFactor = scaleFactor
        self.delTime = delTime
        self.erase = erase
        self.ct = ct

    def getShotInfo(self):
        with TableClient.from_connection_string(self.connection_string, table_name="GameChronicle") as table:
            shotsFilter = ""
            if self.gameID:
                if shotsFilter:
                    shotsFilter = shotsFilter + " and "
                shotsFilter = shotsFilter + f"PartitionKey eq '{self.gameID}'"
            shotEntities = table.query_entities(
                query_filter=shotsFilter
            )
            shots = []
            for shot in shotEntities:
                shot.pop("RowKey", None)
                shot.pop("PartitionKey", None)
                shot['trace'] = shot['trace'].replace('[', '').replace(']', '')
                shot['trace'] = shot['trace'].replace(' ', '').split(',')
                traces = np.array(shot["trace"])
                shot["trace"] = traces.astype(np.float).tolist()
                shots.append(shot)
            self.shotsDF = pd.DataFrame.from_dict(shots)
            self.shotsDF = self.shotsDF.sort_values(by=['eid']).reset_index(drop=True)
            lastEvent = int(self.shotsDF["eid"].iloc[-1])
        logging.info(f"LAST EVENT =  {lastEvent}")

    def getDeltas(self):
        timeRemaining = []
        prevTime = 2880
        prevQ = 1
        for pos in range(0, len(self.shotsDF)):
            row = self.shotsDF.iloc[pos]
            ts = row["tr"]
            pe = row["pe"]
            mins = (int(ts.split(':')[0]) * 60)
            secs = (float(ts.split(':')[1]))
            timeSecs = mins + secs + ((4 - pe) * (12 * 60))
            if prevQ != pe:
                timeSecs += 120.0
            timeDiff = abs(prevTime - timeSecs)
            if timeDiff < 0:
                logging.info("NEGATIVE TIME DIFF")
                logging.info(pe)
                logging.info(ts)
                logging.info(prevTime)
                logging.info(timeSecs)

            timeRemaining.append(timeDiff)
            prevQ = pe
            prevTime = timeSecs
        self.timeDiffs = timeRemaining
        self.timeDF = pd.DataFrame(timeRemaining, columns=['tr'])

    def createTables(self):
        with TableClient.from_connection_string(self.connection_string, table_name="simGameChronicle") as table:
            table.create_table()
        with TableClient.from_connection_string(self.connection_string, table_name="simLeaderBoard") as table:
            table.create_table()

    def streamlineData(self):
        self.getShotInfo()
        self.getDeltas()
        self.leaderBoard()
        shots = self.shotsDF.to_dict("records")
        if self.ct == 1:
            self.createTables()

        for pos in range(0, len(self.shotsDF)):
            gameData = shots[pos]
            self.writeTableLivSim(gameData=gameData)
            self.changeLeaders(ind=pos)
            if pos % 5 == 0:
                self.writeLeaders()
            timeDelta = self.timeDF.iloc[pos]["tr"] / self.scaleFactor
            # logging.info(gameData["eid"])
            # logging.info(timeDelta)
            time.sleep(timeDelta)

        if self.erase != 0:
            self.eraseTable()

    def leaderBoard(self):
        leadersFilter = ""
        if self.gameID:
            if leadersFilter:
                leadersFilter = leadersFilter + " and "
            leadersFilter = leadersFilter + f"PartitionKey eq '{self.gameID}'"

        leaderData = []
        with TableClient.from_connection_string(self.connection_string, table_name="LeaderBoard") as table:
            tls = table.query_entities(query_filter=leadersFilter)
            for tl in tls:
                tl["PartitionKey"] = "9876543210"
                leaderData.append(tl)

        self.gameLeaders = leaderData

    def changeLeaders(self, ind):
        self.leaderBoard()
        logging.info("GAME LEADERS")
        logging.info(self.gameLeaders)
        newLeaders = self.gameLeaders
        if ind < 4:
            for tl in newLeaders:
                tl["scr"] = 0
                tl["fn"] = "N/A"
                tl["sn"] = "N/A"
                tl["hs"] = ""
                tl["pid"] = 0
                # newLeaders.append(tl)
            logging.info("STEP-1")
            logging.info(newLeaders)
        else:
            cats = ["AST", "BLK", "PTS", "REB", "STL"]
            random.shuffle(cats)
            randInd = random.sample(range(0, len(self.gameLeaders)), 3)
            newLeaders = self.gameLeaders
            logging.info("GAME LEADERS")
            logging.info(self.gameLeaders)

            newLeaders[randInd[0]]["scr"] = 0
            newLeaders[randInd[0]]["fn"] = "N/A"
            newLeaders[randInd[0]]["sn"] = "N/A"
            newLeaders[randInd[0]]["hs"] = ""
            newLeaders[randInd[0]]["pid"] = 0

            newLeaders[randInd[1]]["scr"] = 49

            newLeaders[randInd[2]]["scr"] = 99

            for team in range(0, 2):
                cnt = 0
                for cat in cats:
                    newLeaders[(team * 5) + cnt]["cat"] = cat
                    cnt += 1

        self.newLeaders = newLeaders
        # logging.info(self.newLeaders)

    def writeLeaders(self):
        with TableClient.from_connection_string(self.connection_string, table_name="simLeaderBoard") as table:
            logging.info("NEW LEADERS")
            logging.info(self.newLeaders)
            for leader in self.newLeaders:
                try:
                    logging.info(leader)
                    createdEntity = table.upsert_entity(mode=UpdateMode.MERGE, entity=leader)
                except HttpResponseError:
                    return func.HttpResponse("Failed to add/update game leaders")

    def eraseTable(self):
        time.sleep(self.delTime)
        with TableClient.from_connection_string(self.connection_string, table_name="simGameChronicle") as table:
            table.delete_table()
        with TableClient.from_connection_string(self.connection_string, table_name="simLeaderBoard") as table:
            table.delete_table()

    def writeTableLivSim(self, gameData):
        shot = gameData
        operations = []
        gameID = "9876543210"
        shot['PartitionKey'] = gameID
        shot['RowKey'] = str(shot['eid'])
        shot['trace'] = "".join(str(shot['trace']))
        shot['gid'] = gameID
        operations.append(("upsert", shot))

        with TableClient.from_connection_string(self.connection_string, table_name="simGameChronicle") as table:
            try:
                logging.info("WRITING TO TABLE")
                try:
                    for i in range(0, len(operations), 100):
                        operation = list(operations[i:i + 100])
                        table.submit_transaction(operation)
                    logging.info("SUBMIT TRANSACTION PASSED")
                except Exception as e:
                    logging.info("SUBMIT TRANSACTION FAILED")
                    lenOp = len(operations)
                    logging.info(f"LENGTH OF OPERATIONS = {lenOp}")
                    logging.info(f"EXCEPTION : {e}")

            except:
                return func.HttpResponse("Failed to add/update game chronicles")


# normal app
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
            # newData = [evt for evt in spbpData["pla"] if int(evt["evt"]) > evtID]
            if "pla" in spbpData:
                newData = [evt for evt in spbpData["pla"] if int(evt["evt"]) > evtID]
            else:
                newData = []
            if newData != []:
                break
            else:
                logging.info("WAITING FOR NEW DATA")
            time.sleep(1)
        # newData = spbpData["pla"]
        numEvts = len(newData)
        # logging.info("NEW DATA")
        # logging.info(newData)
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
                logData(relData) # logging Data to JSON file here
                # logging.info("RELDATAT")
                # logging.info(relData)
                self.events.append(relData)
                if de == "end period":
                    break
            # logging.info(self.events)
        return evtID, period, de.lower()


class shotInfo:  ## Get SHOTS, SCORING
    def __init__(self, game_ID, hTeam):
        self.game_ID = game_ID
        self.hTeam = hTeam

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
        result = getParams()
        shotTrailData = result[0]['shotTrails']
        offset = shotTrailData['startHeightOffset']
        height = (int(playerData["pl"]["ht"].split("-")[0]) * 10) + math.floor(
            (float(playerData["pl"]["ht"].split("-")[1]) / 12) * 10) + offset

        if self.st == "ft":
            p1 = (0, self.pen, height)
        else:
            p1 = (self.x, self.y, height)
        p2 = (self.p[0], self.p[1], 100)
        dist_points = (p1[0], p1[1])
        origin = (self.p[0], self.p[1])

        num_points = shotTrailData['numPoints']

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
            maxH = shotTrailData['apex_ft']
        elif self.st == "fg":
            maxH = shotTrailData['apex_2pt']
        elif self.st == "3pt":
            maxH = shotTrailData['apex_3pt']
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
                logging.info(evt["de"])
                logging.info(evt["pid"])
                if evt["pid"] in rebounds[evt["tid"]]:
                    rebounds[evt["tid"]][evt["pid"]] += 1
                else:
                    rebounds[evt["tid"]][evt["pid"]] = 1
                if "phi" in evt["de"]:
                    logging.info(rebounds)
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
        homePlayerdict = {}
        for player in playerNames:
            visitorPlayerDict[player['vls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']
            homePlayerDict[player['hls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']

        return homePlayerDict, visitorPlayerDict


# In[120]:


def writeTable(gameData, connection_string, gameID):
    shots = gameData["shots"]
    leaders = gameData["leaderboard"]
    # logging.info(gameData)
    operations = []
    for shot in shots:
        # logging.info(shot)
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


# In[121]:


# def pub2Queue(jsonData, gameID):
# credentials = pika.PlainCredentials('quintar', 'quintar123')
# parameters = pika.ConnectionParameters('20.231.253.196', 5672, '/', credentials)
# parameters = pika.ConnectionParameters('20.232.3.112', 5672, '/', credentials)
# connection = pika.BlockingConnection(parameters)
# channel = connection.channel()

#    channel.exchange_declare(exchange='tq6_exchange', exchange_type='fanout')
#    channel.queue_declare(queue='testq6', arguments={'x-message-ttl' : 30000})
#
#    message = json.dumps(jsonData)

#   channel.basic_publish(exchange='tq6_exchange', routing_key=str(gameID), body=message)
#   logging.info(" [x] Sent %r" % message)
#   connection.close()


# In[122]:


def main():
    logging.info('game chronicles received a request')
    connection_string = WRITE_CONNECTION_STRING
    leagueID = 'nba'
    result = getParams()
    logging.info(result)
    liveSimulator = result[1]
    gameID = result[0]['gid']
    for i in range(0, 3):
        logging.info(f"GAME ID = {gameID}")
    evtID = 0

    # gameID = '0042100405'
    # homePlayerDict, visitorPlayerDict = getPlayerName("vegas", gameID)
    # operations = []
    if liveSimulator == 0:
        with TableClient.from_connection_string(connection_string, table_name="Game") as table:
            try:
                logging.info("STEP-1")
                gamesFilter = f"PartitionKey eq '{gameID}'"
                gameEntity = table.query_entities(query_filter=gamesFilter)
                logging.info("STEP-2")
                count = 0
                logging.info(f'COUNT = {count}')
                logging.info((gameEntity))
                for entity in gameEntity:
                    count += 1
                    logging.info(f'COUNT = {count}')
                    entity.pop("RowKey", None)
                    entity.pop("PartitionKey", None)
                    gameDetails = entity
                    logging.info("STEP-3")
                tids = [gameDetails["hid"], gameDetails["vid"]]
                hTid = gameDetails["hid"]
                logging.info("WE LAND HERE???? ARE YOU SURE??")
            except:
                logging.info("ARE WE IN TROUBLE????")
                return (f"Failed to get games data")

        logging.info("HERE I AM!")
        # gameID = gameID_orig

        try:
            with TableClient.from_connection_string(connection_string, table_name="Team") as table:
                teams = []
                teamFilter = f"PartitionKey eq 'nba' and RowKey eq '{hTid}'"
                teamEntities = table.query_entities(query_filter=teamFilter)
                for teamEntity in teamEntities:
                    hTeam = teamEntity["ab"]
        except:
            return (f"Failed to get home team data")

        try:
            evtCount = 0
            quarter = 1
            de = "start period"
            gameOn = True
            shots = []
            for i in range(0, 10):
                logging.info(de)

            points = {tids[0]: {}, tids[1]: {}}
            assists = {tids[0]: {}, tids[1]: {}}
            blocks = {tids[0]: {}, tids[1]: {}}
            rebounds = {tids[0]: {}, tids[1]: {}}
            steals = {tids[0]: {}, tids[1]: {}}
            shotInfoObj = shotInfo(gameID, hTeam)
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
                nxtUrl = liObj.nextURL
                # logging.info("LIVE INFO")
                # logging.info(liObj.events)
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
                #logData(json_data)
                logDataToAzureFile("logging_data.json")
                lenShots = len(shots)
                logging.info(f"LENGTH OF SHOTS = {lenShots}")
                if len(shots) > 0:
                    logging.info("WRITING NOW!!!!!!")
                    # pub2Queue(json_data, gameID)
                    evtCount += writeTable(json_data, connection_string, gameID)
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
            except HttpResponseError as e:
                #return ("Failed to add game-chronicles information")
                time.sleep(5)

        logging.info(f"HOME TEAM = {hTeam}")
        return f'Game Chronicles Data uploaded. No. of Events = {evtCount}'

    
    ##########################################
    
    
    else: # if it is a live game
        parser = argparse.ArgumentParser()
        parser.add_argument('-gid', '--gameID', required=True)
        parser.add_argument('-speed', '--speedValue', required=True)
        parser.add_argument('-delay', '--delayValue', required=True)
        parser.add_argument('-erase', '--eraseValue', default=1, required=True)
        parser.add_argument('-create', '--createValue', default=1, required=True)
        args = parser.parse_args()
        argsDict = vars(args)
        logging.info('game chronicles received a request')
        connection_string = os.environ["AzureWebJobsStorage"]
        
        if not args.gameID:  # replace all informationReq?
            gameID = result[0]['gid']
        else:
            gameID = int(arg.gameID)
        
        if not args.speedValue:
            scaleFactor = 1
        else:
            scaleFactor = int(args.speedValue)
            
        if not args.delayValue:
            delTime = 300
        else:
            delTime = int(args.delayValue)
        
        #if not informationReq.params.get('erase'):
            erase = 1  # always erase after dummy table is created
        #else:
         #   erase = int(informationReq.params.get('erase'))
            
        #if not informationReq.params.get('create'):
            ct = 1 # always create a table
        #else:
         #   ct = int(informationReq.params.get('create'))
        
        dataObj = getSampleGame(gameID = gameID, connection_string = connection_string, scaleFactor= scaleFactor, delTime= delTime, erase=erase, ct=ct)
        dataObj.streamlineData()
        
        # use the shot info to get the cl, use cl to get the delay

        with open("logging_data.json", "r") as f:
            data = json.load(f)
            events = data["g"]["pla"]
            clock = 12*60
            for dict in events:
                timeShotTaken = 0
                delayTime = 0
                if "shot" in dict["de"]:
                    writeTableLiveSim(gameData=dict["de"])  # writing table to simGameChronicles
                    timeShotTaken = dict["cl"]
                    shotInSeconds = sum(x * int(t) for x, t in zip([60, 1], timeShotTaken.split(":")))
                    delayTime = clock - shotInSeconds
                    clock -= timeShotTaken
                    time.sleep(delayTime)
                if "End Quarter" in dict["de"]:
                    time.sleep(120)
                    clock = 12*60

        return print('Result:', "Live SImulation ended")
    #logger = logging.getLogger()
    #logger.setLevel(logging.INFO)
# In[ ]:


if __name__ == "__main__":
    main()


# In[ ]:




