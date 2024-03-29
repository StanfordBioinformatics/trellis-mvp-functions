import os
import pdb
import sys
import json
import math
import time
import yaml
import base64
import logging
import neobolt

from datetime import datetime

from py2neo import Graph

from urllib3.exceptions import ProtocolError
from neobolt.exceptions import ServiceUnavailable

from google.cloud import pubsub
from google.cloud import storage

# Get runtime variables from cloud storage bucket
# https://www.sethvargo.com/secrets-in-serverless/
ENVIRONMENT = os.environ.get('ENVIRONMENT')
if ENVIRONMENT == 'google-cloud':
    FUNCTION_NAME = os.environ['FUNCTION_NAME']

    vars_blob = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    parsed_vars = yaml.load(vars_blob, Loader=yaml.Loader)

    # Runtime variables
    DATA_GROUP = parsed_vars['DATA_GROUP']
    PROJECT_ID = parsed_vars['GOOGLE_CLOUD_PROJECT']
    DB_QUERY_TOPIC = parsed_vars['DB_QUERY_TOPIC']

    #NEO4J_URL = parsed_vars['NEO4J_URL']
    NEO4J_SCHEME = parsed_vars['NEO4J_SCHEME']
    NEO4J_HOST = parsed_vars['NEO4J_HOST']
    NEO4J_PORT = parsed_vars['NEO4J_PORT']
    NEO4J_USER = parsed_vars['NEO4J_USER']
    NEO4J_PASSPHRASE = parsed_vars['NEO4J_PASSPHRASE']
    #NEO4J_MAX_CONN = parsed_vars['NEO4J_MAX_CONN']

    # Pubsub client
    PUBLISHER = pubsub.PublisherClient()

    # Neo4j graph
    GRAPH = Graph(
                  scheme=NEO4J_SCHEME,
                  host=NEO4J_HOST,
                  port=NEO4J_PORT,
                  user=NEO4J_USER,
                  password=NEO4J_PASSPHRASE)
                  #max_connections=NEO4J_MAX_CONN)

QUERY_ELAPSED_MAX = 0.300
PUBSUB_ELAPSED_MAX = 10

def format_pubsub_message(method, labels, query, results, seed_id, event_id, retry_count=None):
    # Labels from the incoming message are perpetuated in the outgoing message with
    # these additional labels
    labels.extend(["Database", "Result"])
    
    message = {
               "header": {
                          "method": method,
                          "resource": "queryResult",
                          "labels": labels,
                          "sentFrom": FUNCTION_NAME,
                          "seedId": f"{seed_id}",
                          "previousEventId": f"{event_id}"
               },
               "body": {
                        "cypher": query,
                        "results": results,
               }
    }

    if retry_count:
        message['header']['retry-count'] = retry_count

    return message


def publish_to_topic(topic, json_data):
    topic_path = PUBLISHER.topic_path(PROJECT_ID, topic)
    # https://stackoverflow.com/questions/11875770/how-to-overcome-datetime-datetime-not-json-serializable/36142844#36142844
    message = json.dumps(json_data, indent=4, sort_keys=True, default=str).encode('utf-8')
    result = PUBLISHER.publish(topic_path, data=message).result()
    return result


def publish_str_to_topic(topic, str_data):
    topic_path = PUBLISHER.topic_path(PROJECT_ID, topic)
    message = str_data.encode('utf-8')
    result = PUBLISHER.publish(topic_path, data=message).result()
    return result


def republish_message(topic, data):
    """Wrapper for publish_to_topic which adds retry chunk.
    """
    max_retries = 3

    header = data["header"]
    counter = header.get("retry-count")
    if counter:
        if counter >= max_retries:
            raise ValueError(f"Function exceeded {max_retries} retries.")
        else:
            header["retry-count"] += 1
    else:
        header["retry-count"] = 1
    result = publish_to_topic(DB_QUERY_TOPIC, data)
    return result


def query_db(event, context):
    """When an object node is added to the database, launch any
       jobs corresponding to that node label.

       Args:
            event (dict): Event payload.
            context (google.cloud.functions.Context): Metadata for the event.
    """

    start = datetime.now()

    pubsub_message = base64.b64decode(event['data']).decode('utf-8')
    data = json.loads(pubsub_message)
    print(f"> Received pubsub message: {data}.")
    print(f"> Context: {context}.")
    #print(f"> Data: {data}.")

    # Load time in RFC 3339 format
    # Description of RFC 3339: http://henry.precheur.org/python/rfc3339.html
    # Pub/Sub message example: https://cloud.google.com/functions/docs/writing/background#functions-writing-background-hello-pubsub-python
    try:
        published_time = datetime.strptime(context.timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError as exception:
        try:
            published_time = datetime.strptime(context.timestamp, '%Y-%m-%dT%H:%M:%SZ')
        except:
            raise
    except:
        raise

    # Time from message publication to reception
    publish_elapsed = datetime.now() - published_time
    if publish_elapsed.total_seconds() > PUBSUB_ELAPSED_MAX:
        print(
              f"> Time to receive message ({int(publish_elapsed.total_seconds())}) " +
              f"exceeded {PUBSUB_ELAPSED_MAX} seconds after publication.")

    if type(data) == str:
        logging.warn("Message data not correctly loaded as JSON. " +
                     "Used eval to convert from string.")
        data = eval(data)

    header = data["header"]
    body = data["body"]

    # Get seed/event ID to track provenance of Trellis events
    event_id = context.event_id
    # If message comes from a CRON job there won't be a seedId
    seed_id = header.get("seedId")
    if not seed_id:
        seed_id = event_id

    # Check that resource is query
    if header['resource'] != 'query':
        raise ValueError(f"Expected resource type 'query', " +
                         f"got '{header['resource']}.'")

    method = header['method']
    labels = header['labels']
    topics = header.get('publishTo')
    retry_count = header.get('retry-count')

    query = body['cypher']
    result_mode = body.get('result-mode')
    result_structure = body.get('result-structure')
    result_split = body.get('result-split')

    try:
        # Calculate elapsed time for each query & print
        query_start = time.time()
        if result_mode == 'stats':
            print(f"> Running stats query: {query}")
            query_results = GRAPH.run(query).stats()
        elif result_mode == 'data':
            print(f"> Running data query: {query}")
            query_results = GRAPH.run(query).data()
        else:
            GRAPH.run(query)
            query_results = None
        query_elapsed = time.time() - query_start
        print(f"> Query results: {query_results}.")
        #print(f"> Elapsed time to run query: {query_elapsed:.3f}. Query: {query}.")
        if query_elapsed > QUERY_ELAPSED_MAX:
            print(f"> Time to run query ({query_elapsed:.3f}) exceeded {QUERY_ELAPSED_MAX:.3f}. Query: {query}.")
    # Neo4j http connector
    except ProtocolError as error:
        logging.warn(f"> Encountered Protocol Error: {error}.")
        # Add message back to queue
        result = republish_message(DB_QUERY_TOPIC, data)
        logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        logging.warn(f"> Encountered Protocol Error: {error}.")
        return
    except ServiceUnavailable as error:
        logging.warn(f"> Encountered Service Interrupion: {error}.")
        # Remove this connection(?) - causes UnboundLocalError
        #GRAPH = None
        # Add message back to queue
        result = republish_message(DB_QUERY_TOPIC, data)
        logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        logging.warn(f"> Requeued message: {pubsub_message}.")
        return
    except ConnectionResetError as error:
        logging.warn(f"> Encountered connection interruption: {error}.")
        # Add message back to queue
        result = republish_message(DB_QUERY_TOPIC, data)
        logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        logging.warn(f"> Requeued message: {pubsub_message}.")
        return

    # Return if not pubsub topic
    if not topics:
        print("No Pub/Sub topic specified; result not published.")

        # Execution time block
        end = datetime.now()
        execution_time = (end - start).seconds
        time_threshold = int(execution_time/10) * 10
        if time_threshold > 0:
            print(f"> Execution time exceeded {time_threshold} seconds.")

        return query_results

    # Hack to convert single publishTo topics into lists
    if isinstance(topics, str):
        topics = [topics]

    # Track how many messages are published to each topic
    published_message_counts = {}
    for topic in topics:
        published_message_counts[topic] = 0

    for topic in topics:
        if result_split == 'True':
            if not query_results:
                # If no results; send one message so triggers can respond to null
                query_result = {}
                message = format_pubsub_message(
                                                method = method,
                                                labels = labels,
                                                query = query,
                                                results = query_result,
                                                seed_id = seed_id,
                                                event_id = event_id,
                                                retry_count=retry_count)
                print(f"> Pubsub message: {message}.")
                publish_result = publish_to_topic(topic, message)
                print(f"> Published message to {topic} with result: {publish_result}.")
                published_message_counts[topic] += 1

            for result in query_results:
                message = format_pubsub_message(
                                                method = method,
                                                labels = labels,
                                                query = query,
                                                results = result,
                                                seed_id = seed_id,
                                                event_id = event_id,
                                                retry_count=retry_count)
                print(f"> Pubsub message: {message}.")
                publish_result = publish_to_topic(topic, message)
                print(f"> Published message to {topic} with result: {publish_result}.")
                published_message_counts[topic] += 1
        else:
            #message['body']['results'] = results
            message = format_pubsub_message(
                                            method = method,
                                            labels = labels,
                                            query = query,
                                            results = query_results,
                                            seed_id = seed_id,
                                            event_id = event_id,
                                            retry_count=retry_count)
            print(f"> Pubsub message: {message}.")
            publish_result = publish_to_topic(topic, message)
            print(f"> Published message to {topic} with result: {publish_result}.")
            published_message_counts[topic] += 1
    logging.info(f"> Summary of published messages: {published_message_counts}")

    # Execution time block
    end = datetime.now()
    execution_time = (end - start).seconds
    time_threshold = int(execution_time/10) * 10
    if time_threshold > 0:
        print(f"> Execution time exceeded {time_threshold} seconds.")

if __name__ == "__main__":
    query_db()
