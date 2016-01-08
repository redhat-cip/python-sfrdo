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
import tempfile
import argparse

from rdopkg.repoman import RepoManager
from rdopkg.helpers import cdir
from rdopkg.utils.cmd import git

from sfrdo import config
from sfrdo import msfutils


class BranchNotFoundException(Exception):
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
    select = [pkg for pkg in rdoinfo['packages'] \
              if pkg['project'] == upstream_project_name]
    if not select:
        raise Exception('Project not found in rdoinfo')
    infos = select[0]
    distgit = infos['distgit']
    mirror = infos['patches']
    upstream = infos['upstream']
    name = infos['project']
    maints = infos['maintainers']
    sfdistgit = "%s-distgit" % name
    return (name, distgit, mirror, upstream,
           sfdistgit, maints)


def display_details(cmdargs, rdoinfo, workdir=None):
    name, distgit, mirror, upstream, \
        sfdistgit, maints = fetch_project_infos(rdoinfo,
                                                cmdargs.name)
    print "=== Details ==="
    print "Project name is: %s" % name
    print "Project upstream RDO distgit is: %s" % distgit
    print "Project upstream RDO mirror is: %s" % mirror

    print "Project upstream is: %s" % upstream

    print "Project distgit name on SF is: %s" % sfdistgit
    print


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

def sync_and_push_branch(rfrom, rto, branch):
    print "sync from %s and push to %s branch %s" % (
        rfrom, rto, branch)
    if branch == 'master':
        git('checkout', branch)
    else:
        git('checkout', '-b', branch)
    initial = git('rev-list', '--max-parents=0', 'HEAD').split('\n')
    if len(initial) > 1:
        raise Exception()
    git('reset', '--hard', initial[0])
    git('rebase', 'remotes/%s/%s' % (rfrom, branch))
    git('push', '-f', rto, branch)


def fetch_flat_patches():
    patches = set([f for f in os.listdir('.') if f.endswith('.patch') and f[4] == '-'])
    spec = file([s for s in os.listdir('.') if s.endswith('.spec')][0])
    used_patches = [p.split(':') for p in spec.readlines() if p.startswith('Patch00')]
    used_patches = set([p.lstrip().rstrip('\n') for _, p in used_patches])
    if len(patches) != len(used_patches):
        print "warn: %s flat file patches exists but are not used" % len(patches - used_patches)
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


def import_distgit(msf, sfgerrit, sfdistgit, distgit, workdir):
    print "=== Import distgit ==="
    create_baseproject(msf, sfdistgit,
                       "\"Packaging content for %s (distgit)\"" % sfdistgit.split('-')[0])
    with cdir(workdir):
        git('clone', 'http://%s/r/%s' % (config.rpmfactory, sfdistgit),
            sfdistgit)
    with cdir(os.path.join(workdir, sfdistgit)):
        # Set remotes and fetch objects
        git('remote', 'add', 'gerrit', sfgerrit + sfdistgit)
        git('remote', 'add', 'upstream', distgit)
        git('fetch', '--all')

        # Assert expected branches exists
        is_branches_exists([('upstream', 'rdo-liberty')])

        # sync and push to rpmfactory
        sync_and_push_branch('upstream', 'gerrit', 'rdo-liberty')


def import_mirror(msf, sfgerrit, name, mirror, upstream, workdir):
    print "=== Import mirror ==="
    create_baseproject(msf, name,
                       "\"Mirror of upstream %s (mirror + patches)\"" % name)
    with cdir(workdir):
        git('clone', 'http://%s/r/%s' % (config.rpmfactory, name),
            name)
    with cdir(os.path.join(workdir, name)):
        # Set remotes and fetch objects
        git('remote', 'add', 'gerrit', sfgerrit + name)
        git('remote', 'add', 'mirror', mirror)
        git('remote', 'add', 'upstream', upstream)
        git('fetch', '--all')

        # Assert expected branches exists
        is_branches_exists([('upstream', 'stable/liberty')])

        # sync and push to rpmfactory
        sync_and_push_branch('upstream', 'gerrit', 'master')
        sync_and_push_branch('upstream', 'gerrit', 'stable/liberty')
        git('push', 'gerrit', '--tags')


def set_patches_on_mirror(msf, sfgerrit, name, mirror, sfdistgit,
                          workdir):
    print "=== Compute and create the patches branch on mirror ==="
    with cdir(os.path.join(workdir, sfdistgit)):
        # Fetch flats file patches
        flat_patches = fetch_flat_patches()
        print "%s owns %s patches" % (sfdistgit, len(flat_patches))

        # Fetch upstream tag based on the spec file
        version = fetch_upstream_tag_name()
        print "%s packaging is based on tag %s" % (sfdistgit, version)
    with cdir(os.path.join(workdir, name)):
        try:
           is_branches_exists([('mirror', 'liberty-patches')])
        except BranchNotFoundException, e:
           print "Upstream layout warn: %s. but we continue" % e

        print "Create %s based on tag %s" % ('liberty-patches', version)
        git('checkout', version)
        git('checkout', '-B', 'liberty-patches')
        git('push', '-f','gerrit', 'liberty-patches')

        print "Apply detected patches (%s)" % len(flat_patches)
        for n, patch in enumerate(flat_patches):
           print "-> Apply patch : %s" % patch
           git('checkout', '-B', 'p%s' % n)
           git('am', os.path.join(workdir, sfdistgit, patch))
           git('review', '-i', '-y', 'liberty-patches')


def project_import(cmdargs, workdir, rdoinfo):
    print "=== Start import ==="
    name, distgit, mirror, upstream, \
        sfdistgit, maints = fetch_project_infos(rdoinfo,
                                                cmdargs.name)
    print "Workdir is: %s" % workdir
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)
    sfgerrit = config.gerrit_rpmfactory % config.userlogin

    if not cmdargs.only_patches_branch:
        try:
            import_distgit(msf, sfgerrit,
                           sfdistgit, distgit, workdir)
        except BranchNotFoundException, e:
            print "Unable to find a specific branch to import distgit: %s" % e
            sys.exit(1)
        try:
            import_mirror(msf, sfgerrit, name, mirror, upstream, workdir)
        except BranchNotFoundException, e:
            print "Unable to find a specific branch to import the mirror repo: %s" % e
            sys.exit(1)

    set_patches_on_mirror(msf, sfgerrit, name, mirror, sfdistgit,
                          workdir)


def project_create(cmdargs, workdir, rdoinfo):
    pass


def project_sync_maints(cmdargs, workdir, rdoinfo):
    pass


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
    parser_import.add_argument('name', type=str, help='project name')
    parser_import.add_argument('--only-patches-branch',
                               action='store_true', default=False,
                               help='Only act on the patches branch (need a workdir)')

    parser_create = subparsers.add_parser(
        'create',
        help='Create a new project template (need admin creds)')
    parser_create.add_argument('name', type=str, help='upstream project name')
    parser_create.add_argument('gituri', type=str, help='upstream project uri')

    parser_sync_maintainer = subparsers.add_parser(
        'sync_maints',
        help='Sync PTL/CORE group with maintainers (rdoinfo)')
    parser_sync_maintainer.add_argument('name', type=str, help='upstream project name')

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
        display_details(**kargs)
        project_import(**kargs)
    elif args.command == 'create':
        project_create(**kargs)
    elif args.command == 'sync_maints':
        project_sync_maints(**kargs)
