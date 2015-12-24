# dictionary mocking JIRA server for its unit test
FAKE_CACHE = {
    'ISSUE-1': {
        'components': [],
        'versions': [],
        'fixVersions': [],
        'status': 'open',
    },
    'ISSUE-2': {
        'components': [],
        'versions': [],
        'fixVersions': [],
        'status': 'closed',
    },
    'ISSUE-3': {
        'components': ['com1', 'com2'],
        'versions': [],
        'fixVersions': [],
        'status': 'open',
    },
    'ISSUE-3F': {
        'components': ['com3', 'com4'],
        'versions': [],
        'fixVersions': [],
        'status': 'open',
    },
    'ISSUE-4': {
        'components': ['com1', 'com2'],
        'versions': [],
        'fixVersions': [],
        'status': 'closed',
    },
    'ISSUE-5': {
        'components': [],
        'versions': ['1.0.0', '1.0.1'],
        'fixVersions': [],
        'status': 'open',
    },
    'ISSUE-6': {
        'components': [],
        'versions': ['1.0.0', '1.0.1'],
        'fixVersions': ['1.0.1'],
        'status': 'closed',
    },
    'ISSUE-6F': {
        'components': [],
        'versions': ['1.0.0', '1.0.1'],
        'fixVersions': ['1.0.0'],
        'status': 'closed',
    },
    'ISSUE-7': {
        'components': ['com1', 'com2'],
        'versions': ['1.0.0', '1.0.1'],
        'fixVersions': [],
        'status': 'open',
    },
    'ISSUE-7F': {
        'components': ['com1', 'com2'],
        'versions': ['1.0.0'],
        'fixVersions': [],
        'status': 'open',
    },

}

# dictionary where all important information about every test is stored
TEST_INFO = {}


def pytest_runtest_makereport(item, call):
    """
    Stores all important information about every test into TEST_INFO.
    Those information are used for a traceback.
    """
    if call.when is 'teardown':
        global TEST_INFO
        test = TEST_INFO.setdefault(item.name, {})
        if not test:
            marker = item.get_marker('jira')
            if marker:
                test['jira_markers'] = marker.args
            else:
                test['jira_markers'] = ()
            try:
                components = item.config.getini('jira_components')
                test['used components:'] = components
            except Exception:
                pass
            try:
                version = item.config.getini('jira_version')
                test['used version:'] = version
            except Exception:
                pass
            test['issue_info'] = {}
            for mark in test['jira_markers']:
                if mark in FAKE_CACHE:
                    test['issue_info'][mark] = FAKE_CACHE[mark]


def pytest_report_teststatus(report):
    """
    Modifies results of the unit test.
    If result of the test is same as expected result (specified
    by the pytest.mark.expect_*), test will PASS, if results differ
    the test will FAIL.
    """
    if report.when == 'call':
        status = 'skipped'
        if hasattr(report, "wasxfail"):
            status = 'xpassed' if report.outcome is 'failed' else 'xfailed'
            if ('expect_xfail' in report.keywords and
                    report.outcome is 'skipped'):
                del report.wasxfail
                report.outcome = 'passed'
            elif ('expect_xpass' in report.keywords and
                    report.outcome is 'failed'):
                del report.wasxfail
                report.outcome = 'passed'
            else:
                del report.wasxfail
                report.outcome = 'failed'
        else:
            status = 'passed' if report.outcome is 'passed' else 'failed'
            if ('expect_fail' in report.keywords and
                    report.outcome is 'failed'):
                report.outcome = 'passed'
            elif ('expect_pass' in report.keywords and
                    report.outcome is 'passed'):
                report.outcome = 'passed'
            elif 'expect_skip' not in report.keywords:
                report.outcome = 'failed'
        test_name = report.nodeid.split('::')[-1]
        report.longrepr = MyExceptionInfo(test_name, status)
    if 'expect_skip' in report.keywords:
        report.outcome = 'passed'


def pytest_collection_modifyitems(session, config, items):
    plug = config.pluginmanager.getplugin('jira_plugin')
    plug.issue_cache = FAKE_CACHE


class MyExceptionInfo(object):
    def __init__(self, name, status):
        self.name = name
        self.status = status
        self.expected = name.split('_')[-1]

    def addsection(self, name, content, sep="-"):
        pass

    def toterminal(self, tw):
        info = TEST_INFO[self.name]
        tw.line(self.name)
        tw.line('expected status is %s, got %s' % (self.expected, self.status))
        tw.line('--------')
        issues = info.pop('issue_info')
        tw.line('ISSUE INFO:')
        for issue in issues:
            tw.line('----')
            tw.line('name: %s' % (issue))
            for section in issues[issue]:
                tw.line(section + ": " + str(issues[issue][section]))
        tw.line('--------')
        tw.line('CONFIGURATION INFO:')
        for section in info:
            tw.line(section + ": " + str(info[section]))
