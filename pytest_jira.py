import os
import re
import sys
import ConfigParser
import pytest
import logging
from jira.client import JIRA

"""
This plugin integrates pytest with jira; allowing the tester to mark a test
with a bug id.  The test will then be skipped unless the issue status is closed
or resolved.

You must set the url either at the command line or in jira.cfg.

Author: James Laska
"""

__version__ = "0.1"
__name__ = "pytest_jira"
logger = logging.getLogger('pytest_jira')

class JiraHooks(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(self, url, username=None, password=None, verify=True):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify

        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

        # Setup basic_auth
        if self.username and self.password:
            basic_auth=(self.username, self.password)
        else:
            basic_auth=None

        # TODO - use requests REST API instead to drop a dependency
        # (https://confluence.atlassian.com/display/DOCSPRINT/The+Simplest+Possible+JIRA+REST+Examples)
        try:
            self.jira = JIRA(options=dict(server=self.url, verify=self.verify),
                         basic_auth=basic_auth, validate=True, max_retries=1)
        except Exception as ex:
            logger.error('Unable to connect to Jira: %s' % ex)
            self.jira = None

    def is_connected(self):
        return self.jira is not None
           
    def get_jira_issues(self, item):
        jira_ids = []
        # Was the jira marker used?
        if 'jira' in item.keywords:
            marker = item.keywords['jira']
            if len(marker.args) == 0:
                raise TypeError('JIRA marker requires one, or more, arguments')
            jira_ids = item.keywords['jira'].args

        # Was a jira issue referenced in the docstr?
        elif item.function.__doc__:
            issue_pattern = re.compile(self.issue_re)
            jira_ids = [m.group(0) \
                for m in issue_pattern.finditer(item.function.__doc__)]
        return jira_ids

    def is_issue_resolved(self, issue_id):
        '''
        Returns whether the provided issue ID is resolved (True|False).  Will
        cache issues to speed up subsequent calls for the same issue.
        '''
        # Access Jira issue (may be cached)
        if issue_id not in self.issue_cache:
            try:
                self.issue_cache[issue_id] = self.jira.issue(issue_id).fields.status.name.lower()
            except:
                self.issue_cache[issue_id] = 'open'

        # Skip test if issue remains unresolved
        return self.issue_cache[issue_id] in ['closed', 'resolved']

    @pytest.mark.tryfirst
    def pytest_runtest_makereport(self, item, call, __multicall__):
        '''
        Figure out how to mark JIRA test other than SKIPPED
        '''

        rep = __multicall__.execute()
        try:
            jira_ids = self.get_jira_issues(item)
        except:
            jira_ids = []

        if call.when == 'call' and jira_ids:
            for issue_id in jira_ids:
                if not self.is_issue_resolved(issue_id):
                    if call.excinfo:
                        rep.outcome = "skipped"
                    else:
                        rep.outcome = "failed"
                    rep.wasxfail = "failed"
                    break

        return rep

    def pytest_runtest_setup(self, item):
        """
        Skip test if ...
          * the provided JIRA issue is unresolved
          * AND jira_run is False
        :param item: test being run.
        """
        jira_run = True
        if 'jira' in item.keywords:
            jira_run = item.keywords['jira'].kwargs.get('run', jira_run)
        jira_ids = self.get_jira_issues(item)

        # Check all linked issues
        for issue_id in jira_ids:
            if not jira_run and not self.is_issue_resolved(issue_id):
                pytest.skip("%s/browse/%s" % (self.url, issue_id))

def pytest_addoption(parser):
    """
    Add a options section to py.test --help for jira integration.
    Parse configuration file, jira.cfg and / or the command line options
    passed.

    :param parser: Command line options.
    """
    group = parser.getgroup('JIRA integration')
    group.addoption('--jira',
                    action='store_true',
                    default=False,
                    dest='jira',
                    help='Enable JIRA integration.')

    # FIXME - Change to a credentials.yaml ?
    config = ConfigParser.ConfigParser()
    if os.path.exists('jira.cfg'):
        config.read('jira.cfg')

    try:
        verify = config.getboolean('DEFAULT', 'ssl_verification')
    except ConfigParser.NoOptionError:
        verify = True
    except ValueError:
        logger.error('Wrong argument for ssl_verification!')
        verify = True

    group.addoption('--jira-url',
                    action='store',
                    dest='jira_url',
                    default=config.get('DEFAULT', 'url'),
                    metavar='url',
                    help='JIRA url (default: %default)')
    group.addoption('--jira-user',
                    action='store',
                    dest='jira_username',
                    default=config.get('DEFAULT', 'username', None),
                    metavar='username',
                    help='JIRA username (default: %default)')
    group.addoption('--jira-password',
                    action='store',
                    dest='jira_password',
                    default=config.get('DEFAULT', 'password', None),
                    metavar='password',
                    help='JIRA password.')
    group.addoption('--jira-verify',
                    action='store',
                    dest='jira_verify',
                    default=verify,
                    metavar='verify',
                    help='Disable SSL verification to Jira'
                    )

def pytest_configure(config):
    """
    If jira is enabled, setup a session
    with jira_url.

    :param config: configuration object
    """
    config.addinivalue_line("markers",
        "jira([issue_id,...], run=True): xfail the test if the provided JIRA "
        "issue(s) remains unresolved.  When 'run' is True, the test will be "
        "executed.  If a failure occurs, the test will xfail.  When 'run' is False, the "
        "test will be skipped prior to execution.  See "
        "https://github.com/jlaska/pytest_jira"
    )
    if config.getvalue("jira") and config.getvalue('jira_url'):
        jira_plugin = JiraHooks(config.getvalue('jira_url'),
                                config.getvalue('jira_username'),
                                config.getvalue('jira_password'),
                                config.getvalue('jira_verify'))
        if jira_plugin.is_connected():
            # if connection to jira fails, plugin won't be loaded
            ok = config.pluginmanager.register(jira_plugin)
            assert ok


