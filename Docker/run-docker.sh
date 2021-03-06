#!/bin/bash

# docker run casue the Docker client to find the image and loads up the container.
# The general form is:
#             $ docker run [OPTIONS] IMAGE[:TAG|@DIGEST] [COMMAND] [ARG... 


#Docker Options used:
# --rm 
# causes Docker to automatically remove the container once it exits.
# -it 
# runs Docker interactively.
# -v  
# used to bind-mount a file or directory that does not yet exist on the Docker host, -v creates the endpoint for you. It is always created as a directory.
# https://docs.docker.com/storage/bind-mounts/

# This command extracts SNPs and INDELs from a list of VCF files, write the SNPs into mg-ref-output/SNP.extract.chrxx.data, 
# and write the INDELs into mg-ref-output/INDEL.extract.chrxx.data, where xx is a chromosome identified from the reference genome.

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" -w / bwbble-ref:dev data_prep /input/ALL.chr21.phase1_release_v3.20101123.snps_indels_svs.genotypes.vcf 
 

#This command reads SNPs from mg-ref-output/SNP.extract.chrxx.data and INDELs from mg-ref-output/INDEL.extract.chrxx.data
# and combines them with the reference genome ref.fasta. The output ref_w_snp.fasta combines the reference genome with the SNPs,
# ref_w_snp_and_bubble.fasta combines the reference genome with the SNPs and the INDELs.

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" -w / bwbble-ref:dev comb /input/human_g1k_v37.fasta /mg-ref-output/ref_w_snp_chr21.fasta /mg-ref-output/ref_w_snp_chr21_and_bubble.fasta /mg-ref-output/bubble21.data 

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" bwbble-align:dev index /mg-ref-output/ref_w_snp_chr21_and_bubble.fasta


##########################################
# Now we're doing an alignment job

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" -v "$(pwd)/align-output:/mg-align-output" bwbble-align:dev2 align -s 5 -p 10 /mg-ref-output/ref_w_snp_chr21_and_bubble.fasta /input/sim_chr21_N100.fastq /mg-align-output/sim_chr21_N100.aln

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" -v "$(pwd)/align-output:/mg-align-output" bwbble-align:dev2 aln2sam /mg-ref-output/ref_w_snp_chr21_and_bubble.fasta /input/sim_chr21_N100.fastq /mg-align-output/sim_chr21_N100.aln /mg-align-output/sim_chr21_N100.sam

#
##########################################

# This command parses the output sam file of mg-aligner.

 docker run --rm -it -v "$(pwd)/input:/input" -v "$(pwd)/ref-output:/mg-ref-output" bwbble-ref:dev sam_pad /mg-ref-output/bubble21.data /mg-ref-output/docker_test_sim_chr21_N100.sam /mg-ref-output/test21output.sam