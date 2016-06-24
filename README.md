python-sfrdo
============

This tool is deprecated.

Hacking
-------

```python
virtualenv --system-site-packages ../sfrdo-venv
. ../sfrdo-venv/bin/activate
pip install -r requirements.txt
python setup.py develop
```

Help
----

```bash
sfrdo --help
usage: sfrdo [-h] [--workdir WORKDIR]
             {import,create,sync_maints,status,ghuser,project_members,infos}
             ...

optional arguments:
  -h, --help            show this help message and exit
  --workdir WORKDIR     helper option

commands:
  {import,create,sync_maints,status,ghuser,project_members,infos,release_branches}
                        Available commands help
    import              Import an existing RDO project (need admin creds)
    create              Create a new project template (need admin creds)
    sync_maints         Sync PTL/CORE group with maintainers (rdoinfo)
    status              Status imported project
    ghuser              Find username based on Github
    project_members     Display project memberships
    infos               Display infos from rdoinfo for a project
    release_branches    Create specific release branches if they don't exist
```
