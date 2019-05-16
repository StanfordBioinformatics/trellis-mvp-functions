import re
import pdb
import json
import pytz
import iso8601

from datetime import datetime

from google.cloud import storage

## Functions for paring custom metadata from blob metadata

#def sample_path_0(db_dict, groupdict):
#    value = db_dict['path'].split('/')[0] 
#    return {'sample': str(value)}

#def trellis_workflow_path_1(db_dict, groupdict):
#    value = db_dict['path'].split('/')[1] 
#    return {'trellisWorkflow': str(value)}

#def trellis_task_path_2(db_dict, groupdict):
#    value = db_dict['path'].split('/')[2] 
#    return {'trellisTask': str(value)}

def trellis_metadata_groupdict(db_dict, groupdict):
    return {
            'sample': groupdict['sample'],
            'trellis_workflow': groupdict['trellis_workflow'],
            'trellis_task': groupdict['trellis_task']
    }

def workflow_path_5(db_dict, groupdict):
    value = db_dict['path'].split('/')[5] 
    return {'workflow': str(value)}

def task_path_6(db_dict, groupdict):
    value = db_dict['path'].split('/')[6] 
    task = value.split('-')[1]
    return {'task': str(task)}

def shard_index_name_1(db_dict, groupdict):
    index = groupdict['shard_index']
    return {'shardIndex': int(index)}  

def get_metadata_from_all_json(db_dict, groupdict):

    meta_bucket = db_dict['bucket']

    meta_blob_path = db_dict['dirname'].split('/')[:-1]
    meta_blob_path.extend(['metadata', 'all-objects.json'])
    meta_blob_path = '/'.join(meta_blob_path)

    metadata_str = storage.Client() \
        .get_bucket(meta_bucket) \
        .blob(meta_blob_path) \
        .download_as_string()
    metadata = json.loads(metadata_str)
    return metadata


class NodeKinds:

    def __init__(self):
        """Use to determine which kind of database node should be created.
        """

        self.match_patterns = {
            "WGS35": [".*"],
            "Blob": ["(?P<sample>\w+)/(?P<trellis_workflow>.*)/(?P<trellis_task>.*)/output/.*"],
            "Vcf": [
                    ".*\\.vcf.gz$", 
                    ".*\\.vcf$",
            ],
            "Tbi": [".*\\.tbi$"],
            "Gzipped": [".*\\.gz$"],
            "Shard": [".*\\/shard-(?P<shard_index>\d+)\\/.*"],
            "Cram": [".*\\.cram$"], 
            "Crai": [".*\\.crai$"],
            "Bam": [".*\\.bam$"], 
            "Bai": [".*\\.bai$"],
            "Ubam": [".*\\.ubam$"],
            "Aligned": [".*\\.aligned\\..*"],
            "Filtered": [".*\\.filtered\\..*"],
            "MarkedDuplicates": [".*\\.duplicates_marked\\..*"],
            "Recalibrated": [".*\\.recalibrated\\..*", ".*\\.recal_.*"],
            "Structured": [
                           ".*\\.recal_data\\.csv$", 
                           ".*\\.preBqsr.selfSM$", 
                           ".*\\/sequence_grouping.*",
                           ".*\\.duplicate_metrics$",
            ],
            "Text": [
                     ".*\\.recal_data\\.csv$", 
                     ".*\\.preBqsr.selfSM$", 
                     ".*\\.txt$", 
                     ".*\\.duplicate_metrics$",
                     ".*\\.validation_report$",
            ],
            "Log": [".*\\.log$"],
            "Stderr": [".*\\/stderr$"],
            "Stdout": [".*\\/stdout$"],
            "Script": [".*\\/script$"],
            "Index": [
                      ".*\\.bai$",
                      ".*\\.tbi$",
                      ".*\\.crai$",
            ],
            "Data": [
                     ".*_data\\..*",
                     ".*\\.recal_data\\.csv$", 
                     ".*\\.preBqsr.selfSM$", 
                     ".*\\/sequence_grouping.*",
                     ".*\\.duplicate_metrics$",
                     ".*\\.validation_report$",
            ],
            "Unsorted": [".*\\.unsorted\\..*"],
            "Sorted": [".*\\.sorted\\..*"],
            "IntervalList": [".*\\.interval_list$"],
            "Json": [".*\\.json$"],
        }

        self.label_functions = {
                                "Blob": [
                                         trellis_metadata_groupdict,
                                         workflow_path_5,
                                         task_path_6,
                                ],
                                "Shard": [shard_index_name_1],
        }
