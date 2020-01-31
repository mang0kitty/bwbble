#!/usr/bin/env python
import hashlib
import string
import random
import logging
import yaml
import pprint
import sys
import os
import time
from typing import List

from kubernetes import client, config, utils
import kubernetes.client
from kubernetes.client.rest import ApiException

# Setup logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# Setup K8 configs
config.load_kube_config()
configuration = kubernetes.client.Configuration()
api_instance = kubernetes.client.BatchV1Api(
    kubernetes.client.ApiClient(configuration))


class Range(object):
    def __init__(self, start: int, length: int = -1):
        self.start = start
        self.length = length

    @property
    def name(self) -> str:
        if self.length == -1:
            return f"{self.start}-end"
        return f"{self.start}-{self.start+self.length}"


# Configuration
file_ranges = [
    Range(0)
]

reads_file = "dummy_reads.fastq"
snp_file = "chr21_ref_w_snp.fasta"


def create_job_resources(namespace: str, release: str, stage: str, container_image: str, args: list, use_config_map_args: bool = True, resources: client.V1ResourceRequirements = None, env: list = None, name_suffix: str = ""):
    labels = {
        "app.kubernetes.io/managed-by": "faaideen",
        "bwbble-stage": stage,
    }

    resources = resources or client.V1ResourceRequirements(
        limits={
            "memory": 0,
            "cpu": 1
        },
        requests={
            "memory": 0,
            "cpu": 1
        })

    resources = []

    if use_config_map_args:
        resources.append(kubernetes.client.CoreV1Api(kubernetes.client.ApiClient()).create_namespaced_config_map(namespace, kubernetes.client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(
                name=f"bwbble-{release}-{stage}{name_suffix}", labels=labels
            ),
            data={
                "args": " ".join([f"'{a}'" if " " in a else a for a in args]),
            }
        )))

    job_spec = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=f"bwbble-{release}-{stage}{name_suffix}", labels=labels),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(metadata=client.V1ObjectMeta(
                name=stage,
                labels=labels
            ), spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name=stage,
                        image=container_image,
                        image_pull_policy="IfNotPresent",
                        args=args,
                        env=[
                            client.V1EnvVar(
                                name="ARGS_FILE", value="/var/run/args/container_args")
                            .extend(env) if env is not None else None],
                        resources=resources,
                        volume_mounts=[
                            client.V1VolumeMount(
                                mount_path="/input",
                                name="input"
                            ),
                            client.V1VolumeMount(
                                mount_path="/mg-ref-output",
                                name="ref-output"
                            ),
                            client.V1VolumeMount(
                                mount_path="/mg-align-output",
                                name="align-output"
                            )
                        ])
                ],
                volumes=[
                    client.V1Volume(
                        name="input"
                    ),
                    client.V1Volume(
                        name="ref-output",
                    ),
                    client.V1Volume(
                        name="align-output",
                    )
                ])
            )
        )
    )
    print(job_spec)

    if use_config_map_args:

        job_spec.spec.template.spec.volumes.append(client.V1Volume(
            name="args",
            config_map=client.V1ConfigMapVolumeSource(
                name=f"bwbble-{release}-{stage}{name_suffix}")
        ))

        job_spec.spec.template.spec.containers[0].args = []
        job_spec.spec.template.spec.containers[0].volume_mounts.append(client.V1VolumeMount(
            mount_path="/var/run/args",
            name="args"
        ))

    resources.append(kubernetes.client.BatchV1Api(
        kubernetes.client.ApiClient()).create_namespaced_job(namespace, job_spec))

    return resources


def wait_for_all_jobs(namespace: str, release: str, stage: str, resources: List[kubernetes.client.V1Job]):
    watcher = kubernetes.watch.Watch()

    pending_jobs = set([r.metadata.name for r in resources])

    for event in watcher.stream(
            kubernetes.client.BatchV1Api.list_namespaced_job, namespace, label_selector=f"bwbble-release={release},bwbble-stage={stage}"):

        if event['object'].state.completion_time:
            pending_jobs.remove(event['object'].metadata.name)

            if len(pending_jobs) == 0:
                watcher.stop()
                return


def run_data_prep(namespace: str, release: str):
    # Do the dataprep job
    api_responses = create_job_resources(
        namespace, release, "data-prep", "bwbble/mg-ref:latest")

    for resource in api_responses:
        pprint(resource)

    # Wait for the data-prep job to complete
    wait_for_all_jobs(namespace, release, "data-prep",
                      [r for r in api_responses if isinstance(r, kubernetes.client.V1Job)])
    print("**** All Jobs completed for dataprep phase of mg-ref ****")

    # Do the combine job
    api_responses = create_job_resources(
        namespace, release, "comb", "bwbble/mg-ref:latest")

    for resource in api_responses:
        pprint(resource)

    # Wait for the data-prep job to complete
    wait_for_all_jobs(
        namespace, [r for r in api_responses if isinstance(r, kubernetes.client.V1Job)])
    print("**** All Jobs completed for comb phase of mg-ref ****")

    return api_responses


def run_index(namespace: str, release: str):
    api_responses = create_job_resources(namespace, release, "index", "bwbble/mg-aligner:latest", resources=client.V1ResourceRequirements(
        limits={
            "memory": "64Gi",
            "cpu": 1
        },
        requests={
            "memory": "1Gi",
            "cpu": 1
        }))

    for resource in api_responses:
        pprint(resource)

    # Wait for the index job to complete
    wait_for_all_jobs(namespace, release, "index", [
                      r for r in api_responses if isinstance(r, kubernetes.client.V1Job)])
    print("**** All Jobs completed for index phase of mg-aligner ****")


def run_align(namespace: str, release: str):
    alignment_jobs = []

    for range in file_ranges:
        api_responses = create_job_resources(namespace, release, "align", "bwbble/mg-aligner:latest",
                                             args=[
                                                 "align",
                                                 "-s",
                                                 f"{range.start}",
                                                 "-p",
                                                 f"{range.length}",
                                                 f"/mg-ref-output/{snp_file}",
                                                 f"/input/{reads_file}",
                                                 f"/mg-align-output/{release}.aligned_reads.{range.name}.aln"
                                             ], name_suffix=f"-{range.name}")

        for resource in api_responses:
            pprint(resource)

        alignment_jobs.extend([
            r for r in api_responses if isinstance(r, kubernetes.client.V1Job)
        ])

    # Wait for the align job to complete
    wait_for_all_jobs(namespace, release, "align", alignment_jobs)
    print("All Jobs completed for align phase of mg-aligner")

    print("**** Starting the merge job ****")
    run_merge(namespace, release)

    print("**** Starting the aln2sam job ****")
    run_aln2sam(namespace, release)

    print("**** Starting the sam_pad job ****")
    run_sam_pad(namespace, release)


def run_merge(namespace: str, release: str):
    merge_command = [
        "cat",
        *[f"/mg-align-output/{release}.aligned_reads.{range.name}.aln" for range in file_ranges],
        ">",
        f"/mg-align-output/{release}.aligned_reads.aln"
    ]

    api_responses = create_job_resources(namespace, release, "merge", "busybox:latest", use_config_map_args=False,
                                         args=[
                                             "sh",
                                             "-c",
                                             " ".join(
                                                 [f"'{p}'" if " " in p else p for p in merge_command])
                                         ])

    for resource in api_responses:
        pprint(resource)

    # Wait for the merge job to complete
    wait_for_all_jobs(namespace, release, "merge", api_responses)
    print("All Jobs completed for merge phase")


def run_aln2sam(namespace: str, release: str):
    api_responses = create_job_resources(namespace, release, "aln2sam", "bwbble/mg-aligner:latest", args=[
        "aln2sam",
        f"/mg-ref-output/{snp_file }",
        f"/input/{reads_file}",
        f"/mg-align-output/{release}.aligned_reads.{range.name}.aln",
        f"/mg-align-output/{release}.aligned_reads.{range.name}.sam"

    ])

    for resource in api_responses:
        pprint(resource)

    # Wait for the aln2sam job to complete
    wait_for_all_jobs(namespace, release, "aln2sam", [
                      r for r in api_responses if isinstance(r, kubernetes.client.V1Job)])
    print("**** All Jobs completed for aln2sam phase of mg-aligner ****")


def run_sam_pad(namespace: str, release: str, bubble_file: str, sam_file: str, output_file: str):
    api_responses = create_job_resources(namespace, release, "sam-pad", "bwbble/mg-ref:latest", args=[
        "sampad",  # TODO: Remove this when you've built the new images which support using entrypoint.sh
        f"/mg-ref-output/{bubble_file}",
        f"/mg-align-output/{sam_file}",
        f"/mg-align-output/{output_file}"
    ],
        env=[
        kubernetes.client.V1EnvVar(name="APPLICATION", value="sampad"),
    ])

    for resource in api_responses:
        pprint(resource)

    # Wait for the sam_pad job to complete
    wait_for_all_jobs(namespace, release, "sam-pad",
                      [r for r in api_responses if isinstance(r, kubernetes.client.V1Job)])
    print("All Jobs completed for sam_pad phase of mg-ref")


def kube_test_credentials():

    try:
        api_response = api_instance.get_api_resources()
        logging.info(api_response)
    except ApiException as e:
        print("Exception when calling API: %s\n" % e)
        sys.exit(0)


def main():
    kube_test_credentials()
    print("Done testing credentials")
    run_align("bwbble-dev", "test0")


if __name__ == '__main__':
    main()