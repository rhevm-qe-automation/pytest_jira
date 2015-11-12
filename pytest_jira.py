import re
import pytest
import logging
import ast
from jira.client import JIRA

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
        self.verify = verify
        self.components = components
        self.version = version

        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

        # Setup basic_auth
        if username and password:
            self.basic_auth=(username, password)
        else:
            self.basic_auth=None

        # TODO - use requests REST API instead to drop a dependency
        # (https://confluence.atlassian.com/display/DOCSPRINT/The+Simplest+Possible+JIRA+REST+Examples)
        try:
            self.jira = JIRA(options=dict(server=self.url, verify=self.verify),
                         basic_auth=self.basic_auth, validate=True, max_retries=1)
        except Exception as ex:
            logger.error('Unable to connect to Jira: %s', ex)
            self.jira = None

    def is_connected(self):
        return self.jira is not None
           
    def get_jira_issues(self, item):
        issue_pattern = re.compile(self.issue_re)
        jira_ids = []
        # Was the jira marker used?
        if 'jira' in item.keywords:
            marker = item.keywords['jira']
            if len(marker.args) == 0:
                raise TypeError('JIRA marker requires one, or more, arguments')
            jira_ids.extend(item.keywords['jira'].args)

        # Was a jira issue referenced in the docstr?
        if item.function.__doc__:
            jira_ids.extend(
                [
                    m.group(0)
                    for m in issue_pattern.finditer(item.function.__doc__)
                ]
            )

        # Filter valid issues, and return unique issues
        return [
            jid for jid in set(jira_ids) if issue_pattern.match(jid)
        ]

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
        if jira_plugin.jira:
            # if connection to jira fails, plugin won't be loaded
            ok = config.pluginmanager.register(jira_plugin)
            assert ok
