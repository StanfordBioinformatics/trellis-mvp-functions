import re
import json
import pytz
import iso8601

from datetime import datetime

from google.cloud import storage

def clean_metadata_dict(raw_dict):
    """Remove dict entries where the value is of type dict"""
    clean_dict = dict(raw_dict)

    # Remove values that are dicts
    delete_keys = []
    for key, value in clean_dict.items():
        if isinstance(value, dict):
            #del clean_dict[key]
            delete_keys.append(key)

    for key in delete_keys:
        del clean_dict[key]

    # Convert size field from str to int
    clean_dict['size'] = int(clean_dict['size'])

    return clean_dict


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


def search_string(string, pattern, group, req_type):
    # kwargs: [pattern, string, group, req_type]
    """Calls regex search function using specified values. 

    Args:
        pattern (str): Pattern to search for. 
        string (str): String that will be searched. 
        group (int): Index of matching group to be returned.
        req_type (type): Type of value that should be returned.

    Returns:
        value (req_type): (n)th element of group elements, where 
                          n==group and type==req_type.

    """
    match = re.search(pattern, string)
    if not match:
        # Throw exception
        print("Error: no match found")
        pdb.set_trace()
    else:
        match_value = match.group(group)

    typed_value = req_type(match_value)

    return(typed_value)


def split_string(string, delimiter, index, req_type):
    """Calls split function on string.

    Args: 
        string (str): String that will be split.
        delimiter (str): Delimiter that will be used to split string. 
        index (int): Index of elements generated by split, that should 
                     be returned. 
        req_type (type): Type of value that should be returned.

    Returns:
        value (req_type): The (n)th element of the split elements, where
                          n==index and type==req_type.
    """
    value = string.split(delimiter)[index]
    typed_value = req_type(value)

    return(typed_value)


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


def get_standard_name_fields(event_name):
    path_elements = event_name.split('/')
    name_elements = path_elements[-1].split('.')
    name_fields = {
                   "path": event_name,
                   "dirname": '/'.join(path_elements[:-1]),
                   "basename": path_elements[-1],
                   "name": name_elements[0],
                   "extension": '.'.join(name_elements[1:])
    }
    return name_fields


def get_standard_time_fields(event):
    """
    Args:
        event (dict): Metadata properties stored as strings
    Return
        (dict): Times in iso (str) and from-epoch (int) formats
    """
    datetime_created = get_datetime_iso8601(event['timeCreated'])
    datetime_updated = get_datetime_iso8601(event['updated'])


    time_created_epoch = get_seconds_from_epoch(datetime_created)
    time_created_iso = datetime_created.isoformat()

    time_updated_epoch = get_seconds_from_epoch(datetime_updated)
    time_updated_iso = datetime_updated.isoformat()

    time_fields = {
                   'timeCreatedEpoch': time_created_epoch,
                   'timeUpdatedEpoch': time_updated_epoch,
                   'timeCreatedIso': time_created_iso,
                   'timeUpdatedIso': time_updated_iso
    }
    return time_fields

## Functions for paring custom metadata from blob metadata

def trellis_metadata_groupdict(db_dict, groupdict):
    return {
            'plate': groupdict['plate'],
            'sample': groupdict['sample'],
    }


def mate_pair_name_0(db_dict, groupdict):
    mate_pair = search_string(
                          string = db_dict['name'], 
                          pattern = "_R(\\d)$", 
                          group = 1, 
                          req_type = int)
    return {'matePair': mate_pair}


def read_group_name_1(db_dict, groupdict):
    """Get 2nd element of db_dict['name'] property & return as readGroup.
    """
    index = db_dict['name'].split('_')[1]
    return {'readGroup': int(index)}  


def read_json(db_dict, groupdict):
    """For a json object, get and return json data.

    Args:
        db_dict(dict): Properties from GCS & standard metadata fields
            generated by Trellis.
        groupdict(dict): Properties generated by match() operation
            to determine whether object path matches a node pattern.
    """
    json_content = storage.Client() \
        .get_bucket(db_dict['bucket']) \
        .blob(db_dict['path']) \
        .download_as_string()
    json_data = json.loads(json_content)
    return json_data


# Relationship functions
def relate_job_to_output(db_dict):

    query = (
             f"MATCH (j:Job {{ taskId:\"{db_dict['taskId']}\" }} ), " +
             f"(b:Blob {{taskId:\"{db_dict['taskId']}\", " +
                       f"id:\"{db_dict['id']}\" }})" +
             f"CREATE (j)-[:OUTPUT]->(b) " +
              "RETURN b")
    return query


class NodeEntry:

    def __init__(self, event, context, labels, label_functions=[]):
        """
        Args:
            event (dict): Blob metadata generated by GCP REST API
            context (dict): Event context generated by GCP REST API
            labels (list): List of database node labels
            label_functions (list): List of functions used to get custom metadata
        
        Returns:

        """
        db_dict = clean_metadata_dict(event)

        name_fields = get_standard_name_fields(event['name'])
        time_fields = get_standard_time_fields(event)

        db_dict.update(name_fields)
        db_dict.update(time_fields)

        # This custom metadata field gets added to all nodes
        db_dict['labels'] = labels

        print(f'>> Label functions: {label_functions}.')
        for function in label_functions:
            custom_fields = function(db_dict)
            db_dict.update(custom_fields)

        self.db_dict = db_dict
        self.gcp_metadata = event

        # Key, value pairs unique to db_dict are trellis metadata
        self.trellis_metadata = {}
        for key, value in self.db_dict.items():
            if not key in self.gcp_metadata.keys():
                self.trellis_metadata[key] = value

    def get_db_dict(self):
        return(self.db_dict)

    def get_gcp_metadata(self):
        return(self.gcp_metadata)

    def get_trellis_metadata(self):
        return(self.trellis_metadata)

class NodeKinds:

    def __init__(self):
        """Use to determine which kind of database node should be created.
        """

        self.match_patterns = {
                               "Blob": [r"^va_mvp_phase2/(?P<plate>\w+)/(?P<sample>\w+)/.*"],
                               "Fastq": ["va_mvp_phase2/.*/.*/FASTQ/.*\\.fastq.gz$"], 
                               "Microarray": ["^va_mvp_phase2/.*/.*/Microarray/.*"], 
                               "PersonalisSequencing": ["^va_mvp_phase2/.*\\.json$"],
                               "Json": ["^va_mvp_phase2/.*\\.json$"],
                               "Checksum": ["^va_mvp_phase2/.*checksum.txt"], 
                               "WGS35": ["^va_mvp_phase2/.*"],
                               "FromPersonalis": ["^va_mvp_phase2/.*"],
        }

        self.label_functions = {
                                "Blob": [trellis_metadata_groupdict],
                                "Fastq": [
                                          mate_pair_name_0, 
                                          read_group_name_1],
                                "PersonalisSequencing": [read_json]
        }

    def get_label_functions(self, labels):
        all_functions = []

        for label in labels:
            label_functions = self.label_functions.get(label)
            if label_functions:
                all_functions.extend(label_functions)
        return all_functions

    def get_global_labels(self):
        return self.global_labels

    def get_match_patterns(self):
        return self.match_patterns

    def get_class(self, name):
        """Return class whose name matches input string.
        """
        return self.kind_classes[name]

class RelationshipKinds:

    def __init__(self):

        self.shipping_properties = {}
