import os
import re
import pdb
import sys
import json
import pytz
import yaml
import base64
import iso8601

from datetime import datetime

from google.cloud import storage
from google.cloud import pubsub

# Get runtime variables from cloud storage bucket
# https://www.sethvargo.com/secrets-in-serverless/
ENVIRONMENT = os.environ.get('ENVIRONMENT', '')
if ENVIRONMENT == 'google-cloud':
    FUNCTION_NAME = os.environ['FUNCTION_NAME']

    vars_blob = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    parsed_vars = yaml.load(vars_blob, Loader=yaml.Loader)

    # Runtime variables
    PROJECT_ID = parsed_vars.get('GOOGLE_CLOUD_PROJECT')
    DB_TOPIC = parsed_vars.get('DB_QUERY_TOPIC')
    KILL_DUPS_TOPIC = parsed_vars.get('KILL_DUPS_TOPIC')
    DATA_GROUP = parsed_vars.get('DATA_GROUP')

    PUBLISHER = pubsub.PublisherClient()


class InsertOperation:

    def __init__(self, data):

        self.name = None
        self.id = None
        self.machine_type = None
        self.start_time = None
        self.start_time_epoch = None
        self.zones = None
        self.project = None
        self.task_id = None 
        self.job_name = None
        self.sample = None
        self.plate = None
        self.status = "running"

        payload = data['protoPayload']
        resource = data['resource']

        # Get task ID from request labels
        # labels: [{0: {key: "trellis-id", value: "1907-5fxf7"}}]
        labels = payload['request']['labels']
        for label in labels:
            if label['key'] == 'trellis-id':
                self.task_id = label['value']
            elif label['key'] == 'sample':
                self.sample = label['value']
            elif label['key'] == 'job-name':
                self.job_name = label['value']
            elif label['key'] == 'plate':
                self.plate = label['value']

        self.name = payload['request']['name']

        machine_type = payload['request']['machineType']
        self.machine_type = machine_type.split('/')[-1]

        self.id = resource['labels']['instance_id']
        self.zone = resource['labels']['zone']
        self.project = resource['labels']['project_id']

        self.start_time = data['timestamp']

        timestamp = get_datetime_iso8601(data['timestamp'])
        self.start_time_epoch = get_seconds_from_epoch(timestamp)


    def compose_query(self):
        query = (
            "MERGE (node:Instance {taskId: " + 
                    f"\"{self.task_id}\"" + 
                    "}) " + 
            "ON CREATE SET " +
            f"node.status = \"{self.status}\", " +
            f"node.instanceName = \"{self.name}\", " +
            f"node.instanceId = {self.id}, " +
            f"node.sample = \"{self.sample}\", " +
            f"node.jobName = \"{self.job_name}\", " + 
            f"node.plate = \"{self.plate}\", " +
            f"node.startTime = \"{self.start_time}\", " +
            f"node.startTimeEpoch = {self.start_time_epoch}, " +
            f"node.project = \"{self.project}\", " +
            f"node.zone = \"{self.zone}\", " +
            f"node.machineType = \"{self.machine_type}\", " +
            f"node.duplicateNameZones = [] " +
            "ON MATCH SET " +
            "node.duplicateNameZones = node.duplicateNameZones + " +
                                        f"\"{self.name},{self.zone}\" " +
            "RETURN node")
        return query


class DeleteOperation:

    def __init__(self, data):

        self.name = None
        self.id = None
        self.stop_time = None
        self.stop_time_epoch = None
        self.status = "stopped"

        payload = data['protoPayload']
        resource = data['resource']

        # resourceName provides entire project path
        name = payload['resourceName']
        self.name = name.split('/')[-1]

        #self.name = payload['resource']['name']
        self.id = resource['labels']['instance_id']

        self.stop_time = data['timestamp']
        timestamp = get_datetime_iso8601(data['timestamp'])
        self.stop_time_epoch = get_seconds_from_epoch(timestamp)


    def compose_query(self):
        query = (
                 "MATCH (node:Instance) " +
                f"WHERE node.instanceId = {self.id} " +
                f"AND node.instanceName = \"{self.name}\" " +
                f"SET node.stopTime = \"{self.stop_time}\", " +
                f"node.stopTimeEpoch = {self.stop_time_epoch}, " + 
                 "node.status = \"stopped\", " +
                 "node.durationMinutes = " +
                    "duration.inSeconds(datetime(node.startTime), datetime(node.stopTime)).minutes " +
                 "RETURN node")
        return query


def format_pubsub_message(query, publish_to=None, perpetuate=None):
    message = {
               "header": {
                          "resource": "query",
                          "method": "POST", 
                          "labels": ['Job', 'Create', 'Node', 'Query', 'Cypher'], 
                          "sentFrom": f"{FUNCTION_NAME}",
               },
               "body": {
                        "cypher": query, 
                        "result-mode": "data",
                        "result-structure": "list",
                        "result-split": "True",
                },
    }
    if publish_to:
        extension = {"publishTo": publish_to}
        message['header'].update(extension)
    if perpetuate:
        extension = {"perpetuate": perpetuate}
        message['body'].update(extension)
    return message


def publish_to_topic(topic, data):
    topic_path = PUBLISHER.topic_path(PROJECT_ID, topic)
    message = json.dumps(data).encode('utf-8')
    result = PUBLISHER.publish(topic_path, data=message).result()
    return result


def get_seconds_from_epoch(datetime_obj):
    """Get datetime as total seconds from epoch.

    Provides datetime in easily sortable format

    Args:
        datetime_obj (datetime): Datetime.
    Returns:
        (float): Seconds from epoch
    """
    from_epoch = datetime_obj - datetime(1970, 1, 1, tzinfo=pytz.UTC)
    from_epoch_seconds = from_epoch.total_seconds()
    return from_epoch_seconds


def get_datetime_iso8601(date_string):
    """ Convert ISO 86801 date strings to datetime objects.

    Google datetime format: https://tools.ietf.org/html/rfc3339
    ISO 8601 standard format: https://en.wikipedia.org/wiki/ISO_8601
    
    Args:
        date_string (str): Date in ISO 8601 format
    Returns
        (datetime.datetime): Datetime objects
    """
    return iso8601.parse_date(date_string)


def update_job_status(event, context):
    """When object created in bucket, add metadata to database.
    Args:
        event (dict): Event payload.
        context (google.cloud.functions.Context): Metadata for the event.
    """

    #print(f"> Processing new Pub/Sub message: {context['event_id']}.")
    print(f"> Context: {context}.")
    pubsub_message = base64.b64decode(event['data']).decode('utf-8')
    data = json.loads(pubsub_message)
    print(f"> Data: {data}.")

    # Handle insert cases
    insert_type = 'type.googleapis.com/compute.instances.insert'
    delete_type = 'type.googleapis.com/compute.instances.delete'

    insert = False
    request_type = data['protoPayload']['request']['@type']
    if request_type == insert_type:
        job_op = InsertOperation(data)
        insert = True
    elif request_type == delete_type:
        job_op = DeleteOperation(data)
    else:
        raise ValueError(f"Request type not supported: {request_type}.")
    query = job_op.compose_query()

    print(f"> Database query: \"{query}\".")

    if insert:
        message = format_pubsub_message(query, publish_to=KILL_DUPS_TOPIC)
    else:
        message = format_pubsub_message(query)
    print(f"> Pubsub message: {message}.")

    result = publish_to_topic(DB_TOPIC, message)
    print(f"> Published message to {DB_TOPIC} with result: {result}.")
    

if __name__ == "__main__":
    # Run unit tests in local
    PROJECT_ID = "gbsc-gcp-project-mvp-dev"
    DB_TOPIC = "wgs35-db-queries"
    KILL_DUPS_TOPIC = "wgs35-kill-duplicate-jobs"
    DATA_GROUP = "wgs35"
    FUNCTION_NAME = "wgs35-update-job-status"

    PUBLISHER = pubsub.PublisherClient()
    
    # Insert operation
    with open("insert_data_sample.json", "r") as fh:
        data = json.load(fh)
    data = json.dumps(data).encode('utf-8') 
    event = {'data': base64.b64encode(data)}
    context = {'test': 123}
    update_job_status(event, context)

    pdb.set_trace()

    # Delete operation
    with open("delete_data_sample.json", "r") as fh:
        data = json.load(fh)
    data = json.dumps(data).encode('utf-8')
    event = {'data': base64.b64encode(data)}   
    context = {'event_id': 611225247182937, 'timestamp': '2019-07-10T04:11:53.865Z', 'event_type': 'google.pubsub.topic.publish', 'resource': {'service': 'pubsub.googleapis.com', 'name': 'projects/gbsc-gcp-project-mvp-test/topics/wgs35-update-vm-status', 'type': 'type.googleapis.com/google.pubsub.v1.PubsubMessage'}}

    update_job_status(event, context)
