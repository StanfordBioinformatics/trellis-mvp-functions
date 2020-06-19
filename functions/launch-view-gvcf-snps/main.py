import os
import pdb
import sys
import json
import time
import uuid
import yaml
import base64
import random
import hashlib
import logging

from google.cloud import storage
from google.cloud import pubsub

from datetime import datetime

from dsub.commands import dsub

class Struct:
    # https://stackoverflow.com/questions/6866600/how-to-parse-read-a-yaml-file-into-a-python-object
    def __init__(self, **entries):
        self.__dict__.update(entries)


ENVIRONMENT = os.environ.get('ENVIRONMENT', '')
if not ENVIRONMENT:
    ENVIRONMENT == 'local'

if ENVIRONMENT == 'google-cloud':
    FUNCTION_NAME = os.environ['FUNCTION_NAME']
    
    vars_blob = storage.Client() \
                .get_bucket(os.environ['CREDENTIALS_BUCKET']) \
                .get_blob(os.environ['CREDENTIALS_BLOB']) \
                .download_as_string()
    parsed_vars = yaml.load(vars_blob, Loader=yaml.Loader)

    PROJECT_ID     = parsed_vars['GOOGLE_CLOUD_PROJECT']
    NEW_JOBS_TOPIC = parsed_vars['NEW_JOBS_TOPIC']
    REGIONS = parsed_vars['DSUB_REGIONS']
    OUT_BUCKET = parsed_vars['DSUB_OUT_BUCKET']
    LOG_BUCKET = parsed_vars['DSUB_LOG_BUCKET']
    DSUB_USER = parsed_vars['DSUB_USER']
    NETWORK = parsed_vars['DSUB_NETWORK']
    SUBNETWORK = parsed_vars['DSUB_SUBNETWORK']

    # Job specific variables
    REF_FASTA = parsed_vars['REF_FASTA']
    REF_FASTA_INDEX = parsed_vars['REF_FASTA_INDEX']
    SNP_LIST = parsed_vars['SIGNATURES']

    PUBLISHER = pubsub.PublisherClient()
    CLIENT = storage.Client()

class TrellisMessage:

    def __init__(self, event, context):
        """Parse Trellis messages from Pub/Sub event & context.

        Args:
            event (type):
            context (type):

        Message format:
            - context
                - event_id (required)
            - event
                - header
                    - sentFrom (required)
                    - method (optional)
                    - resource (optional)
                    - labels (optional)
                    - seedId (optional)
                    - previousEventId (optional)
                - body
                    - cypher (optional)
                    - results (optional)
        """
        pubsub_message = base64.b64decode(event['data']).decode('utf-8')
        data = json.loads(pubsub_message)
        logging.info(f"> Context: {context}.")
        logging.info(f"> Data: {data}.")
        logging.info(f"> Context: {context}.")
        logging.info(f"> Data: {data}.")
        
        header = data['header']
        body = data['body']

        self.event_id = context.event_id
        self.seed_id = header.get('seedId')
        
        # If no seed specified, assume this is the seed event
        if not self.seed_id:
            self.seed_id = self.event_id

        self.header = data['header']
        self.body = data['body']

        self.results = {}
        if body.get('results'):
            self.results = body.get('results')

        self.node = None
        if self.results.get('node'):
            self.node = self.results['node']


def format_pubsub_message(job_dict, seed_id, event_id, function_name):
    message = {
        "header": {
            "resource": "job-metadata",
            "method": "POST",
            "labels": ["Create", "Job", "ViewGvcfSnps", "Node"],
            "sentFrom": function_name,
            "seedId": seed_id,
            "previousEventId": event_id
        },
        "body": {
            "node": job_dict,
        }
    }
    return message


def publish_to_topic(publisher, project_id, topic, data):
    topic_path = publisher.topic_path(project_id, topic)
    data = json.dumps(data).encode('utf-8')
    result = publisher.publish(topic_path, data=data)
    return result


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


def load_json(path):
    with open(path) as fh:
        data = json.load(fh)
    return data


def check_conditions(node):
    required_labels = ['Blob', 'Vcf', 'Merged', 'Gzipped']

    conditions = [
        # Check that all required labels are present
        set(required_labels).issubset(set(node.get('labels'))),
    ]

    for condition in conditions:
        if condition:
            continue
        else:
            return False
    return True


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


def load_local_env():
    class Struct:
        # https://stackoverflow.com/questions/6866600/how-to-parse-read-a-yaml-file-into-a-python-object
        def __init__(self, **entries):
            self.__dict__.update(entries)

    with open('trellis-config.yaml', 'r') as fh:
        trellis_vars = yaml.load(fh, Loader=yaml.Loader)
    trellis = Struct(**trellis_vars)
    return trellis


def launch_view_gvcf_snps(event, context, test=False):
    """When an object node is added to the database, launch any
       jobs corresponding to that node label.

       Args:
            event (dict): Event payload.
            context (google.cloud.functions.Context): Metadata for the event.
    """

    if test:
        trellis = load_local_env()
        FUNCTION_NAME = 'trellis-launch-gvcf-snps'
        PUBLISHER = pubsub.PublisherClient()

    # Parse message
    message = TrellisMessage(event, context)
    node = message.node

    # Check that message includes node metadata
    if not node:
        logging.warning("> No node provided. Exiting.")
        return(1)

    #filetype = node['filetype'].upper()

    # Create unique task ID
    datetime_stamp = get_datetime_stamp()
    task_id, trunc_nodes_hash = make_unique_task_id([node], datetime_stamp)

    # Check whether node & message metadata meets function conditions
    conditions_met = check_conditions(node)
    if not conditions_met:
        raise RuntimeError(f"> Input node does not match requirements. Node: {node}.")

    # Database entry variables
    bucket = node['bucket']
    plate = node['plate']
    path = node['path']
    sample = node['sample']
    basename = node['basename']

    task_name = 'view-gvcf-snps'
    unique_task_label = 'ViewGvcfSnps'
    job_dict = {
        "provider": "google-v2",
        "user": trellis.DSUB_USER,
        "regions": trellis.DSUB_REGIONS,
        "project": trellis.GOOGLE_CLOUD_PROJECT,
        "minCores": 1,
        "image": f"gcr.io/{trellis.GOOGLE_CLOUD_PROJECT}/biocontainers/bcftools:v1.9-1-deb_cv1",
        "logging": f"gs://{trellis.DSUB_LOG_BUCKET}/{plate}/{sample}/{task_name}/{task_id}/logs",
        # bcftools view <SAMPLE>.g.vcf.gz -R signatureSNPs.txt -Ou | 
        # bcftools convert --gvcf2vcf --fasta-ref Homo_sapiens_assembly38.fasta -Ou | 
        # bcftools view -T signatureSNPs.txt -Oz -o <SAMPLE>.signatureSNPs.vcf.gz

        "command": (
                    "bcftools index --tbi ${INPUT} | " +
                    "bcftools view ${INPUT} -R {$SNP_LIST} -Ou | " +
                    "bcftools convert --gvcf2vcf --fasta-ref ${REF_FASTA} -Ou | " +
                    "bcftools view -T ${SNP_LIST} -Oz -o ${OUTPUT}"),
                    #"bcftools view -Oz -o ${OUTPUT}"
        "envs": {
            "SAMPLE_ID": sample
        },
        "inputs": {
            "INPUT": f"gs://{bucket}/{path}",
            "SNP_LIST": trellis.SNP_LIST, 
            "REF_FASTA": trellis.REF_FASTA,
            "REF_FASTA_INDEX": trellis.REF_FASTA_INDEX
        },
        "outputs": {
            "OUTPUT": f"gs://{trellis.DSUB_OUT_BUCKET}/{plate}/{sample}/{task_name}/{task_id}/output/{sample}.signatureSNPs.vcf.gz"
        },
        "trellisTaskId": task_id,
        "sample": sample,
        "plate": plate,
        "name": task_name,
        "inputHash": trunc_nodes_hash,
        "labels": ["Job", "Dsub", unique_task_label],
        "inputIds": [node['id']],
        "network": trellis.DSUB_NETWORK,
        "subnetwork": trellis.DSUB_SUBNETWORK,       
    }

    dsub_args = [
        "--name", f"{task_name}-{job_dict['inputHash'][0:5]}",
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
        "--logging", job_dict["logging"],
        "--image", job_dict["image"],
        #"--use-private-address",
        "--network", job_dict["network"],
        "--subnetwork", job_dict["subnetwork"],        
        "--command", job_dict["command"],
    ]

    # Perform dry-run on local execution
    if test:
        dsub_args.extend(['--ssh', '--keep-alive', '600'])
    #    dsub_args.append('--dry-run')

    # Add dsub list arguments
    for key, value in job_dict["inputs"].items():
        dsub_args.extend([
                          "--input", 
                          f"{key}={value}"])
    for key, value in job_dict['envs'].items():
        dsub_args.extend([
                          "--env",
                          f"{key}={value}"])
    for key, value in job_dict['outputs'].items():
        dsub_args.extend([
                          "--output",
                          f"{key}={value}"])
    
    # Launch dsub job
    print(f"> Launching dsub with args: {dsub_args}.")
    dsub_result = launch_dsub_task(dsub_args)
    print(f"> Dsub result: {dsub_result}.")

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

        # Format inputs for neo4j database
        for key, value in job_dict["inputs"].items():
            job_dict[f"input_{key}"] = value
        for key, value in job_dict["envs"].items():
            job_dict[f"env_{key}"] = value
        for key, value in job_dict["outputs"].items():
            job_dict[f"output_{key}"] = value

        # Send job metadata to create-job-node function
        message_to_publish = format_pubsub_message(
                                        job_dict = job_dict,
                                        seed_id = message.seed_id,
                                        event_id = message.event_id,
                                        function_name = FUNCTION_NAME)
        print(f"> Pubsub message: {message_to_publish}.")
        result = publish_to_topic(
                                  publisher = PUBLISHER,
                                  project_id = trellis.GOOGLE_CLOUD_PROJECT,
                                  topic = trellis.NEW_JOBS_TOPIC,
                                  data = message_to_publish) 
        print(f"> Published message to {trellis.NEW_JOBS_TOPIC} with result: {result}.")  


