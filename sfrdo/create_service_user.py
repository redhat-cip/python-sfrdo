#!/usr/bin/env python

from pysflib.sfauth import get_cookie
from sfrdo import config

#  Need to run that before fetching the cookie:
#  sfmanager --url https://rpmfactory.beta.rdoproject.org --auth admin:xxx \
#  user create --username sfbender --password 'userpass' --email \
#  'dev-robot@rpmfactory.beta.rdoproject.org' --fullname \
#  'Bender RPM Factory' --ssh-key /var/lib/jenkins/.ssh/id_rsa.pub

auth_cookie = {'auth_pubtkt': get_cookie(config.rpmfactory,
                                         'sfrdobender', 'userpass')}
