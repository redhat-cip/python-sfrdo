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
import json
import yaml
import shutil
import logging
import requests
import tempfile
import argparse

from rdopkg.helpers import cdir
from rdopkg.utils.cmd import git

from copy import deepcopy

from sfrdo import config
from sfrdo import msfutils
from sfrdo import osreleases
from sfrdo import rdoinfoutils


logging.basicConfig(filename='warns.log', level=logging.DEBUG)


BL = []


NOT_IN_LIBERTY = ['cloudkittyclient', 'openstacksdk',
                  'mistralclient', 'os-win', 'ironic-lib', 'octavia',
                  'cloudkitty', 'mistral', 'osprofiler', 'pysaml2',
                  'networking-arista', 'networking-cisco', 'vmware-nsx',
                  'networking-mlnx', 'app-catalog-ui',
                  'UcsSdk', 'cachetools', 'networking-ovn', 'neutron-lib',
                  'cisco-ironic-contrib', 'magnum']


# g42b3426 is not found upstream so force to do not create
# the liberty-patches branch even if in liberty.
NOT_IN_LIBERTY.append('packstack')


class BranchNotFoundException(Exception):
    pass


class RequestedTagDoesNotExists(Exception):
    pass


class PRequestedTagDoesNotExists(Exception):
    pass


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
    if not name.endswith("-distgit"):
        opts['readonly'] = ''
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
        if name in rdoinfoutils.RDOINFOS_FIXES and \
           'rdo-liberty-tag' in rdoinfoutils.RDOINFOS_FIXES[name]:
            # Overwrite spec
            version = rdoinfoutils.RDOINFOS_FIXES[name]['rdo-liberty-tag']
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
        # Set code to 0 avoid exiting with an error code
        return [0, "[SKIPPED] remote branch not found %s:%s " % (upstream,
                                                                 rbranch)]
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
                if l_ref != 0:
                    difflog = git('--no-pager', 'log', '--oneline', '%s..%s' %
                                  (l_ref, u_ref)).split('\n')
                    for cmsg in difflog:
                        print cmsg
                sync_and_push_branch('upstream', 'local',
                                     rbranch, branch)
                if push_tags:
                    git('push', 'local', '--tags')
        except Exception, e:
            return [1, "[FAILED] Sync from %s:%s (%s)" % (upstream,
                                                          rbranch, e)]

        if l_ref == 0:
            difflog = "BRANCH CREATED"
        else:
            difflog = "%s COMMIT(S)" % len(difflog)
        return [0, "[SYNC SUCCEED: %s] synced from %s:%s" % (
            difflog, upstream, rbranch)]
    return [0, "[UP TO DATE] compared to %s:%s" % (upstream, rbranch)]


def project_import(cmdargs, workdir, rdoinfo):
    print "\n=== Start import ==="
    name, distgit, upstream, \
        sfdistgit, maints, conf, mdistgit = \
        rdoinfoutils.fetch_project_infos(rdoinfo, cmdargs.name)

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


def replicate_project(cmdargs, workdir, rdoinfo):
    print "Setup replication for %s" % cmdargs.name
    msf = msfutils.ManageSfUtils('http://' + config.rpmfactory,
                                 'admin', config.adminpass)
    msf.replicateProjectGithub(
        cmdargs.name, cmdargs.token, rdoinfo, org="rdo-packages")


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
    (name, distgit, upstream, sfdistgit, maints,
     conf, mdistgit) = rdoinfoutils.fetch_project_infos(rdoinfo,
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
    print "\n=== Update jobs to trigger for project %s" % (
        ", ".join(cmdargs.name))
    sfgerrit = config.gerrit_rpmfactory % config.userlogin

    mirror_p_jobs_tmpl = {'name': None,
                          'check':
                          ['tox-validate']}
    distgit_p_jobs_tmpl = {'name': None,
                           'check': ['packstack-validate', 'rpmlint-validate',
                                     'pkg-upgrade-validate', 'delorean-ci'],
                           'gate': ['packstack-validate', 'pkg-export'],
                           }

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

        for name in cmdargs.name:
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
            if len(cmdargs.name) > 1:
                cmtmsg = 'Config update for multiple projects'
            else:
                cmtmsg = 'Config update for %s' % cmdargs.name[0]
            git('commit', '-a', '--author',
                '%s <%s>' % (config.username, config.useremail),
                '-m', cmtmsg)
            git('review', '-i', '-r', 'gerrit', 'master')
            sha = open(".git/refs/heads/master").read()
            gu = msfutils.GerritSfUtils(config.rpmfactory,
                                        config.userlogin)
            try:
                gu.approve_and_wait_for_merge(sha)
            except msfutils.UnableToMergeException, e:
                print "Config change for has not be merged (%s)" % e


def refresh_repo_for_project(cmdargs, workdir, rdoinfo, rtype):
    (name, distgit, upstream, sfdistgit, maints,
     conf, mdistgit) = rdoinfoutils.fetch_project_infos(rdoinfo, cmdargs.name)

    in_liberty = True
    if name in NOT_IN_LIBERTY:
        in_liberty = False

    if rtype == 'distgit':
        name = sfdistgit

    print "\n=== Refresh %s branches for project %s" % (rtype, name)

    if cmdargs.user:
        sfgerrit = config.gerrit_rpmfactory % config.userlogin
    else:
        sfgerrit = config.gerrit_rpmfactory % config.service_user_name

    local = sfgerrit + name

    push_tags = False

    if rtype == 'mirror':
        push_tags = True
        branches = ((upstream, 'master', 'master'),
                    (upstream, 'stable/liberty', 'stable/liberty'))
    elif rtype == 'distgit':
        if conf == 'core':
            branches = [
                (distgit, 'rdo-liberty', 'rdo-liberty'),
            ]
        elif conf == 'client' or conf == 'lib' or conf == 'None':
            branches = []
            # /!\ Some projects still have a rdo-liberty branch on the
            # master branch from Fedora VCS.
            # So try to sync from there first.
            # Then check if rdo-liberty branch is found on github (mdistgit)
            # then try to sync from github. /!\
            print name
            if distgit.find('pkgs.fedoraproject.org') >= 0:
                if in_liberty:
                    # Check this above prevents when we request a missing repo
                    # that not exists on pkgs.fedoraproject.org
                    branches.extend(((distgit, 'rdo-liberty', 'master'),))
            # The NOT_IN_LIBERTY list is not fully accurate and sometime
            # a rdo-liberty branch exists on Github so fetch it if exists.
            branches.extend(((mdistgit, 'rdo-liberty', 'rdo-liberty'),))

        branches.extend(((mdistgit, 'rdo-kilo', 'rdo-kilo'),
                         (mdistgit, 'rpm-master', 'rpm-master'),
                         (mdistgit, 'rpm-liberty', 'rpm-liberty'),
                         (mdistgit, 'rpm-kilo', 'rpm-kilo'),))

    ret = {}
    for branch in branches:
        status = check_upstream_and_sync(name, workdir, local,
                                         branch[1], branch[0],
                                         rbranch=branch[2],
                                         push_tags=push_tags)
        if branch[0].find('pkgs.fedoraproject.org') >= 0:
            # Just for clarify the summary
            branch_name = "%s (legacy)" % branch[1]
        else:
            branch_name = branch[1]
        ret[branch_name] = status

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


def get_release_branch_status(cmdargs):
    if cmdargs.branch == 'stable':
        template = 'stable/%s'
    elif cmdargs.branch == 'patches':
        template = '%s-patches'
    else:
        template = cmdargs.branch
    status, missing = osreleases.get_projects_status(config.rpmfactory,
                                                     cmdargs.user,
                                                     release=cmdargs.release,
                                                     rdo_project=cmdargs.name,
                                                     branch_template=template)
    print "---%s---" % (template % cmdargs.release).upper()
    line = ("%(project)30s  %(is_in_rpmfactory)13s  %(has_branch)6s  "
            "%(hash)14s  %(upstream_name)30s  %(version)15s  "
            "%(upstream_hash)14s  %(synced)6s")
    print line % {'project': 'Project',
                  'is_in_rpmfactory': 'In RPMFactory',
                  'has_branch': 'Branch',
                  'hash': 'Commit Hash',
                  'upstream_name': 'Upstream Name',
                  'upstream_hash': 'Upstream Hash',
                  'version': 'Version',
                  'synced': 'Synced'}
    for p in status:
        f = {'project': p,
             'is_in_rpmfactory': status[p]['rdo'] and 'YES' or 'NO',
             'has_branch': 'N/A',
             'hash': 'N/A',
             'upstream_name': status[p]['upstream']['name'],
             'upstream_hash': status[p]['upstream']['hash'][:8],
             'version': status[p]['upstream']['version'],
             'synced': status[p]['branch_is_synced'] and "YES" or "NO"}
        if status[p]['rdo']:
            f['has_branch'] = status[p]['rdo']['hash'] and 'YES' or 'NO'
            if status[p]['rdo']['hash']:
                f['hash'] = status[p]['rdo']['hash'][:8]
        print line % f
    print "---The following projects are not tracked by RDO---"
    for m in missing.items():
        print "* %s (%s)" % m


def create_stable_and_patches_branches(cmdargs):
    if cmdargs.branch == 'stable':
        template = 'stable/%s'
    elif cmdargs.branch == 'patches':
        template = '%s-patches'
    else:
        template = cmdargs.branch
    s = osreleases.create_remote_branch(config.rpmfactory, cmdargs.user,
                                        project=cmdargs.name,
                                        branch_template=template,
                                        release=cmdargs.release,
                                        dry_run=cmdargs.dry_run,
                                        modify_branches=False)

    print '\n====== %s [%s] ======' % (cmdargs.release.upper(),
                                       template % cmdargs.release)
    print 'Repositories missing in %s:' % config.rpmfactory
    for m in s['missing'].keys():
        print '* %s' % m
    print '---------------------'
    print 'Repositories without branch %s:' % template % cmdargs.release
    for r, v in s['no_branch'].items():
        print r
    print '---------------------'
    print 'Repositories with obsolete branch:'
    for r, v in s['obsolete'].items():
        print r
    print '---------------------'
    print 'Repositories with up-to-date branch:'
    for r, v in s['synced'].items():
        if v:
            print "(synced on this run) ",
        print r


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

    parser_replicate = subparsers.add_parser(
        'replicate',
        help='Setup replication to Github')
    parser_replicate.add_argument(
        '--name', type=str, help='Limit to project name')
    parser_replicate.add_argument(
        '--token', type=str, default='None',
        help='Github authentication token')

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
    parser_release_subcommand = parser_release_branches.add_subparsers(
        dest='subcommand')
    parser_release_status = parser_release_subcommand.add_parser('status')
    parser_release_create = parser_release_subcommand.add_parser('create')
    parser_release_status.add_argument(
        '--user', type=str, default=None,
        help=('User with whom project(s) will be checked out.'))
    parser_release_status.add_argument(
        '--name', type=str, default=None,
        help=('Limit task to this project, leave empty to scan all OS '
              'projects.'))
    parser_release_status.add_argument(
        '--release', type=str, default='mitaka',
        help='Do check status for this release')
    parser_release_status.add_argument(
        '--branch', type=str, default='stable',
        help='Check this branch type. Values are "stable" or "patches"')

    parser_release_create.add_argument(
        '--user', type=str, default=None,
        help=('User with whom project(s) will be checked out. User should be '
              'at least core-dev on the project'))
    parser_release_create.add_argument(
        '--name', type=str, default=None,
        help=('Limit task to this project, leave empty to scan all OS '
              'projects.'))
    parser_release_create.add_argument(
        '--release', type=str, default='kilo',
        help='Do this for releases newer than XXX')
    parser_release_create.add_argument(
        '--branch', type=str, default='stable',
        help='Check this branch type. Values are "stable" or "patches"')
    parser_release_create.add_argument(
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
    rdoinfo = rdoinfoutils.fetch_rdoinfo()
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
            rdoinfoutils.display_details(**kargs)
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
    elif args.command == 'replicate':
        if not (args.name and args.token):
            print "Provide project name and github token"
            sys.exit(1)
        replicate_project(**kargs)
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
            maintainers = rdoinfoutils.fetch_project_infos(rdoinfo, p)[4]
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
        rdoinfoutils.display_details(**kargs)
    elif args.command == 'config':
        if args.type:
            projects = fetch_all_project_type(rdoinfo, args.type)
            projects = get_project_status(projects, 2)
        else:
            projects = [args.name]
        print "Update jobs to trigger for projects : %s" % ", ".join(projects)
        kargs['cmdargs'].name = projects
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
                print "Local branch %s:%s: %s" % (
                    project, branch, status[1])
                cmd_ret += status[0]
        print "Return %s" % cmd_ret
        sys.exit(cmd_ret)
    elif args.command == 'pre_register_rdo_users':
        for k, v in rdoinfoutils.RDOINFOS_USERS_FIXES.items():
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
        if args.subcommand == 'create':
            create_stable_and_patches_branches(args)
        elif args.subcommand == 'status':
            get_release_branch_status(args)
