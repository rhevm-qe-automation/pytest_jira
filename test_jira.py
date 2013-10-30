import pytest
import os
import xmlrpclib

RESOLVED_ISSUE = 'ORG-1412'
UNRESOLVED_ISSUE = 'ORG-1382'

@pytest.mark.skip_selenium
@pytest.mark.nondestructive
class Test_Pytest_JIRA_Marker(object):

    @pytest.mark.xfail(reason='Expected xfail due to bad marker')
    @pytest.mark.jira
    def test_jira_marker_no_args(self):
        assert True

    @pytest.mark.xfail(reason='Expected xfail due to bad marker')
    @pytest.mark.jira('there is no issue here')
    def test_jira_marker_bad_args(self):
        assert True

    @pytest.mark.xfail(reason='Expected xfail due to bad marker')
    @pytest.mark.jira(None)
    def test_jira_marker_bad_args2(self):
        assert True

    @pytest.mark.jira(UNRESOLVED_ISSUE, run=False)
    def test_jira_marker_no_run(self):
        '''Expected skip due to run=False'''
        assert False

    @pytest.mark.jira(UNRESOLVED_ISSUE, run=True)
    def test_open_jira_marker_pass(self):
        '''Expected skip due to unresolved JIRA'''
        assert True

    def test_open_jira_docstr_pass(self):
        '''Expected skip due to unresolved JIRA Issue %s'''
        assert True
    test_open_jira_docstr_pass.__doc__ %= UNRESOLVED_ISSUE

    @pytest.mark.jira(UNRESOLVED_ISSUE, run=True)
    def test_open_jira_marker_fail(self):
        '''Expected skip due to unresolved JIRA'''
        assert False

    def test_open_jira_docstr_fail(self):
        '''Expected skip due to unresolved JIRA Issue %s'''
        assert False
    test_open_jira_docstr_fail.__doc__ %= UNRESOLVED_ISSUE

    @pytest.mark.jira(RESOLVED_ISSUE, run=True)
    def test_closed_jira_marker_pass(self):
        '''Expected PASS due to resolved JIRA Issue'''
        assert True

    def test_closed_jira_docstr_pass(self):
        '''Expected PASS due to resolved JIRA Issue %s'''
        assert True
    test_closed_jira_docstr_pass.__doc__ %= RESOLVED_ISSUE

    @pytest.mark.xfail(reason='Expected xfail due to resolved JIRA issue')
    @pytest.mark.jira(RESOLVED_ISSUE, run=True)
    def test_closed_jira_marker_fail(self):
        assert False

    @pytest.mark.xfail(reason='Expected xfail due to resolved JIRA issue')
    def test_closed_jira_docstr_fail(self):
        '''Expected xfail due to resolved JIRA Issue %s'''
        assert False
    test_closed_jira_docstr_fail.__doc__ %= RESOLVED_ISSUE

    def test_pass_without_jira(self):
        assert True

    @pytest.mark.xfail(reason='Expected xfail due to normal test failure')
    def test_fail_without_jira_marker(self):
        assert False

    @pytest.mark.xfail(reason='Expected xfail due to normal test failure')
    def test_fail_without_jira_docstr(self):
        '''docstring with no jira issue'''
        assert False
