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

import os
import sys
import imp
import json
import yaml
import shutil
import logging
import requests
import urlparse
import tempfile
import argparse
import pprint

from rdopkg.repoman import RepoManager
from rdopkg.helpers import cdir
from rdopkg.utils.cmd import git

from copy import deepcopy

from sfrdo import config
from sfrdo import msfutils
from sfrdo import branches


logging.basicConfig(filename='warns.log', level=logging.DEBUG)


BL = []


NOT_IN_LIBERTY = ['cloudkittyclient', 'openstacksdk', 'dracclient',
                  'mistralclient', 'os-win', 'ironic-lib', 'octavia',
                  'cloudkitty', 'mistral', 'osprofiler', 'pysaml2',
                  'networking-arista', 'networking-cisco', 'vmware-nsx',
                  'networking-mlnx', 'networking-odl', 'app-catalog-ui',
                  'UcsSdk', 'cachetools']


# g42b3426 is not found upstream so force to do not create
# the liberty-patches branch even if in liberty.
NOT_IN_LIBERTY.append('packstack')


RDOINFOS_USERS_FIXES = {
    'fpercoco@redhat.com': ('flaper87', 'flaper87@flaper87.org'),
    'zaitcev@redhat.com': ('zaitcev', 'ota4250258078e9638@kotori.zaitcev.us'),
    'greg.swift@rackspace.net': ('gregswift', 'xaeth@fedoraproject.org'),
    'gchamoul@redhat.com':
        ('strider', 'strider@rpmfactory.beta.rdoproject.org'),
    'jprovazn@redhat.com': ('jprovaznik', 'jan.provaznik@gmail.com'),
    'dtantsur@redhat.com': ('dtantsur', 'dtantsur@redhat.com'),
    'dmellado@redhat.com': ('danielmellado', 'danielmelladoarea@gmail.com'),
    'mrunge@redhat.com': ('mrunge', 'mrunge@redhat.com'),
    'victoria@redhat.com': ('vkmc', 'victoria@redhat.com'),
    'dprince@redhat.com': ('dprince', 'dprince@redhat.com'),
    'nmagnezi@redhat.com': ('nmagnezi', 'nmagnezi@redhat.com'),
    'mabaakou@redhat.com': ('sileht', 'sileht@sileht.net'),
    'trown@redhat.com': ('trown', 'trown@redhat.com'),
    'hguemar@redhat.com': ('hguemar', 'hguemar@fedoraproject.org'),
    'ihrachys@redhat.com': ('booxter', 'ihrachys@redhat.com'),
    'sferdjao@redhat.com': ('sahid', 'sahid.ferdjaoui@gmail.com'),
    'jruzicka@redhat.com': ('yac', 'yac@rpmfactory.beta.rdoproject.org'),
    'brad@redhat.com': ('bcrochet', 'brad@redhat.com'),
    'slinaber@redhat.com': ('eggmaster', 'slinaber@redhat.com'),
    'eglynn@redhat.com': ('eglynn', 'eglynn@redhat.com'),
    'lbezdick@redhat.com': ('xbezdick', 'lbezdick@redhat.com'),
    'msm@redhat.com': ('elmiko', 'msm@opbstudios.com'),
    'vimartin@redhat.com': ('vkmc', 'victoria@redhat.com'),
    'pkilambi@redhat.com': ('pkilambi', None),
    'eharney@redhat.com': ('eharney', None),
    'jslagle@redhat.com': ('slagle', None),
    'matmaul@gmail.com': ('matmaul', None),
    'egafford@redhat.com': ('egafford', None),
    'ndipanov@redhat.com': ('djipko', None),
    'ifarkas@redhat.com': ('ifarkas', None),
    'zbitter@redhat.com': ('zaneb', None),
    'apevec@redhat.com': ('apevec', None),
    'gauvain.pocentek@objectif-libre.com': ('gpocentek', None),
    'apevec@gmail.com': ('apavec', None),
    'Kevin.Fox@pnnl.gov': ('kfox1111', None),
    'majopela@redhat.com': ('mangelajo', None),
    'marcos.fermin.lobo@cern.ch': ('marcosflobo', None),
    'chkumar@redhat.com': ('chkumar246', None),
    'ryansb@redhat.com': (None, None),
    'openstack-networking@cisco.com': (None, None),
    'jpena@redhat.com': (None, None),
    'lennyb@mellanox.com': (None, None),
    'brdemers@cisco.com': (None, None),
    'ichavero@redhat.com': (None, None),
    'mmagr@redhat.com': (None, None),
    'xin.wu@bigswitch.com': (None, None),
    'pbrady@redhat.com': (None, None),
}


RDOINFOS_FIXES = {
    'glance_store': {
        'distgit': 'git://pkgs.fedoraproject.org/python-glance-store.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'swift': {
        'distgit': 'git://pkgs.fedoraproject.org/openstack-swift.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'horizon': {
        'distgit': 'git://github.com/openstack-packages/horizon',
    },
    'dib-utils': {
        'distgit': 'git://pkgs.fedoraproject.org/dib-utils.git',
        'conf': 'client',  # Use the client style (master branch)
    },
    'tripleo-incubator': {
        'distgit': 'git://github.com/openstack-packages/tripleo',
        'conf': 'core',  # Use the core style rdo-liberty branch)
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
    'zaqar': {
        'distgit': 'git://pkgs.fedoraproject.org/openstack-zaqar.git',
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
    'horizon': {  # Can be reported
        'conf': 'client',  # Use the core style rdo-liberty branch)
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
}


class BranchNotFoundException(Exception):
    pass


class RequestedTagDoesNotExists(Exception):
    pass


class PRequestedTagDoesNotExists(Exception):
    pass


def fetch_rdoinfo():
    if not os.path.isdir(config.userdir):
        os.mkdir(config.userdir)
    rm = RepoManager(config.userdir, config.rdoinfo, verbose=True)
    rm.init(force_fetch=True)
    file, path, desc = imp.find_module('rdoinfo', [rm.repo_path])
    rdoinfo = imp.load_module('rdoinfo', file, path, desc)
    return rdoinfo.parse_info_file(os.path.join(config.userdir,
                                                'rdoinfo/rdo.yml'))


def fetch_project_infos(rdoinfo, upstream_project_name):
    select = [pkg for pkg in rdoinfo['packages']
              if pkg['project'] == upstream_project_name]
    if not select:
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
        sfdistgit, maintsi, conf, \
        mdistgit = fetch_project_infos(rdoinfo, cmdargs.name)
    print "=== Details ==="
    print "Project name is: %s" % name
    print "Project type is: %s" % conf
    print "Project upstream RDO distgit is: %s" % distgit
    print "Project upstream RDO master-distgit is: %s" % mdistgit

    print "Project upstream is: %s" % upstream

    print "Project distgit name on SF is: %s" % sfdistgit
    print


def fetch_all_project_type(rdoinfo, t='None'):
    select = [pkg for pkg in rdoinfo['packages']]
    if t == 'All':
        return [p['project'] for p in select]
    if t == 'None':
        return [p['project'] for p in select if
                'conf' not in p]
    else:
        return [p['project'] for p in select if
                'conf' in p and p['conf'] == t]


def create_baseproject(msf, name, desc):
    print "Delete previous %s" % name
    msf.deleteProject(name)
    print "Create %s" % name
    opts = {'description': desc}
    msf.createProject(name, opts)
    print "Add %s to core and ptl group for %s" % (
        config.userlogin, name)
    msf.addUsertoProjectGroups(name, config.useremail,
                               "ptl-group core-group")


def sync_and_push_branch(rfrom, rto, branch, tbranch=None):
    if not tbranch:
        tbranch = branch
    print "sync from %s:%s and push to %s:%s" % (
        rfrom, branch, rto, tbranch)
    if tbranch == 'master':
        git('checkout', tbranch)
    else:
        git('checkout', '-b', tbranch)
    git('reset', '--hard', 'remotes/%s/%s' % (rfrom, branch))
    git('push', '-f', rto, tbranch)


def fetch_flat_patches(name):
    patches = set([f for f in os.listdir('.') if
                   f.endswith('.patch') and f[4] == '-'])
    spec = file([s for s in os.listdir('.') if
                 s.endswith('.spec')][0])
    used_patches = [p.split(':') for p in spec.readlines() if
                    p.startswith('Patch00')]
    used_patches = set([p.lstrip().rstrip('\n') for _, p in used_patches])
    if len(patches) != len(used_patches):
        msg = "(%s) %s flat file patches exists but are not used" % \
            (name, len(patches - used_patches))
        logging.warning(msg)
        print msg
    return used_patches


def fetch_upstream_tag_name():
    spec = file([f for f in os.listdir('.') if f.endswith('.spec')][0])
    version = [l for l in spec.readlines() if l.startswith('Version')]
    version = version[0].split()[1]
    return version


def is_branches_exists(expected_remotes_branches):
    remote_branches = git('branch', '-a').split('\n')
    for remote, branch in expected_remotes_branches:
        exists = False
        for b in remote_branches:
            bn = "remotes/%s/%s" % (remote, branch)
            if bn in b:
                exists = True
        if not exists:
            raise BranchNotFoundException("%s does not exist" % bn)


def import_distgit(msf, sfgerrit, sfdistgit, distgit, mdistgit,
                   conf, workdir, in_liberty=True):
    print "=== Import distgit ==="
    try:
        create_baseproject(msf, sfdistgit,
                           "\"Packaging content for %s (distgit)\"" %
                           sfdistgit.split('-')[0])
    except msfutils.SFManagerException, e:
        print "Unable to create %s: %s" % (sfdistgit, e)
        sys.exit(1)
    with cdir(workdir):
        git('clone', 'http://%s/r/%s' % (config.rpmfactory, sfdistgit),
            sfdistgit)
    with cdir(os.path.join(workdir, sfdistgit)):
        # Set remotes and fetch objects
        git('remote', 'add', 'gerrit', sfgerrit + sfdistgit)
        if in_liberty:
            git('remote', 'add', 'upstream', distgit)
        git('remote', 'add', 'upstream-mdistgit', mdistgit)
        git('fetch', 'gerrit')
        if in_liberty:
            git('fetch', 'upstream')
        git('fetch', 'upstream-mdistgit')

        # Behave correctly according to project type and actual upstream layout
        if conf == 'core':
            if in_liberty:
                is_branches_exists([('upstream', 'rdo-liberty')])
                sync_and_push_branch('upstream', 'gerrit', 'rdo-liberty')
            is_branches_exists([('upstream-mdistgit', 'rpm-master')])
            sync_and_push_branch('upstream-mdistgit', 'gerrit',
                                 'rpm-master')
        elif conf == 'client' or conf == 'lib' or conf == 'None':
            if in_liberty:
                # Assume master targets liberty atm
                is_branches_exists([('upstream', 'master')])
                sync_and_push_branch('upstream', 'gerrit', 'master',
                                     'rdo-liberty')
            is_branches_exists([('upstream-mdistgit', 'rpm-master')])
            sync_and_push_branch('upstream-mdistgit', 'gerrit',
                                 'rpm-master')

        # Remove master branch (as not needed)
        # git('push', '-f', 'gerrit', ':master')


def import_mirror(msf, sfgerrit, name, upstream, workdir, in_liberty=True):
    print "=== Import mirror ==="
    try:
        create_baseproject(msf, name,
                           "\"Mirror of upstream %s (mirror + patches)\"" %
                           name)
    except msfutils.SFManagerException, e:
        print "Unable to create %s: %s" % (name, e)
        sys.exit(1)
    with cdir(workdir):
        git('clone', 'http://%s/r/%s' % (config.rpmfactory, name),
            name)
    with cdir(os.path.join(workdir, name)):
        # Set remotes and fetch objects
        git('remote', 'add', 'gerrit', sfgerrit + name)
        git('remote', 'add', 'upstream', upstream)
        git('fetch', '--all')

        # Assert expected branches exists
        if in_liberty:
            try:
                is_branches_exists([('upstream', 'stable/liberty')])
                sync_and_push_branch('upstream', 'gerrit', 'stable/liberty')
            except BranchNotFoundException, e:
                msg = "(%s) does not have a stable/liberty branch." % name + \
                      " Skip the sync."
                logging.warning(msg)
                print msg

        # sync and push to rpmfactory
        sync_and_push_branch('upstream', 'gerrit', 'master')
        git('push', 'gerrit', '--tags')


def set_patches_on_mirror(msf, sfgerrit, name, sfdistgit,
                          workdir):
    print "=== Compute and create the patches branch on mirror ==="
    with cdir(os.path.join(workdir, sfdistgit)):
        git('checkout', 'rdo-liberty')
        # Fetch flats file patches
        flat_patches = list(fetch_flat_patches(name))
        print "%s owns %s patches" % (sfdistgit, len(flat_patches))

        # Fetch upstream tag based on the spec file
        if name in RDOINFOS_FIXES and \
           'rdo-liberty-tag' in RDOINFOS_FIXES[name]:
            # Overwrite spec
            version = RDOINFOS_FIXES[name]['rdo-liberty-tag']
        else:
            version = fetch_upstream_tag_name()
        print "%s packaging is based on tag %s" % (sfdistgit, version)
    with cdir(os.path.join(workdir, name)):
        print "Create %s based on tag %s" % ('liberty-patches', version)
        try:
            git('checkout', version)
        except:
            if not flat_patches:
                raise RequestedTagDoesNotExists(
                    "%s is missing. But no patches rely on it" % version)
            else:
                raise PRequestedTagDoesNotExists(
                    "%s is missing. But patches rely on it" % (version))
        git('checkout', '-B', 'liberty-patches')
        git('push', '-f', 'gerrit', 'liberty-patches')

        print "Apply detected patches (%s)" % len(flat_patches)
        flat_patches.sort()
        for n, patch in enumerate(flat_patches):
            print "-> Apply patch : %s" % patch
            git('checkout', '-B', 'p%s' % n)
            git('am', os.path.join(workdir, sfdistgit, patch))
            git('review', '-i', '-y', 'liberty-patches')


def check_upstream_and_sync(name, workdir, local, branch,
                            upstream, rbranch=None, push_tags=False):
    if not rbranch:
        rbranch = branch
    print "Attempt to sync %s:%s from %s:%s" % (local, branch,
                                                upstream, rbranch)

    try:
        u_ref = [l.split()[0] for l in git('ls-remote', upstream).split('\n')
                 if l.endswith('refs/heads/%s' % rbranch)][0]
    except IndexError:
        raise BranchNotFoundException(
            "%s does not exist on %s" % (rbranch, upstream))
    try:
        l_ref = [l.split()[0] for l in git('ls-remote', local).split('\n')
                 if l.endswith('refs/heads/%s' % branch)][0]
    except IndexError:
        l_ref = 0

    if l_ref == u_ref:
        print "Branch is up to date. Nothing to do."
    else:
        print "Need a sync [l:%s != u:%s]" % (l_ref, u_ref)
        pdir = os.path.join(workdir, name)
        # Clean previous if exist
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)
        try:
            with cdir(workdir):
                git('clone', 'http://%s/r/%s' % (config.rpmfactory, name),
                    name)
            with cdir(pdir):
                # Set remotes and fetch objects
                git('remote', 'add', 'local', local)
                git('remote', 'add', 'upstream', upstream)
                git('fetch', '--all')
                difflog = git('--no-pager', 'log', '--oneline', '%s..%s' %
                              (l_ref, u_ref)).split('\n')
                for cmsg in difflog:
                    print cmsg
                sync_and_push_branch('upstream', 'local',
                                     rbranch, branch)
                if push_tags:
                    git('push', 'local', '--tags')
        except Exception, e:
            return [1, "Sync failed: %s" % e]

        return [0, "Sync succeed: %s commits has been synced" % len(difflog)]
    return [0, "Repo is up to date. Nothing to do."]


def project_import(cmdargs, workdir, rdoinfo):
    print "\n=== Start import ==="
    name, distgit, upstream, \
        sfdistgit, maints, conf, mdistgit = \
        fetch_project_infos(rdoinfo, cmdargs.name)

    sfgerrit = config.gerrit_rpmfactory % config.userlogin

    in_liberty = True
    if name in NOT_IN_LIBERTY:
        in_liberty = False

    print "In liberty ?: %s" % in_liberty

    r = requests.get('http://%s/r/projects/?d' % config.rpmfactory)
    projects = json.loads(r.text[4:])

    create = True
    if set([name, sfdistgit]).issubset(set(projects)):
        create = False

    if not cmdargs.force and not create:
        print "Project %s and %s already exists" % (name, sfdistgit)
        return

    if cmdargs.force and not create:
        print "Project %s already exists. But force !" % name

    print "Workdir is: %s" % workdir
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)

    try:
        import_distgit(msf, sfgerrit,
                       sfdistgit, distgit, mdistgit,
                       conf, workdir, in_liberty=in_liberty)
    except BranchNotFoundException, e:
        msg = "(%s) Unable to find a specific branch to import" % name + \
            " distgit: %s" % e
        logging.warning(msg)
        print msg
        delete_project(name)
        return False
    try:
        import_mirror(msf, sfgerrit, name, upstream, workdir,
                      in_liberty=in_liberty)
    except BranchNotFoundException, e:
        msg = "(%s) Unable to find a specific branch to import" % name + \
            " the mirror repo: %s" % e
        logging.warning(msg)
        print msg
        delete_project(name)
        return False

    if in_liberty:
        try:
            set_patches_on_mirror(msf, sfgerrit, name, sfdistgit,
                                  workdir)
        except RequestedTagDoesNotExists, e:
            print "Import warning: %s. liberty-patches not created" % e
            return False
        except PRequestedTagDoesNotExists, e:
            print "Import error: %s. Clean project" % e
            delete_project(name)
            return False

    return True


def project_create(cmdargs, workdir, rdoinfo):
    pass


def add_to_project_groups(name, maintainer):
    print "Add %s to project groups for %s" % (maintainer, name)
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)
    msf.addUsertoProjectGroups(name,
                               maintainer,
                               "ptl-group core-group")
    msf.addUsertoProjectGroups(name + '-distgit',
                               maintainer,
                               "ptl-group core-group")


def project_sync_maints(cmdargs, workdir, rdoinfo):
    print "\n=== Sync maintainer in project " + \
          "%s groups + service user ===" % cmdargs.name
    (name, distgit, upstream,
     sfdistgit, maints, conf, mdistgit) = fetch_project_infos(rdoinfo,
                                                              cmdargs.name)

    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)

    infos = msf.listAllProjectDetails()
    memberships = fetch_project_members(infos, name)

    # Clean actual members
    print "\nAttempt to clean existing members in %s" % name
    for project_mbs in memberships:
        for mb in memberships[project_mbs][0]:  # ptl
            if mb == 'admin@rpmfactory.beta.rdoproject.org':
                continue
            msf.deleteUserFromProjectGroup(project_mbs, mb, 'ptl-group')
        for mb in memberships[project_mbs][1]:  # core
            if mb == 'admin@rpmfactory.beta.rdoproject.org':
                continue
            msf.deleteUserFromProjectGroup(project_mbs, mb, 'core-group')

    for maintainer in maints:
        print "\nAttempt to add maintainer %s" % maintainer
        try:
            add_to_project_groups(name, maintainer)
        except msfutils.SFManagerException, e:
            print "Failed to add user in groups : %s" % e

    # Add a service user to the project group
    print
    add_to_project_groups(name, config.service_user_mail)


def get_project_status(projects, typ):
    r = requests.get('http://%s/r/projects/?d' % config.rpmfactory)
    sfprojects = json.loads(r.text[4:])

    status = {}
    for project in projects:
        status[project] = check_project_status(sfprojects, project)

    return [p for p, s in status.items() if s == typ]


def projects_status(cmdargs, workdir, rdoinfo):
    projects = fetch_all_project_type(rdoinfo, cmdargs.type)
    print "rdoinfo reports %s %s projects" % (len(projects), cmdargs.type)
    print "%s project list: %s" % (cmdargs.type, ", ".join(projects))

    print

    imported = get_project_status(projects, 2)
    print "Imported: %s : %s" % (len(imported), ", ".join(imported))
    inconsistent = get_project_status(projects, 1)
    print "Inconsistent: %s : %s" % (
        len(inconsistent), ", ".join(inconsistent))
    notimported = get_project_status(projects, 0)
    print "Not imported: %s : %s" % (
        len(notimported), ", ".join(notimported))

    print

    if cmdargs.clean:
        for p in inconsistent:
            delete_project(p)


def update_config_for_project(cmdargs, workdir, rdoinfo):
    print "\n=== Update jobs to trigger for project %s" % cmdargs.name
    sfgerrit = config.gerrit_rpmfactory % config.userlogin
    name = cmdargs.name

    mirror_p_jobs_tmpl = {'name': None,
                          'check': ['tox-validate']}
    distgit_p_jobs_tmpl = {'name': None,
                           'check': ['pkg-validate', 'delorean-ci']}

    pdir = os.path.join(workdir, 'config')
    # Clean previous if exist
    if os.path.isdir(pdir):
        shutil.rmtree(pdir)
    with cdir(workdir):
        git('clone', 'http://%s/r/%s' % (config.rpmfactory, 'config'),
            'config')
    with cdir(pdir):
        git('remote', 'add', 'gerrit', sfgerrit + 'config')
        zuul_projects = yaml.load(
            file("zuul/projects.yaml").read())
        for pname in (name, name + '-distgit'):
            # Clean previous if exists
            for i, p_def in enumerate(zuul_projects['projects']):
                if p_def['name'] == pname:
                    zuul_projects['projects'].pop(i)
            # Add the config entry
            if pname.endswith('-distgit'):
                zuul_projects['projects'].append(
                    deepcopy(distgit_p_jobs_tmpl))
            else:
                zuul_projects['projects'].append(
                    deepcopy(mirror_p_jobs_tmpl))
            zuul_projects['projects'][-1]['name'] = pname
        file("zuul/projects.yaml", "w").write(
            yaml.safe_dump(zuul_projects, default_flow_style=False))
        ret = git('ls-files', '-o', '-m', '--exclude-standard')
        if ret:
            git('commit', '-a', '--author',
                '%s <%s>' % (config.userlogin, config.useremail),
                '-m', 'Config update for %s' % name)
            git('review', '-i', '-r', 'gerrit', 'master')
            sha = open(".git/refs/heads/master").read()
            gu = msfutils.GerritSfUtils(config.rpmfactory,
                                        config.userlogin)
            try:
                gu.approve_and_wait_for_merge(sha)
            except msfutils.UnableToMergeException, e:
                print "Config change for %s has not be merged (%s)" % (
                    name, e)


def refresh_repo_for_project(cmdargs, workdir, rdoinfo, rtype):
    (name, distgit, upstream,
     sfdistgit, maints, conf, mdistgit) = fetch_project_infos(rdoinfo,
                                                              cmdargs.name)
    if rtype == 'distgit':
        name = sfdistgit

    print "\n=== Refresh %s branches for project %s" % (rtype, name)

    if cmdargs.user:
        sfgerrit = config.gerrit_rpmfactory % config.userlogin
    else:
        sfgerrit = config.gerrit_rpmfactory % config.service_user_name

    local = sfgerrit + name

    in_liberty = True
    if name in NOT_IN_LIBERTY:
        in_liberty = False

    push_tags = False

    if rtype == 'mirror':
        push_tags = True
        branches = ((upstream, 'master', 'master'),
                    (upstream, 'stable/liberty', 'stable/liberty'))
        local_branches = [l.split()[1] for
                          l in git('ls-remote', local).split('\n')
                          if l.find('refs/heads/') > 0]
    elif rtype == 'distgit':
        if conf == 'core':
            rbranch = 'rdo-liberty'
        if conf == 'client' or conf == 'lib' or conf == 'None':
            rbranch = 'master'

        branches = [(distgit, 'rdo-liberty', rbranch),
                    (mdistgit, 'rpm-master', 'rpm-master')]

        local_branches = [l.split()[1] for
                          l in git('ls-remote', local).split('\n')
                          if l.find('refs/heads/') > 0]

        if not in_liberty:
            del branches[0]

    ret = {}
    for branch in branches:
        if 'refs/heads/%s' % branch[1] not in local_branches:
            continue
        try:
            status = check_upstream_and_sync(name, workdir, local,
                                             branch[1], branch[0],
                                             rbranch=branch[2],
                                             push_tags=push_tags)
            ret[branch[1]] = status
        except BranchNotFoundException, e:
            ret[branch[1]] = [1, "Branch not found upstream !: %s" % e]
    return ret


def delete_project(p):
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)
    print "Delete %s (%s, %s)" % (p, p, p + '-distgit')
    msf.deleteProject(p)
    msf.deleteProject(p + '-distgit')


def check_project_status(sfprojects, name):

    sfdistgit = name + '-distgit'

    status = 2  # imported
    if not set([name, sfdistgit]).issubset(set(sfprojects)):
        status = 1  # inconsistent

    if name not in sfprojects and sfdistgit not in sfprojects:
        status = 0  # not imported

    return status


def fetch_project_members(infos, name):
    sfdistgit = name + '-distgit'
    ret = {}
    for p in (name, sfdistgit):
        groups = infos[p]['groups']
        ret[p] = []
        ret[p].append([m['email'] for m in groups['ptl']['members']])
        ret[p].append([m['email'] for m in groups['core']['members']])
    return ret


def project_members(cmdargs, workdir, rdoinfo):
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)
    name = cmdargs.name
    infos = msf.listAllProjectDetails()
    ret = fetch_project_members(infos, name)
    print ret


def create_stable_and_patches_branches(cmdargs):
    print "STABLE"
    s = branches.create_remote_branch(config.rpmfactory, 'admin',
                                      project=cmdargs.project,
                                      branch_template='stable/%s',
                                      newer_than=cmdargs.newer_than,
                                      dry_run=cmdargs.dry_run)
    print "PATCHES"
    p = branches.create_remote_branch(config.rpmfactory, 'admin',
                                      project=cmdargs.project,
                                      branch_template='%s-patches',
                                      newer_than=cmdargs.newer_than,
                                      dry_run=cmdargs.dry_run)
    for release in s.keys():
        print '\n====== %s ======' % release.upper()
        print 'Missing repositories:'
        missing = dict([(k, v) for k, v in s[release]['missing'].items()] +
                       [(k, v) for k, v in p[release]['missing'].items()])
        for m in missing.keys():
            print '* %s' % m
        print '---------------------'
        print 'Repositories missing stable/%s branch:' % release
        for r, v in s[release]['no_branch'].items():
            print '* %s (v. %s)' % (r, v)
        print '---------------------'
        print 'Repositories missing %s-patches branch:' % release
        for r, v in p[release]['no_branch'].items():
            print '* %s (v. %s)' % (r, v)
        print '---------------------'
        print 'Repositories with obsolete stable/%s branch:' % release
        for r, v in s[release]['obsolete'].items():
            print '* %s (should be v. %s)' % (r, v)
        print '---------------------'
        print 'Repositories with obsolete %s-patches branch:' % release
        for r, v in p[release]['obsolete'].items():
            print '* %s (should be v. %s)' % (r, v)
        print '---------------------'
        print 'Repositories with up-to-date stable/%s branch:' % release
        for r, v in s[release]['synced'].items():
            print '* %s (v. %s or above)' % (r, v)
        print '---------------------'
        print 'Repositories with up-to-date %s-patches branch:' % release
        for r, v in p[release]['synced'].items():
            print '* %s (v. %s or above)' % (r, v)


def main():
    parser = argparse.ArgumentParser(prog='sfrdo')
    parser.add_argument('--workdir', type=str, help='helper option')

    subparsers = parser.add_subparsers(
        title='commands',
        dest='command',
        help='Available commands help')

    parser_import = subparsers.add_parser(
        'import',
        help='Import an existing RDO project (need admin creds)')
    parser_import.add_argument('--name', type=str, help='project name')
    parser_import.add_argument(
        '--type', type=str, default=None,
        help='Import all project of type (core, client, lib)')
    parser_import.add_argument('--force',
                               action='store_true', default=False,
                               help='Overwrite a project if already exists')
    parser_import.add_argument('--from-p',
                               type=str, default=False,
                               help='Restart import from "project"')
    parser_import.add_argument(
        '--serviceuser', action='store_true', default=None,
        help='Use service identity to sync (set in config.py)')

    parser_create = subparsers.add_parser(
        'create',
        help='Create a new project template (need admin creds)')
    parser_create.add_argument('name', type=str, help='upstream project name')
    parser_create.add_argument('gituri', type=str, help='upstream project uri')

    parser_sync_maintainer = subparsers.add_parser(
        'sync_maints',
        help='Sync PTL/CORE group with maintainers (rdoinfo)')
    parser_sync_maintainer.add_argument(
        '--name', type=str, help='upstream project name')
    parser_sync_maintainer.add_argument(
        '--type', type=str, default=None,
        help='Limit to imported projects of type (core, client, lib)')
    parser_sync_maintainer.add_argument(
        '--github-usernames', type=str, default=None,
        help=('a file with a list of the github usernames of maintainers '
              'to sync in the form <email>:<username>. This should match '
              'the maintainers that could not be found with the '
              '"ghuser" command.'))

    parser_sync_repo = subparsers.add_parser(
        'sync_repo',
        help='Sync imported projects branches (mirror project by default)')
    parser_sync_repo.add_argument(
        '--name', type=str, help='Limit to project name')
    parser_sync_repo.add_argument(
        '--type', type=str, default=None,
        help='Limit to projects of type (core, client, lib)')
    parser_sync_repo.add_argument(
        '--user', action='store_true', default=None,
        help='Use your identity to sync (set in config.py)')
    parser_sync_repo.add_argument(
        '--distgit', action='store_true', default=None,
        help='Only act on distgit project branches')

    parser_status = subparsers.add_parser(
        'status',
        help='Status imported project')
    parser_status.add_argument(
        '--type', type=str, default='None',
        help='Limit status to projects of type (core, client, lib)')
    parser_status.add_argument(
        '--clean', action='store_true', default=None,
        help='Clean partially imported projects')

    parser_release_branches = subparsers.add_parser(
        'release_branches',
        help='Create stable/RELEASE and RELEASE-patches branches if needed')
    parser_release_branches.add_argument(
        '--project', type=str, default=None,
        help='Limit task to this project, default is to scan all OS projects')
    parser_release_branches.add_argument(
        '--newer-than', type=str, default='kilo',
        help='Do this for releases newer than XXX')
    parser_release_branches.add_argument(
        '--dry-run', action='store_true', default=False,
        help='Run the process but do not create the branches')

    subparsers.add_parser(
        'ghuser',
        help='Find username based on Github')

    parser_project_members = subparsers.add_parser(
        'project_members',
        help='Display project memberships')
    parser_project_members.add_argument(
        '--name', type=str, help='project name')

    parser_infos = subparsers.add_parser(
        'infos',
        help='Display infos from rdoinfo for a project')
    parser_infos.add_argument(
        '--name', type=str, help='project name')

    parser_config = subparsers.add_parser(
        'config',
        help='Configure jobs for project')
    parser_config.add_argument(
        '--name', type=str, help='project name')
    parser_config.add_argument(
        '--type', type=str, default=None,
        help='Limit to imported projects of type (core, client, lib)')

    subparsers.add_parser(
        'pre-register-rdo-users',
        help='This command pre register RDO user (from rdoinfo)')

    args = parser.parse_args()
    rdoinfo = fetch_rdoinfo()
    if not args.workdir:
        workdir = tempfile.mkdtemp()
    else:
        workdir = args.workdir
    kargs = {'cmdargs': args,
             'workdir': workdir,
             'rdoinfo': rdoinfo}

    if args.command == 'import':
        if args.type:
            projects = fetch_all_project_type(rdoinfo, args.type)
            if args.from_p:
                projects = projects[projects.index(args.from_p):]
        else:
            projects = [args.name]
        print "Import projects : %s" % ", ".join(projects)
        for project in projects:
            if project in BL:
                print "Skip %s as BL" % project
                continue
            kargs['cmdargs'].name = project
            display_details(**kargs)
            status = project_import(**kargs)
            if status:
                project_sync_maints(**kargs)
                update_config_for_project(**kargs)
    elif args.command == 'create':
        project_create(**kargs)
    elif args.command == 'sync_maints':
        if args.type:
            projects = fetch_all_project_type(rdoinfo, args.type)
            projects = get_project_status(projects, 2)
        else:
            projects = [args.name]
        print "Sync maints on projects : %s" % ", ".join(projects)
        for project in projects:
            kargs['cmdargs'].name = project
            project_sync_maints(**kargs)
    elif args.command == 'status':
        if not args.type:
            print "Provide the --type options"
            sys.exit(1)
        projects_status(**kargs)
    elif args.command == 'ghuser':
        import time
        projects = fetch_all_project_type(rdoinfo, 'core')
        projects.extend(fetch_all_project_type(rdoinfo, 'client'))
        projects.extend(fetch_all_project_type(rdoinfo, 'lib'))
        projects.extend(fetch_all_project_type(rdoinfo, 'None'))
        maints = {}
        for p in projects:
            maintainers = fetch_project_infos(rdoinfo, p)[4]
            for m in maintainers:
                maints[m] = None
        print maints
        return
        for m in maints.keys():
            time.sleep(15)
            print "\n---> Looking for %s" % m
            try:
                user_info = msfutils.get_github_user_by_mail(m)
                print "Found user %s detail (username, ...)" % user_info
                maints[m] = user_info
            except Exception as e:
                msg = "Could not find user."
                print "%s (Reason: %s)" % (msg, e.message)

        print maints
    elif args.command == 'project_members':
        project_members(**kargs)
    elif args.command == 'infos':
        display_details(**kargs)
    elif args.command == 'config':
        if args.type:
            projects = fetch_all_project_type(rdoinfo, args.type)
            projects = get_project_status(projects, 2)
        else:
            projects = [args.name]
        print "Update jobs to trigger for projects : %s" % ", ".join(projects)
        for project in projects:
            kargs['cmdargs'].name = project
            update_config_for_project(**kargs)
    elif args.command == 'sync_repo':
        # This command can be used in a Jenkins job so use WORKSPACE if exists.
        kargs['workdir'] = os.environ.get('WORKSPACE', kargs['workdir'])
        kargs['rtype'] = 'mirror'
        if args.distgit:
            kargs['rtype'] = 'distgit'
        final_status = {}
        if args.type:
            projects = fetch_all_project_type(rdoinfo, args.type)
            projects = get_project_status(projects, 2)
        else:
            projects = [args.name]
        print "Refresh %s branches for projects : %s" % (
            kargs['rtype'], ", ".join(projects))
        for project in projects:
            kargs['cmdargs'].name = project
            ret = refresh_repo_for_project(**kargs)
            status_name = kargs['cmdargs'].name
            if args.distgit:
                status_name += '-distgit'
            final_status[status_name] = ret
            sys.stdout.flush()
        print "\n=== Sync summary ==="
        cmd_ret = 0
        for project, bstatus in final_status.items():
            for branch, status in bstatus.items():
                print "project %s:%s: %s" % (
                    project, branch, status[1])
                cmd_ret += status[0]
        print "Return %s" % cmd_ret
        sys.exit(cmd_ret)
    elif args.command == 'pre_register_rdo_users':
        for k, v in RDOINFOS_USERS_FIXES.items():
            print "Process: %s %s" % (k, v)
            msfutils.delete_user(config.rpmfactory, 'admin',
                                 config.adminpass, email=k)
            if v[1]:
                msfutils.delete_user(config.rpmfactory, 'admin',
                                     config.adminpass, email=v[1])
            if v[0]:
                msfutils.delete_user(config.rpmfactory, 'admin',
                                     config.adminpass, username=v[0])
                print msfutils.provision_user(config.rpmfactory,
                                              'admin', config.adminpass,
                                              {"username": v[0],
                                               "email": k,
                                               "full_name": v[0],
                                               "ssh_keys": []})
            else:
                print "Skip"
    elif args.command == 'release_branches':
        create_stable_and_patches_branches(args)
