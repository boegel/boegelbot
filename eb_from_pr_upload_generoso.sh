#!/bin/bash -l
#SBATCH --nodes 1
#SBATCH --ntasks=4
#SBATCH --time 100:0:0
#SBATCH --output /project/boegelbot/slurmjobs/slurm-%j.out
#SBATCH --get-user-env

set -e

TOPDIR="/project"
CONTAINER_BIND_PATHS="--bind ${TOPDIR}/$USER --bind ${TOPDIR}/maintainers"

EB_PREFIX=${HOME}/easybuild
export PYTHONPATH=${EB_PREFIX}/easybuild-framework:${EB_PREFIX}/easybuild-easyblocks:${EB_PREFIX}/easybuild-easyconfigs
# $HOME/.local/bin is added to $PATH for Python packages like archspec installed with 'pip install --user'
export PATH=${EB_PREFIX}/easybuild-framework:${HOME}/.local/bin:${PATH}

# hardcode to haswell for now, workernodes are actually a mix of haswell/broadwell (but seems to work fine)
export CPU_ARCH=haswell
export EASYBUILD_PREFIX=${TOPDIR}/${USER}/Rocky8/${CPU_ARCH}
export EASYBUILD_BUILDPATH=/tmp/${USER}
export EASYBUILD_SOURCEPATH=${TOPDIR}/${USER}/sources:${TOPDIR}/maintainers/sources

export EASYBUILD_GITHUB_USER=boegelbot

export EB_PYTHON=python3

export EASYBUILD_ACCEPT_EULA_FOR='.*'

export EASYBUILD_HOOKS=${HOME}/boegelbot/eb_hooks.py

export EASYBUILD_CUDA_COMPUTE_CAPABILITIES=7.0

# see https://github.com/easybuilders/easybuild-easyconfigs/issues/18925
export PSM3_DEVICES='self,shm'

# see https://github.com/easybuilders/easybuild-easyconfigs/pull/19314#issuecomment-1825665377
export I_MPI_FABRICS=shm

export INTEL_LICENSE_FILE=${TOPDIR}/maintainers/licenses/intel.lic

module use ${EASYBUILD_PREFIX}/modules/all

repo_pr_arg='--from-pr'
if [ $EB_REPO == "easybuild-easyblocks" ]; then
    repo_pr_arg='--include-easyblocks-from-pr'
fi

EB_CMD="eb ${repo_pr_arg} ${EB_PR} --debug --rebuild --robot --upload-test-report --download-timeout=1000"
if [ ! -z "${EB_ARGS}" ]; then
    EB_CMD="${EB_CMD} ${EB_ARGS}"
fi

if [ -z "${EB_CONTAINER}" ]; then
    ${EB_CMD}
else
    if [ ! -z "$(command -v apptainer)" ]; then
        CONTAINER_EXEC_CMD="apptainer exec"
    elif [ ! -z "$(command -v singularity)" ]; then
        CONTAINER_EXEC_CMD="singularity exec"
    else
        echo "Neither Apptainer nor Singularity available, can't test PR ${EB_PR} in ${EB_CONTAINER} container!" >&2
        exit 1
    fi
    module unuse ${EASYBUILD_PREFIX}/modules/all
    export EASYBUILD_PREFIX=${TOPDIR}/${USER}/container-$(basename ${EB_CONTAINER})/${CPU_ARCH}
    module use ${EASYBUILD_PREFIX}/modules/all

    ${CONTAINER_EXEC_CMD} ${CONTAINER_BIND_PATHS} ${EB_CONTAINER} bash -l -c "export PATH=$PATH:\$PATH; export PYTHONPATH=$PYTHONPATH:\$PYTHONPATH; module unuse $MODULEPATH; ${EB_CMD}"
fi
