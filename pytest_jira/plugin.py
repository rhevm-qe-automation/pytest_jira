"""
This plugin integrates pytest with jira; allowing the tester to mark a test
with a bug id.  The test will then be skipped unless the issue status matches
at least one of resolved statuses.

You must set the url either at the command line or in jira.cfg.

Author: James Laska
"""

import os

import six

from pytest_jira.hooks import JiraHooks
from pytest_jira.markbroker import JiraMarkerReporter
from pytest_jira.connection import JiraSiteConnection
# Let the pytest to discover fixtures
from pytest_jira.fixtures import jira_issue  # noqa

DEFAULT_RESOLVE_STATUSES = ('closed', 'resolved')
DEFAULT_RUN_TEST_CASE = True


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
            config._jira = jira_plugin
            ok = config.pluginmanager.register(jira_plugin, "jira_plugin")
            assert ok
