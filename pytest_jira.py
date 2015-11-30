import re
import pytest
import logging
import ast
import jira
from jira import JIRA

"""
This plugin integrates pytest with jira; allowing the tester to mark a test
with a bug id.  The test will then be skipped unless the issue status is closed
or resolved.

You must set the url either at the command line or in any pytest INI file.

Author: James Laska
"""

__version__ = "0.1"
__name__ = "pytest_jira"
logger = logging.getLogger('pytest_jira')

class JiraHooks(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(
            self, url,
            username=None, password=None,
            verify=True, components=None,
            version=None
            ):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify
        self.components = components
        self.version = version

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
                self.issue_cache[issue_id] = self.jira.issue(issue_id).fields
            except jira.JIRAError:
                logger.warning('Issue ID not found: %s' % issue_id)
            except Exception as ex:
                logger.warning('Unexpected error %s' % ex)
        if issue_id not in self.issue_cache:
            return True
        # Skip test if issue remains unresolved
        return self.issue_cache[issue_id].status.name.lower() in ['closed', 'resolved']

    def is_component_affected(self, issue_id):
        '''
        Return whether used components is affected. If no components specified
        in Jira, it assumes it is affected.
        (True|False)
        '''
        if issue_id not in self.issue_cache:
            return False
        if not self.components:
            return True
        components = [c.name for c in self.issue_cache[issue_id].components]
        if not components:
            # assumption: all components are affected
            return True
        else:
            for c in self.components:
                if c in components:
                    return True
        return False

    def is_version_affected(self, issue_id):
        '''
        Return whether tested version is affected. If no version specified
        in Jira, it assumes all versions are affected.
        (True|False)
        '''
        if not self.version:
            return True
        if issue_id not in self.issue_cache:
            return True
        versions = [v.name for v in self.issue_cache[issue_id].versions]
        if not versions:
            # assumption: all versions are affected
            return True
        elif self.version in versions:
            return True
        return False

    def is_fixed_in_version(self, issue_id):
        '''
        Returns whether resolved issue was fixed in specific version.
        (True|False)
        '''
        if issue_id not in self.issue_cache:
            return True
        versions = [v.name for v in self.issue_cache[issue_id].versions]
        fixed = [v.name for v in self.issue_cache[issue_id].fixVersions]
        if not fixed:
            # assumption: fixed for all versions
            return True
        if not versions:
            # assumption: all versions are affected
            if self.version in fixed:
                return True
            return False
        affected = [v for v in versions if v not in fixed]
        if self.version in affected:
            return False
        return True

    def mark_as_skipped(self, call, rep):
        if call.excinfo:
            rep.outcome = "skipped"
        else:
            rep.outcome = "failed"
        rep.wasxfail = "failed"

    @pytest.mark.tryfirst
    def pytest_runtest_makereport(self, item, call, __multicall__):
        '''
        Figure out how to mark JIRA test other than SKIPPED
        '''

        rep = __multicall__.execute()
        try:
            jira_ids = self.get_jira_issues(item)
        except Exception:
            jira_ids = []

        if call.when == 'call' and jira_ids:
            for issue_id in jira_ids:
                if self.is_issue_resolved(issue_id):
                    # resolved
                    if not self.is_fixed_in_version(issue_id):
                        # resolved but not fixed for this version
                        self.mark_as_skipped(call, rep)
                    break
                else:
                    # not resolved
                    if self.is_version_affected(issue_id) and \
                        self.is_component_affected(issue_id):
                        self.mark_as_skipped(call, rep)
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
    Parse configuration file and / or the command line options
    passed.

    :param parser: Command line options.
    """
    # INI file options
    parser.addini(
        'jira_url',
        'JIRA url (default: %s)' % None,
        default=None
        )
    parser.addini(
        'jira_username',
        'JIRA username (default: %s)' % None,
        default=None
        )
    parser.addini(
        'jira_password',
        'JIRA password.',
        default=None
        )
    parser.addini(
        'jira_ssl_verification',
        'SSL verification (default: %s)' % True,
        default='True'
        )
    parser.addini(
        'jira_version',
        'Used version.',
        default=None
        )
    parser.addini(
        'jira_components',
        'Used components.',
        type='args',
        default=None
        )
    # command line options
    parser.addoption(
        '--jira',
        action='store_true',
        default=False,
        dest='jira',
        help='Enable JIRA integration.'
        )
    parser.addoption(
        '--jira-url',
        action='store',
        dest='jira_url',
        default=None,
        metavar='jira_url',
        help='JIRA url (default: %s)' % None
        )
    parser.addoption(
        '--jira-user',
        action='store',
        dest='jira_username',
        default=None,
        metavar='jira_username',
        help='JIRA username (default: %s)' % None
        )
    parser.addoption(
        '--jira-password',
        action='store',
        dest='jira_password',
        default=None,
        metavar='jira_password',
        help='JIRA password.'
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
    verify = ast.literal_eval(config.getini('jira_ssl_verification'))
    if config.getoption('jira'):
        jira_plugin = JiraHooks(
            config.getoption('jira_url') or config.getini('jira_url'),
            config.getoption('jira_username') or config.getini('jira_username'),
            config.getoption('jira_password') or config.getini('jira_password'),
            verify,
            config.getini('jira_components'),
            config.getini('jira_version')
            )
        if jira_plugin.is_connected():
            # if connection to jira fails, plugin won't be loaded
            ok = config.pluginmanager.register(jira_plugin)
            assert ok
