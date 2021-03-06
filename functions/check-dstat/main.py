# Copyright 2019 Google, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# [START run_pubsub_server_setup]
import base64
from flask import Flask, request
import os
import re
import pdb
import sys
import yaml
import json
import logging

import subprocess

from google.cloud import pubsub
from google.cloud import storage

app = Flask(__name__)
# [END run_pubsub_server_setup]

ENVIRONMENT = os.environ.get('ENVIRONMENT', '')
print(f"Environment: {ENVIRONMENT}.")
if ENVIRONMENT == 'google-cloud':
    FUNCTION_NAME = os.environ['FUNCTION_NAME']

    vars_blob = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    parsed_vars = yaml.load(vars_blob, Loader=yaml.Loader)

    # Runtime variables
    PROJECT_ID = parsed_vars.get('GOOGLE_CLOUD_PROJECT')
    DATA_GROUP = parsed_vars.get('DATA_GROUP')
    DB_TOPIC = parsed_vars.get('DB_QUERY_TOPIC')
    TRIGGER_TOPIC = parsed_vars.get('TOPIC_TRIGGERS')

    PUBLISHER = pubsub.PublisherClient()


def _dash_to_camelcase(word):
    return re.sub(r'(?!^)-([a-zA-Z])', lambda m: m.group(1).upper(), word)


def _format_pubsub_message(query, event_id, retry_count=None):
    message = {
               "header": {
                          "resource": "query",
                          "method": "POST",
                          "labels": ["Create", "Dstat", "Node", "Cypher", "Query"],
                          "sentFrom": FUNCTION_NAME,
                          "publishTo": TRIGGER_TOPIC,
                          "seedId": f"{event_id}",
                          "previousEventId": f"{event_id}"
               },
               "body": {
                        "cypher": query,
                        "result-mode": "data",
                        "result-structure": "list",
                        "result-split": "True",
               },
    }
    if retry_count:
        message['header']['retry-count'] = retry_count
    return message


def _create_query(dstat_cmd, dstat_json):
    # Parse dstat_json
    property_strings = []

    # Add node labels as a property that can be accessed by triggers
    property_strings.append('dstat.labels = ["Dstat", "Status"]')

    # Add dstat command to properties so can be requeued by trigger
    property_strings.append(f'dstat.command = "{dstat_cmd}"')

    # Convert script double quotes to single
    script = dstat_json.pop('script')
    script = script.replace("\"", "\'")
    property_strings.append(f'dstat.script = "{script}"')

    # Convert events from list of dicts to list of strings
    events = dstat_json.pop('events')
    formatted_events = []
    for event in events:
        formatted_events.append(str(event))
    property_strings.append(f'dstat.events= {formatted_events}')

    # Pop provider attributes to add all as properties
    provider_attributes = dstat_json.pop('provider-attributes')

    # Convert regions to list
    regions = provider_attributes.pop('regions')
    #### ERROR: Can't get it formatted correctly
    formatted_regions = []
    for region in regions:
        region = region.replace('"', "'")
        formatted_regions.append(region)
    property_strings.append(f'dstat.regions= {formatted_regions}')

    for key, value in provider_attributes.items():
        if not value:
            continue
        neo4j_key = _dash_to_camelcase(key)
        if isinstance(value, str):
            value = value.replace('"', "'")
            # Place new value in dstat dict for MERGE operations
            dstat_json[key] = value
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        elif isinstance(value, dict):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        else:
            property_strings.append(f'dstat.{neo4j_key}= {value}')

    # All other dstat items
    for key, value in dstat_json.items():
        if not value:
            continue

        neo4j_key = _dash_to_camelcase(key)
        if isinstance(value, str):
            value = value.replace('"', "'")
            # Place new value in dstat dict for MERGE operations
            dstat_json[key] = value
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        elif isinstance(value, dict):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        else:
            property_strings.append(f'dstat.{neo4j_key}= {value}')
    properties_string = ', '.join(property_strings)

    query = (
             f"MERGE (dstat:Dstat " +
              "{ " +
                f"instanceName:\"{provider_attributes['instance-name']}\", " +
                f"jobId:\"{dstat_json['job-id']}\" " +
              "}) " +
             f"ON CREATE SET {properties_string} " +
             f"ON MATCH SET dstat.statusMessage=\"{dstat_json['status-message']}\", " +
             f"dstat.status=\"{dstat_json['status']}\", " +
             f"dstat.statusDetail=\"{dstat_json['status-detail']}\", " +
             f"dstat.endTime=\"{dstat_json['end-time']}\", " +
             f"dstat.events={formatted_events} " +
              "RETURN dstat AS node")
    return query


def _publish_to_topic(topic, data):
    topic_path = PUBLISHER.topic_path(PROJECT_ID, topic)
    message = json.dumps(data).encode('utf-8')
    result = PUBLISHER.publish(topic_path, data=message).result()
    return result


# [START run_pubsub_handler]
@app.route('/', methods=['POST'])
def get_dstat_result():
    envelope = request.get_json()
    if not envelope:
        msg = 'no Pub/Sub message received'
        print(f'error: {msg}')
        return f'Bad Request: {msg}', 400

    if not isinstance(envelope, dict) or 'message' not in envelope:
        msg = 'invalid Pub/Sub message format'
        print(f'error: {msg}')
        return f'Bad Request: {msg}', 400

    pubsub_message = envelope['message']
    message_id = pubsub_message['message_id']
    trunc_id = message_id[-7:]
    print(f"{trunc_id}> Received pubsub message: {pubsub_message}.")

    if isinstance(pubsub_message, dict) and 'data' in pubsub_message:
        data = base64.b64decode(pubsub_message['data']).decode('utf-8').strip()
        data = json.loads(data)
        print(f"{trunc_id}> Data: {data}.\n")
        header = data['header']
        body = data['body']

        retry_count = header.get('retry-count')

        dstat_cmd = body['command']

    try:
        dstat_results = subprocess.check_output(dstat_cmd, stderr=subprocess.STDOUT, shell=True)
    except:
        logging.error(f"{trunc_id}> Error: could not run dstat command {dstat_cmd}.")
        return('', 204)

    print(f"{trunc_id}> Dstat results: {dstat_results}.")
    try:
        json_results = json.loads(dstat_results)
    except:
        logging.error(f"{trunc_id}> Could not load dstat result as json.")
        return('', 204)
    print(f"{trunc_id}> Json result: {json_results}.")

    for json_result in json_results:
        # Only update database once job has stopped
        #if json_result["status"] == "RUNNING":
        #    continue
        query = _create_query(dstat_cmd, json_result)
        message = _format_pubsub_message(
                                         query = query,
                                         event_id = message_id,
                                         retry_count = retry_count)
        print(f"{trunc_id}> Pubsub message: {message}.")
        result = _publish_to_topic(DB_TOPIC, message)
        print(f"{trunc_id}> Published message to {DB_TOPIC} with result: {result}.")

    # Flush the stdout to avoid log buffering.
    sys.stdout.flush()

    return ('', 204)
# [END run_pubsub_handler]
