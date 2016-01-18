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
import logging
import requests
import urlparse
import tempfile
import argparse

from rdopkg.repoman import RepoManager
from rdopkg.helpers import cdir
from rdopkg.utils.cmd import git

from sfrdo import config
from sfrdo import msfutils


logging.basicConfig(filename='warns.log', level=logging.DEBUG)


# TODO(fbo): Add an option to fired the periodic job to fetch lasts changes
# on mirror repos
# TODO(fbo): Add an option to add config jobs for earch project


BL = ['instack-undercloud',  # upstream 2.1.3 tag (used in spec) does not exits
      'tripleo-common',  # upstream 0.1 tag does not exists (0.1.0)
      'cloudkittyclient',  # distgit project not found on pkg.fedoraproject.org
      'tripleoclient',  # distgit project not found on pkg.fedoraproject.org
      'openstacksdk',  # distgit project not found on pkg.fedoraproject.org
      'dracclient',  # distgit project not found on pkg.fedoraproject.org
      'mistralclient',  # distgit project not found on pkg.fedoraproject.org
      'django_openstack_auth',  # distgit project not found on pkg.fedo...
      ]


class BranchNotFoundException(Exception):
    pass


class RequestedTagDoesNotExists(Exception):
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

    mdistgit = infos['master-distgit']
    upstream = infos['upstream']
    name = infos['project']
    maints = infos['maintainers']
    sfdistgit = "%s-distgit" % name
    conf = infos['conf']
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


def fetch_all_project_type(rdoinfo, t):
    select = [pkg for pkg in rdoinfo['packages']]
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
                   conf, workdir):
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
        git('remote', 'add', 'upstream', distgit)
        git('remote', 'add', 'upstream-mdistgit', mdistgit)
        git('fetch', '--all')

        # Behave correctly according to project type and actual upstream layout
        if conf == 'core':
            is_branches_exists([('upstream', 'rdo-liberty'),
                                ('upstream-mdistgit', 'rpm-master')])
            sync_and_push_branch('upstream', 'gerrit', 'rdo-liberty')
            sync_and_push_branch('upstream-mdistgit', 'gerrit',
                                 'rpm-master', 'master')
        elif conf == 'client':
            is_branches_exists([('upstream', 'master'),
                                ('upstream-mdistgit', 'rpm-master')])
            # Assume master targets liberty atm
            sync_and_push_branch('upstream', 'gerrit', 'master', 'rdo-liberty')
            sync_and_push_branch('upstream-mdistgit', 'gerrit',
                                 'rpm-master', 'master')


def import_mirror(msf, sfgerrit, name, upstream, workdir):
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
        skip = False
        try:
            is_branches_exists([('upstream', 'stable/liberty')])
        except BranchNotFoundException, e:
            msg = "(%s) does not have a stable/liberty branch." % name + \
                  " Skip the sync."
            logging.warning(msg)
            print msg
            skip = True

        # sync and push to rpmfactory
        sync_and_push_branch('upstream', 'gerrit', 'master')
        if not skip:
            sync_and_push_branch('upstream', 'gerrit', 'stable/liberty')
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
        version = fetch_upstream_tag_name()
        print "%s packaging is based on tag %s" % (sfdistgit, version)
    with cdir(os.path.join(workdir, name)):
        print "Create %s based on tag %s" % ('liberty-patches', version)
        try:
            git('checkout', version)
        except:
            raise RequestedTagDoesNotExists("%s is missing" % version)
        git('checkout', '-B', 'liberty-patches')
        git('push', '-f', 'gerrit', 'liberty-patches')

        print "Apply detected patches (%s)" % len(flat_patches)
        flat_patches.sort()
        for n, patch in enumerate(flat_patches):
            print "-> Apply patch : %s" % patch
            git('checkout', '-B', 'p%s' % n)
            git('am', os.path.join(workdir, sfdistgit, patch))
            git('review', '-i', '-y', 'liberty-patches')


def check_upstream_and_sync(local, branch, upstream, rbranch=None):
    if not rbranch:
        rbranch = branch
    print "Attempt to sync %s:%s from %s:%s" % (local, branch,
                                                upstream, rbranch) 
    u_ref = [l.split()[0] for l in git('ls-remote', upstream).split('\n')
           if l.endswith('refs/heads/%s' % rbranch)][0]
    l_ref = [l.split()[0] for l in git('ls-remote', local).split('\n')
           if l.endswith('refs/heads/%s' % branch)][0]

    if l_ref == u_ref:
        print "Distgit is up to date. Continue."
    else:
        print "Need a sync [l:%s != u:%s]" % (l_ref, u_ref)
        print "Not implemented."


def project_import(cmdargs, workdir, rdoinfo):
    print "\n=== Start import ==="
    name, distgit, upstream, \
        sfdistgit, maints, conf, mdistgit = \
        fetch_project_infos(rdoinfo, cmdargs.name)

    sfgerrit = config.gerrit_rpmfactory % config.userlogin

    r = requests.get('http://%s/r/projects/?d' % config.rpmfactory)
    projects = json.loads(r.text[4:])

    create = True
    if set([name, sfdistgit]).issubset(set(projects)):
        create = False

    # Refresh rdo-liberty and rpm-master
    if cmdargs.refresh_distgit:
        # The project exist
        if create == False:
            if conf == 'core':
                check_upstream_and_sync(sfgerrit + sfdistgit, 'rdo-liberty', distgit)
            if conf == 'client':
                check_upstream_and_sync(sfgerrit + sfdistgit, 'rdo-liberty', distgit, 'master')
            check_upstream_and_sync(sfgerrit + sfdistgit, 'master', mdistgit, 'rpm-master')
            return True
        print "Project has not been imported yet."
        return False

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
                       conf, workdir)
    except BranchNotFoundException, e:
        msg = "(%s) Unable to find a specific branch to import" % name + \
            " distgit: %s" % e
        logging.warning(msg)
        print msg
        delete_project(name)
        return False
    try:
        import_mirror(msf, sfgerrit, name, upstream, workdir)
    except BranchNotFoundException, e:
        msg = "(%s) Unable to find a specific branch to import" % name + \
            " the mirror repo: %s" % e
        logging.warning(msg)
        print msg
        delete_project(name)
        return False

    try:
        set_patches_on_mirror(msf, sfgerrit, name, sfdistgit,
                              workdir)
    except RequestedTagDoesNotExists, e:
        print "Import error: %s" % e
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
    users = msf.listRegisteredUsers()
    users = json.loads(users)

    infos = msf.listAllProjectDetails()
    memberships = fetch_project_members(infos, name)

    # Clean actual members
    print "\nAttempt to clean existing members in %s" % name
    for project_mbs in memberships:
        for mb in memberships[project_mbs][0]:  # ptl
            if mb == 'admin@rpmfactory.beta.rdoproject.org':
                continue
            msf.deleteUserToProjectGroup(project_mbs, mb, 'ptl-group')
        for mb in memberships[project_mbs][1]:  # core
            if mb == 'admin@rpmfactory.beta.rdoproject.org':
                continue
            msf.deleteUserToProjectGroup(project_mbs, mb, 'core-group')

    for maintainer in maints:
        print "\nAttempt to add maintainer %s" % maintainer
        if maintainer in [user[1] for user in users]:
            pass
        else:
            msg = "Not registered on SF so looking up on Github"
            print msg
            try:
                user_info = msfutils.get_github_user_by_mail(maintainer)
                print "Found user %s detail (username, ...)" % \
                    user_info['username']
                print "Do %s pre-registration" % maintainer
            except Exception as e:
                msg = "Could not find user."
                print "%s (Reason: %s)" % (msg, e.message)
                print "Skip %s pre-registration" % maintainer
                continue
            r = msfutils.provision_user(config.rpmfactory,
                                        'admin', config.adminpass,
                                        user_info)
            if r.status_code > 399:
                print "Could not pre-register user in rpmfactory :("
            else:
                print "User registered in rpmfactory"

        add_to_project_groups(name, maintainer)

    # Add a service user to the project group
    print
    add_to_project_groups(name, config.service_user)


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
    parser_import.add_argument(
        '--refresh-distgit',
        action='store_true', default=False,
        help='Sync previously imported disgit repo with upstream')
    parser_import.add_argument('--force',
                               action='store_true', default=False,
                               help='Overwrite a project if already exists')

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

    parser_status = subparsers.add_parser(
        'status',
        help='Status imported project')
    parser_status.add_argument(
        '--type', type=str, default=None,
        help='Limit status to projects of type (core, client, lib)')
    parser_status.add_argument(
        '--clean', action='store_true', default=None,
        help='Clean partially imported projects')

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
            if status and not args.refresh_distgit:
                project_sync_maints(**kargs)
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
        projects.extend(fetch_all_project_type(rdoinfo, 'core'))
        maints = {}
        for p in projects:
            maintainers = fetch_project_infos(rdoinfo, p)[4]
            for m in maintainers:
                maints[m] = None
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
