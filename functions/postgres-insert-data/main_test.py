import json
import mock
import base64
import google
from uuid import uuid4

import pytest

import main

mock_context = mock.Mock()
mock_context.event_id = '617187464135194'
mock_context.timestamp = '2019-07-15T22:09:03.761Z'

class TestTrellisMessage:
    """Test the TrellisMessage class.
    
        Cases:
            - expected input
            - no node
            - no seed
    """

    def test_expected(self):
        data = {
            'header': {
                'method': 'VIEW', 
                'resource': 'queryResult', 
                'labels': ['Trigger', 'Import', 'BigQuery', 'Contamination', 'Cypher', 'Query', 'Database', 'Result'], 
                'sentFrom': 'wgs35-db-query', 
                'seedId': '1062325217821887', 
                'previousEventId': '1062332838591023'
            }, 
            'body': {
                'cypher': 'MATCH (s:CromwellStep)-[:OUTPUT]->(node:Blob) WHERE node.id ="gbsc-gcp-project-mvp-dev-from-personalis-wgs35/DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM/1585064324765059" AND s.wdlCallAlias = "checkcontamination" AND NOT (node)-[:INPUT_TO]->(:JobRequest:BigQueryAppendTsv) CREATE (jr:JobRequest:BigQueryAppendTsv { sample: node.sample, nodeCreated: datetime(), nodeCreatedEpoch: datetime().epochSeconds, name: "bigquery-append-tsv", eventId: 1062332023587484 }) MERGE (node)-[:INPUT_TO]->(jr) RETURN node LIMIT 1', 
                'results': {'node': {'wdlCallAlias': 'CheckContamination', 'filetype': 'selfSM', 'extension': 'preBqsr.selfSM', 'plate': 'DVALABP000398', 'trellisTaskId': '200323-224846-831-1d509436', 'dirname': 'DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination', 'path': 'DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM', 'storageClass': 'REGIONAL', 'md5Hash': '+wodn8rzpnwpsS8cLlvHQQ==', 'timeCreatedEpoch': 1585064324.764, 'timeUpdatedEpoch': 1585064324.764, 'timeCreated': '2020-03-24T15:38:44.764Z', 'id': 'gbsc-gcp-project-mvp-dev-from-personalis-wgs35/DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM/1585064324765059', 'contentType': 'application/octet-stream', 'generation': '1585064324765059', 'nodeIteration': 'initial', 'metageneration': '1', 'kind': 'storage#object', 'timeUpdatedIso': '2020-03-24T15:38:44.764000+00:00', 'trellisTask': 'gatk-5-dollar', 'cromwellWorkflowName': 'germline_single_sample_workflow', 'sample': 'SHIP4946371', 'mediaLink': 'https://www.googleapis.com/download/storage/v1/b/gbsc-gcp-project-mvp-dev-from-personalis-wgs35/o/DVALABP000398%2FSHIP4946371%2Fgatk-5-dollar%2F200323-224846-831-1d509436%2Foutput%2Fgermline_single_sample_workflow%2F697594a9-165b-4f1e-9ee3-6e6a39cb6c88%2Fcall-CheckContamination%2FSHIP4946371.preBqsr.selfSM?generation=1585064324765059&alt=media', 'selfLink': 'https://www.googleapis.com/storage/v1/b/gbsc-gcp-project-mvp-dev-from-personalis-wgs35/o/DVALABP000398%2FSHIP4946371%2Fgatk-5-dollar%2F200323-224846-831-1d509436%2Foutput%2Fgermline_single_sample_workflow%2F697594a9-165b-4f1e-9ee3-6e6a39cb6c88%2Fcall-CheckContamination%2FSHIP4946371.preBqsr.selfSM', 'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data', 'CheckContamination'], 'nodeCreated': 1585064325422, 'bucket': 'gbsc-gcp-project-mvp-dev-from-personalis-wgs35', 'basename': 'SHIP4946371.preBqsr.selfSM', 'crc32c': '5mVCSg==', 'size': 237, 'timeStorageClassUpdated': '2020-03-24T15:38:44.764Z', 'name': 'SHIP4946371', 'etag': 'CIOrmOC4s+gCEAE=', 'timeCreatedIso': '2020-03-24T15:38:44.764000+00:00', 'cromwellWorkflowId': '697594a9-165b-4f1e-9ee3-6e6a39cb6c88', 'triggerOperation': 'finalize', 'updated': '2020-03-24T15:38:44.764Z'}}
            }
        }
        data_str = json.dumps(data)
        data_utf8 = data_str.encode('utf-8')
        event = {'data': base64.b64encode(data_utf8)}

        message = main.TrellisMessage(event, mock_context)

        # Check that everything asserts correctly
        assert message.event_id == mock_context.event_id
        assert message.seed_id  == data['header']['seedId']
        assert message.header   == data['header']
        assert message.body     == data['body']
        assert message.results  == data['body']['results']
        assert message.node     == data['body']['results']['node']

    def test_no_results(self):
        data = {
                 'header': {},
                 'body': {
                          'results': {}
                 }
        }
        data_str = json.dumps(data)
        data_utf8 = data_str.encode('utf-8')
        event = {'data': base64.b64encode(data_utf8)}

        message = main.TrellisMessage(event, mock_context)

        # Check that everything asserts correctly
        assert message.event_id == mock_context.event_id
        assert message.seed_id  == mock_context.event_id
        assert message.header   == data['header']
        assert message.body     == data['body']
        assert message.results  == data['body']['results']
        assert message.node     == None

    def test_no_seed(self):
        data = {
            'header': {
                'method': 'VIEW', 
                'resource': 'queryResult', 
                'labels': ['Trigger', 'Import', 'BigQuery', 'Contamination', 'Cypher', 'Query', 'Database', 'Result'], 
                'sentFrom': 'wgs35-db-query', 
                'previousEventId': '1062332838591023'
            }, 
            'body': {
                'cypher': 'MATCH (s:CromwellStep)-[:OUTPUT]->(node:Blob) WHERE node.id ="gbsc-gcp-project-mvp-dev-from-personalis-wgs35/DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM/1585064324765059" AND s.wdlCallAlias = "checkcontamination" AND NOT (node)-[:INPUT_TO]->(:JobRequest:BigQueryAppendTsv) CREATE (jr:JobRequest:BigQueryAppendTsv { sample: node.sample, nodeCreated: datetime(), nodeCreatedEpoch: datetime().epochSeconds, name: "bigquery-append-tsv", eventId: 1062332023587484 }) MERGE (node)-[:INPUT_TO]->(jr) RETURN node LIMIT 1', 
                'results': {'node': {'wdlCallAlias': 'CheckContamination', 'filetype': 'selfSM', 'extension': 'preBqsr.selfSM', 'plate': 'DVALABP000398', 'trellisTaskId': '200323-224846-831-1d509436', 'dirname': 'DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination', 'path': 'DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM', 'storageClass': 'REGIONAL', 'md5Hash': '+wodn8rzpnwpsS8cLlvHQQ==', 'timeCreatedEpoch': 1585064324.764, 'timeUpdatedEpoch': 1585064324.764, 'timeCreated': '2020-03-24T15:38:44.764Z', 'id': 'gbsc-gcp-project-mvp-dev-from-personalis-wgs35/DVALABP000398/SHIP4946371/gatk-5-dollar/200323-224846-831-1d509436/output/germline_single_sample_workflow/697594a9-165b-4f1e-9ee3-6e6a39cb6c88/call-CheckContamination/SHIP4946371.preBqsr.selfSM/1585064324765059', 'contentType': 'application/octet-stream', 'generation': '1585064324765059', 'nodeIteration': 'initial', 'metageneration': '1', 'kind': 'storage#object', 'timeUpdatedIso': '2020-03-24T15:38:44.764000+00:00', 'trellisTask': 'gatk-5-dollar', 'cromwellWorkflowName': 'germline_single_sample_workflow', 'sample': 'SHIP4946371', 'mediaLink': 'https://www.googleapis.com/download/storage/v1/b/gbsc-gcp-project-mvp-dev-from-personalis-wgs35/o/DVALABP000398%2FSHIP4946371%2Fgatk-5-dollar%2F200323-224846-831-1d509436%2Foutput%2Fgermline_single_sample_workflow%2F697594a9-165b-4f1e-9ee3-6e6a39cb6c88%2Fcall-CheckContamination%2FSHIP4946371.preBqsr.selfSM?generation=1585064324765059&alt=media', 'selfLink': 'https://www.googleapis.com/storage/v1/b/gbsc-gcp-project-mvp-dev-from-personalis-wgs35/o/DVALABP000398%2FSHIP4946371%2Fgatk-5-dollar%2F200323-224846-831-1d509436%2Foutput%2Fgermline_single_sample_workflow%2F697594a9-165b-4f1e-9ee3-6e6a39cb6c88%2Fcall-CheckContamination%2FSHIP4946371.preBqsr.selfSM', 'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data', 'CheckContamination'], 'nodeCreated': 1585064325422, 'bucket': 'gbsc-gcp-project-mvp-dev-from-personalis-wgs35', 'basename': 'SHIP4946371.preBqsr.selfSM', 'crc32c': '5mVCSg==', 'size': 237, 'timeStorageClassUpdated': '2020-03-24T15:38:44.764Z', 'name': 'SHIP4946371', 'etag': 'CIOrmOC4s+gCEAE=', 'timeCreatedIso': '2020-03-24T15:38:44.764000+00:00', 'cromwellWorkflowId': '697594a9-165b-4f1e-9ee3-6e6a39cb6c88', 'triggerOperation': 'finalize', 'updated': '2020-03-24T15:38:44.764Z'}}
            }
        }
        data_str = json.dumps(data)
        data_utf8 = data_str.encode('utf-8')
        event = {'data': base64.b64encode(data_utf8)}

        message = main.TrellisMessage(event, mock_context)

                # Check that everything asserts correctly
        assert message.event_id == mock_context.event_id
        assert message.seed_id  == mock_context.event_id


class TestLoadJson:

    def test_expected(self):
        data = main.load_json('postgres-config.json')
        assert len(data.keys())        == 2
        assert len(data['CSV'].keys()) == 3
        assert len(data['PREBQSR.SELFSM'].keys()) == 1


class TestCheckConditions:

    def test_expected(self):
        data_labels = ['CheckContamination']
        node = {'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data', 'CheckContamination']}

        result = main.check_conditions(data_labels, node)
        assert result == True

    def test_empty_labels(self):
        data_labels = ['CheckContamination']
        node = {'labels': []}

        result = main.check_conditions(data_labels, node)
        assert result == False

    def test_missing_data_label(self):
        data_labels = ['CheckContamination']
        node = {'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data']}

        result = main.check_conditions(data_labels, node)
        assert result == False


class TestGetTableConfigData:

    def test_expected(self):
        table_configs = {"CheckContamination" : {}}
        node = {'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data', 'CheckContamination']}

        result = main.get_table_config_data(
                                            table_configs,
                                            node)
        assert result == table_configs['CheckContamination']

    def test_missing_label(self):
        table_configs = {"CheckContamination" : {}}
        node = {'labels': ['WGS35', 'Blob', 'Cromwell', 'Gatk', 'Structured', 'Text', 'Data']}
        
        with pytest.raises(KeyError):
            main.get_table_config_data(
                                       table_configs,
                                       node)


class TestCheckTableExists:

    def test_table_does_not_exist(self):
        table_name = "check_contamination"
        fetchone_result = (False,)

        with mock.patch('psycopg2.connect') as mock_connect:
            mock_connect.cursor.return_value.fetchone.return_value = fetchone_result
            table_exists = main.check_table_exists(mock_connect, table_name)

            assert table_exists == False

    def test_table_does_exist(self):
        table_name = "check_contamination"
        fetchone_result = (True,)

        with mock.patch('psycopg2.connect') as mock_connect:
            mock_connect.cursor.return_value.fetchone.return_value = fetchone_result
            table_exists = main.check_table_exists(mock_connect, table_name)

            assert table_exists == True


class TestGetDelimiter:

    def test_check_contamination(self):
        node = {"extension": "preBqsr.selfSM"}
        delimiter = main.get_delimiter(node)

        assert delimiter == "\t"

    def test_csv(self):
        node = {"extension": "csv"}
        delimiter = main.get_delimiter(node)

        assert delimiter == ","

    def test_no_rule(self):
        node = {"extension": "nonsense_extension"}
        delimiter = main.get_delimiter(node)

        assert delimiter == None