#!/bin/bash -l
#SBATCH --nodes 1
#SBATCH --ntasks=4
#SBATCH --mem-per-cpu=4000M
#SBATCH --time 100:0:0
#SBATCH --partition=jsczen3c
#SBATCH --output /project/def-maintainers/boegelbot/slurmjobs/slurm-%j.out
#SBATCH --get-user-env

set -e

TOPDIR="/project/def-maintainers"
CONTAINER_BIND_PATHS="--bind ${TOPDIR}/$USER --bind ${TOPDIR}/maintainers"

if [ "$EB_BRANCH" = "develop" ]; then
    EB_PREFIX=$HOME/easybuild
else
    EB_PREFIX=$HOME/easybuild/$EB_BRANCH
fi
export PYTHONPATH=${EB_PREFIX}/easybuild-framework:${EB_PREFIX}/easybuild-easyblocks:${EB_PREFIX}/easybuild-easyconfigs
# $HOME/.local/bin is added to $PATH for Python packages like archspec installed with 'pip install --user'
export PATH=${EB_PREFIX}/easybuild-framework:${HOME}/.local/bin:${PATH}

# use archspec to determine CPU architecture
export CPU_ARCH=$(archspec cpu)
export OS_DISTRO=$(source /etc/os-release; echo $ID)
export OS_VERSION=$(source /etc/os-release; echo $VERSION_ID | awk -F '.' '{print $1}')
export EASYBUILD_PREFIX=${TOPDIR}/${USER}/${OS_DISTRO}${OS_VERSION}/${CPU_ARCH}
export EASYBUILD_BUILDPATH=/tmp/${USER}
export EASYBUILD_SOURCEPATH=${TOPDIR}/${USER}/sources:${TOPDIR}/maintainers/sources

export EASYBUILD_GITHUB_USER=boegelbot

export EB_PYTHON=python3

export EASYBUILD_ACCEPT_EULA_FOR='.*'

export EASYBUILD_HOOKS=${HOME}/boegelbot/eb_hooks.py

export EASYBUILD_OPTARCH='Intel:march=core-avx2'

export EASYBUILD_CUDA_COMPUTE_CAPABILITIES=8.0

export EASYBUILD_SET_GID_BIT=1

export EASYBUILD_UMASK='022'

module use ${EASYBUILD_PREFIX}/modules/all

repo_pr_arg='--from-pr'
if [ $EB_REPO == "easybuild-easyblocks" ]; then
    repo_pr_arg='--include-easyblocks-from-pr'
fi

if [[ $EB_BRANCH == *"5.0.x"* ]]; then
  export EASYBUILD_FAIL_ON_MOD_FILES_GCCCORE=1
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
