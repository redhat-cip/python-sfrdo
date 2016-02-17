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

userdir = os.path.join(os.path.expanduser('~/'), '.sfrdo')

rdoinfo = 'https://github.com/redhat-openstack/rdoinfo.git'

rpmfactory = 'rpmfactory.beta.rdoproject.org'
gerrit_rpmfactory = 'ssh://%%s@%s:29418/' % rpmfactory
service_user_name = 'sfrdobender'
service_user_mail = '%s@rpmfactory.beta.rdoproject.org' % service_user_name

userlogin = 'admin'
useremail = 'admin@rpmfactory.beta.rdoproject.org'
username = 'Anonymous Coward'
userpass = ''

adminpass = ''
