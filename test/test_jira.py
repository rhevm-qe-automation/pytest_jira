import pytest


failed = pytest.mark.expect_fail
passed = pytest.mark.expect_pass
xfailed = pytest.mark.expect_xfail
xpassed = pytest.mark.expect_xpass
skipped = pytest.mark.expect_skip


@pytest.mark.skip_selenium
@pytest.mark.nondestructive
class Test_Pytest_JIRA(object):
    """
    Following tests cover the functionality of jira plugin.
    JIRA server is mocked by dictionary FAKE_CACHE in conftest.py,
    where all used issues and their information are stored.
    Marks passed|failed|xpassed|xfailed|skipped are expected
    results of those tests.

    Results of this unit test are modified in conftest.py
    If result of the test is same as expected result, test will PASS,
    if results differ the test will FAIL.

    This allows us to check plugin's functionality faster and the
    result is easier to read.
    """

    @passed
    def test_no_jira_marker_passed(self):
        assert True

    @failed
    def test_no_jira_marker_failed(self):
        assert False

    @pytest.mark.jira
    @passed
    def test_jira_marker_no_args_passed(self):
        assert True

    @pytest.mark.jira
    @failed
    def test_jira_marker_no_args_failed(self):
        assert False

    @pytest.mark.jira('there is no issue here')
    @passed
    def test_jira_marker_bad_args_passed(self):
        assert True

    @pytest.mark.jira('there is no issue here')
    @failed
    def test_jira_marker_bad_args_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-2')
    @passed
    def test_closed_no_comp_no_version_passed(self):
        assert True

    @pytest.mark.jira('ISSUE-2')
    @failed
    def test_closed_no_comp_no_version_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-1')
    @xpassed
    def test_open_no_comp_no_version_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-1')
    @xfailed
    def test_open_no_comp_no_version_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-3')
    @xpassed
    def test_open_match_comp_no_version_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-3')
    @xfailed
    def test_open_match_comp_no_version_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-3F')
    @passed
    def test_open_no_match_comp_no_version_passed(self):
        assert True

    @pytest.mark.jira('ISSUE-3F')
    @failed
    def test_open_no_match_comp_no_version_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-4')
    @passed
    def test_closed_match_comp_no_version_passed(self):
        assert True

    @pytest.mark.jira('ISSUE-4')
    @failed
    def test_closed_match_comp_no_version_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-5')
    @xpassed
    def test_open_no_comp_match_version_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-5')
    @xfailed
    def test_open_no_comp_match_version_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-6')
    @passed
    def test_closed_no_comp_match_version_passed(self):
        assert True

    @pytest.mark.jira('ISSUE-6')
    @failed
    def test_closed_no_comp_match_version_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-6F')
    @xpassed
    def test_closed_for_diff_version_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-6F')
    @xfailed
    def test_closed_for_diff_version_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-7')
    @xpassed
    def test_open_match_comp_match_version_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-7')
    @xfailed
    def test_open_match_comp_match_version_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-7F')
    @passed
    def test_open_for_diff_version_passed(self):
        assert True

    @pytest.mark.jira('ISSUE-7F')
    @failed
    def test_open_for_diff_version_failed(self):
        assert False

    @pytest.mark.jira('ISSUE-4', 'ISSUE-1')
    @xpassed
    def test_multiple_issues_one_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-1', 'ISSUE-4')
    @xpassed
    def test_multiple_issues_two_xpassed(self):
        assert True

    @pytest.mark.jira('ISSUE-4', 'ISSUE-1')
    @xfailed
    def test_multiple_issues_one_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-1', 'ISSUE-4')
    @xfailed
    def test_multiple_issues_two_xfailed(self):
        assert False

    @pytest.mark.jira('ISSUE-7', run=False)
    @skipped
    def test_run_false_open_skipped(self):
        assert True

    @pytest.mark.jira('ISSUE-6F', run=False)
    @skipped
    def test_run_false_closed_for_diff_version_skipped(self):
        assert False

    @pytest.mark.jira('ISSUE-3F', run=False)
    @failed
    def test_run_false_resolved_failed(self):
        assert False
