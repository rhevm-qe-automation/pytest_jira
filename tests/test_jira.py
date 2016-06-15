import os


CONFTEST = """
import pytest


FAKE_ISSUES = {
    "ORG-1412": "closed",
    "ORG-1382": "open",
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
    '''Expected skip due to run=False'''
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
    '''Expected skip due to unresolved JIRA'''
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
    '''Expected skip due to unresolved JIRA Issue %s'''
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
    '''Expected skip due to unresolved JIRA'''
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
    '''Expected skip due to unresolved JIRA Issue %s'''
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
    '''Expected PASS due to resolved JIRA Issue'''
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
    '''Expected PASS due to resolved JIRA Issue %s'''
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
    '''Expected xfail due to resolved JIRA Issue %s'''
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
    '''docstring with no jira issue'''
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
    '''Invalid option in config file, exception should be rised'''
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


def test_invalid_authentification_exception(testdir):
    '''Failed authentication, exception should be rised'''
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
    assert "JIRAError: JiraError" in result.stderr.str()


def test_disabled_ssl_verification_pass(testdir):
    '''Expected PASS due to resolved JIRA Issue'''
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
    '''Jira url set in ~/jira.cfg'''
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