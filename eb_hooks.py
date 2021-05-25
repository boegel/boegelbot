import os
from distutils.version import LooseVersion

from easybuild.tools.build_log import print_warning
from easybuild.tools.config import build_option, update_build_option
from easybuild.tools.modules import get_software_version


def pre_sanitycheck_hook(self, *args, **kwargs):

    # make sure that nothing links to system OpenSSL libraries directly,
    # should be done via OpenSSL wrapper installation provided through EasyBuild

    # note: for banned library paths starting with /lib or /lib64 we need to include a space in front,
    # to avoid that paths like $EBROOTOPENSSL/lib/libssl.so.10 are reported as linking to a banned library...
    openssl_libs = [
        # CentOS 7, openssl-libs package (OpenSSL 1.0.2)
        ' ' + os.path.join('/lib', 'libcrypto.so.10'),
        ' ' + os.path.join('/lib', 'libssl.so.10'),
        ' ' + os.path.join('/lib64', 'libcrypto.so.10'),
        ' ' + os.path.join('/lib64', 'libssl.so.10'),
        os.path.join('/usr', 'lib', 'libcrypto.so.10'),
        os.path.join('/usr', 'lib', 'libssl.so.10'),
        os.path.join('/usr', 'lib64', 'libcrypto.so.10'),
        os.path.join('/usr', 'lib64', 'libssl.so.10'),
        # CentOS 7, openssl11-libs package (OpenSSL 1.1.1)
        # RHEL 8, openssl-libs package (OpenSSL 1.1.1)
        ' ' + os.path.join('/lib', 'libcrypto.so.1.1'),
        ' ' + os.path.join('/lib', 'libssl.so.1.1'),
        ' ' + os.path.join('/lib64', 'libcrypto.so.1.1'),
        ' ' + os.path.join('/lib64', 'libssl.so.1.1'),
        os.path.join('/usr', 'lib', 'libcrypto.so.1.1'),
        os.path.join('/usr', 'lib', 'libssl.so.1.1'),
        os.path.join('/usr', 'lib64', 'libcrypto.so.1.1'),
        os.path.join('/usr', 'lib64', 'libssl.so.1.1'),
    ]

    gccver = get_software_version('GCC') or get_software_version('GCCcore')
    if gccver and LooseVersion(gccver) >= LooseVersion('10.3'):
        banned_linked_shared_libs = build_option('banned_linked_shared_libs')
        if banned_linked_shared_libs:
            print_warning("Overwriting banned_linked_shared_libs build option, was %s", banned_linked_shared_libs)

        update_build_option('banned_linked_shared_libs', openssl_libs)
        print("Updated banned_linked_shared_libs build option: %s" % build_option('banned_linked_shared_libs'))
