import schedule
import time
import json
import csv
import requests
import logging
import sys
import os
import boto3
import sqlite3
import datetime
import socket

from datetime import datetime

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger('Service Discovery')

sns = boto3.client('sns')
topicArn = os.environ['topicArn']
notification_send_period = os.environ['notification_send_period']+' minutes'

def watchlist():
    services = []
    with open('/config/watchlist.csv', 'r') as watchlist:
        for service in watchlist:
            (name, protocol, host, port) = service.split(',')
            services.append((name.strip(), protocol.strip(), host.strip(), port.strip()))
    return services

def httpcheck(service):
    (name, protocol, host, port) = service
    URI = "{0}://{1}:{2}".format(protocol,host,port)
    try:
        response = requests.get(URI)
        if response.status_code == 200:
            logger.info("SUCCESS connection to <{0}:{1}://{2}:{3}>".format(name, protocol, host, port))
        else:
            endpoint="<{0}:{1}>".format(name, port)
            sendNotification( endpoint, datetime.now())
            logger.error("FAILURE connecting to <{0}:{1}://{2}:{3}>".format(name, protocol, host, port))
    except:
        endpoint="<{0}:{1}>".format(name, port)
        sendNotification( endpoint, datetime.now())
        logger.error("EXCEPT: FAILURE connecting to <{0}:{1}://{2}:{3}>".format(name, protocol, host, port))

def tcpcheck(service):
    (name, protocol, host, port) = service
    s = socket.socket()
    tcp_port=int("{0}".format(port))
    tcp_host="{0}".format(host)
    try:
        s.connect((tcp_host, tcp_port)) 
        logger.info("TCPCHECK: SUCCESS connection to <{0}:{1}://{2}:{3}>".format(name, protocol, host, port))
    except:
        endpoint="<{0}:{1}>".format(name, port)
        sendNotification( endpoint, datetime.now())
        logger.error("TCPCHECK: FAILURE connecting to <{0}:{1}://{2}:{3}>".format(name, protocol, host, port))
    finally:
        s.close()

def sendNotification(endpoint,timestamp):
    insert_failure = """INSERT INTO 'failed_checks'
                          ('endpoint', 'timestamp') 
                          VALUES (?, ?);"""
    select_last_failures = """SELECT endpoint, timestamp from failed_checks
                            WHERE timestamp > datetime('now','localtime', '{period}')
                            AND endpoint = (?);""".format(period=notification_send_period)
    need_to_delete = """SELECT endpoint, timestamp from failed_checks
                        WHERE timestamp < datetime('now','localtime', '{period}')
                        AND endpoint = (?);""".format(period=notification_send_period)
    try:
        sqliteConnection = sqlite3.connect('SQLite_Python.db')
        cursor = sqliteConnection.cursor()
        cursor.execute(need_to_delete, (endpoint,))
        recordsq = cursor.fetchall()      
        for row in recordsq:
            expired_record=row[0]        
            deleteRecord(expired_record)     
        cursor.execute(select_last_failures, (endpoint,))
        records = cursor.fetchall() 
        if (len(records) > 0 and len(recordsq) == 0):
            logger.info("Notification for {0} was sent earlier. Skipping...".format(endpoint))
        elif (len(records) > 0 and len(recordsq) > 0):
            logger.info("Sending notification about {0}".format(endpoint))
            msg="FAILURE connecting to {0}".format(endpoint)
            logger.error(msg)
            sns.publish(TopicArn=topicArn, Message=msg)              
        else:
            logger.info("Sending notification about {0}".format(endpoint))
            msg="FAILURE connecting to {0}".format(endpoint)
            logger.error(msg)
            sns.publish(TopicArn=topicArn, Message=msg)            



        cursor.execute(insert_failure, (endpoint, timestamp,))
        sqliteConnection.commit()
        cursor.close()
    except sqlite3.Error as error:
        logger.error("Error while working with SQLite", error)
    finally:
        if (sqliteConnection):
            sqliteConnection.close()       

def deleteRecord(expired_record):
    try:
        sqliteConnection = sqlite3.connect('SQLite_Python.db')
        cursor = sqliteConnection.cursor()
        delete_last_failures = """DELETE from failed_checks
                                    WHERE endpoint=?;"""
        cursor.execute(delete_last_failures, (expired_record,))
        sqliteConnection.commit()
        cursor.close()

    except sqlite3.Error as error:
        logger.error("Failed to delete record from sqlite table", error)
    finally:
        if (sqliteConnection):
            sqliteConnection.close()
            logger.info("records was deleted")

def healthcheck():
    services = watchlist()
    for service in services:
        _, protocol, _, _ = service
        if protocol.upper() in  ["HTTP", "HTTPS"]: 
            httpcheck(service)
        elif protocol.upper() == "TCP":
            tcpcheck(service)
        else: 
            logger.error("PROTOCOL {0} is not supported".format(protocol))


def init_db():
    sqliteConnection = sqlite3.connect('SQLite_Python.db')
    cursor = sqliteConnection.cursor()
    sqlite_create_table_query = '''CREATE TABLE failed_checks (
                                       endpoint TEXT NOT NULL,
                                       timestamp timestamp);'''
    cursor.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='failed_checks' ''')
    if cursor.fetchone()[0]==1 :
        logger.info("Table exists.")
           
    else:
        cursor.execute(sqlite_create_table_query)
        sqliteConnection.commit()
        logger.info("Table created successfully ")
        cursor.close() 
    sqliteConnection.commit()
    sqliteConnection.close()


def main():

    init_db()

    try:
        interval = os.environ['INTERVAL']
    except:
        interval = 0.5
    schedule.every(interval).minutes.do(healthcheck)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()