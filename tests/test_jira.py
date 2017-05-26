import os
import pytest

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
}


@pytest.mark.tryfirst
def pytest_collection_modifyitems(session, config, items):
    plug = config.pluginmanager.getplugin("jira_plugin")
    assert plug is not None
    plug.issue_cache.update(FAKE_ISSUES)
"""

PLUGIN_ARGS = (
    '--jira',
    '--jira-url', 'https://issues.jboss.org',
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


def test_jira_marker_no_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest
        @pytest.mark.jira
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 1)


def test_jira_marker_bad_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira("there is no issue here")
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 1)


def test_jira_marker_bad_args2(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile("""
        import pytest

        @pytest.mark.jira(None)
        def test_pass():
            assert True
    """)
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 1)


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

        def test_pass():
            pass
    """)
    ARGS = (
        '--jira',
        '--jira-url', 'https://issues.jboss.org',
        '--jira-user', 'user123',
        '--jira-password', 'passwd123'
    )
    result = testdir.runpytest(*ARGS)
    assert "Invalid credentials" in result.stderr.str()


@pytest.mark.parametrize("status_code", [
    (400), (401), (403), (404), (500), (501), (503)
])
def test_request_exception(testdir, status_code):
    """HTTP Error when trying to connect"""
    testdir.makepyfile("""
        import pytest

        def test_pass():
            pass
    """)
    ARGS = (
        '--jira',
        '--jira-url', 'http://httpbin.org/status/{status_code}'.format(
            status_code=status_code
        ),
        '--jira-user', 'user123',
        '--jira-password', 'passwd123'
    )
    result = testdir.runpytest(*ARGS)
    assert "HTTPError" in result.stderr.str()


def test_disabled_ssl_verification_pass(testdir):
    """Expected PASS due to resolved JIRA Issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'url = https://issues.jboss.org',
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
        '[DEFAULT]\nurl = https://issues.jboss.org',
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
        'https://issues.jboss.org',
        '--jira-components',
        'com3',
        'com1',
    )
    assert_outcomes(result, 0, 1, 0)


def test_strategy_ignore_failed(testdir):
    """Invalid issue ID is ignored and test failes"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'url = https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
        '--jira-marker-strategy', 'strict',
        '--jira-issue-regex', '[0-9]+-[0-9]+',
    )
    assert "89745-1412789456148865" in result.stdout.str()


def test_strategy_warn_fail(testdir):
    """Invalid issue ID is ignored and warning is written"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        '.cfg',
        jira="\n".join([
            '[DEFAULT]',
            'url = https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
        '--jira-disable-docs-search',
    )
    assert_outcomes(result, 0, 0, 1)


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
        '--jira-url', 'https://issues.jboss.org',
        '--jira-issue-regex', '[0-9]+-[0-9]+',
    )
    assert_outcomes(result, 0, 0, 0, error=1)


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
        '--jira-url', 'https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
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
        '--jira-url', 'https://issues.jboss.org',
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
