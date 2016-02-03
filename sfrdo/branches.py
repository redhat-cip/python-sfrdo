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
import requests
import json
import urllib
import os
from pysflib.sfauth import get_cookie
import copy


releases_info = 'https://github.com/openstack/releases.git'


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


def list_release_dirs(repo_dir, skip_older_than="kilo"):
    return [r for r in glob.glob(os.path.join(repo_dir, 'deliverables/*'))
            if (r.split('/')[-1] >= skip_older_than)]


def get_repos_infos_for_project(project_descriptor):
    descriptor = yaml.load(file(project_descriptor).read())
    infos = {}
    # get latest stable release
    release = max([r for r in descriptor['releases']],
                  key=lambda x: LooseVersion(x['version']))
    for p in release['projects']:
        # remove leading "openstack/"
        project = p['repo'].split('/')[-1]
        # technically the release number should be enough since a tag exists
        infos[project] = p['hash']
    return release['version'], infos


def create_branch_in_gerrit(project, branch_name, commit_id):
    # assuming we're in the repo dir
    git('branch', branch_name, commit_id)
    git('push', 'origin', branch_name)


def update_branch_in_gerrit(project, branch_name, commit_id):
    # assuming we're in the repo dir
    git('branch', '-f', branch_name, commit_id)
    git('push', 'origin', branch_name)


def create_remote_branch(sf_url, user, 
                         project=None,
                         branch_template='stable/%s',
                         newer_than='kilo', dry_run=True):
    raw_results = {'missing': {},
                   'synced': {},
                   'obsolete': {},
                   'no_branch': {}}
    results = {}
    if dry_run:
        print "This is a dry run, no repository will be modified."
    url = 'ssh://%s@%s:29418' % (user, sf_url)
    
    tempdir = create_and_get_tempdir()
    releases_dir = os.path.join(tempdir, 'releases')
    # checkout the releases repo
    print "Cloning releases info ... ",
    clone(releases_info, releases_dir)
    print "Done."
    print "checking releases in %s" % releases_dir
    if project:
        filter = '*%s*.yaml' % project
    else:
        filter = '*.yaml'
    for rel in list_release_dirs(releases_dir, newer_than):
        os_release = rel.split('/')[-1]
        results[os_release] = copy.deepcopy(raw_results)
        print "== %s release ==" % os_release
        for descriptor in glob.glob(os.path.join(releases_dir,
                                                 rel,
                                                 filter)):
            version, infos = get_repos_infos_for_project(descriptor)
            branch = branch_template % os_release
            for project, commit in infos.items():
                # RDO client libraries aren't called python-XXXclient
                if project.startswith('python-'):
                    project = project[len('python-'):]
                print "\tChecking %s ..." % project
                try:
                    clone('%s/%s.git' % (url, project),
                          os.path.join(tempdir, project))
                except CommandFailed:
                    # we already get the output, so do nothing
                    results[os_release]['missing'][project] = version
                    continue
                with cdir(os.path.join(tempdir, project)):
                    # does the stable branch exist on origin ?
                    if git.ref_exists('refs/remotes/origin/%s' % branch):
                        print "\t\tBranch %s already exists." % branch
                        # is it set to the correct hash ?
                        git('checkout', 'origin/%s' % branch)
                        latest = git('log', '-1', '--pretty=format:%H')
                        if get_commit_time(commit) > get_commit_time(latest):
                            msg = "\t\t%s is obsolete."
                            print msg % (branch)
                            p = project
                            if dry_run:
                                results[os_release]['obsolete'][p] = version
                                continue
                            try:
                                update_branch_in_gerrit(project,
                                                        branch, commit)
                                msg = "\t\t%s reset at %s for project %s"
                                print msg % (branch,
                                             commit,
                                             project)
                                results[os_release]['synced'][p] = version
                            except Exception as e:
                                msg = "\t\t:( %s at %s for project %s: %s"
                                print msg % (branch,
                                             commit,
                                             project,
                                             e)
                                results[os_release]['obsolete'][p] = version
                        else:
                            msg = "\t\t%s is in sync with releases info for %s"
                            print msg % (branch, project)
                            results[os_release]['synced'][project] = version
                    else:
                        print "\t\tBranch %s does not exist yet." % branch
                        if dry_run:
                            results[os_release]['no_branch'][project] = version
                            continue
                        try:
                            create_branch_in_gerrit(project, branch, commit)
                            msg = "\t\t%s created at %s for project %s"
                            print msg % (branch,
                                         commit,
                                         project)
                            results[os_release]['synced'][project] = version
                        except Exception as e:
                            msg = "\t\tFailure for %s at %s for project %s: %s"
                            print msg % (branch,
                                         commit,
                                         project,
                                         e)
                            results[os_release]['obsolete'][project] = version
                # clean the project repo
                nuke_dir(os.path.join(tempdir, project))
    nuke_dir(tempdir)
    return results
