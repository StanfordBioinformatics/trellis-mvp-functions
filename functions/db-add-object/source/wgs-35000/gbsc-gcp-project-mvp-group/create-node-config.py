import datetime
import iso8601

def _remove_value_is_dict(raw_dict):
  """Remove dict entries where the value is of type dict"""

  clean_dict = dict(raw_dict)

  for key, value in clean_dict.items():
    if isinstance(value, dict):
      del clean_dict[key]
  return clean_dict

def get_seconds_from_epoch(datetime_obj):
    """Get datetime as total seconds from epoch.

    Provides datetime in easily sortable format
    """
    return (datetime_obj - datetime(1970, 1, 1, tzinfo=pytz.UTC)).total_seconds()

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

def get_date_object(date_string):
  return iso8601.parse_date(date_string)

def get_generic_name_fields(event_name):
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

class Sample:

    def __init__(self, event, context):

        self.labels = ['Sample', 'WGS_9000', 'Group']

        # First element == parent directory == sample name
        path = event['name']
        sample = path.split('/')[0]

        self.db_dict = {
                        'sample': sample, 
                        'labels': labels
                       }

    def get_db_dict(self):

        return(self.db_dict)

class SampleTar:

    def __init__(self, event, context):

        labels = ['Sample_tar', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = name_fields['path'].split('/')[0]

        # Copy GCS metadata to database
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class Bam:

    def __init__(self, event, context):

        labels = ['Bam', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = name_fields['path'].split('/')[0]
        chromosome = split_string(
                                  string = name_fields['name'], 
                                  delimiter = "_", 
                                  index = 2, 
                                  req_type = str)

        # Copy GCS metadata to database
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['chromosome'] = chromosome
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class Bai:

    def __init__(self, event, context):

        labels = ['Bai', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = name_fields['path'].split('/')[0]
        chromosome = split_string(
                                  string = name_fields['name'], 
                                  delimiter = "_", 
                                  index = 2, 
                                  req_type = str)
        
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['chromosome'] = chromosome
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class CnvReport:

    def __init__(self, event, context):

        labels = ['Cnv_report', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = name_fields['path'].split('/')[0]
        
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class SmallVariantReport:

    def __init__(self, event, context):

        labels = ['Small_variant_report', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = str(name_fields['path'].split('/')[0])
        category = str(name_fields['dirname'].split('/')[2])
        
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['category'] = category
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class Bed:

    def __init__(self, event, context):

        labels = ['Bed', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = str(name_fields['path'].split('/')[0])
        category = str(name_fields['extension'].split('.')[0])
        
        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)

        db_dict['sample'] = sample
        db_dict['category'] = category
        db_dict['labels'] = labels 

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class Fastq:

    def __init__(self, event, context):

        labels = ['Fastq', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        # Custom metadata fields
        sample = str(name_fields['path'].split('/')[0])
        mate_pair = search_string(
                                  string = name_fields['name'], 
                                  pattern = "_R(\\d)$", 
                                  group = 1, 
                                  req_type = int)
        index = int(name_fields['name'].split('_')[1])
        #/

        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)
        db_dict['labels'] = labels

        db_dict['sample'] = sample
        db_dict['mate-pair'] = category
        db_dict['index'] = index

        self.db_dict = db_dict

    def get_db_dict(self):

        return(self.db_dict)

class PersonalisQc:

    def __init__(self, event, context):

        labels = ['Personalis_qc', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = str(name_fields['path'].split('/')[0])

        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)
        db_dict['labels'] = labels

        db_dict['sample'] = sample

        self.db_dict = db_dict

    def get_db_dict(self):
        return(self.db_dict)

class PersonalisQcStatic:

    def __init__(self, event, context):

        labels = ['Personalis_qc_static', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = str(name_fields['path'].split('/')[0])

        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)
        db_dict['labels'] = labels

        db_dict['sample'] = sample

        self.db_dict = db_dict

    def get_db_dict(self):
        return(self.db_dict)    

class Vcf:

    def __init__(self, event, context):
        
        labels = ['Vcf', 'WGS_9000', 'Group']

        name_fields = get_generic_name_fields(event['name'])

        sample = str(name_fields['path'].split('/')[0])

        db_dict = _remove_value_is_dict(event)
        db_dict.update(name_fields)
        db_dict['labels'] = labels

        db_dict['sample'] = sample

        self.db_dict = db_dict

    def get_db_dict(self):
        return(self.db_dict)  

## Potentially use these generic classes going forward
#class NamedNode:

#class DirectoryNode:

#class ObjectNode:

class NodeKinds:

    def __init__(self):
        """Use to determine which kind of database node should be created.
        """
        self.match_patterns = {
                               "Sample": ["SHIP\\d+/"], 
                               "Sample_tar": [".*/SHIP\\d+\\.tar$"], 
                               "Bam": [".*/Alignments/.*\\.bam$"], 
                               "Bai": [".*/Alignments/.*bam\\.bai$"], 
                               "Fastq": [".*/FASTQ/.*\\.fastq\\.gz"], 
                               "Vcf": [".*/Variants/.*\\.vcf\\.gz$"], 
                               "Cnv_report": [
                                              ".*/Annotated_CopyNumber_Reports/tsv/.*\\.tsv", 
                                              ".*/Variants/.*\\.genomeCNV\\.gff"], 
                               "Small_variant_report": [".*/Annotated_SmallVariant_Reports/.*/tsv/.*\\.tsv"], 
                               "Personalis_qc": [
                                                 ".*/QC_REPORT/.*_statistics\\.tsv", 
                                                 ".*/QC_REPORT/.*_statistics\\.html"],
                               "Personalis_qc_static": [".*/QC_REPORT/static/.*"], 
                               "Bed": [".*/BED/.*\\.bed$"] 
        }

        self.kind_classes = {
                             "Sample": Sample, 
                             "Sample_tar": SampleTar,
                             "Bam": Bam, 
                             "Bai": Bai, 
                             "Cnv_report": CnvReport, 
                             "Small_variant_report": SmallVariantReport, 
                             "Bed": Bed, 
                             "Fastq": Fastq, 
                             "Personalis_qc": PersonalisQc, 
                             "Personalis_qc_static": PersonalisQcStatic, 
                             "Vcf": Vcf

        }

    def get_match_patterns(self):
        return self.match_patterns

    def get_class(self, name):
        """Return class whose name matches input string.
        """
        return self.kind_classes[name]
