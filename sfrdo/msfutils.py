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
import tempfile
import time
import shlex
import subprocess

from Crypto.PublicKey import RSA
import requests

from pysflib.sfauth import get_cookie


class SFManagerException(Exception):
    pass


class UnableToMergeException(Exception):
    pass


class Tool:
    def __init__(self):
        self.debug = None
        if "DEBUG" in os.environ:
            self.debug = sys.stdout
        self.env = os.environ.copy()

    def exe(self, cmd, cwd=None):
        if self.debug:
            self.debug.write("\n\ncmd = %s\n" % cmd)
            self.debug.flush()
        cmd = shlex.split(cmd)
        ocwd = os.getcwd()
        if cwd:
            os.chdir(cwd)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 env=self.env)
            output = p.communicate()[0]
            if self.debug:
                self.debug.write(output)
        finally:
            os.chdir(ocwd)
        return output, p.returncode


class GerritSfUtils(Tool):
    def __init__(self, host, user):
        Tool.__init__(self)
        self.host = host
        self.user = user
        self.cmd = "ssh -l %s -p 29418 %s gerrit " % (self.user, self.host)

    def approve_and_wait_for_merge(self, sha):
        cmd = self.cmd + "review --code-review +2 --workflow +1 %s" % sha
        self.exe(cmd)
        cmd = self.cmd + "query --format JSON --current-patch-set %s" % sha
        attempts = 0
        infos = {}
        infos['status'] = None
        while 'status' in infos and infos['status'] != "MERGED":
            out, _ = self.exe(cmd)
            infos = json.loads(out.split('\n')[0])
            print "Waiting to be merged ..."
            if attempts >= 21:
                raise UnableToMergeException("Timeout exceeded")
            time.sleep(3)
            attempts += 1
        print "Merged."


class ManageSfUtils(Tool):
    def __init__(self, url, user, passwd):
        Tool.__init__(self)
        self.url = url
        self.user = user
        self.passwd = passwd
        self.base_cmd = "sfmanager --url %s " \
            "--auth %s:%s " % (url, user, passwd)

    def createProject(self, name, options=None):
        cmd = self.base_cmd + " project create --name %s " % name
        if options:
            for k, v in options.items():
                cmd = cmd + " --" + k + " " + v

        out, code = self.exe(cmd)
        if code:
            raise SFManagerException(out)

    def deleteProject(self, name):
        cmd = self.base_cmd + " project delete --name %s" % name
        out, code = self.exe(cmd)
        if code:
            raise SFManagerException(out)

    def replicateAllProjectsGithub(self, token, rdoinfo,
                                   org="rdo-packages"):
        # Get list of all projects available on rpmfactory
        projects = requests.get('%s/r/projects/?d' % self.url)
        data = projects.text[4:]  # First 4 bytes are garbage
        for project, _details in json.loads(data).iteritems():
            self.replicateProjectGithub(project, token, rdoinfo, org)

    def replicateProjectGithub(self, project, token,
                               rdoinfo, org="rdo-packages"):
        pkgs = rdoinfo.get('packages')

        basename = project.replace('-distgit', '')
        distgit = upstream = None

        for pkg in pkgs:
            if pkg.get('project') == basename:
                patches = pkg.get('patches')
                upstream = pkg.get('upstream')
                distgit = pkg.get('master-distgit')

        if not distgit and upstream:
            print ("[WARNING] No details found for %s, skipping" % project)
            return

        key = RSA.generate(4096)

        privkey = tempfile.NamedTemporaryFile(delete=False)
        privkey.write(key.exportKey('PEM'))
        privkey.close()

        pubkey = tempfile.NamedTemporaryFile(delete=False)
        pubkey.write(key.publickey().exportKey('OpenSSH'))
        pubkey.close()

        if project.endswith('-distgit'):
            origin = distgit.replace('//git.openstack.org/', '//github.com/')
        else:
            origin = patches.replace('//git.openstack.org/', '//github.com/')
            origin = origin.replace('git://', 'http://')
            resp = requests.get(origin)
            if not resp.ok:
                origin = upstream.replace('git://git.openstack.org/',
                                          'http://github.com/')

        cmds = []
        cmds.append(" --github-token %s github fork-repo --origin %s --name %s --org %s" % (token, origin, project, org))  # noqa
        cmds.append(" --github-token %s github deploy-key -n %s -o %s --keyfile %s" % (token, project, org, pubkey.name))  # noqa
        cmds.append(" replication configure add --section %s url 'git@alias_gh_%s:%s/${name}.git'" % (project, project, org))  # noqa
        cmds.append(" replication configure add --section %s projects %s" % (project, project))  # noqa
        cmds.append(" gerrit_ssh_config add --alias alias_gh_%s --key %s --hostname github.com" % (project, privkey.name))  # noqa
        cmds.append(" replication trigger")

        for cmd in cmds:
            out, code = self.exe(self.base_cmd + cmd)
            if code:
                raise SFManagerException(out)
            time.sleep(15)

    def addUsertoProjectGroups(self, project, email, groups):
        cmd = self.base_cmd + " membership add --project %s " % project
        cmd = cmd + " --user %s --groups %s" % (email, groups)
        out, code = self.exe(cmd)
        if code:
            raise SFManagerException(out)

    def deleteUserFromProjectGroup(self, project, email, group):
        cmd = self.base_cmd + " membership remove --project %s " % project
        cmd = cmd + " --user %s --group %s" % (email, group)
        out, code = self.exe(cmd)
        if code:
            raise SFManagerException(out)

    def listRegisteredUsers(self):
        cmd = self.base_cmd + " membership list"
        out, code = self.exe(cmd)
        if code:
            raise SFManagerException(out)
        return out

    def listAllProjectDetails(self):
        auth_cookie = {'auth_pubtkt': get_cookie(self.url.lstrip('http://'),
                                                 self.user, self.passwd)}
        return requests.get(self.url + "/manage/project/",
                            cookies=auth_cookie).json()


def get_github_user_by_mail(email):
    """Retrieves user info from Github from an email address"""
    endpoint = "https://api.github.com/search/users?q=%s+in%%3Aemail"
    user_info = requests.get(endpoint % email).json()
    print user_info
    user_info = user_info['items']
    if not user_info:
        raise Exception("No user found")
    user_info = user_info[0]
    login = user_info['login']
    full_name = login
    # fech ssh keys
    endpoint = "https://api.github.com/users/%s/keys"
    keys = requests.get(endpoint % login).json()
    ssh_keys = [{"key": s["key"]} for s in keys]
    return {"username": login,
            "email": email,
            "full_name": full_name,
            "ssh_keys": ssh_keys}


def get_github_user_by_username(username):
    endpoint = "https://api.github.com/users/%s" % username
    user_info = requests.get(endpoint).json()
    if username != user_info.get('login'):
        raise Exception("No user found")
    email = user_info.get('email')
    # might not be world readable, might be a problem at provisioning ...
    if not email:
        print ("[WARNING] %s has no public email, first login "
               "after automated provisioning might fail.")
    full_name = username
    # fetch ssh keys
    keys = requests.get(endpoint + "/keys").json()
    ssh_keys = [{"key": s["key"] for s in keys}]
    return {"username": username,
            "email": email,
            "full_name": full_name,
            "ssh_keys": ssh_keys}


def provision_user(sf_url, username, password, user_data):
    auth_cookie = {'auth_pubtkt': get_cookie(sf_url, username, password)}
    return requests.post('http://' + sf_url + "/manage/services_users/",
                         json=user_data,
                         cookies=auth_cookie)


def delete_user(sf_url, login, password, username=None, email=None):
    auth_cookie = {'auth_pubtkt': get_cookie(sf_url, login, password)}
    if username:
        query = '?username=%s' % username
        requests.delete('http://' + sf_url + "/manage/services_users/" + query,
                        cookies=auth_cookie)
    # if both are given we'll just be extra cautious and delete two times
    if email:
        query = '?email=%s' % email
        requests.delete('http://' + sf_url + "/manage/services_users/" + query,
                        cookies=auth_cookie)
