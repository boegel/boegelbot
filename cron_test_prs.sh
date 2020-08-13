#!/bin/bash

# change to directory in which this script is located
cd `dirname $(realpath $0)`

# update EasyBuild to latest 'develop' branches
./easybuild_develop.sh

# set up environment
EB_PREFIX=$HOME/easybuild source init_env_easybuild_develop.sh

# check notifications for new PRs to test
./test_prs_generoso.sh
