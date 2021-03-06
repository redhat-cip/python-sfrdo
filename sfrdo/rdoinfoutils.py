# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import imp
import os
import urlparse

from rdopkg.repoman import RepoManager

from sfrdo import config


RDOINFOS_USERS_FIXES = {
}


RDOINFOS_FIXES = {
    'glance_store': {
        'distgit': 'git://pkgs.fedoraproject.org/python-glance-store.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'horizon': {
        'distgit': 'git://github.com/openstack-packages/horizon',
        'conf': 'client',  # Use the core style rdo-liberty branch)
    },
    'dib-utils': {
        'distgit': 'git://pkgs.fedoraproject.org/dib-utils.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'tripleo-incubator': {
        'rdo-liberty-tag': '7461b01e393931e0f4cf1ff38eadb0755a49d658',
    },
    'os-apply-config': {
        'distgit': 'git://pkgs.fedoraproject.org/os-apply-config.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'os-collect-config': {
        'distgit': 'git://pkgs.fedoraproject.org/os-collect-config.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'os-net-config': {
        'distgit': 'git://pkgs.fedoraproject.org/os-net-config.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'os-refresh-config': {
        'distgit': 'git://pkgs.fedoraproject.org/os-refresh-config.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'os-cloud-config': {
        'distgit': 'git://pkgs.fedoraproject.org/os-cloud-config.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'ironic-python-agent': {
        'distgit':
            'git://pkgs.fedoraproject.org/openstack-ironic-python-agent.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'django_openstack_auth': {
        'distgit':
            'git://pkgs.fedoraproject.org/python-django-openstack-auth.git',
    },
    'tripleoclient': {
        #  https://github.com/openstack-packages/python-tripleoclient/blob/rdo-liberty/python-tripleoclient.spec#L14
        'distgit': 'git://github.com/openstack-packages/python-tripleoclient',
        'conf': 'core',  # Use the core style rdo-liberty branch)
        'rdo-liberty-tag': '2aac09de13f4cfd4b9d87cdcdd860388e21aef0a',
    },
    'openstack-puppet-modules': {
        'distgit':
            'git://pkgs.fedoraproject.org/openstack-puppet-modules.git',
    },
    'networking-arista': {  # Can be reported
        'distgit':
            'git://github.com/openstack-packages/python-networking-arista',
    },
    'tempest': {
        'conf': 'client',
        'distgit': 'git://pkgs.fedoraproject.org/tempest.git',
        'rdo-liberty-tag': 'openstack-tempest-liberty-20151020',
    },
    'packstack': {
        'conf': 'core',
        'distgit': 'git://github.com/openstack-packages/packstack',
        'rdo-liberty-tag': 'g42b3426',
    },
    'networking-ovn': {
        'distgit': 'git://github.com/openstack-packages/python-networking-ovn',
    },
    'neutron-lib': {
        'distgit': 'git://github.com/openstack-packages/python-neutron-lib',
    },
    'cisco-ironic-contrib': {
        'distgit': 'git://github.com/openstack-packages/python-ironic-cisco',
    },
    'mistralclient': {
        'distgit': 'git://github.com/openstack-packages/python-mistralclient',
        'conf': 'core',
    },
    'dracclient': {
        'distgit': 'git://github.com/openstack-packages/python-dracclient',
        'conf': 'core',
    },
    'openstacksdk': {
        'distgit': 'git://github.com/openstack-packages/python-openstacksdk',
        'conf': 'core',
    },
    'cloudkittyclient': {
        'distgit':
            'git://github.com/openstack-packages/python-cloudkittyclient',
        'conf': 'core',
    },
    'vmware-nsx': {
        'distgit':
            'git://github.com/openstack-packages/python-networking-vmware-nsx',
        'conf': 'core',
    },
    'networking-mlnx': {
        'distgit':
            'git://github.com/openstack-packages/python-networking-mlnx',
        'conf': 'core',
    },
    'networking-odl': {
        'distgit': 'git://github.com/openstack-packages/python-networking-odl',
        'conf': 'core',
    },
    'ironic-lib': {
        'distgit': 'git://github.com/openstack-packages/python-ironic-lib',
        'conf': 'core',
    },
}


def fetch_rdoinfo(repo=None):
    if not os.path.isdir(config.userdir):
        os.mkdir(config.userdir)
    rdoinfo_repo = config.rdoinfo
    if repo:
        rdoinfo_repo = repo
    rm = RepoManager(config.userdir, rdoinfo_repo, verbose=True)
    rm.init(force_fetch=True)
    file, path, desc = imp.find_module('rdoinfo', [rm.repo_path])
    rdoinfo = imp.load_module('rdoinfo', file, path, desc)
    return rdoinfo.parse_info_file(os.path.join(config.userdir,
                                                'rdoinfo/rdo.yml'))


def fetch_project_infos(rdoinfo, upstream_project_name):
    select = [pkg for pkg in rdoinfo['packages']
              if pkg['project'] == upstream_project_name]
    if not select:
        # some projects differ from the upstream name (ex: oslo.* is oslo-*)
        # so look again by using the upstream url
        select = [pkg for pkg in rdoinfo['packages']
                  if pkg['upstream'].endswith(upstream_project_name)]
    if not select:
        # yup, out of luck now
        raise Exception('Project not found in rdoinfo: %s' %
                        upstream_project_name)
    infos = select[0]

    distgit = infos['distgit']
    # Change scheme from ssh to git (avoid the need of being authenticated)
    # For some projects we need it
    # (eg. client project) still hosted fedora side.
    parts = urlparse.urlparse(distgit)
    distgit = urlparse.urlunparse(['git', parts.netloc,
                                   parts.path, '', '', ''])
    conf = 'None'
    if 'conf' in infos:
        conf = infos['conf']

    if upstream_project_name in RDOINFOS_FIXES:
        if 'distgit' in RDOINFOS_FIXES[upstream_project_name]:
            print "Distgit target has been fixed by sfrdo !"
            distgit = RDOINFOS_FIXES[upstream_project_name]['distgit']
        if 'conf' in RDOINFOS_FIXES[upstream_project_name]:
            print "Conf type has been fixed by sfrdo !"
            conf = RDOINFOS_FIXES[upstream_project_name]['conf']

    mdistgit = infos['master-distgit']
    upstream = infos['upstream']
    name = infos['project']
    maints = infos['maintainers']
    sfdistgit = "%s-distgit" % name
    return (name, distgit, upstream,
            sfdistgit, maints, conf, mdistgit)


def display_details(cmdargs, rdoinfo, workdir=None):
    name, distgit, upstream, \
        sfdistgit, maints, conf, mdistgit = \
        fetch_project_infos(rdoinfo, cmdargs.name)
    print "=== Details ==="
    print "Project name is: %s" % name
    print "Project type is: %s" % conf
    print "Project upstream RDO distgit is: %s" % distgit
    print "Project upstream RDO master-distgit is: %s" % mdistgit

    print "Project upstream is: %s" % upstream

    print "Project distgit name on SF is: %s" % sfdistgit
    print
