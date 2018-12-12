"""
This plugin integrates pytest with jira; allowing the tester to mark a test
with a bug id.  The test will then be skipped unless the issue status matches
at least one of resolved statuses.

You must set the url either at the command line or in jira.cfg.

Author: James Laska
"""

import os
import re
import sys

import pytest
import requests
import six
from distutils.version import LooseVersion

DEFAULT_RESOLVE_STATUSES = 'closed', 'resolved'
DEFAULT_RUN_TEST_CASE = True
CONNECTION_SKIP_MESSAGE = 'Jira connection issue, skipping test: %s'
CONNECTION_ERROR_FLAG_NAME = '--jira-connection-error-strategy'
STRICT = 'strict'
SKIP = 'skip'
IGNORE = 'ignore'
PLUGIN_NAME = "jira_plugin"
PASSWORD_ENV_VAR = 'PYTEST_JIRA_PASSWORD'


class JiraHooks(object):
    def __init__(
            self,
            connection,
            marker,
            version=None,
            components=None,
            resolved_statuses=None,
            run_test_case=DEFAULT_RUN_TEST_CASE,
            strict_xfail=False,
            connection_error_strategy=None
    ):
        self.conn = connection
        self.mark = marker
        self.components = set(components) if components else None
        self.version = version
        if resolved_statuses:
            self.resolved_statuses = resolved_statuses
        else:
            self.resolved_statuses = DEFAULT_RESOLVE_STATUSES
        self.run_test_case = run_test_case
        self.connection_error_strategy = connection_error_strategy
        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

        self.strict_xfail = strict_xfail

    def is_issue_resolved(self, issue_id):
        """
        Returns whether the provided issue ID is resolved (True|False).  Will
        cache issues to speed up subsequent calls for the same issue.
        """
        # Access Jira issue (may be cached)
        if issue_id not in self.issue_cache:
            try:
                self.issue_cache[issue_id] = self.conn.get_issue(issue_id)
            except requests.RequestException as e:
                if not hasattr(e.response, 'status_code') \
                        or not e.response.status_code == 404:
                    raise
                self.issue_cache[issue_id] = self.mark.get_default(issue_id)

        # Skip test if issue remains unresolved
        if self.issue_cache[issue_id] is None:
            return True

        if self.issue_cache[issue_id]['status'] in self.resolved_statuses:
            return self.fixed_in_version(issue_id)
        else:
            return not self.is_affected(issue_id)

    def get_marker(self, item):
        if LooseVersion(pytest.__version__) >= LooseVersion("4.0.0"):
            return item.get_closest_marker("jira")
        else:
            return item.keywords.get("jira")

    def pytest_collection_modifyitems(self, config, items):
        for item in items:
            try:
                jira_ids = self.mark.get_jira_issues(item)
            except Exception as exc:
                pytest.exit(exc)

            jira_run = self.run_test_case

            marker = self.get_marker(item)
            if marker:
                jira_run = marker.kwargs.get('run', jira_run)

            for issue_id, skipif in jira_ids:
                try:
                    if not self.is_issue_resolved(issue_id):
                        if callable(skipif):
                            if not skipif(self.issue_cache[issue_id]):
                                continue
                        else:
                            if not skipif:
                                continue
                        reason = "%s/browse/%s" % \
                                 (self.conn.get_url(), issue_id)
                        if jira_run:
                            item.add_marker(pytest.mark.xfail(reason=reason))
                        else:
                            item.add_marker(pytest.mark.skip(reason=reason))
                except requests.RequestException as e:
                    if self.connection_error_strategy == STRICT:
                        raise
                    elif self.connection_error_strategy == SKIP:
                        item.add_marker(pytest.mark.skip(
                            reason=CONNECTION_SKIP_MESSAGE % e)
                        )
                    else:
                        return

    def fixed_in_version(self, issue_id):
        """
        Return True if:
            jira_product_version was not specified
            OR issue was fixed for jira_product_version
        else return False
        """
        if not self.version:
            return True
        affected = self.issue_cache[issue_id].get('versions')
        fixed = self.issue_cache[issue_id].get('fixed_versions')
        return self.version not in (affected - fixed)

    def is_affected(self, issue_id):
        """
        Return True if:
            at least one component affected (or not specified)
            version is affected (or not specified)
        else return False
        """
        return (
            self._affected_version(issue_id) and
            self._affected_components(issue_id)
        )

    def _affected_version(self, issue_id):
        affected = self.issue_cache[issue_id].get('versions')
        if not self.version or not affected:
            return True
        return self.version in affected

    def _affected_components(self, issue_id):
        affected = self.issue_cache[issue_id].get('components')
        if not self.components or not affected:
            return True
        return bool(self.components.intersection(affected))


class JiraSiteConnection(object):
    def __init__(
            self, url,
            username=None,
            password=None,
            verify=True
    ):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify

        self.is_connected = False

        # Setup basic_auth
        if self.username and self.password:
            self.basic_auth = (self.username, self.password)
        else:
            self.basic_auth = None

    def _jira_request(self, url, method='get', **kwargs):
        if 'verify' not in kwargs:
            kwargs['verify'] = self.verify
        if self.basic_auth:
            rsp = requests.request(
                method, url, auth=self.basic_auth, **kwargs
            )
        else:
            rsp = requests.request(method, url, **kwargs)
        rsp.raise_for_status()
        return rsp

    def check_connection(self):
        # This URL work for both anonymous and logged in users
        auth_url = '{url}/rest/api/2/mypermissions'.format(url=self.url)
        r = self._jira_request(auth_url)

        # For some reason in case on invalid credentials the status is still
        # 200 but the body is empty
        if not r.text:
            raise Exception(
                'Could not connect to {url}. Invalid credentials'.format(
                    url=self.url)
            )

        # If the user does not have sufficient permissions to browse issues
        elif not r.json()['permissions']['BROWSE']['havePermission']:
            raise Exception('Current user does not have sufficient permissions'
                            ' to view issue')
        else:
            self.is_connected = True
            return True

    def get_issue(self, issue_id):
        if not self.is_connected:
            self.check_connection()
        issue_url = '{url}/rest/api/2/issue/{issue_id}'.format(
            url=self.url, issue_id=issue_id
        )
        issue = self._jira_request(issue_url).json()
        field = issue['fields']
        return {
            'components': set(
                c['name'] for c in field.get('components', set())
            ),
            'versions': set(
                v['name'] for v in field.get('versions', set())
            ),
            'fixed_versions': set(
                v['name'] for v in field.get('fixVersions', set())
            ),
            'status': field['status']['name'].lower(),
        }

    def get_url(self):
        return self.url


class JiraMarkerReporter(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(self, strategy, docs, pattern):
        self.issue_pattern = re.compile(pattern or self.issue_re)
        self.docs = docs
        self.strategy = strategy.lower()

    def _get_marks(self, item):
        marks = []
        if LooseVersion(pytest.__version__) >= LooseVersion("4.0.0"):
            for mark in item.iter_markers("jira"):
                marks.append(mark)
        else:
            if 'jira' in item.keywords:
                marker = item.keywords['jira']
                # process markers independently
                if not isinstance(marker, (list, tuple)):
                    marker = [marker]
                for mark in marker:
                    marks.append(mark)
        return marks

    def get_jira_issues(self, item):
        jira_ids = []
        for mark in self._get_marks(item):
            skip_if = mark.kwargs.get('skipif', True)

            if len(mark.args) == 0:
                raise TypeError(
                    'JIRA marker requires one, or more, arguments')

            for arg in mark.args:
                jira_ids.append((arg, skip_if))

        # Was a jira issue referenced in the docstr?
        if self.docs and item.function.__doc__:
            jira_ids.extend(
                [
                    (m.group(0), True)
                    for m in self.issue_pattern.finditer(item.function.__doc__)
                ]
            )

        # Filter valid issues, and return unique issues
        for jid, _ in set(jira_ids):
            if not self.issue_pattern.match(jid):
                raise ValueError(
                    'JIRA marker argument `%s` does not match pattern' % jid
                )
        return list(
            set(jira_ids)
        )

    def get_default(self, jid):
        if self.strategy == 'open':
            return {'status': 'open'}
        if self.strategy == 'strict':
            raise ValueError(
                'JIRA marker argument `%s` was not found' % jid
            )
        if self.strategy == 'warn':
            sys.stderr.write(
                'JIRA marker argument `%s` was not found' % jid
            )
        return None


def _get_value(config, section, name, default=None):
    if config.has_option(section, name):
        return config.get(section, name)
    return default


def _get_bool(config, section, name, default=False):
    if config.has_option(section, name):
        return config.getboolean(section, name)
    return default


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
    config = six.moves.configparser.ConfigParser()
    config.read([
        '/etc/jira.cfg',
        os.path.expanduser('~/jira.cfg'),
        'jira.cfg',
    ])

    group.addoption('--jira-url',
                    action='store',
                    dest='jira_url',
                    default=_get_value(config, 'DEFAULT', 'url'),
                    metavar='url',
                    help='JIRA url (default: %(default)s)')
    group.addoption('--jira-user',
                    action='store',
                    dest='jira_username',
                    default=_get_value(config, 'DEFAULT', 'username'),
                    metavar='username',
                    help='JIRA username (default: %(default)s)')
    group.addoption('--jira-password',
                    action='store',
                    dest='jira_password',
                    default=_get_value(config, 'DEFAULT', 'password'),
                    metavar='password',
                    help='JIRA password.')
    group.addoption('--jira-no-ssl-verify',
                    action='store_false',
                    dest='jira_verify',
                    default=_get_bool(
                        config, 'DEFAULT', 'ssl_verification', True,
                    ),
                    help='Disable SSL verification to Jira',
                    )
    group.addoption('--jira-components',
                    action='store',
                    nargs='+',
                    dest='jira_components',
                    default=_get_value(config, 'DEFAULT', 'components', ''),
                    help='Used components'
                    )
    group.addoption('--jira-product-version',
                    action='store',
                    dest='jira_product_version',
                    default=_get_value(config, 'DEFAULT', 'version'),
                    help='Used version'
                    )
    group.addoption('--jira-marker-strategy',
                    action='store',
                    dest='jira_marker_strategy',
                    default=_get_value(
                        config, 'DEFAULT', 'marker_strategy', 'open'
                    ),
                    choices=['open', 'strict', 'ignore', 'warn'],
                    help="""Action if issue ID was not found
                    open - issue is considered as open (default)
                    strict - raise an exception
                    ignore - issue id is ignored
                    warn - write error message and ignore
                    """,
                    )
    group.addoption('--jira-disable-docs-search',
                    action='store_false',
                    dest='jira_docs',
                    default=_get_bool(config, 'DEFAULT', 'docs_search', True),
                    help='Issue ID in doc strings will be ignored'
                    )
    group.addoption('--jira-issue-regex',
                    action='store',
                    dest='jira_regex',
                    default=_get_value(config, 'DEFAULT', 'issue_regex'),
                    help='Replace default `[A-Z]+-[0-9]+` regular expression'
                    )
    group.addoption('--jira-resolved-statuses',
                    action='store',
                    dest='jira_resolved_statuses',
                    default=_get_value(
                        config, 'DEFAULT', 'resolved_statuses',
                        ','.join(DEFAULT_RESOLVE_STATUSES),
                    ),
                    help='Comma separated list of resolved statuses (closed, '
                         'resolved)'
                    )
    group.addoption('--jira-do-not-run-test-case',
                    action='store_false',
                    dest='jira_run_test_case',
                    default=_get_bool(
                        config, 'DEFAULT', 'run_test_case',
                        DEFAULT_RUN_TEST_CASE,
                    ),
                    help='If set and test is marked by Jira plugin, such '
                         'test case is not executed.'
                    )
    group.addoption(CONNECTION_ERROR_FLAG_NAME,
                    action='store',
                    dest='jira_connection_error_strategy',
                    default=_get_value(
                        config, 'DEFAULT', 'error_strategy', 'strict'
                    ),
                    choices=[STRICT, SKIP, IGNORE],
                    help="""Action if there is a connection issue
                    strict - raise an exception
                    ignore - marker is ignored
                    skip - skip any test that has a marker
                    """
                    )


def pytest_configure(config):
    """
    If jira is enabled, setup a session
    with jira_url.

    :param config: configuration object
    """
    config.addinivalue_line(
        "markers",
        "jira([issue_id,...], run=True): xfail the test if the provided JIRA "
        "issue(s) remains unresolved.  When 'run' is True, the test will be "
        "executed.  If a failure occurs, the test will xfail. "
        "When 'run' is False, the test will be skipped prior to execution. "
        "See https://github.com/rhevm-qe-automation/pytest_jira"
    )
    components = config.getvalue('jira_components')
    if isinstance(components, six.string_types):
        components = [c for c in components.split(',') if c]

    resolved_statuses = config.getvalue('jira_resolved_statuses')
    if isinstance(resolved_statuses, six.string_types):
        resolved_statuses = [
            s.strip().lower() for s in resolved_statuses.split(',')
            if s.strip()
        ]
    if not resolved_statuses:
        resolved_statuses = list(DEFAULT_RESOLVE_STATUSES)

    if config.getvalue('jira') and config.getvalue('jira_url'):
        jira_connection = JiraSiteConnection(
            config.getvalue('jira_url'),
            config.getvalue('jira_username'),
            os.getenv(PASSWORD_ENV_VAR) or config.getvalue('jira_password'),
            config.getvalue('jira_verify')
        )
        jira_marker = JiraMarkerReporter(
            config.getvalue('jira_marker_strategy'),
            config.getvalue('jira_docs'),
            config.getvalue('jira_regex')
        )

        jira_plugin = JiraHooks(
            jira_connection,
            jira_marker,
            config.getvalue('jira_product_version'),
            components,
            resolved_statuses,
            config.getvalue('jira_run_test_case'),
            config.getini("xfail_strict"),
            config.getvalue('jira_connection_error_strategy')
        )
        ok = config.pluginmanager.register(jira_plugin, PLUGIN_NAME)
        assert ok


@pytest.fixture
def jira_issue(request):
    """
    Returns a bool representing the state of the issue, or None if no
    connection could be made. See
    https://github.com/rhevm-qe-automation/pytest_jira#fixture-usage
    for more details
    """

    def wrapper_jira_issue(issue_id):
        jira_plugin = request.config.pluginmanager.getplugin(PLUGIN_NAME)
        if jira_plugin:
            try:
                return not jira_plugin.is_issue_resolved(issue_id)
            except requests.RequestException as e:
                strategy = request.config.getoption(CONNECTION_ERROR_FLAG_NAME)
                if strategy == SKIP:
                    pytest.skip(CONNECTION_SKIP_MESSAGE % e)
                elif strategy == STRICT:
                    raise

    return wrapper_jira_issue
