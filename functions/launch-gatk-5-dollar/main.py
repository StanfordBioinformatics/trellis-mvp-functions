import os
import sys
import json
import uuid
import yaml
import base64
import hashlib
import logging

from google.cloud import storage
from google.cloud import pubsub

from datetime import datetime

from dsub.commands import dsub

ENVIRONMENT = os.environ.get('ENVIRONMENT', '')
if ENVIRONMENT == 'google-cloud':
    FUNCTION_NAME = os.environ['FUNCTION_NAME']
    
    vars_blob = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    parsed_vars = yaml.load(vars_blob, Loader=yaml.Loader)

    PROJECT_ID = parsed_vars['GOOGLE_CLOUD_PROJECT']
    REGIONS = parsed_vars['DSUB_REGIONS']
    OUT_BUCKET = parsed_vars['DSUB_OUT_BUCKET']
    LOG_BUCKET = parsed_vars['DSUB_LOG_BUCKET']
    DSUB_USER = parsed_vars['DSUB_USER']
    NETWORK = parsed_vars['DSUB_NETWORK']
    SUBNETWORK = parsed_vars['DSUB_SUBNETWORK']

    TRELLIS_BUCKET = parsed_vars['TRELLIS_BUCKET']
    GATK_MVP_DIR = parsed_vars['GATK_MVP_DIR']
    GATK_MVP_HASH = parsed_vars['GATK_MVP_HASH']
    GATK_GERMLINE_DIR = parsed_vars['GATK_GERMLINE_DIR']
    #GATK_HG38_INPUTS = parsed_vars['GATK_HG38_INPUTS']
    #GATK_PAPI_INPUTS = parsed_vars['GATK_PAPI_INPUTS']
    NEW_JOBS_TOPIC = parsed_vars['NEW_JOBS_TOPIC']

    # Establish PubSub connection
    PUBLISHER = pubsub.PublisherClient()


def format_pubsub_message(job_dict, seed_id, event_id):
    message = {
        "header": {
            "resource": "job-metadata",
            "method": "POST",
            "labels": ["Create", "Job", "CromwellWorkflow", "Dsub", "Node"],
            "sentFrom": f"{FUNCTION_NAME}",
            "seedId": f"{seed_id}",
            "previousEventId": f"{event_id}"
        },
        "body": {
            "node": job_dict,
        }
    }
    return message


def publish_to_topic(topic, data):
    topic_path = PUBLISHER.topic_path(PROJECT_ID, topic)
    data = json.dumps(data).encode('utf-8')
    result = PUBLISHER.publish(topic_path, data=data)
    return result


def launch_dsub_task(dsub_args):
    try:
        result = dsub.dsub_main('dsub', dsub_args)
    except ValueError as exception:
        print(exception)
        print(f'Error with dsub arguments: {dsub_args}')
        return(exception)
    except:
        print("Unexpected error:", sys.exc_info())
        for arg in dsub_args:
            print(arg)
        return(sys.exc_info())
    return(result)


def get_datetime_stamp():
    now = datetime.now()
    datestamp = now.strftime("%y%m%d-%H%M%S-%f")[:-3]
    return datestamp


def make_unique_task_id(nodes, datetime_stamp):
    # Create pretty-unique hash value based on input nodes
    # https://www.geeksforgeeks.org/ways-sort-list-dictionaries-values-python-using-lambda-function/
    sorted_nodes = sorted(nodes, key = lambda i: i['id'])
    nodes_str = json.dumps(sorted_nodes, sort_keys=True, ensure_ascii=True, default=str)
    nodes_hash = hashlib.sha256(nodes_str.encode('utf-8')).hexdigest()
    print(nodes_hash)
    trunc_nodes_hash = str(nodes_hash)[:8]
    task_id = f"{datetime_stamp}-{trunc_nodes_hash}"
    return(task_id, trunc_nodes_hash)


def launch_gatk_5_dollar(event, context):
    """When an object node is added to the database, launch any
       jobs corresponding to that node label.

       Args:
            event (dict): Event payload.
            context (google.cloud.functions.Context): Metadata for the event.
    """

    pubsub_message = base64.b64decode(event['data']).decode('utf-8')
    logging.info(f"> Received PubSub Message: {pubsub_message}.")
    data = json.loads(pubsub_message)
    logging.info(f"> Context: {context}.")
    logging.info(f"> Data: {data}.")
    header = data['header']
    body = data['body']

    seed_id = header['seedId']
    event_id = context.event_id

    dry_run = header.get('dryRun')
    if not dry_run:
        dry_run = False

    #metadata = {}
    if len(body['results']) == 0:
        # This is expected, because everytime a ubam is created 
        # a query result will be sent here, but will be empty 
        # unless all ubams are present
        logging.warn("No results found; ignoring.")
        return
    elif len(body['results']) != 1:
        raise ValueError(f"Expected single result, got {len(body['results'])}.")
    else:
        pass
    
    nodes = body['results']['nodes']
    # If not all Ubams present in database, results will be NoneType
    if not nodes:
        raise ValueError("No nodes provided; exiting.")

    # Dsub data
    task_name = 'gatk-5-dollar'
    # Create unique task ID
    datetime_stamp = get_datetime_stamp()
    task_id, trunc_nodes_hash = make_unique_task_id(nodes, datetime_stamp)

    ubams = []
    # inputIds used to create relationships via trigger
    input_ids = []
    for node in nodes:
        if 'Ubam' not in node['labels']:
            print(f"Error: inputs must be ubams.")
            return

        plate = node['plate']
        sample = node['sample']
        input_id = node['id']

        bucket = node['bucket']
        path = node['path']

        ubam_path = f"gs://{bucket}/{path}"
        ubams.append(ubam_path)
        input_ids.append(input_id)

    # Load Pipeline API (PAPI) options JSON from GCS
    logging.info(f"> Loading PAPI options")
    gatk_papi_inputs = f"{GATK_MVP_DIR}/{GATK_MVP_HASH}/{GATK_GERMLINE_DIR}/generic.google-papi.options.json"
    papi_options_template = storage.Client(project=PROJECT_ID) \
        .get_bucket(TRELLIS_BUCKET) \
        .blob(gatk_papi_inputs) \
        .download_as_string()
    papi_options = json.loads(papi_options_template)

    # Add Trellis ID to Cromwell workers
    # NOTE: Doesn't work. Don't know where these are supposed to go.
    #papi_options["google_labels"] = {
    #                                 "trellis-id": task_id,
    #                                 "sample": sample
    #}

    # Write workflow-specific PAPI options to GCS
    logging.info(f"> Writing workflow-specific PAPI options to GCS")
    papi_options_path = f"{plate}/{sample}/{task_name}/{task_id}/inputs/{sample}.google-papi.options.json"
    papi_options_blob = storage.Client(project=PROJECT_ID) \
        .get_bucket(OUT_BUCKET) \
        .blob(papi_options_path) \
        .upload_from_string(json.dumps(papi_options, indent=4))
    logging.info(f"> Created PAPI options blob at gs://{OUT_BUCKET}/{papi_options_path}.")

    # Load inputs JSON from GCS
    logging.info(f"> Loading workflow inputs JSON from GCS")
    gatk_hg38_inputs = f"{GATK_MVP_DIR}/{GATK_MVP_HASH}/mvp.hg38.inputs.json"
    gatk_input_template = storage.Client(project=PROJECT_ID) \
        .get_bucket(TRELLIS_BUCKET) \
        .blob(gatk_hg38_inputs) \
        .download_as_string()
    gatk_inputs = json.loads(gatk_input_template)

    # Add key/values
    logging.info(f"> Adding sample-specific inputs to JSON")
    gatk_inputs['germline_single_sample_workflow.sample_name'] = sample
    gatk_inputs['germline_single_sample_workflow.base_file_name'] = sample
    gatk_inputs['germline_single_sample_workflow.flowcell_unmapped_bams'] = ubams
    gatk_inputs['germline_single_sample_workflow.final_vcf_base_name'] = sample

    # Write inputs JSON to GCS
    logging.info(f"> Write workflow inputs JSON back to GCS")
    gatk_inputs_path = f"{plate}/{sample}/{task_name}/{task_id}/inputs/inputs.json"
    gatk_inputs_blob = storage.Client(project=PROJECT_ID) \
        .get_bucket(OUT_BUCKET) \
        .blob(gatk_inputs_path) \
        .upload_from_string(json.dumps(gatk_inputs, indent=4))
    print(f"> Created input blob at gs://{OUT_BUCKET}/{gatk_inputs_path}.")

    # Debugging
    return

    #workflow_inputs_path = "workflow-inputs/gatk-mvp/gatk-mvp-pipeline"
    unique_task_label = "Gatk5Dollar"
    job_dict = {
                "provider": "google-v2",
                "user": DSUB_USER,
                "regions": REGIONS,
                "project": PROJECT_ID,
                "minCores": 1,
                "minRam": 12,
                "preemptible": False,
                "bootDiskSize": 20,
                "image": f"gcr.io/{PROJECT_ID}/broadinstitute/cromwell:47",
                "logging": f"gs://{LOG_BUCKET}/{plate}/{sample}/{task_name}/{task_id}/logs",
                "diskSize": 100,
                "command": ("java " +
                            "-Dconfig.file=${CFG} " +
                            "-Dbackend.providers.${BACKEND_PROVIDER}.config.project=${PROJECT} " +
                            "-Dbackend.providers.${BACKEND_PROVIDER}.config.root=${ROOT} " +
                            "-jar /app/cromwell.jar " +
                            "run ${WDL} " +
                            "--inputs ${INPUT} " +
                            "--options ${OPTION}"
                ),
                "inputs": {
                           "CFG": f"gs://{TRELLIS_BUCKET}/{GATK_MVP_DIR}/{GATK_MVP_HASH}/{GATK_GERMLINE_DIR}/google-adc.conf", 
                           "OPTION": f"gs://{OUT_BUCKET}/{papi_options_path}",
                           "WDL": f"gs://{TRELLIS_BUCKET}/{GATK_MVP_DIR}/{GATK_MVP_HASH}/{GATK_GERMLINE_DIR}/fc_germline_single_sample_workflow.wdl",
                           "SUBWDL": f"gs://{TRELLIS_BUCKET}/{GATK_MVP_DIR}/{GATK_MVP_HASH}/{GATK_GERMLINE_DIR}/tasks_pipelines/*.wdl",
                           "INPUT": f"gs://{OUT_BUCKET}/{gatk_inputs_path}",
                },
                "envs": {
                         "PROJECT": PROJECT_ID,
                         "ROOT": f"gs://{OUT_BUCKET}/{plate}/{sample}/{task_name}/{task_id}/output",
                         "BACKEND_PROVIDER": "PAPIv2"
                },
                "preemptible": False,
                "dryRun": dry_run,
                "trellisTaskId": task_id,
                "sample": sample,
                "plate": plate,
                "name": task_name,
                "inputHash": trunc_nodes_hash,
                "labels": [
                            'Job',
                            'Dsub',
                            'CromwellWorkflow',
                            unique_task_label],
                "inputIds": input_ids,
                "gatkMvpCommit": GATK_MVP_HASH,
                "network": NETWORK,
                "subnetwork": SUBNETWORK,
                "timeout": "48h"
    }

    dsub_args = [
                 "--name", f"gatk-{job_dict['inputHash'][0:5]}",
                 "--label", f"sample={sample.lower()}",
                 "--label", f"trellis-id={task_id}",
                 "--label", f"trellis-name={job_dict['name']}",
                 "--label", f"plate={plate.lower()}",
                 "--label", f"input-hash={trunc_nodes_hash}",
                 "--provider", job_dict["provider"], 
                 "--user", job_dict["user"], 
                 "--regions", job_dict["regions"],
                 "--project", job_dict["project"],
                 "--min-cores", str(job_dict["minCores"]), 
                 "--min-ram", str(job_dict["minRam"]),
                 "--boot-disk-size", str(job_dict["bootDiskSize"]), 
                 "--image", job_dict["image"], 
                 "--logging", job_dict["logging"],
                 "--disk-size", str(job_dict["diskSize"]),
                 "--command", job_dict["command"],
                 "--network", job_dict["network"],
                 "--subnetwork", job_dict["subnetwork"],
                 "--use-private-address",
                 "--enable-stackdriver-monitoring",
                 "--timeout", job_dict["timeout"]
    ]

    # Argument lists
    for key, value in job_dict['inputs'].items():
        dsub_args.extend([
                          "--input",
                          f"{key}={value}"]
        )
    for key, value in job_dict['envs'].items():
        dsub_args.extend([
                          "--env",
                          f"{key}={value}"]
        )
    
    # Optional flags
    if job_dict['preemptible']:
        dsub_args.append("--preemptible")
    if job_dict['dryRun']:
        dsub_args.append("--dry-run")

    print(f"> Launching dsub with args: {dsub_args}.")
    dsub_result = launch_dsub_task(dsub_args)
    print(f"> Dsub result: {dsub_result}.")

    # If job launch is successful, add job to database
    if 'job-id' in dsub_result.keys():
        # Add dsub job ID to neo4j database node
        job_dict['dsubJobId'] = dsub_result['job-id']
        job_dict['dstatCmd'] = (
                                 "dstat " +
                                f"--project {job_dict['project']} " +
                                f"--provider {job_dict['provider']} " +
                                f"--jobs '{job_dict['dsubJobId']}' " +
                                f"--users '{job_dict['user']}' " +
                                 "--full " +
                                 "--format json " +
                                 "--status '*'")
        
        # Reformat dict values as separate key/value pairs
        # to be compatible with Neo4j
        for key, value in job_dict["inputs"].items():
            job_dict[f"input_{key}"] = value
        for key, value in job_dict["envs"].items():
            job_dict[f"env_{key}"] = value

        # Package job node and inputs into JSON message
        message = format_pubsub_message(
                                        job_dict = job_dict,
                                        seed_id = seed_id,
                                        event_id = event_id)
        print(f"> Pubsub message: {message}.")
        result = publish_to_topic(NEW_JOBS_TOPIC, message)  
        print(f"> Published message to {NEW_JOBS_TOPIC} with result: {result}.")


# For local testing
if __name__ == "__main__":
    PROJECT_ID = "***REMOVED***-dev"
    ZONES =  "us-west1*"
    TRELLIS_BUCKET = "***REMOVED***-dev-trellis"
    GATK_INPUTS_PATH = "workflow-inputs/gatk-mvp/mvp.hg38.inputs.json"
    OUT_BUCKET = "***REMOVED***-dev-from-personalis-gatk"
    LOG_BUCKET = "***REMOVED***-dev-from-personalis-gatk-logs"
    DSUB_USER = "trellis"
    NEW_JOBS_TOPIC = "wgs35-new-jobs"

    PUBLISHER = pubsub.PublisherClient()

    data = {
        'header': {
            'method': 'VIEW',
            'labels': ['Ubam', 'Nodes'],
            'resource': 'query-result',
            'sentFrom': 'db-query',
            'dryRun': True,
        },
        'body': {
            'query': 'MATCH (n:Ubam) WHERE n.sample="SHIP4946367" WITH n.sample AS sample, COLLECT(n) as nodes RETURN CASE WHEN size(nodes) = 4 THEN nodes ELSE NULL END',
            'results': [
                {
                    'CASE \nWHEN size(nodes) = 4 \nTHEN nodes \nELSE NULL \nEND': [
                        {
                            'basename': 'SHIP4946367_2.ubam',
                            'bucket': '***REMOVED***-dev-from-personalis-gatk',
                            'contentType': 'application/octet-stream',
                            'crc32c': 'ojStVg==',
                            'dirname': 'SHIP4946367/fastq-to-vcf/fastq-to-ubam/output',
                            'etag': 'CJTpxe3ynuICEAM=',
                            'extension': 'ubam',
                            'generation': '1557970088457364',
                            'id': '***REMOVED***-dev-from-personalis-gatk/SHIP4946367/fastq-to-vcf/fastq-to-ubam/output/SHIP4946367_2.ubam/1557970088457364',
                            'kind': 'storage#object',
                            'labels': ['WGS35', 'Blob', 'Ubam'],
                            'md5Hash': 'opGAi0f9olAu4DKzvYiayg==',
                            'mediaLink': 'https://www.googleapis.com/download/storage/v1/b/***REMOVED***-dev-from-personalis-gatk/o/SHIP4946367%2Ffastq-to-vcf%2Ffastq-to-ubam%2Foutput%2FSHIP4946367_2.ubam?generation=1557970088457364&alt=media',
                            'metageneration': '3',
                            'name': 'SHIP4946367_2',
                            'path': 'SHIP4946367/fastq-to-vcf/fastq-to-ubam/output/SHIP4946367_2.ubam',
                            'sample': 'SHIP4946367',
                            'selfLink': 'https://www.googleapis.com/storage/v1/b/***REMOVED***-dev-from-personalis-gatk/o/SHIP4946367%2Ffastq-to-vcf%2Ffastq-to-ubam%2Foutput%2FSHIP4946367_2.ubam',
                            'size': 16886179620,
                            'storageClass': 'REGIONAL',
                            'timeCreated': '2019-05-16T01:28:08.455Z',
                            'timeCreatedEpoch': 1557970088.455,
                            'timeCreatedIso': '2019-05-16T01:28:08.455000+00:00',
                            'timeStorageClassUpdated': '2019-05-16T01:28:08.455Z',
                            'timeUpdatedEpoch': 1558045261.522,
                            'timeUpdatedIso': '2019-05-16T22:21:01.522000+00:00',
                            'trellisTask': 'fastq-to-ubam',
                            'trellisWorkflow': 'fastq-to-vcf',
                            'updated': '2019-05-16T22:21:01.522Z'
                        },
                        {
                            'basename': 'SHIP4946367_0.ubam',
                            'bucket': '***REMOVED***-dev-from-personalis-gatk',
                            'contentType': 'application/octet-stream',
                            'crc32c': 'ZaJM+g==',
                            'dirname': 'SHIP4946367/fastq-to-vcf/fastq-to-ubam/output',
                            'etag': 'CM+sxKDynuICEAY=',
                            'extension': 'ubam',
                            'generation': '1557969926952527',
                            'id': '***REMOVED***-dev-from-personalis-gatk/SHIP4946367/fastq-to-vcf/fastq-to-ubam/output/SHIP4946367_0.ubam/1557969926952527',
                            'kind': 'storage#object',
                            'labels': ['WGS35', 'Blob', 'Ubam'],
                            'md5Hash': 'Tgh+eyIiKe8TRWV6vohGJQ==',
                            'mediaLink': 'https://www.googleapis.com/download/storage/v1/b/***REMOVED***-dev-from-personalis-gatk/o/SHIP4946367%2Ffastq-to-vcf%2Ffastq-to-ubam%2Foutput%2FSHIP4946367_0.ubam?generation=1557969926952527&alt=media',
                            'metageneration': '6',
                            'name': 'SHIP4946367_0',
                            'path': 'SHIP4946367/fastq-to-vcf/fastq-to-ubam/output/SHIP4946367_0.ubam',
                            'sample': 'SHIP4946367',
                            'selfLink': 'https://www.googleapis.com/storage/v1/b/***REMOVED***-dev-from-personalis-gatk/o/SHIP4946367%2Ffastq-to-vcf%2Ffastq-to-ubam%2Foutput%2FSHIP4946367_0.ubam',
                            'size': 16871102587,
                            'storageClass': 'REGIONAL',
                            'timeCreated': '2019-05-16T01:25:26.952Z',
                            'timeCreatedEpoch': 1557969926.952,
                            'timeCreatedIso': '2019-05-16T01:25:26.952000+00:00',
                            'timeStorageClassUpdated': '2019-05-16T01:25:26.952Z',
                            'timeUpdatedEpoch': 1558045265.901,
                            'timeUpdatedIso': '2019-05-16T22:21:05.901000+00:00',
                            'trellisTask': 'fastq-to-ubam',
                            'trellisWorkflow': 'fastq-to-vcf',
                            'updated': '2019-05-16T22:21:05.901Z'
                        }
                    ]
                }
            ]
        }
    }

    with open('test-inputs.json', 'w') as fh:
        fh.write(json.dumps(data))

    data = json.dumps(data).encode('utf-8')
    event = {'data': base64.b64encode(data)}

    result = launch_gatk_5_dollar(event, context=None)