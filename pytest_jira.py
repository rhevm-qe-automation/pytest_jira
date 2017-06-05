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

PYTEST_MAJOR_VERSION = int(pytest.__version__.split(".")[0])
DEFAULT_RESOLVE_STATUSES = ('closed', 'resolved')
DEFAULT_RUN_TEST_CASE = True


class JiraHooks(object):
    def __init__(
            self,
            connection,
            marker,
            version=None,
            components=None,
            resolved_statuses=None,
            run_test_case=DEFAULT_RUN_TEST_CASE,
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

        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

    def is_issue_resolved(self, issue_id):
        """
        Returns whether the provided issue ID is resolved (True|False).  Will
        cache issues to speed up subsequent calls for the same issue.
        """
        # Access Jira issue (may be cached)
        if issue_id not in self.issue_cache:
            try:
                self.issue_cache[issue_id] = self.conn.get_issue(issue_id)
            except Exception:
                self.issue_cache[issue_id] = self.mark.get_default(issue_id)

        # Skip test if issue remains unresolved
        if self.issue_cache[issue_id] is None:
            return True

        if self.issue_cache[issue_id]['status'] in self.resolved_statuses:
            return self.fixed_in_version(issue_id)
        else:
            return not self.is_affected(issue_id)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        """
        Figure out how to mark JIRA test other than SKIPPED
        """

        outcome = yield
        rep = outcome.get_result()
        try:
            jira_ids = self.mark.get_jira_issues(item)
        except Exception:
            jira_ids = []

        if call.when == 'call' and jira_ids:
            for issue_id in jira_ids:
                if not self.is_issue_resolved(issue_id):
                    if call.excinfo:
                        rep.outcome = "skipped"
                    elif PYTEST_MAJOR_VERSION < 3:
                        rep.outcome = "failed"
                    rep.wasxfail = "failed"
                    break

    def pytest_runtest_setup(self, item):
        """
        Skip test if ...
          * the provided JIRA issue is unresolved
          * AND jira_run is False
        :param item: test being run.
        """
        jira_run = self.run_test_case
        if 'jira' in item.keywords:
            jira_run = item.keywords['jira'].kwargs.get('run', jira_run)
        jira_ids = self.mark.get_jira_issues(item)

        # Check all linked issues
        for issue_id in jira_ids:
            if not jira_run and not self.is_issue_resolved(issue_id):
                pytest.skip("%s/browse/%s" % (self.conn.get_url(), issue_id))

    def fixed_in_version(self, issue_id):
        """
        Return True if:
            jira_product_version was not specified
            OR issue was fixed for jira_product_version
        else return False
        """
        if not self.version:
            return True
        affected = self.issue_cache[issue_id].get('versions', set())
        fixed = self.issue_cache[issue_id].get('fixed_versions', set())
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
        affected = self.issue_cache[issue_id].get('versions', set())
        if not self.version or not affected:
            return True
        return self.version in affected

    def _affected_components(self, issue_id):
        affected = self.issue_cache[issue_id].get('components', set())
        if not self.components or not affected:
            return True
        return bool(self.components.intersection(affected))


class JiraSiteConnection(object):
    def __init__(
            self, url,
            username=None,
            password=None,
            verify=True,
    ):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify

        # Setup basic_auth
        if self.username and self.password:
            self.basic_auth = (self.username, self.password)
        else:
            self.basic_auth = None

    def _jira_request(self, url, method='get', **kwargs):
        if 'verify' not in kwargs:
            kwargs['verify'] = self.verify
        if self.basic_auth:
            return requests.request(
                method, url, auth=self.basic_auth, **kwargs
            )
        else:
            return requests.request(method, url, **kwargs)

    def check_connection(self):
        # This URL work for both anonymous and logged in users
        auth_url = '{url}/rest/api/2/mypermissions'.format(url=self.url)
        r = self._jira_request(auth_url)
        # Handle connection errors
        r.raise_for_status()

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
            return True

    def is_connected(self):
        return self.check_connection()

    def get_issue(self, issue_id):
        issue_url = '{url}/rest/api/2/issue/{issue_id}'.format(
            url=self.url, issue_id=issue_id
        )
        issue = self._jira_request(issue_url).json()
        field = issue['fields']
        return {
            'components': set(c['name'] for c in field['components']),
            'versions': set(v['name'] for v in field['versions']),
            'fixed_versions': set(v['name'] for v in field['fixVersions']),
            'status': field['status']['name'].lower(),
        }

    def get_url(self):
        return self.url


class JiraMarkerReporter(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(self, strategy, docs, patern):
        self.issue_pattern = re.compile(patern or self.issue_re)
        self.docs = docs
        self.strategy = strategy.lower()

    def get_jira_issues(self, item):
        jira_ids = []
        # Was the jira marker used?
        if 'jira' in item.keywords:
            marker = item.keywords['jira']
            if len(marker.args) == 0:
                raise TypeError('JIRA marker requires one, or more, arguments')
            jira_ids.extend(item.keywords['jira'].args)

        # Was a jira issue referenced in the docstr?
        if self.docs and item.function.__doc__:
            jira_ids.extend(
                [
                    m.group(0)
                    for m in self.issue_pattern.finditer(item.function.__doc__)
                ]
            )

        # Filter valid issues, and return unique issues
        for jid in set(jira_ids):
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
        resolved_statuses = (
            s.strip().lower() for s in resolved_statuses.split(',')
            if s.strip()
        )
    if not resolved_statuses:
        resolved_statuses = DEFAULT_RESOLVE_STATUSES

    if config.getvalue('jira') and config.getvalue('jira_url'):
        jira_connection = JiraSiteConnection(
            config.getvalue('jira_url'),
            config.getvalue('jira_username'),
            config.getvalue('jira_password'),
            config.getvalue('jira_verify'),
        )
        jira_marker = JiraMarkerReporter(
            config.getvalue('jira_marker_strategy'),
            config.getvalue('jira_docs'),
            config.getvalue('jira_regex'),
        )
        if jira_connection.is_connected():
            # if connection to jira fails, plugin won't be loaded
            jira_plugin = JiraHooks(
                jira_connection,
                jira_marker,
                config.getvalue('jira_product_version'),
                components,
                resolved_statuses,
                config.getvalue('jira_run_test_case'),
            )
            ok = config.pluginmanager.register(jira_plugin, "jira_plugin")
            assert ok
