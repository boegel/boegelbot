#!/bin/bash -l
#SBATCH --nodes 1
#SBATCH --ntasks=16
#SBATCH --ntasks-per-node=16
#SBATCH --time 100:0:0
#SBATCH --get-user-env

set -e

module use /shared/easybuilder/CentOS8/haswell/modules/all

EB_PREFIX=$HOME/easybuild
export PYTHONPATH=$EB_PREFIX/easybuild-framework:$EB_PREFIX/easybuild-easyblocks:$EB_PREFIX/easybuild-easyconfigs
# $HOME/.local/bin is added to $PATH for Python packages like archspec installed with 'pip install --user'
export PATH=$EB_PREFIX/easybuild-framework:$HOME/.local/bin:$PATH

export EASYBUILD_PREFIX=$HOME/CentOS8/$(archspec cpu)
export EASYBUILD_BUILDPATH=/tmp/$USER
export EASYBUILD_SOURCEPATH=$EASYBUILD_PREFIX/sources:/shared/maintainers/sources

export EASYBUILD_GITHUB_USER=boegelbot

export EB_PYTHON=python3

eb --from-pr $EB_PR --debug --rebuild --robot --upload-test-report $EB_ARGS
