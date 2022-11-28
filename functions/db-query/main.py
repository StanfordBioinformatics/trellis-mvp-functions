import os
import re
import pdb
import sys
import json
import math
import time
import yaml
import base64
import neobolt

from datetime import datetime

#import neo4j
from neo4j import GraphDatabase

from urllib3.exceptions import ProtocolError
from neobolt.exceptions import ServiceUnavailable

from google.cloud import pubsub
from google.cloud import storage

import trellisdata as trellis

# Get runtime variables from cloud storage bucket
# https://www.sethvargo.com/secrets-in-serverless/
ENVIRONMENT = os.environ.get('ENVIRONMENT')
if ENVIRONMENT == 'google-cloud':

    # set up the Google Cloud Logging python client library
    # source: https://cloud.google.com/blog/products/devops-sre/google-cloud-logging-python-client-library-v3-0-0-release
    import google.cloud.logging
    client = google.cloud.logging.Client()
    # log_level=10 is equivalent to DEBUG; default is 20 == INFO
    # NOTE: this debug setting doesn't work
    # Gcloud Python logging client: https://googleapis.dev/python/logging/latest/client.html?highlight=setup_logging#google.cloud.logging_v2.client.Client.setup_logging
    # Logging levels: https://docs.python.org/3/library/logging.html#logging-levels
    client.setup_logging(log_level=10)

    # use Python's standard logging library to send logs to GCP
    import logging
    #logging.basicConfig()

    FUNCTION_NAME = os.environ['FUNCTION_NAME']
    GCP_PROJECT = os.environ['GCP_PROJECT']

    config_doc = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    # https://stackoverflow.com/questions/6866600/how-to-parse-read-a-yaml-file-into-a-python-object
    TRELLIS = yaml.safe_load(config_doc)

    # Pubsub client
    PUBLISHER = pubsub.PublisherClient()

    # Load queries predefined by Trellis developers.
    queries_document = storage.Client() \
                        .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                        .get_blob(TRELLIS["USER_DEFINED_QUERIES"]) \
                        .download_as_string()
    queries = yaml.load_all(queries_document, Loader=yaml.FullLoader)
    
    # Load list of existing queries that have been dynamically
    # generated by the create-blob-node function.
    CREATE_BLOB_QUERY_DOC = storage.Client() \
                                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                                .get_blob(TRELLIS["CREATE_BLOB_QUERIES"]) \
                                .download_as_string()

    # Load list of existing queries that have been dynamically
    # generated by the create-blob-node function.
    CREATE_JOB_QUERY_DOC = storage.Client() \
                            .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                            .get_blob(TRELLIS["CREATE_JOB_QUERIES"]) \
                            .download_as_string()

    QUERY_DICT = {}
    for query in queries:
        if query.name in QUERY_DICT.keys():
            raise ValueError(f"Query {query.name} is defined in duplicate.")
        QUERY_DICT[query.name] = query

    # Use Neo4j driver object to establish connections to the Neo4j
    # database and manage connection pool used by neo4j.Session objects
    # https://neo4j.com/docs/api/python-driver/current/api.html#driver
    DRIVER = GraphDatabase.driver(
        f"{TRELLIS['NEO4J_SCHEME']}://{TRELLIS['NEO4J_HOST']}:{TRELLIS['NEO4J_PORT']}",
        auth=("neo4j", TRELLIS["NEO4J_PASSPHRASE"]),
        max_connection_pool_size=10)
else:
    FUNCTION_NAME = 'db-query-local'
    local_queries = "sample-queries.yaml"

    # Load database queries into a dictionary
    with open(local_queries, "r") as file_handle:
        queries = yaml.load_all(file_handle, Loader=yaml.FullLoader)
        QUERY_DICT = {}
        for query in queries:
            QUERY_DICT[query.name] = query

QUERY_ELAPSED_MAX = 300
PUBSUB_ELAPSED_MAX = 10

def query_database(driver, query, parameters):
    """Run a Cypher query against the Neo4j database.

    Args:
        write_transaction (bool): Indicate whether write permission is needed.
        driver (neo4j.Driver): Official Neo4j Python driver
        query (str): Parameterized Cypher query
        query_parameters (dict): Parameters values that will be used in the query.
    Returns:
        neo4j.graph.Graph: https://neo4j.com/docs/api/python-driver/current/api.html#neo4j.graph.Graph
        neo4j.ResultSummary: https://neo4j.com/docs/api/python-driver/current/api.html#resultsummary
    """

    # Reload predefined database queries every time a function instance
    # is launched in development mode to make sure queries are current.
    DEVELOPMENT = os.environ.get('DEVELOPMENT')
    if DEVELOPMENT:
        queries_document = storage.Client() \
                        .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                        .get_blob(TRELLIS["USER_DEFINED_QUERIES"]) \
                        .download_as_string()
        queries = yaml.load_all(queries_document, Loader=yaml.FullLoader)


    # Check whether query parameters match the required keys and types
    key_difference = set(query.required_parameters.keys()).difference(set(parameters.keys()))
    if key_difference:
        #logging.error(f"Query parameters do not match requirements. Difference: {key_difference}.")
        raise ValueError(f"Query parameters do not match requirements. Difference: {key_difference}.")

    for key, type_name in query.required_parameters.items():
        if not type(parameters[key]).__name__ == type_name:
            raise ValueError(f"Query parameter {parameters[key]} does not match type {type_name}.")

    with driver.session() as session:
        if query.write_transaction:
            graph, result_summary = session.write_transaction(_stored_procedure_transaction_function, query.cypher, **parameters)
        else:
            graph, result_summary = session.read_transaction(_stored_procedure_transaction_function, query.cypher, **parameters)
    return graph, result_summary

def _stored_procedure_transaction_function(tx, query, **query_parameters):
    """ Standard function for running parameterized cypher queries.

    Args:
        tx (neo4j.session.[read,write]_transaction): Method for running managed Neo4j transaction.
        query (str): Cypher query.
        query_parameters (dict): The query will be populated with these parameters.

    Returns:
        neo4j.graph.Graph: Graph object with returned nodes and relationships.
        neo4j.ResultSummary: Summary statistics detailing changes made by the transaction.
    """

    result = tx.run(query, query_parameters)
    return result.graph(), result.consume()

def new_query_found_in_catalogue(
                                 new_query: trellis.DatabaseQuery, 
                                 catalogued_queries: str) -> bool:
    # Typing hints: https://docs.python.org/3/library/typing.html

    query_match_found = False
    query_name_found = False
    catalogued_queries = yaml.load_all(catalogued_queries, Loader=yaml.FullLoader)
    
    for logged_query in catalogued_queries:
        if new_query.name == logged_query.name:
                query_name_found = True
        if new_query == logged_query:
                query_match_found = True

    if query_name_found and not query_match_found:
        logging.warning(
                        f"163 >> Found catalogued query named {new_query.name} " +
                         "but does not match current query.")
    return query_match_found
  
def main(event, context, local_driver=None):
    """When an object node is added to the database, launch any
       jobs corresponding to that node label.

       Args:
            event (dict): Event payload.
            context (google.cloud.functions.Context): Metadata for the event.
    """

    start = datetime.now()
    query_request = trellis.QueryRequestReader(
                                               event=event, 
                                               context=context)
    
    logging.info(f"+> Received query request; " +
                    f"event ID : {query_request.event_id}, " +
                    f"previous event ID : {query_request.previous_event_id}, " +
                    f"seed event ID : {query_request.seed_id}.")
    logging.info(f"> Query request info: " +
                    f"custom : {query_request.custom}, " +
                    f"name : {query_request.query_name}.")
    logging.debug(f"> Received message body: {query_request.body}.")

    if ENVIRONMENT == 'google-cloud':
        # Time from message publication to reception
        request_publication_time = trellis.utils.convert_timestamp_to_rfc_3339(query_request.context.timestamp)
        publish_elapsed = datetime.now() - request_publication_time
        if publish_elapsed.total_seconds() > PUBSUB_ELAPSED_MAX:
            logging.warning(
                f"> Time to receive message ({int(publish_elapsed.total_seconds())}) " +
                f"exceeded {PUBSUB_ELAPSED_MAX} seconds after publication.")

    if query_request.custom == True:
        logging.info("> Processing custom query.")

        # Parse query parameters and data types from request
        required_parameters = {}
        for key, value in query_request.query_parameters.items():
            required_parameters[key] = type(value).__name__
        logging.info(f"> Custom query required parameters: {required_parameters}.")

        # Create DatabaseQuery object
        database_query = trellis.DatabaseQuery(
            name=query_request.query_name,
            cypher=query_request.cypher,
            # Maybe I should populate this
            required_parameters=required_parameters,
            write_transaction=query_request.write_transaction,
            returns = query_request.returns,
            publish_to = query_request.publish_to,
            aggregate_results = query_request.aggregate_results,
            active = True)

        register_new_query = True
        
        if re.match(pattern = r"^mergeBlob.*", string = database_query.name):
            if new_query_found_in_catalogue(database_query, CREATE_BLOB_QUERY_DOC):
                register_new_query = False
                logging.info("> Merge blob query already stored.")
            else:
                logging.info("> Merge blob query not found in current catalogue; reloading latest version.")
                # Reload create blob queries to make sure list is current
                create_blob_query_doc = storage.Client() \
                                        .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                                        .get_blob(TRELLIS["CREATE_BLOB_QUERIES"]) \
                                        .download_as_string()
                if new_query_found_in_catalogue(database_query, create_blob_query_doc):
                    register_new_query = False
                    logging.info("> Merge blob query already stored.")
            
            if register_new_query:
                logging.info(f"> Merge blob query not found in existing catalogue; adding to {TRELLIS['CREATE_BLOB_QUERIES']}")
                create_blob_query_str = create_blob_query_doc.decode("utf-8")
                create_blob_query_str += "--- "
                create_blob_query_str += yaml.dump(database_query)

                storage.Client() \
                    .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                    .get_blob(TRELLIS["CREATE_BLOB_QUERIES"]) \
                    .upload_from_string(create_blob_query_str)
        # Register new create-job-node queries
        elif re.match(pattern = r"^mergeJob.*", string = database_query.name):
            if new_query_found_in_catalogue(database_query, CREATE_JOB_QUERY_DOC):
                register_new_query = False
                logging.info(">> Merge job query already stored.")
            else:
                logging.info(">> Merge job query not found in current catalogue; reloading latest version.")
                # Reload create job queries to make sure list is current
                create_job_query_doc = storage.Client() \
                                        .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                                        .get_blob(TRELLIS["CREATE_JOB_QUERIES"]) \
                                        .download_as_string()
                if new_query_found_in_catalogue(database_query, create_job_query_doc):
                    register_new_query = False
                    logging.info(">> Merge job query already stored.")

            if register_new_query:
                logging.info(f">> Merge job query not found in existing catalogue; adding to {TRELLIS['CREATE_JOB_QUERIES']}")
                create_job_query_str = create_job_query_doc.decode("utf-8")
                create_job_query_str += "--- "
                create_job_query_str += yaml.dump(database_query)
                storage.Client() \
                    .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                    .get_blob(TRELLIS["CREATE_JOB_QUERIES"]) \
                    .upload_from_string(create_job_query_str)
        else:
            logging.warning("> Custom query name did not match any recognized pattern.")
    else:
        try:
            database_query = QUERY_DICT[query_request.query_name]
        except KeyError:
            raise KeyError(f"> Database query '{query_request.query_name}' " +
                           "is not available. Check that is has been " +
                           f"added to {TRELLIS['USER_DEFINED_QUERIES']}.")

    try:
        # TODO: Compare the provided query parameters against the 
        # required query parameters
        logging.info(f"> Running query: {database_query.name} " +
                     f"with parameters: {query_request.query_parameters}.")
        graph, result_summary = query_database(
            driver = DRIVER,
            query = database_query,
            parameters = query_request.query_parameters)
    except ProtocolError as error:
        logging.error(f"> Encountered Protocol Error: {error}.")
        # Add message back to queue
        #result = republish_message(DB_QUERY_TOPIC, data)
        #logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        #logging.warn(f"> Encountered Protocol Error: {error}.")
        return
    except ServiceUnavailable as error:
        logging.error(f"> Encountered Service Interrupion: {error}.")
        # Remove this connection(?) - causes UnboundLocalError
        #GRAPH = None
        # Add message back to queue
        #result = republish_message(DB_QUERY_TOPIC, data)
        #logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        #logging.warn(f"> Requeued message: {pubsub_message}.")
        return
    except ConnectionResetError as error:
        logging.error(f"> Encountered connection interruption: {error}.")
        # Add message back to queue
        #result = republish_message(DB_QUERY_TOPIC, data)
        #logging.warn(f"> Published message to {DB_QUERY_TOPIC} with result: {result}.")
        # Duplicate message flagged as warning
        #logging.warn(f"> Requeued message: {pubsub_message}.")
        return

    result_available_after = result_summary.result_available_after
    result_consumed_after = result_summary.result_consumed_after
    logging.info(
                 f"> Query result available after: {result_available_after} ms, " +
                 f"consumed after: {result_consumed_after} ms.")
        #print(f"> Elapsed time to run query: {query_elapsed:.3f}. Query: {query}.")
    if int(result_available_after) > QUERY_ELAPSED_MAX:
        logging.warning(
                        f"> Result available time ({result_available_after} ms) " +
                        f"exceeded {QUERY_ELAPSED_MAX:.3f}. " +
                        f"Query: {database_query.name}.")
    logging.info(f"> Query result counter: {result_summary.counters}.")

    query_response = trellis.QueryResponseWriter(
        sender = FUNCTION_NAME,
        seed_id = query_request.seed_id,
        previous_event_id = query_request.event_id,
        query_name = query_request.query_name,
        graph = graph,
        result_summary = result_summary)

    logging.info(f"> Query response nodes: {[list(node.labels) for node in query_response.nodes]}")
    logging.info(f"> Query response relationships:")
    for relationship in query_response.relationships:
        logging.info(f">> (:{list(relationship.start_node.labels)})-[:{relationship.type}]->(:{list(relationship.end_node.labels)})")

    # Return if no pubsub topic or not running on GCP
    if not database_query.publish_to or not ENVIRONMENT == 'google-cloud':
        print("> No Pub/Sub topic specified; result not published.")
        return

    # Track how many messages are published to each topic
    published_message_counts = {}
    for topic_name in database_query.publish_to:
        topic = TRELLIS[topic_name]
        published_message_counts[topic] = 0

        # Default behavior will be to split results
        if hasattr(database_query, "aggregate_results") and database_query.aggregate_results == 'True':
            message = query_response.return_json_with_all_nodes()
            logging.info(f"> Publishing query response to topic: {topic}.")
            logging.debug(f"> Publising message: {message}.")
            publish_result = trellis.utils.publish_to_pubsub_topic(
                    publisher = PUBLISHER,
                    project_id = GCP_PROJECT,
                    topic = topic, 
                    message = message)
            logging.info(f"> Published message to {topic} with result (event_id): {publish_result}.")
            published_message_counts[topic] += 1
        else:
            for message in query_response.generate_separate_entity_jsons():
                logging.info(f"> Publishing query response to topic: {topic}.")
                logging.debug(f"> Publishing message: {message}.")
                publish_result = trellis.utils.publish_to_pubsub_topic(
                    publisher = PUBLISHER,
                    project_id = GCP_PROJECT,
                    topic = topic,
                    message = message)
                logging.info(f"> Published message to {topic} with result: {publish_result}.")
                published_message_counts[topic] += 1
    logging.info(f"-> Summary of published messages: {published_message_counts}")