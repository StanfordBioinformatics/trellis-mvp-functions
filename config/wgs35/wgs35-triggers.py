import time

MAX_RETRIES = 10

class AddFastqSetSize:
    """Add setSize property to Fastqs and send them back to 
    triggers to launch fastq-to-ubam.
    """

    def __init__(self, function_name, env_vars):
        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):

        required_labels = [
                           'Json',
                           'FromPersonalis',
                           'Marker']

        if not node:
            return False

        conditions = [
            set(required_labels).issubset(set(node.get('labels'))),
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        sample = node['sample']

        message = {
                   "header": {
                              "resource": "query",
                              "method": "UPDATE",
                              "labels": ["Cypher", "Query", "Set", "Properties"], 
                              "sentFrom": self.function_name,
                              "publishTo": self.env_vars['TOPIC_TRIGGERS'],
                   },
                   "body": {
                          "cypher": (
                                     "MATCH (n:Fastq) " +
                                    f"WHERE n.sample=\"{sample}\" " +
                                     "WITH n.sample AS sample, " +
                                     "COLLECT(n) AS nodes " +
                                     "UNWIND nodes AS node " +
                                     "SET node.setSize = size(nodes)" +
                                     "RETURN node "),
                          "result-mode": "data",
                          "result-structure": "list",
                          "result-split": "True",
                   }
        }
        return([(topic, message)])


class CheckUbamCount:

    def __init__(self, function_name, env_vars):
        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        # Only trigger GATK after relationship has been added
        reqd_header_labels = ['Relationship', 'Database', 'Result']
        required_labels = ['Ubam']

        if not node:
            return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            set(required_labels).issubset(set(node.get('labels'))),
            node.get('setSize'),
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        """Send full set of ubams to GATK task"""
        topic = self.env_vars['DB_QUERY_TOPIC']

        sample = node['sample']
        set_size = node['setSize']

        message = {
                   "header": {
                              "resource": "query",
                              "method": "VIEW",
                              "labels": ["Cypher", "Query", "Ubam", "GATK", "Nodes"],
                              "sentFrom": self.function_name,
                              "publishTo": self.env_vars['TOPIC_GATK_5_DOLLAR'],
                   },
                   "body": {
                            "cypher": (
                                       "MATCH (n:Ubam) " +
                                       f"WHERE n.sample=\"{sample}\" " +
                                       "AND NOT (n)-[:INPUT_TO]->(:Job:Cromwell {name: \"gatk-5-dollar\"}) " +
                                       "WITH n.sample AS sample, " +
                                       "n.readGroup AS readGroup, " +
                                       "COLLECT(n) as allNodes " +
                                       "WITH head(allNodes) AS heads " +
                                       "UNWIND [heads] AS uniqueNodes " +
                                       "WITH uniqueNodes.sample AS sample, " +
                                       "uniqueNodes.setSize AS setSize, " +
                                       "COLLECT(uniqueNodes) AS sampleNodes " +
                                       "WHERE size(sampleNodes) = setSize " +
                                       "RETURN sampleNodes AS nodes"),
                            "result-mode": "data", 
                            "result-structure": "list",
                            "result-split": "True",
                   }
        }
        return([(topic, message)])


class GetFastqForUbam:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):

        required_labels = [
                           'Blob', 
                           'Fastq', 
                           'WGS35', 
                           'FromPersonalis']

        if not node:
            return False

        conditions = [
            node.get('setSize'),
            node.get('sample'),
            node.get('readGroup') == 0,
            node.get('matePair') == 1,
            set(required_labels).issubset(set(node.get('labels'))),
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        sample = node['sample']

        message = {
                   "header": {
                              "resource": "query",
                              "method": "VIEW",
                              "labels": ["Cypher", "Query", "Fastq", "Nodes"],
                              "sentFrom": self.function_name,
                              "publishTo": self.env_vars['TOPIC_FASTQ_TO_UBAM'],
                   },
                   "body": {
                            "cypher": (
                                       "MATCH (n:Fastq) " + 
                                       f"WHERE n.sample=\"{sample}\" " +
                                       "AND NOT (n)-[*2]->(:Ubam) " +
                                       "WITH n.readGroup AS read_group, " +
                                       "n.setSize AS set_size, " +
                                       "COLLECT(n) AS nodes " +
                                       "WHERE size(nodes) = 2 " + 
                                       "RETURN [n IN nodes] AS nodes, "
                                       "set_size/2 AS metadata_setSize"
                            ), 
                            "result-mode": "data",
                            "result-structure": "list",
                            "result-split": "True"
                   }
        }
        return([(topic, message)])


class KillDuplicateJobs:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        # Only trigger when job node is created
        reqd_header_labels = ['Update', 'Job', 'Node']

        required_labels = ['Job']

        if not node:
            return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            set(required_labels).issubset(set(node.get('labels'))),
            node.get('startTime'),
            node.get('instanceName'),
            node.get('instanceId'),
            node.get('inputHash'),
            node.get('status') == 'RUNNING',
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        """
        Send results to 
            1) kill-duplicates to kill jobs and 
            2) triggers to mark job a duplicate in database
        """
        topic = self.env_vars['DB_QUERY_TOPIC']

        sample = node['sample']
        name = node['name']
        input_hash = node['inputHash']

        message = {
                   "header": {
                              "resource": "query",
                              "method": "VIEW",
                              "labels": ["Duplicate", "Jobs", "Running", "Cypher", "Query", ],
                              "sentFrom": self.function_name,
                              "publishTo": [
                                            self.env_vars['TOPIC_KILL_DUPLICATES'],
                                            self.env_vars['DB_QUERY_TOPIC']
                              ]
                   }, 
                   "body": {
                        "cypher": (
                            "MATCH (n:Job) " +
                            f"WHERE n.sample = \"{sample}\" " +
                            f"AND n.name = \"{name}\" " +
                            f"AND n.inputHash = \"{input_hash}\" " +
                            "AND n.status = \"RUNNING\" " +
                            "WITH n.inputHash AS hash, " +
                            "COLLECT(n) AS nodes " +
                            "WHERE SIZE(nodes) > 1 " +
                            "UNWIND tail(nodes) AS node " +
                            "RETURN node"
                        ),
                        "result-mode": "data",
                        "result-structure": "list",
                        "result-split": "True"
                   }
        }
        return([(topic, message)])


class MarkJobAsDuplicate:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        # Only trigger when job node is created
        reqd_header_labels = ['Duplicate', 'Jobs', 'Database', 'Result']

        required_labels = ['Job']

        if not node:
            return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            set(required_labels).issubset(set(node.get('labels'))),
            not "Duplicate" in node.get('labels')
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        """Mark duplicate job in the database.
        """
        topic = self.env_vars['DB_QUERY_TOPIC']

        instance_name = node['instanceName']

        query = self._create_query(instance_name)

        message = {
                   "header": {
                              "resource": "query",
                              "method": "UPDATE",
                              "labels": ["Mark", "Duplicate", "Job", "Cypher", "Query"],
                              "sentFrom": self.function_name,
                   }, 
                   "body": {
                        "cypher": query,
                        "result-mode": "stats"
                   }
        }
        return([(topic, message)])


    def _create_query(self, instance_name):
        query = (
                  "MATCH (n:Job) " +
                 f"WHERE n.instanceName = \"{instance_name}\" " +
                  "SET n.labels = n.labels + \"Duplicate\", " +
                  "n:Marker, " +
                  "n.duplicate=True")
        return query


class RequeueJobQuery:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node=None):
        reqd_header_labels = ['Query', 'Cypher', 'Update', 'Job', 'Node']

        conditions = [
            header.get('method') == "UPDATE",
            (not header.get('retry-count') 
             or header.get('retry-count') < MAX_RETRIES),
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            not node
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True


    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        # Requeue original message, updating sentFrom property
        message = {}
        
        # Add retry count
        retry_count = header.get('retry-count')
        if retry_count:
            header['retry-count'] += 1
        else:
            header['retry-count'] = 1

        header['sentFrom'] = self.function_name
        header['resource'] = 'query'
        header['publishTo'] = self.function_name
        header['labels'].remove('Database')
        header['labels'].remove('Result')

        del(body['results'])
        body['result-mode'] = 'data'
        body['result-structure'] = 'list'
        body['result-split'] = 'True'

        message['header'] = header
        message['body'] = body

        # Wait 2 seconds before re-queueing
        time.sleep(2)

        return([(topic, message)])


class RequeueRelationshipQuery:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars

    def check_conditions(self, header, body, node=None):
        reqd_header_labels = ['Relationship', 'Create', 'Cypher', 'Query', ]

        conditions = [
            header.get('method') == "POST",
            (not header.get('retry-count') 
             or header.get('retry-count') < MAX_RETRIES),
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            not node
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True

    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        # Requeue original message, updating sentFrom property
        message = {}

        # Add retry count
        retry_count = header.get('retry-count')
        if retry_count:
            header['retry-count'] += 1
        else:
            header['retry-count'] = 1
        
        header['sentFrom'] = self.function_name
        header['resource'] = 'query'
        header['publishTo'] = self.function_name
        header['labels'].remove('Database')
        header['labels'].remove('Result')

        del(body['results'])
        body['result-mode'] = 'data'
        body['result-structure'] = 'list'
        body['result-split'] = 'True'

        message['header'] = header
        message['body'] = body

        # Wait 2 seconds before re-queueing
        time.sleep(2)

        return([(topic, message)])   


class RelateOutputToJob:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars

    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Create', 'Blob', 'Node', 'Cypher', 'Query', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            node.get("nodeIteration") == "initial",
            node.get("taskId"),
            node.get("id")
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True

    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        node_id = node['id']
        task_id = node['taskId']

        query = self._create_query(node_id, task_id)

        # Requeue original message, updating sentFrom property
        message = {
                   "header": {
                              "resource": "query",
                              "method": "POST",
                              "labels": ["Create", "Relationship", "Output", "Cypher", "Query"],
                              "sentFrom": self.function_name,
                              "publishTo": self.function_name
                   },
                   "body": {
                            "cypher": query,
                            "result-mode": "data",
                            "result-structure": "list",
                            "result-split": "True"
                   }
        }
        return([(topic, message)]) 

    def _create_query(self, node_id, task_id):
        query = (
                 f"MATCH (j:Job {{ taskId:\"{task_id}\" }} ), " +
                 f"(node:Blob {{taskId:\"{task_id}\", " +
                              f"id:\"{node_id}\" }}) " +
                  "WHERE NOT j.Duplicate=True " +
                  "CREATE (j)-[:OUTPUT]->(node) " +
                  "RETURN node")


class RelatedInputToJob:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars

    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Create', 'Job', 'Node', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            "Job" in node.get("labels"),
            node.get("inputIds"),
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True

    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        messages = []
        for input_id in node["inputIds"]:
            # Create a separate message for each related node
            query = self._create_query(node, input_id)

            # Requeue original message, updating sentFrom property
            message = {
                       "header": {
                                  "resource": "query",
                                  "method": "POST",
                                  "labels": ["Create", "Relationship", "Input", "Cypher", "Query"],
                                  "sentFrom": self.function_name,
                                  "publishTo": self.function_name
                       },
                       "body": {
                                "cypher": query,
                                "result-mode": "data",
                                "result-structure": "list",
                                "result-split": "True"
                       }
            }
            result = (topic, message)
            messages.append(result)
        return(messages)  

    def _create_query(self, job_node, input_id):
        query = (
                 f"MATCH (input:Blob {{ id:\"{input_id}\" }}), " +
                 f"(job:Job {{ taskId:\"{job_node['taskId']}\"  }}) " +
                 f"CREATE (input)-[:INPUT_TO]->(job) " +
                  "RETURN job AS node")
        return query


class RunDsubWhenJobStopped:
    
    def __init__(self, function_name, env_vars):
        """Launch dstat after dsub jobs finish.
        """

        self.function_name = function_name
        self.env_vars = env_vars

    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Update', 'Job', 'Node', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            "Job" in node.get("labels"),
            node.get("status") == "STOPPED",
            node.get("dstatCmd")
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True

    def compose_message(self, header, body, node):
        topic = self.env_vars['TOPIC_DSTAT']

        messages = []
        # Requeue original message, updating sentFrom property
        message = {
                   "header": {
                              "resource": "command",
                              "method": "POST",
                              "labels": ["Dstat", "Command"],
                              "sentFrom": self.function_name,
                   },
                   "body": {
                            "command": node["dstatCmd"]
                   }
        }
        return([(topic, message)])  


class RelateDstatToJob:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Create', 'Dstat', 'Node', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            node.get("jobId"),
            node.get("instanceName")
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True    


    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        query = self._create_query(node)
        message = {
                   "header": {
                              "resource": "query",
                              "method": "POST",
                              "labels": ["Create", "Relationship", "Dstat", "Cypher", "Query"],
                              "sentFrom": self.function_name,
                              "trigger": "RelateDstatToJob",
                   },
                   "body": {
                            "cypher": query,
                            "result-mode": "stats",
                   }
        }
        return([(topic, message)])   


    def _create_query(self, node):
        query = (
                 "MATCH (job:Dsub " +
                    "{ " +
                        f"dsubJobId:\"{node['jobId']}\", " +
                        f"instanceName:\"{node['instanceName']}\" " +
                    "}), " +
                 "(dstat:Dstat " +
                    "{ " +
                        f"jobId:\"{node['jobId']}\", " +
                        f"instanceName:\"{node['instanceName']}\" " +
                    "}) " +
                  "WHERE NOT (job)-[:STATUS]->(dstat) " +
                  "CREATE (job)-[:STATUS]->(dstat) ")
        return query


class RecheckDstat:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Create', 'Dstat', 'Node', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            (not header.get('retry-count') 
             or header.get('retry-count') < MAX_RETRIES),
            node.get("status") == "RUNNING",
            node.get("command")
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True    


    def compose_message(self, header, body, node):
        topic = self.env_vars['TOPIC_DSTAT']

        message = {
                   "header": {
                              "resource": "command",
                              "method": "POST",
                              "labels": ["Dstat", "Command"],
                              "sentFrom": self.function_name,
                              "trigger": "RecheckDstat",
                   },
                   "body": {
                            "command": node["command"]
                   }
        }
        
        # Add retry count
        retry_count = header.get('retry-count')
        if retry_count:
            message["header"]["retry-count"] = retry_count + 1
        else:
            message["header"]["retry-count"] = 1
        
        # Wait 2 seconds before re-queueing
        time.sleep(2)

        return([(topic, message)])   


class RelateFromPersonalisToSample:

    def __init__(self, function_name, env_vars):

        self.function_name = function_name
        self.env_vars = env_vars


    def check_conditions(self, header, body, node):
        reqd_header_labels = ['Create', 'Blob', 'Node', 'Database', 'Result']

        if not node:
                return False

        conditions = [
            # Check that message has appropriate headers
            set(reqd_header_labels).issubset(set(header.get('labels'))),
            # Check that retry count has not been met/exceeded
            (not header.get('retry-count') 
             or header.get('retry-count') < MAX_RETRIES),
            # Check node-specific information
            "Sample" in node.get("labels")
            node.get("sample"),
            node.get("bucket")
        ]

        for condition in conditions:
            if condition:
                continue
            else:
                return False
        return True    


    def compose_message(self, header, body, node):
        topic = self.env_vars['DB_QUERY_TOPIC']

        query = self._create_query(node)

        # Requeue original message, updating sentFrom property
        message = {
                   "header": {
                              "resource": "query",
                              "method": "POST",
                              "labels": ["Create", "Relationship", "Sample", "Cypher", "Query"],
                              "sentFrom": self.function_name,
                   },
                   "body": {
                            "cypher": query
                            "result-mode": "stats"
                   }
        }
        return([(topic, message)])  

    def _create_query(self, sample_node):
        sample = sample_node['sample']
        query = (
                 f"MATCH (j:Blob:Json:FromPersonalis:Sample {{ sample:\"{sample}\" }}), " +
                  "(b:Blob:FromPersonalis) " +
                  "WHERE b.sample = j.sample " +
                  "AND b.bucket = j.bucket " +
                  "AND NOT \"Sample\" IN labels(b) " +
                  "MERGE (j)-[:HAS]->(b)")
        return query


def get_triggers(function_name, env_vars):

    triggers = []
    triggers.append(AddFastqSetSize(
                                    function_name,
                                    env_vars))
    triggers.append(CheckUbamCount(
                                   function_name,
                                   env_vars))
    triggers.append(GetFastqForUbam(
                                    function_name,
                                    env_vars))
    triggers.append(KillDuplicateJobs(
                                      function_name,
                                      env_vars))
    triggers.append(RequeueJobQuery(
                                    function_name,
                                    env_vars))
    triggers.append(RequeueRelationshipQuery(
                                    function_name,
                                    env_vars))
    triggers.append(RelateOutputToJob(
                                    function_name,
                                    env_vars))
    triggers.append(RelatedInputToJob(
                                    function_name,
                                    env_vars))
    triggers.append(RunDsubWhenJobStopped(
                                    function_name,
                                    env_vars))
    triggers.append(RelateDstatToJob(
                                    function_name,
                                    env_vars))
    triggers.append(RecheckDstat(
                                 function_name,
                                 env_vars))
    triggers.append(RelateFromPersonalisToSample(
                                    function_name,
                                    env_vars))
    triggers.append(MarkJobAsDuplicate(
                                    function_name,
                                    env_vars))
    return triggers

