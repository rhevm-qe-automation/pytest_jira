import os
import re
from packaging.version import Version

import pytest

PUBLIC_JIRA_SERVER = "https://issues.jboss.org"

SKIP_REASON_UNAUTHORIZED = """
Current public jira server doesn't allow anonymous anymore
"""

CONFTEST = """
import pytest


FAKE_ISSUES = {
    "ORG-1412": {"status": "closed"},
    "ORG-1382": {"status": "open"},
    "ORG-1510": {
        "components": set(["com1", "com2"]),
        "versions": set(),
        "fixed_versions": set(),
        "status": "open",
    },
    "ORG-1511": {
        "components": set(["com1", "com2"]),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixVersions": set(),
        "status": "open",
    },
    "ORG-1512": {
        "components": set(),
        "versions": set(),
        "fixed_versions": set(),
        "status": "custom-status",
    },
    "ORG-1501": {
        "components": set(),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
    },
    "ORG-1513": {
        "components": set(['component1', 'component2']),
        "versions": set(),
        "fixed_versions": set(),
        "status": "custom-status",
    },
    "ORG-1514": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
    },
    "ORG-1515": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
        "resolution": "won't fix"
    },
    "ORG-1516": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
        "resolution": "done"
    },
}


@pytest.mark.tryfirst
def pytest_collection_modifyitems(session, config, items):
    plug = config.pluginmanager.getplugin("jira_plugin")
    assert plug is not None
    plug.issue_cache.update(FAKE_ISSUES)
"""

PLUGIN_ARGS = (
    '--jira',
    '--jira-url', PUBLIC_JIRA_SERVER,
)


def assert_outcomes(
        result, passed, skipped, failed, error=0, xpassed=0, xfailed=0
):
    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == passed
    assert outcomes.get("skipped", 0) == skipped
    assert outcomes.get("failed", 0) == failed
    assert outcomes.get("error", 0) == error
    assert outcomes.get("xpassed", 0) == xpassed
    assert outcomes.get("xfailed", 0) == xfailed


def test_jira_plugin_disabled(testdir):
    testdir.makepyfile("""
        import pytest
        @pytest.mark.jira("ORG-1382", run=True)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest()
    assert_outcomes(result, 1, 0, 0)


def test_jira_marker_no_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest
        @pytest.mark.jira
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    text = 'JIRA marker requires one, or more, arguments'
    assert text in result.stdout.str()


def test_jira_marker_bad_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("there is no issue here")
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    text = ('JIRA marker argument `there is no issue here` '
            'does not match pattern')
    assert text in result.stdout.str()


def test_jira_marker_bad_args2(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira(None)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert 'expected string or ' in result.stdout.str()


def test_jira_marker_no_run(testdir):
    """Expected skip due to run=False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 1, 0)


def test_open_jira_marker_pass(testdir):
    """Expected skip due to unresolved JIRA"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 0, 1)


def test_open_jira_marker_with_skipif_pass(testdir):
    """Expected skip due to unresolved JIRA when skipif is True"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=True)
        def test_pass():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_marker_without_skipif_fail(testdir):
    """Expected test to fail as unresolved JIRA marker
    is parametrized with False skipif"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_open_jira_marker_with_callable_skipif_pass(testdir):
    """
    Expected skip as skipif value is a lambda returning True. Expected
    component 'component2' is present on both closed and open JIRA issue
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1513", "ORG-1514",
            skipif=lambda i: 'component2' in i.get('components'))
        def test_pass():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_marker_with_callable_skipif_fail(testdir):
    """
    Expected fail as skipif value for open issue is a lambda returning False.
    Expected component 'component3' is present only on closed JIRA issue
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1513", "ORG-1514",
            skipif=lambda i: 'component3' in i.get('components'))
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_with_skipif_pass(testdir):
    """Expected test to skip due to multiple JIRA lines with skipif set"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=True)
        @pytest.mark.jira("ORG-1412", skipif=True)
        def test_pass():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_multiple_jira_markers_open_without_skipif_fail(testdir):
    """Expected to fail as skipif for open JIRA is False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=False)
        @pytest.mark.jira("ORG-1412", skipif=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_without_skipif_fail(testdir):
    """Expected to fail as skipif is False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", "ORG-1412", skipif=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_with_one_skipif_pass(testdir):
    """Expected to skip as skipif for JIRA tickets is True"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", "ORG-1412", skipif=True)
        def test_pass():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_docstr_pass(testdir):
    """Expected skip due to unresolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_pass():
            \"\"\"
            ORG-1382
            \"\"\"
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 0, 1)


def test_open_jira_marker_fail(testdir):
    """Expected skip due to unresolved JIRA"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_docstr_fail(testdir):
    """Expected skip due to unresolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_fail():
            \"\"\"
            ORG-1382
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_closed_jira_marker_pass(testdir):
    """Expected PASS due to resolved JIRA Issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_jira_docstr_pass(testdir):
    """Expected PASS due to resolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_fail():
            \"\"\"
            ORG-1412
            \"\"\"
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_jira_marker_fail(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_closed_jira_docstr_fail(testdir):
    """Expected xfail due to resolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_fail():
            \"\"\"
            ORG-1412
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_pass_without_jira(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_pass():
            \"\"\"
            some description
            \"\"\"
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_fail_without_jira_marker(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_fail_without_jira_docstr(testdir):
    """docstring with no jira issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        def test_pass():
            \"\"\"
            some description
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_invalid_configuration_exception(testdir):
    """Invalid option in config file, exception should be rised"""
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'ssl_verification = something',
        ])
    )
    testdir.makepyfile("""
        import pytest

        def test_pass():
            pass
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert "ValueError: Not a boolean: something" in result.stderr.str()


def test_invalid_authentication_exception(testdir):
    """Failed authentication, exception should be raised"""
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira('FOO-1234')
        def test_pass():
            pass
    """)
    ARGS = (
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-user', 'user123',
        '--jira-password', 'passwd123'
    )
    result = testdir.runpytest(*ARGS)
    assert re.search(
        "4(01|29) Client Error", result.stdout.str(), re.MULTILINE
    )


def test_disabled_ssl_verification_pass(testdir):
    """Expected PASS due to resolved JIRA Issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            "url = " + PUBLIC_JIRA_SERVER,
            'ssl_verification = false',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest('--jira')
    result.assert_outcomes(1, 0, 0)


def test_config_file_paths_xfail(testdir):
    """Jira url set in ~/jira.cfg"""
    testdir.makeconftest(CONFTEST)
    homedir = testdir.mkdir('home')
    os.environ['HOME'] = os.getcwd() + '/home'
    homedir.ensure('jira.cfg').write(
        '[DEFAULT]\nurl = ' + PUBLIC_JIRA_SERVER,
    )
    assert os.path.isfile(os.getcwd() + '/home/jira.cfg')
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest('--jira')
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_closed_for_different_version_skipped(testdir):
    """Skiped, closed for different version"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'components = com1,com3',
            'version = foo-0.1',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1501", run=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 1, 0)


def test_open_for_different_version_failed(testdir):
    """Failed, open for different version"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'components = com1,com3',
            'version = foo-1.1',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1511", run=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 1)


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
def test_get_issue_info_from_remote_passed(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
            def test_pass():
                \"\"\"
                XNIO-250
                \"\"\"
                assert True
        """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_affected_component_skiped(testdir):
    """Skiped, affected component"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1511", run=False)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url',
        PUBLIC_JIRA_SERVER,
        '--jira-components',
        'com3',
        'com1',
    )
    assert_outcomes(result, 0, 1, 0)


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
def test_strategy_ignore_failed(testdir):
    """Invalid issue ID is ignored and test fails"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'url = ' + PUBLIC_JIRA_SERVER,
            'marker_strategy = ignore',
            'docs_search = False',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1412789456148865", run=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest('--jira')
    result.assert_outcomes(0, 0, 1)


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
def test_strategy_strict_exception(testdir):
    """Invalid issue ID, exception is rised"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_fail():
            \"\"\"
            issue: 89745-1412789456148865
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-marker-strategy', 'strict',
        '--jira-issue-regex', '[0-9]+-[0-9]+',
    )
    assert "89745-1412789456148865" in result.stdout.str()


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
def test_strategy_warn_fail(testdir):
    """Invalid issue ID is ignored and warning is written"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'url = ' + PUBLIC_JIRA_SERVER,
            'marker_strategy = warn',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1511786754387", run=True)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest('--jira')
    assert "ORG-1511786754387" in result.stderr.str()
    result.assert_outcomes(0, 0, 1)


def test_ignored_docs_marker_fail(testdir):
    """Issue is open but docs is ignored"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_fail():
            \"\"\"
            open issue: ORG-1382
            ignored
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-disable-docs-search',
    )
    assert_outcomes(result, 0, 0, 1)


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
def test_issue_not_found_considered_open_xfailed(testdir):
    """Issue is open but docs is ignored"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_fail():
            \"\"\"
            not existing issue: ORG-13827864532876523
            considered open by default
            \"\"\"
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_jira_marker_bad_args_due_to_changed_regex(testdir):
    """Issue ID in marker doesn't match due to changed regex"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-issue-regex', '[0-9]+-[0-9]+',
    )
    text = 'JIRA marker argument `ORG-1382` does not match pattern'
    assert text in result.stdout.str()


def test_invalid_jira_marker_strategy_parameter(testdir):
    """Invalid parameter for --jira-marker-strategy"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-marker-strategy', 'invalid',
    )
    assert "invalid choice: \'invalid\'" in result.stderr.str()


def test_custom_resolve_status_fail(testdir):
    """
    Test case matches custom status and do not skip it because it is considered
    as closed, in additional test fails because of some regression.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1512", run=True)
        def test_fail():
            assert False  # some regression
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-resolved-statuses', 'custom-status',
    )
    assert_outcomes(result, 0, 0, 1)


def test_custom_resolve_status_pass(testdir):
    """
    Test case matches custom status and do not skip it because it is considered
    as closed, in additional test passes.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1512", run=True)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-resolved-statuses', 'custom-status',
    )
    assert_outcomes(result, 1, 0, 0)


def test_custom_resolve_status_skipped_on_closed_status(testdir):
    """
    Test case is marked by issue with status 'closed' which is one of defaults
    resolved statuses. But test-case gets skipped because custom resolved
    statuses are set.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1501", run=False)
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-resolved-statuses', 'custom-status,some-other',
    )
    assert_outcomes(result, 0, 1, 0)


def test_run_test_case_false1(testdir):
    """Test case shouldn't get executed"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'run_test_case = False',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=1, failed=0, error=0)


def test_run_test_case_false2(testdir):
    """Test case shouldn't get executed"""
    testdir.makeconftest(CONFTEST)
    plugin_args = (
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-do-not-run-test-case',
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*plugin_args)
    assert_outcomes(result, passed=0, skipped=1, failed=0, error=0)


def test_run_test_case_true1(testdir):
    """Test case should get executed"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'run_test_case = True',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=0, failed=0, error=0, xfailed=1)


def test_jira_fixture_plugin_disabled(testdir):
    testdir.makepyfile("""
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("ORG-1382") is None
    """)
    result = testdir.runpytest()
    assert_outcomes(result, 1, 0, 0)


def test_jira_fixture_run_positive(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("ORG-1382")
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_jira_fixture_run_negative(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_pass(jira_issue):
            assert not jira_issue("ORG-1382")
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_run_false_for_resolved_issue(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1412", run=False)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_xfail_strict(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.ini',
        pytest="\n".join([
            '[pytest]',
            'xfail_strict = True',
        ])
    )
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=0, failed=1, error=0, xfailed=0)


@pytest.mark.skipif(
    Version(pytest.__version__) < Version("3.0.0"),
    reason="requires pytest-3 or higher")
def test_jira_marker_with_parametrize_pytest3(testdir):
    """"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.parametrize('arg', [
            pytest.param(1, marks=pytest.mark.jira("ORG-1382", run=True)),
            2,
        ])
        def test_fail(arg):
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, failed=1, xfailed=1)


@pytest.mark.skipif(
    Version(pytest.__version__) >= Version("3.0.0"),
    reason="requires pytest-2 or lower")
def test_jira_marker_with_parametrize_pytest2(testdir):
    """"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.parametrize('arg', [
            pytest.mark.jira("ORG-1382", run=True)(1),
            2,
        ])
        def test_fail(arg):
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, failed=1, xfailed=1)


@pytest.mark.parametrize("error_strategy, passed, skipped, failed, error", [
    ('strict', 0, 0, 0, 0),
    ('skip', 0, 1, 0, 0),
    ('ignore', 1, 0, 0, 0),
])
def test_marker_error_strategy(
        testdir,
        error_strategy,
        passed,
        skipped,
        failed,
        error
):
    """HTTP Error when trying to connect"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("FOO-1234")
        def test_pass():
            pass
    """)
    ARGS = (
        '--jira',
        '--jira-url', 'http://foo.bar.com',
        '--jira-user', 'user123',
        '--jira-password', 'passwd123',
        '--jira-connection-error-strategy', error_strategy
    )
    result = testdir.runpytest(*ARGS)
    assert_outcomes(
        result,
        passed=passed,
        skipped=skipped,
        failed=failed,
        error=error
    )


@pytest.mark.parametrize("error_strategy, passed, skipped, failed, error", [
    ('strict', 0, 0, 1, 0),
    ('skip', 0, 1, 0, 0),
    ('ignore', 0, 0, 1, 0),
])
def test_jira_fixture_request_exception(
        testdir,
        error_strategy,
        passed,
        skipped,
        failed,
        error
):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("FOO-1234")
    """)
    ARGS = (
        '--jira',
        '--jira-url', 'http://foo.bar.com',
        '--jira-user', 'user123',
        '--jira-password', 'passwd123',
        '--jira-connection-error-strategy', error_strategy
    )
    result = testdir.runpytest(*ARGS)
    assert_outcomes(
        result,
        passed=passed,
        skipped=skipped,
        failed=failed,
        error=error
    )


@pytest.mark.skip(reason=SKIP_REASON_UNAUTHORIZED)
@pytest.mark.parametrize("ticket", ['ORG-1382', 'Foo-Bar'])
@pytest.mark.parametrize("return_method, _type", [
    ('--jira-return-metadata', 'JiraIssue'),
    ('', 'bool'),
])
def test_jira_fixture_return_metadata(testdir, return_method, _type, ticket):
    testdir.makepyfile("""
        import pytest
        from issue_model import JiraIssue

        def test_pass(jira_issue):
            issue = jira_issue('%s')
            assert isinstance(issue, %s)
    """ % (ticket, _type))
    ARGS = (
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        return_method
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_nofix_nooption(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1515", run=False)
        def test_pass():
            assert False
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_closed_nofix_option(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1515", run=False)
        def test_pass():
            assert False
    """)
    ARGS = (
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-resolved-resolutions', 'done,fixed,completed'
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(0, 1, 0)


def test_closed_fixed_nooption(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1516", run=False)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_fixed_option(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("ORG-1516", run=False)
        def test_pass():
            assert True
    """)
    ARGS = (
        '--jira',
        '--jira-url', PUBLIC_JIRA_SERVER,
        '--jira-resolved-resolutions', 'done,fixed,completed'
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(1, 0, 0)
