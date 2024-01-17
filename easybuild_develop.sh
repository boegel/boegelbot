#!/bin/bash

set -e

# If $EB_BRANCH is not set, assume that we want to test the develop branch
if [ "x$EB_BRANCH" = "x" ]; then
    EB_BRANCH=develop
fi

# Use different EB_PREFIX for different branches to allow testing multiple branches at the same time
if [ "$EB_BRANCH" = "develop" ]; then
    EB_PREFIX=$HOME/easybuild
else
    EB_PREFIX=$HOME/easybuild/$EB_BRANCH
fi
mkdir -p $EB_PREFIX

INIT_ENV=`dirname $(realpath $0)`/init_env_easybuild_develop.sh
if [ ! -f $INIT_ENV ]; then
    echo "$INIT_ENV not found!?" >&2
    exit 1
fi

for eb_repo in easybuild-framework easybuild-easyblocks easybuild-easyconfigs; do

    cd $EB_PREFIX

    if [ ! -d ${eb_repo} ]; then
        echo
        echo "+++ cloning ${eb_repo} repository to $EB_PREFIX/${eb_repo}..."
        echo

        git clone https://github.com/easybuilders/${eb_repo}.git
    fi

    cd ${eb_repo}

    echo
    echo "+++ checking out '$EB_BRANCH' branch"
    echo

    git checkout $EB_BRANCH

    echo
    echo "+++ updating '$EB_BRANCH' branch"
    echo
    git pull origin $EB_BRANCH

    echo
    echo "+++ current HEAD:"
    echo
    git log -n 1

    echo
done

source $INIT_ENV

eb --version
