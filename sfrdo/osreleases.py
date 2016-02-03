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


from distutils.version import LooseVersion
from rdopkg.utils.cmd import git
from rdopkg.utils.exception import CommandFailed
from rdopkg.helpers import cdir
import yaml
import glob
import tempfile
import shutil
import os
import copy

from sfrdo import rdoinfoutils


releases_info = 'https://github.com/openstack/releases.git'
os_git_root = 'http://git.openstack.org/cgit/'


def create_and_get_tempdir():
    return tempfile.mkdtemp()


def nuke_dir(dir):
    shutil.rmtree(dir)


def clone(repo, root_dir):
    if not os.path.isdir(root_dir):
        git('clone', repo, root_dir)


def get_commit_time(commit_id):
    return git('log', '-1', '--date=short', '--pretty=format:%ct',
               '-U', commit_id, '--no-patch')


def list_release_dirs(repo_dir, release="mitaka"):
    return [r for r in glob.glob(os.path.join(repo_dir, 'deliverables/*'))
            if (r.split('/')[-1] == release)]


def get_repos_infos_for_project(project_descriptor):
    descriptor = yaml.load(file(project_descriptor).read())
    infos = {}
    repos = {}
    # get latest stable release
    release = max([r for r in descriptor['releases']],
                  key=lambda x: LooseVersion(x['version']))
    for p in release['projects']:
        # remove leading "openstack/"
        project = p['repo'].split('/')[-1]
        # technically the release number should be enough since a tag exists
        infos[project] = p['hash']
        repos[project] = p['repo']
    return release['version'], infos, repos


def get_projects_status(sf_url, user, release,
                        rdo_project=None, branch_template='stable/%s'):
    """Compiles the latest tag/hash for rdo_project for <release> on branch"""
    url = 'ssh://%s@%s:29418' % (user, sf_url)
    rdoinfo = rdoinfoutils.fetch_rdoinfo()
    branch = branch_template % release
    projects = {}
    missing_from_rdo = {}
    status = {'upstream': {'name': None,
                           'version': None,
                           'hash': None,
                           'timestamp': None},
              'rdo': {'hash': None,
                      'timestamp': None},
              'branch_is_synced': False}
    tempdir = create_and_get_tempdir()
    releases_dir = os.path.join(tempdir, 'releases')
    # checkout the releases repo
    print "Cloning releases info ... "
    clone(releases_info, releases_dir)
    release_dir = os.path.join(releases_dir, 'deliverables/%s' % release)
    for descriptor in glob.glob(os.path.join(release_dir, '*.yaml')):
        version, infos, repos = get_repos_infos_for_project(descriptor)
        for project in infos.keys():
            try:
                (name, distgit, upstream, sfdistgit, maints,
                 conf, mdistgit) = rdoinfoutils.fetch_project_infos(rdoinfo,
                                                                    project)
            except Exception as e:
                print "Skipping %s: %s" % (project, e)
                missing_from_rdo[project] = os_git_root + repos.get(project)
                continue
            p_status = copy.deepcopy(status)
            if rdo_project and name != rdo_project:
                continue
            desc_file = descriptor.split('/')[-1]
            if rdo_project:
                print 'Info for %s found in %s' % (rdo_project, desc_file)
            p_status['upstream'] = {'name': project,
                                    'version': version,
                                    'hash': infos[project],
                                    'timestamp': None}
            if not os.path.isdir(os.path.join(tempdir, project)):
                try:
                    clone('%s/%s.git' % (url, name),
                          os.path.join(tempdir, project))
                except CommandFailed:
                    # we already get the output, so do nothing
                    p_status['rdo'] = {}
                    projects[name] = p_status
                    continue
            with cdir(os.path.join(tempdir, project)):
                if git.ref_exists('refs/remotes/origin/%s' % branch):
                    git('checkout', 'origin/%s' % branch)
                    current = git('log', '-1', '--pretty=format:%H')
                    commit = infos[project]
                    rdo_time = get_commit_time(current)
                    upstream_time = get_commit_time(commit)
                    p_status['upstream']['timestamp'] = upstream_time
                    p_status['rdo']['hash'] = current
                    p_status['rdo']['timestamp'] = rdo_time
                    if upstream_time <= rdo_time:
                        # rdo is up-to-date and more
                        p_status['branch_is_synced'] = True
            projects[name] = p_status
    nuke_dir(tempdir)
    return projects, missing_from_rdo


def create_branch_in_gerrit(project, branch_name, commit_id):
    # assuming we're in the repo dir
    git('branch', branch_name, commit_id)
    git('push', 'origin', branch_name)


def update_branch_in_gerrit(project, branch_name, commit_id):
    # assuming we're in the repo dir
    git('checkout', 'master')
    git('branch', '-f', branch_name, commit_id)
    git('checkout', branch_name)
    git('pull', 'origin', branch_name)
    git('push', 'origin', branch_name)


def create_remote_branch(sf_url, user,
                         project=None,
                         branch_template='stable/%s',
                         release='mitaka', dry_run=True,
                         modify_branches=False):
    raw_results = {'missing': {},
                   'synced': {},
                   'obsolete': {},
                   'no_branch': {}}
    if dry_run:
        print "This is a dry run, no repository will be modified."
    url = 'ssh://%s@%s:29418' % (user, sf_url)
    tempdir = create_and_get_tempdir()
    projects, missing = get_projects_status(sf_url, user, release,
                                            rdo_project=project,
                                            branch_template=branch_template)
    todo = projects.keys()
    if project:
        todo = [project, ]
    branch = branch_template % release
    for p in todo:
        if projects[p]['branch_is_synced']:
            msg = "Branch %s is synced for project %s, nothing to do"
            print msg % (branch, p)
            raw_results['synced'][p] = False
        elif not projects[p].get('rdo'):
            # project is listed in rdo but does not exist on rpmfactory
            print "Project %s does not exist on %s" % (p, sf_url)
            raw_results['missing'][p] = None
        elif projects[p].get('rdo') and not projects[p]['rdo']['hash']:
            # project exists on rpmfactory, is missing the branch
            msg = "Project %s has no branch called %s"
            print msg % (p, branch)
            if dry_run:
                raw_results['no_branch'][p] = None
            else:
                commit = projects[p]['upstream']['hash']
                print "Creating branch %s on project %s at %s .." % (branch, p,
                                                                     commit),
                # True if created in this run, False if already synced
                try:
                    clone('%s/%s.git' % (url, p),
                          os.path.join(tempdir, p))
                    with cdir(os.path.join(tempdir, p)):
                        create_branch_in_gerrit(p, branch, commit)
                        print " Done"
                    raw_results['synced'][p] = True
                except Exception as e:
                    print " Something bad happened :( %s" % e
                    raw_results['no_branch'][p] = None
        else:
            # project on rpmfactory has an obsolete branch
            msg = ("Project %s has obsolete branch %s, "
                   "set at %s, should be %s")
            print msg % (p, branch)
            if dry_run or not modify_branches:
                raw_results['obsolete'][p] = None
            else:
                commit = projects[p]['upstream']['hash']
                print "Updating branch %s on project %s at %s .." % (branch, p,
                                                                     commit),
                try:
                    clone('%s/%s.git' % (url, p),
                          os.path.join(tempdir, p))
                    with cdir(os.path.join(tempdir, p)):
                        update_branch_in_gerrit(p, branch, commit)
                        print "Done"
                        raw_results['synced'][p] = True
                except Exception as e:
                    print " Something bad happened :( %s" % e
                    raw_results['no_branch'][p] = None
    nuke_dir(tempdir)
    return raw_results
