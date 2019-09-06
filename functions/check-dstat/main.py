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
import json

import subprocess

from google.cloud import pubsub
from google.cloud import storage

app = Flask(__name__)
# [END run_pubsub_server_setup]

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
    TOPIC = parsed_vars.get('DB_QUERY_TOPIC')
    DATA_GROUP = parsed_vars.get('DATA_GROUP')

    PUBLISHER = pubsub.PublisherClient()


def dash_to_camelcase(word):
    return re.sub(r'(?!^)-([a-zA-Z])', lambda m: m.group(1).upper(), word)

def format_pubsub_message(query):
    message = {
               "header": {
                          "resource": "query", 
                          "method": "POST",
                          "labels": ["Create", "Dstat", "Node", "Cypher", "Query"],
                          "sentFrom": "wgs35-get-dstat-status",
                          "publishTo": "wgs35-triggers",
               },
               "body": {
                        "cypher": query,
                        "result-mode": "data",
                        "result-structure": "list",
                        "result-split": "True",
               },
    }
    return message


def create_query(dstat_json):
    # Parse dstat_json

    # I think: 
    ## store outputs (dict) as text
    ## stored events (list-of-dicts) as text
    ## store each provider-attributes as key:value property

    property_strings = []

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
    print(formatted_events)

    # Pop provider attributes to add all as properties
    provider_attributes = dstat_json.pop('provider-attributes')

    # Convert regions to list
    regions = provider_attributes.pop('regions')
    #### ERROR: Can't get it formatted correctly
    #formatted_regions = []
    #for region in regions:
    #    print(region)
    #    formatted_regions.append(json.dumps(region))
    #property_strings.append(f'dstat.regions= {formatted_regions}')

    for key, value in provider_attributes.items():
        if not value:
            continue
        neo4j_key = dash_to_camelcase(key)
        if isinstance(value, str):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        elif isinstance(value, dict):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        else:
            property_strings.append(f'dstat.{neo4j_key}= {value}')

    # All other dstat items
    for key, value in dstat_json.items():
        if not value:
            continue

        neo4j_key = dash_to_camelcase(key)
        if isinstance(value, str):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        elif isinstance(value, dict):
            property_strings.append(f'dstat.{neo4j_key}= "{value}"')
        else:
            property_strings.append(f'dstat.{neo4j_key}= {value}')
    properties_string = ', '.join(property_strings)   
    #pdb.set_trace()

    query = (
             f"MERGE (dstat:Dstat:Status {{ dsubJobId:\"{dstat_json['job-id']}\" }}) " +
             f"ON CREATE SET {properties_string} " +
              "RETURN dstat AS node")
    return query


def publish_to_topic(topic, data):
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
    #print(pubsub_message)

    #name = 'World'
    if isinstance(pubsub_message, dict) and 'data' in pubsub_message:
        dstat_cmd = base64.b64decode(pubsub_message['data']).decode('utf-8').strip()
        print(f"Dstat cmd: {dstat_cmd}.")

    #print(f'Hello {name}!')
    try:
        dstat_result = subprocess.check_output(dstat_cmd, stderr=subprocess.STDOUT, shell=True)
    except:
        print(f"Error: could not run dstat command {dstat_cmd}.")
        return('', 204)

    print(f"Dstat result: {dstat_result}.")
    json_result = json.loads(dstat_result)
    print(f"Json result: {json_result}.")

    query = create_query(json_result[0])
    message = format_pubsub_message(query)
    print(f"> Pubsub message: {message}.")
    result = publish_to_topic(TOPIC, message)
    print(f"> Published message to {TOPIC} with result: {result}.")
    #return message

    # Publish to message

    # Flush the stdout to avoid log buffering.
    sys.stdout.flush()

    return ('', 204)
# [END run_pubsub_handler]


if __name__ == '__main__':
    #PORT = int(os.getenv('PORT')) if os.getenv('PORT') else 8080

    # This is used when running locally. Gunicorn is used to run the
    # application on Cloud Run. See entrypoint in Dockerfile.
    #app.run(host='127.0.0.1', port=PORT, debug=True)

    dstat_cmd = "dstat --provider google-v2 --project gbsc-gcp-project-mvp-dev --jobs 'echo--pbilling--190903-164833-50' --users 'pbilling' --status '*' --full --format json"
    dstat_result = subprocess.check_output(dstat_cmd, stderr=subprocess.STDOUT, shell=True)
    json_result = json.loads(dstat_result)

    #with open('dstat_result.json', 'r') as fh:
    #    json_result = json.load(fh)
    query = create_query(json_result[0])
    message = format_pubsub_message(query)
    print(message)