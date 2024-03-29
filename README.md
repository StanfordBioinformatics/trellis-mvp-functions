# Trellis for efficient data and task management in the VA Million Veteran Program


This repository contains the source code for the microservices that run Trellis. We recently published a manuscript describing Trellis in detail, that can be found here: <INSERT LINK>

Other relevant repositories:

* https://github.com/StanfordBioinformatics/trellis-mvp-terraform: Terraform resources for deploying Trellis.
* https://github.com/StanfordBioinformatics/trellis-mvp-api: GraphQL API schema for interacting with the Trellis Neo4j database.
* https://github.com/StanfordBioinformatics/trellis-mvp-analysis: Source for Jupyter notebooks used to summarize metadata in Neo4j database.
  
## Repository Structure
* __config__: This directory contains configuration files that describe various ways in which metadata should be handled by Trellis.
  * __phase3__: Directory with resources specific to the "phase3" batch of data received from Personalis.
    * __from-personalis-phase3-data__
      * __create-node-config.py__: Configuration file specifying how to parse metadata from the paths of objects generated by Trellis while processing WGS data.
    * __from-personalis-qc__
      * __create-node-config.py__: Configuration file specifying how to parse metadata from QC data objects generated by Trellis.
    * __from-personalis__: 
      * __create-node-config.py__: Configuration file specifying how to parse metadata from the paths of objects delivered by Personalis. 
    * __database-triggers.py__: Database triggers used to control Trellis operations.
* databases
  * __db-indexes.txt__: A document containing the Cypher commands used to add Trellis indexes to the Neo4j metadata store.
  * db-schema.yaml: A working attempt at modelling the Trellis database schema using a YAML configuration file. Currently does not have a functional application.
* docs: Deprecated instructions for deploying Cloud Functions and the Neo4j database manually. We now recommend using Terraform to deploy resources (https://github.com/StanfordBioinformatics/trellis-mvp-terraform). We have left them here in case folks are interested in exploring specific Trellis resources.
* __functions__: This directory contains the source code for microservices used to operate Trellis for MVP. These functions are implemented for GCP using Cloud Functions or Cloud Run.
* __images__
  * __cloudbuild.yaml__: This directory contains a configuration file that Google Cloud Build uses to add Trellis Docker images to the GCP project. The Docker image paths are listed at the bottom of the config file under "substitutions."


### Overview
Trellis is an asynchronous, event-driven data management system designed to automatically track the data objects associated with biological samples and launch workflows that are tailored to different data types. Trellis annotates data objects with rich metadata and tracks them as nodes in a graph database. It uses the metadata associated with each node to determine which tasks it should be input to, launches those jobs, and then adds the jobs and their outputs as nodes in the database. Data objects and job nodes are connected to each other by relationships that describe the lineage or provenance of the data, e.g. (object)-[:WAS_USED_BY]->(:Job)-[:GENERATED]->(anotherObject). Trellis can then use the properties associated with each node, as well as all other nodes it is connected to, to make context-aware decisions about how to continue processing the data. The more data is added to the graph, the smarter the decision making becomes.

### Trellis design principles
* event-driven
* asynchronous
* stateless (except for the database)
* idempotent

### Architecture
Trellis is a designed as a system of microservices that communicate with each other via an asynchronous message broker. All metadata describing the state of the system is stored in a Neo4j labelled property graph database. Trellis operations are controlled by events and the state of the database. For more information, please reference the manuscript.

### Context
As part of The Department of Veteran's Affairs (VA) Million Veteran Program, the VA has gathered genetic samples from 100,000s of donors within the VA health care system. The VA has, so far, contracted Personalis to perform whole-genome sequencing (WGS) on samples from 115,000 donors. The sequencing reads generated from these experiments are stored in Fastq format and streamed into buckets on the Google Cloud Platform. 

The value of performing whole-genome sequencing is that it generates sequencing reads from across all 3 billion positions in the human genome, while smaller-scale experiments such as genotyping arrays and whole-exome sequencing only assay small, select regions of the genome. However, only about 1-2% of the positions sequenced by whole-genome sequencing will be useful to researchers; these are the sites with nucleotides (or alleles) that are different from other individuals within the sample ancestral population. These single-nucleotide variants have the potential to contribute to the differences we see between people, and affect how they respond to medically relevant stimuli such as diet, viruses, bacteria, or other perturbations.

To discover these variants, we use the GATK best-practices pipeline, developed by the Broad Institute to do this variant calling. In addition to the GATK pipeline, we also run several applications to generate quality-control metrics, and are planning on adding additional tasks to detect variants in the mitochondrial genome (MT), sex chromosomes (X,Y) and structural variants (insertions, deletions, and copy number variants).


