#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <test_prs_*.sh script to run>" >&2
    exit 1
fi
TEST_PRS_SCRIPT=$1

# change to directory in which this script is located
cd `dirname $(realpath $0)`

# update EasyBuild to latest 'develop' branches
./easybuild_develop.sh

# set up environment
EB_PREFIX=$HOME/easybuild source init_env_easybuild_develop.sh

# check notifications for new PRs to test
$TEST_PRS_SCRIPT
