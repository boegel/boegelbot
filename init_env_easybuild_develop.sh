if [ -z $EB_PREFIX ]; then
    echo "ERROR: Specify location of EasyBuild repositories via \$EB_PREFIX!" >&2
    exit 1
fi

export PYTHONPATH=$EB_PREFIX/easybuild-framework:$EB_PREFIX/easybuild-easyblocks:$EB_PREFIX/easybuild-easyconfigs
# $HOME/.local/bin is added to $PATH for Python packages like archspec installed with 'pip install --user'
export PATH=$EB_PREFIX/easybuild-framework:$HOME/.local/bin:$PATH
