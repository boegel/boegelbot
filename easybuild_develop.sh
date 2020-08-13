#!/bin/bash

set -e

EB_PREFIX=$HOME/easybuild
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
    echo "+++ checking out 'develop' branch"
    echo

    git checkout develop

    echo
    echo "+++ updating 'develop' branch"
    echo
    git pull origin develop

    echo
    echo "+++ current HEAD:"
    echo
    git log -n 1

    echo
done

source $INIT_ENV

eb --version
