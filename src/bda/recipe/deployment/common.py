# -*- coding: utf-8 -*-
import os
import sys
import re
import copy
import getpass
import ConfigParser
import logging
from distutils.dist import Distribution
from bda.recipe.deployment import env

log = logging.getLogger('bda.recipe.deployment')

version_pattern = re.compile("""[ \t]*version[ \t]*=[ \t]*["\'](.*)["\'].*""")

class DeploymentError(Exception): pass

class _ConfigMixin(object):
    
    def __init__(self, path):
        self.path = path
        self.config = ConfigParser.ConfigParser()
        self.config.optionxform = str
        if os.path.exists(path):
            self.config.read(path)
    
    def __call__(self):
        file = open(self.path, 'wb')
        self.config.write(file)
        file.close()
    
    def as_dict(self, section):
        return dict(self.config.items(section))
    
    def read_option(self, section, name):
        if self.config.has_option(section, name):
            return self.config.get(section, name)

class Config(_ConfigMixin):
    
    def __init__(self, path, deployment_base=None, distserver=None, packages=None,
                 sources=None, rc=None, live=None, env=None, sources_dir=None,
                 register=None):
        _ConfigMixin.__init__(self, path)
        self.packages = packages
        if not self.config.has_section('distserver'):
            self.config.add_section('distserver')
        if not self.config.has_section('packages'):
            self.config.add_section('packages')
        if not self.config.has_section('sources'):
            self.config.add_section('sources')
        if not self.config.has_section('settings'):
            self.config.add_section('settings')
        if distserver is not None:
            for key, val in distserver.items():
                self.config.set('distserver', key, val)
        if packages is not None:
            for key, val in packages.items():
                self.config.set('packages', key, val)
        if sources is not None:
            for key, val in sources.items():
                self.config.set('sources', key, val)
        if deployment_base is not None:
            self.config.set('settings', 'deployment_base', deployment_base)
        if rc is not None:
            self.config.set('settings', 'rc', rc)
        if live is not None:
            self.config.set('settings', 'live', live)
        if env is not None:
            self.config.set('settings', 'env', env)
        if sources_dir is not None:
            self.config.set('settings', 'sources_dir', sources_dir)
        if register is not None:
            self.config.set('settings', 'register', register)
    
    @property
    def deployment_base(self):
        return self.read_option('settings', 'deployment_base')
    
    @property
    def rc(self):
        return self.read_option('settings', 'rc')
    
    @property
    def live(self):
        return self.read_option('settings', 'live')
    
    @property
    def env(self):
        return self.read_option('settings', 'env')
    
    @property
    def sources_dir(self):
        return self.read_option('settings', 'sources_dir')

    @property
    def registerdist(self):
        return self.read_option('settings', 'register')
    
    def distserver(self, name):
        return self.read_option('distserver', name)    
    
    def package(self, name):
        return self.read_option('packages', name)
    
    def source(self, name):
        return self.read_option('sources', name)

class RcSourcesCFG(_ConfigMixin):
    
    def __init__(self, path):
        _ConfigMixin.__init__(self, path)
        if not self.config.has_section('sources'):
            self.config.add_section('sources')
    
    def set(self, package, source):
        self.config.set('sources', package, source)

    def get(self, package):
        return self.read_option('sources', package)        

class LiveVersionsCFG(_ConfigMixin):
    
    def __init__(self, path):
        _ConfigMixin.__init__(self, path)
        if not self.config.has_section('versions'):
            self.config.add_section('versions')
    
    def set(self, package, version):
        self.config.set('versions', package, version)

    def get(self, package):
        return self.config.get('versions', package)        

class ReleaseRC(_ConfigMixin):
    
    def set(self, server, user, password):
        if not self.config.has_section(server):
            self.config.add_section(server)
        self.config.set(server, 'username', user)
        self.config.set(server, 'password', password)
    
    def get(self, server):
        if not self.config.has_option(server, 'username') \
          or not self.config.has_option(server, 'password'):
            return None
        return self.config.get(server, 'username'), \
               self.config.get(server, 'password')

class PackageVersion(object):
    
    def __init__(self, path):
        self.path = path
    
    def _get_version(self):
        file = open(self.path)
        version = "0"
        for line in file.readlines():
            mo = version_pattern.match(line)
            if mo:
                version = mo.group(1)
                break
        file.close()
        return version
    
    def _set_version(self, value):
        out = list()
        file = open(self.path)
        for line in file.readlines():
            mo = version_pattern.match(line)
            if mo:
                line = line[:mo.span(1)[0]] + value + line[mo.span(1)[1]:]
            out.append(line)
        file.close()
        file = open(self.path, 'w')
        file.writelines(out)
        file.close()    
    
    version = property(_get_version, _set_version)

class PWDManager(object):
    
    def __init__(self, server):
        self.server = server
        self.releaserc = ReleaseRC(env.RC_PATH)
    
    def get(self):
        res = self.releaserc.get(self.server)
        if res is not None:
            return res
        self.set()
        return self.releaserc.get(self.server)
    
    def set(self):
        username = password = None
        while not username:
            username = raw_input('Username: ')
        while not password:
            password = getpass.getpass('Password: ')
        self.releaserc.set(self.server, username, password)
        self.releaserc()

class DeploymentPackage(object):
    
    connectors = dict()
    
    def __init__(self, config, package):
        self.config = config
        self.package = package
    
    def commit(self, resource, message):
        """Commit resource of package with message.
        
        @param resource: path to resource. If None, all resources in package
                         are committed
        @param message: commit message
        """
        self.connector.commit(resource, message)
    
    def commit_rc_source(self):
        """Function committing RC source file.
        
        XXX: move logic to connector.
        """
        connector = self.connectors['svn'](self) # XXX
        url = self.config.deployment_base[4:] # XXX
        message = '"RC Sources changed"'
        args = ["svn", "ci", self.config.rc, '-m', message]
        kwargs = {}
        msg = ' '.join(args)
        log.info(msg)
        stdout, stderr, returncode = connector._svn_communicate(args, url,
                                                           **kwargs)
    
    def commit_live_versions(self):
        """Function committing RC source file.
        
        XXX: move logic to connector.
        """
        connector = self.connectors['svn'](self) # XXX
        url = self.config.deployment_base[4:] # XXX
        message = '"Live versions changed"'
        args = ["svn", "ci", self.config.live, '-m', message]
        kwargs = {}
        msg = ' '.join(args)
        log.info(msg)
        stdout, stderr, returncode = connector._svn_communicate(args, url,
                                                           **kwargs)
    
    def merge(self, resource=None):
        """Merge from trunk to rc.
        
        Function only callable in ``rc`` environment.
        
        Raise ``DeploymentError`` if called in wrong environment.
        
        @param resource: path to resource. If None, all resources in package
                         are merged
        """
        self._check_environment('merge', 'rc')
        self.connector.merge(resource)
    
    def creatercbranch(self):
        """Create RC branch for package.
        """
        self._check_environment('creatercbranch', 'dev')
        self.connector.creatercbranch()        
    
    def tag(self):
        """Tag package from rc to tags/version. Use version of
        package ``setup.py``
        
        Function only callable in ``rc`` environment.
        
        Raise ``DeploymentError`` if tag already exists or if called in
        wrong environment.
        """
        self._check_environment('tag', 'rc')
        self.connector.tag()
    
    def release(self):
        """Release package to configured dist server.
        
        Function only callable in ``rc`` environment.
        
        Raise ``DeploymentError`` if called in wrong environment.
        
        XXX: make me thread safe.
        """
        self._check_environment('release', 'rc')
        pwdmgr = PWDManager(self.config.package(self.package))
        username, password = pwdmgr.get()
        package_path = self.package_path
        setup = os.path.join(package_path, 'setup.py')
        old_argv = copy.copy(sys.argv)
        sys.argv = ['setup.py', 
                    'sdist',                     
                    'deploymentupload']        
        if self.config.package(self.package) in self.register_dist:
            sys.argv.append('deploymentregister')  
        env.waitress = {
            'repository': self.dist_server,
            'username': username,
            'password': password,
        }
        os.chdir(package_path)
        res = execfile('setup.py', globals(), {'__file__': setup})
        sys.argv = old_argv
        env.waitress = dict()
    
    def export_rc(self):
        """Export package rc repo info to configured rc sources config.
        
        Function only callable in ``dev`` environment.
        
        Raise ``DeploymentError`` if called in wrong environment.
        """
        self._check_environment('export_rc', 'dev')
        sources = RcSourcesCFG(self.config.rc)
        sources.set(self.package, self.connector.rc_source)
        sources()
    
    @property
    def rc_source(self):
        sources = RcSourcesCFG(self.config.rc)
        return sources.get(self.package)
    
    def export_version(self):
        """Export current resource version to configured live versions config.
        
        Function only callable in ``rc`` environment.
        
        Raise ``DeploymentError`` if called in wrong environment.
        """
        self._check_environment('export_version', 'rc')
        versions = LiveVersionsCFG(self.config.live)
        versions.set(self.package, self.version)
        versions()
        
    @property
    def live_version(self):
        versions = LiveVersionsCFG(self.config.live)
        return versions.read_option('versions', self.package)
        
    
    def _check_environment(self, operation, env):
        if self.config.env == 'all' or self.config.env == env:
            return
        msg = "Wrong environment for '%s' operation: '%s'" % (operation, env)
        raise DeploymentError(msg)
    
    @property
    def _source(self):
        source = self.config.source(self.package)
        if source is None:
            raise KeyError, \
                  'no package %s found in [sources] section!' % self.package +\
                  ' maybe misspelled?'
        return source
    
    @property
    def connector_name(self):        
        return self._source.split(' ')[0]
    
    @property
    def connector(self):
        return self.connectors[self.connector_name](self)
    
    @property
    def package_path(self):
        return os.path.join(self.config.sources_dir, self.package)
    
    @property
    def dist_server(self):
        return self.config.distserver(self.config.package(self.package))

    @property
    def register_dist(self):
        return self.config.registerdist
    
    @property
    def version(self):
        path = os.path.join(self.package_path, 'setup.py')
        return PackageVersion(path).version
    
    @property
    def package_uri(self):
        source = self.config.source(self.package)
        return self._source.split(' ')[1].rstrip('/')