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

DEV_CONNECTION = "DefaultEndpointsProtocol=https;AccountName=nbadatalakedev;AccountKey=Gs49jwtBv2AaK6MTJnlc2iiqc1yCbZKVliwGveYkjbF+f1mjSukpnUk07RaWkCMqP4VOk5bh+bucVtMdhT3x2g==;EndpointSuffix=core.windows.net"
STAG_CONNECTION = "DefaultEndpointsProtocol=https;AccountName=nbadatalakestag;AccountKey=W6zvjH5eVmnMEZnGy8DvY3G24TvdeB+mBXZ8hguUjSTkPKuxNfLE/BvJdgKo54kbhIZSOkQaolIX+AStoshxaA==;EndpointSuffix=core.windows.net"
PROD_CONNECTION = "DefaultEndpointsProtocol=https;AccountName=nbadatalakeprod;AccountKey=bdrJN2qPorn3BLaog07RQM++Gxw46ZZc9SzGSMc5QYSpxYvJ4v3HpBS5OhT2OWYtpoK5Bs12Q3iL+AStggiIbA==;EndpointSuffix=core.windows.net"

CONTAINER_NAME = "nba"

JSON_FILE_PATH = "nba_sdk/nbaIngestParams_" + sys.argv[1].lower() + ".json"

LOG_PATH = "sport-data/games/"

CFG_CONNECTION = DEV_CONNECTION

def getParams():    
    blob_service_client = BlobServiceClient.from_connection_string(CFG_CONNECTION)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    file_client = container_client.get_blob_client(JSON_FILE_PATH)
    streamdownloader = file_client.download_blob()
    ingestParams = json.loads(streamdownloader.readall())
    
    if ingestParams["ENVIRONMENT"].lower() == "dev":
        CONNECTION_STRING = DEV_CONNECTION
    elif ingestParams["ENVIRONMENT"].lower() == "stag":
        CONNECTION_STRING = STAG_CONNECTION
    elif ingestParams["ENVIRONMENT"].lower() == "prod":
        CONNECTION_STRING = PROD_CONNECTION
    
    params = {"WRITE_CONNECTION_STRING" : CONNECTION_STRING,
              "MODE" : ingestParams["MODE"],
              "SIM_PARAMS" : ingestParams["SIM_PARAMS"],
              "LOG_LEVEL" : ingestParams["LOG_LEVEL"],
              "LEAGUE_ID" : ingestParams['LEAGUE_ID'],
              "SEASON" : ingestParams["SEASON"],
              "GAME_ID" : ingestParams['GAME_ID'],
              "SHOT_TRAIL_PARAMS" : ingestParams['SHOT_TRAIL_PARAMS'],
              "SIMULATION_GAME_ID" : ingestParams['SIMULATION_GAME_ID']}

    return params

class liveInfo:
    def __init__(self, gameID, quarter, leagueID, MODE, season):
        self.gameID = gameID
        urlInfo = str(str(self.gameID) + "_" + str(quarter))
        self.url = "http://data.nba.com/data/5s/v2015/json/mobile_teams/" + leagueID + "/" + season + "/scores/pbp/" + urlInfo + "_pbp.json"

        logging.info(self.url)
        self.MODE = MODE
        while True:
            try:
                c = urlopen(self.url)
                break
            except Exception as e:
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
                if self.MODE == 2:
                    newData = [newData[0]]
                    newEvt = newData[0]["evt"]
                    logging.info(f'EVENT NEXT : {newEvt}')
                    logging.info(f"NEW DATA: {newEvt}")
                break
            else:
                logging.info("WAITING FOR NEW DATA")
                logging.info(f'EVENT ID : {evtID}')
                

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
                logging.debug(f'RELDATAT : {relData}')
                self.events.append(relData)
                if de == "end period":
                    break
            logging.debug(self.events)
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

    def getTrace(self, pid, leagueID, season):
        if leagueID.lower() == "vegas":
            lid = "15"
        elif leagueID.lower() == "nba":
            lid = "00"
        try:
            playerURL = "http://data.nba.com/data/10s/v2015/json/mobile_teams/" + leagueID.lower() + "/" + str(season) + "/players/" + lid + "_player_info.json"
            playerInfo = urlopen(playerURL)
            
            playersData = json.loads(playerInfo.read())["pls"]["pl"]
            for player in playersData:
                if player["pid"] == pid:
                    plHT = player["ht"]
        
            offset = self.shotTrailParams['startHeightOffset']
            height = (int(plHT.split("-")[0]) * 10) + math.floor(
                (float(plHT.split("-")[1]) / 12) * 10) + offset
            
            #height = 25

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
        except Exception as e:
            logging.error(f"GET TRACE METHOD EXCEPTION : {e}")
            #sys.exit(0)

    def getEvtData(self, tids, qData, shots, points, assists, blocks, rebounds, steals, leagueID, season):
        try:
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

                    self.getTrace(evt["pid"], leagueID, season)
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
            logging.info(f"SHOTS : {shots}")
            logging.info(f"Points : {points}")
            logging.info(f"Assists : {assists}")
            logging.info(f"Blocks : {blocks}")
            logging.info(f"Rebounds : {rebounds}")
            logging.info(f"Steals : {steals}")
            return shots, points, assists, blocks, rebounds, steals
        except Exception as e:
            logging.error(f"GET EVENT METHOD EXCEPTION : {e}")

    def leaderBoard(self, tids, points, assists, blocks, rebounds, steals, leagueID, season):
        leaderboardData = []
        cats = ["PTS", "AST", "BLK", "REB", "STL"]
        
        if leagueID == "vegas":
            lid = "15"
        elif leagueID == "nba":
            lid = "00"
        
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
                    try:
                        playerURL = "http://data.nba.com/data/10s/v2015/json/mobile_teams/" + leagueID.lower() + "/" + str(season) + "/players/" + lid + "_player_info.json"
                        playerInfo = urlopen(playerURL)
                        logging.info(playerInfo)
                        playersData = json.loads(playerInfo.read())["pls"]["pl"]
                        for player in playersData:
                            if player["pid"] == pid:
                                playerFN = player["fn"]
                                playerSN = player["ln"]
                    except:
                        playerFN = "First"
                        playerSN = "Last"
                    # playerData = {"pl": {"ln": "Parsons", "fn": "Jim"}}
                    pl_hs = "https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/" + str(
                        pid) + ".png"
                    leader = {"cat": cats[i], "fn": playerFN, "sn": playerSN,
                              "pid": int(pid), "scr": scr, "hs": pl_hs}
                else:
                    pid = 0
                    scr = 0
                    leader = {"cat": cats[i], "fn": "N/A", "sn": "N/A", "pid": pid, "scr": scr, "hs": ""}
                teamLeaders.append(leader)
            leaderboardData.append({"tid": tid, "teamLeaders": teamLeaders})
        return leaderboardData

    def getPlayerName(leagueID, gameID, season):
        pc_url = "http://data.nba.com/data/5s/v2015/json/mobile_teams/" + leagueID.lower() + "/" + season + "/scores/gamedetail/" + gameID + ".json"
        response = urlopen(pc_url)
        playerNames = json.loads(response.read())
        visitorPlayerDict = {}
        homePlayerDict = {}
        for player in playerNames:
            visitorPlayerDict[player['vls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']
            homePlayerDict[player['hls']['pid']] = player['pstsg']['fn'] + " " + player['pstsg']['fn']

        return homePlayerDict, visitorPlayerDict

class dataOutput:
    def __init__(self, GAME_ID):
        logging.info("Data Writing!")
        self.logChronicles = str(GAME_ID) + "_gameData_formatted.json" 
        self.sqShots = []
        self.sqLeaders = []
    
    def log2File(self):
        try:
            logging.info(f'Writing to {self.logChronicles}')
            gameData = {"shots" : self.sqShots, "gameLeaders" : self.sqLeaders}
            with open(self.logChronicles, 'w') as logChronicles:
                json.dump(gameData, logChronicles)
        
            blob_service_client = BlobServiceClient.from_connection_string(DEV_CONNECTION)
            container_client = blob_service_client.get_container_client(CONTAINER_NAME)
            UPLOAD_FILE_PATH = LOG_PATH + self.logChronicles
            file_client = container_client.get_blob_client(UPLOAD_FILE_PATH)
            file_client.upload_blob(json.dumps(gameData))
        except Exception as e:
            logging.error(f"EXCEPTION IN LOG2FILE: {e}")
                
        
    def writeTable(self, gameData, connection_string, gameID):
        shots = gameData["shots"]
        leaders = gameData["leaderboard"]
        logging.debug(gameData)
        operations = []
        for shot in shots:
            logging.debug(shot)
            shot['PartitionKey'] = str(gameID)
            shot['RowKey'] = str(shot['eid'])
            shot['trace'] = "".join(str(shot['trace']))
            operations.append(("upsert", shot))
            self.sqShots.append(shot)
            EID =  shot['eid']

        with TableClient.from_connection_string(connection_string, table_name="GameChronicle") as table:
            try:
                logging.info("WRITING TO TABLE")
                try:
                    for i in range(0, len(operations), 100):
                        operation = list(operations[i:i + 100])
                        lastTask = operation[-1]
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
                    logging.debug(f'LEADERS : {leader}')
                    leader['PartitionKey'] = str(gameID)
                    leader['RowKey'] = str(team['tid']) + '_' + leader['cat']  # + '_' + str(eid)
                    leader['eid'] = EID
                    self.sqLeaders.append(leader)
                    if leader:
                        with TableClient.from_connection_string(connection_string, table_name="LeaderBoard") as table:
                            try:
                                # add new entity if it does not exist. update if the entity exists
                                createdEntity = table.upsert_entity(mode=UpdateMode.MERGE, entity=leader)
                                logging.debug(createdEntity)
                                # Return http response
                                updateStatus = 1
                            except HttpResponseError:
                                updateStatus = 0
                                return ("Failed to add/update game leaders")
                    else:
                        return ("Failed to add/update game leaders")
            
        return len(shots)



    def pub2Queue(self, jsonData, gameID):
        try:
            credentials = pika.PlainCredentials('quintar', 'quintar123')
            #parameters = pika.ConnectionParameters('20.231.253.196', 5672, '/', credentials)
            parameters = pika.ConnectionParameters('20.121.92.76', 5672, '/', credentials)
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()

            channel.exchange_declare(exchange='tq6_exchange', exchange_type='fanout')
            channel.queue_declare(queue='rabbit_test', arguments={'x-message-ttl' : 30000})
            message = json.dumps(jsonData)

            channel.basic_publish(exchange='tq6_exchange', routing_key=str(gameID), body=message)
            logging.info(" [x] Sent %r" % message)
            connection.close()
        except Exception as e:
            logging.error(f"EXCEPTION IN PUBLISH : {e}")
            
class simMethods:
    def __init__(self, GAME_ID, SIM_PARAMS, WRITE_CONNECTION_STRING):
        logging.info("RUNNING IN SIMULATOR MODE")
        logging.info(f'SIMULATING GAME: {GAME_ID}')
        
        self.connection_string = WRITE_CONNECTION_STRING
        self.scaleFactor = SIM_PARAMS["SPEED"]
        self.delTime = SIM_PARAMS["DELAY"]
        
        ARCHIVED_FILE = LOG_PATH + GAME_ID + "_gameData_formatted.json"
         
        blob_service_client = BlobServiceClient.from_connection_string(DEV_CONNECTION)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)
        file_client = container_client.get_blob_client(ARCHIVED_FILE)
        streamdownloader = file_client.download_blob()
        gameData = json.loads(streamdownloader.readall())
        shots = gameData["shots"]
        gameLeaders = gameData["gameLeaders"]
        
        self.shotsDF = pd.DataFrame.from_dict(shots)
        self.leadersDF = pd.DataFrame.from_dict(gameLeaders)
        self.shotsDF.PartitionKey = "9876543210"
        self.leadersDF.PartitionKey = "9876543210"
        lastEvent = int(self.shotsDF["eid"].iloc[-1])
        
        
        logging.debug(f'SHOTS : {self.shotsDF}')
        logging.debug(f'GAME LEADERS : {self.leadersDF}')
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
        
    def delEntries(self, tableName):
        gameID = "9876543210"
        qFilter = f"PartitionKey eq '{gameID}'"
        with TableClient.from_connection_string(self.connection_string, table_name=tableName) as table:
            tableEntities = table.query_entities(query_filter=qFilter)
            for entity in tableEntities:
                logging.info(f"ENTITY : {entity}")
                PartitionKey = str(entity["PartitionKey"])
                RowKey = str(entity["RowKey"])
                table.delete_entity(PartitionKey, RowKey)
    
    def streamlineData(self):
        self.getDeltas()
        shots = self.shotsDF.to_dict("records")
        tables = ["simGameChronicle", "simLeaderBoard"]
        for tableName in tables:
            self.delEntries(tableName)
        
        for pos in range(0, len(self.shotsDF)):
            gameData = shots[pos]
            self.writeTable(gameData=gameData)
            timeDelta = self.timeDF.iloc[pos]["tr"] / self.scaleFactor
            logging.debug(f'TIME DELTA : {timeDelta}')
            time.sleep(timeDelta)

        #logging.info(self.delTime)
        #time.sleep(self.delTime)
        #self.eraseTable()
            
    
    def writeTable(self, gameData):
        shot = gameData
        shotOperation = [("upsert", shot)]
        gameID = "9876543210"
        shot['PartitionKey'] = gameID
        shot['RowKey'] = str(shot['eid'])
        shot['trace'] = "".join(str(shot['trace']))
        shot['gid'] = gameID

        with TableClient.from_connection_string(self.connection_string, table_name="simGameChronicle") as gcTable:
            logging.info("WRITING TO TABLE")
            try:
                gcTable.submit_transaction(shotOperation)
                logging.info("SUBMIT TRANSACTION PASSED")
            except Exception as e:
                logging.info("SUBMIT TRANSACTION FAILED")
                logging.info(f"EXCEPTION : {e}")
        
        logging.info(shotOperation)
        
        currentLeaders = self.leadersDF[self.leadersDF["eid"] == shot["eid"]]
        logging.info(currentLeaders)
        leaderOperation = []
        for leader in currentLeaders.to_dict("records"):
            leaderOperation.append(("upsert", leader))
        logging.info(leaderOperation)
        with TableClient.from_connection_string(self.connection_string, table_name="simLeaderBoard") as lbTable:
            logging.info("CURRENT LEADERS")
            logging.info(currentLeaders)
            try:
                lbTable.submit_transaction(leaderOperation)
            except Exception as e:
                logging.error(f"ERROR : {e}")
    
class ingestMethods:
    def __init__(self):
        logging.info('######################################################################################')
        logging.info('NBA DATA INGEST PIPELINE INITIATED!!!')

    
    def getGames(self, params):
        league = params["LEAGUE_ID"]
        season = params["SEASON"]
        if league == "nba":
            lid = "00"
        elif league == "vegas":
            lid = "15"
        gameIDs = []
        scheduleURL = "http://data.nba.com/data/v2015/json/mobile_teams/" + league + "/" + season + "/league/" + lid +"_full_schedule.json"
        response = urlopen(scheduleURL)
        for leagueData in json.loads(response.read())["lscd"]:
            for gameData in leagueData["mscd"]["g"]:
                gameIDs.append(gameData["gid"])
            logging.info(gameIDs)
        return gameIDs

    def ingestPipeline(self, params, gameID):
        logging.info(f'USING PARAMETERS : {params}')
        WRITE_CONNECTION_STRING = params['WRITE_CONNECTION_STRING']
        leagueID = params['LEAGUE_ID']
        #gameID = params['GAME_ID']
        evtID = 0
        opObj = dataOutput(gameID)

        if params["MODE"] == 0 or params["MODE"] == 2: # LIVE MODE OR ARCHIVAL MODE FOR OLD GAMES
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
                    liObj = liveInfo(gameID, quarter, leagueID, params["MODE"], params["SEASON"])
                    evtID, period, de = liObj.getData(evtID, de)
                    logging.info(f"DESCRIPTION : {de}")
                    #nxtUrl = liObj.nextURL

                    shots, points, assists, blocks, rebounds, steals = shotInfoObj.getEvtData(tids, liObj.events, shots,
                                                                                              points, assists, blocks,
                                                                                              rebounds, steals, leagueID, params["SEASON"])
                    leaders = shotInfoObj.leaderBoard(tids, points, assists, blocks, rebounds, steals, leagueID, params["SEASON"])
                    printStr = "DESCRIPTION : " + de.lower()
                    evtIDstr = "EVENT ID = " + str(evtID)
                    logging.info(printStr)
                    logging.info(evtIDstr)
                    json_data = {"shots": shots, "leaderboard": leaders}
                    lenShots = len(shots)
                    logging.info(f"LENGTH OF SHOTS = {lenShots}")
                    if len(shots) > 0:
                        logging.info("WRITING NOW!!!!!!")
                        opObj.pub2Queue(json_data, gameID)
                        evtCount += opObj.writeTable(json_data, WRITE_CONNECTION_STRING, gameID)
                        #evtCount += opObj.writeTable(json_data, CFG_CONNECTION, gameID)
                        logging.info(gameStatus)
                    if (de.lower() == "end period" and period != 4):
                        logging.info("CHANGE PERIOD")
                        quarter += 1
                    lastEvt = "LAST EVENT = " + str(evtID)
                    logging.info(lastEvt)
                    if (period == 4 and de.lower() == "end period"):
                        #logging.info(json_data["shots"][-1]["de"])
                        gameOn = False
                        break
                    time.sleep(1)
                except Exception as e:
                    logging.error(f"MAIN METHOD EXCEPTION : {e}")
                    time.sleep(5)
                    break
            if params["MODE"] == 2:
                opObj.log2File()

            return f'Game Chronicles Data uploaded. No. of Events = {evtCount}'
    
        elif params["MODE"] == 1: # SIMULATOR MODE
            simObj = simMethods(params["SIMULATION_GAME_ID"], params["SIM_PARAMS"], WRITE_CONNECTION_STRING)
            for i in range(0, params["SIM_PARAMS"]["REPEAT"]):
                simObj.streamlineData()

def main():
    params = getParams()
    MODE = params["MODE"]
    imObj = ingestMethods()
    season = params["SEASON"]
    league = params["LEAGUE_ID"]
    if MODE in [0, 1, 2]:
        imObj.ingestPipeline(params, params["GAME_ID"])
    elif MODE == 4:
        logging.info("RUNNING IN ARCHIVAL MODE")
        logging.info(f"SEASON : {season}, LEAGUE : {league}")
        params["MODE"] = 2
        gameIDs = imObj.getGames(params)
        for gameID in gameIDs:
            imObj.ingestPipeline(params, gameID)

if __name__ == "__main__":
    main()