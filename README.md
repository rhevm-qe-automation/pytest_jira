# Intro
A [pytest][pytest] plugin for JIRA integration.

This plugin links tests with JIRA tickets. The plugin behaves similar to the [pytest-bugzilla](https://pypi.python.org/pypi/pytest-bugzilla) plugin.

* If the test fails ...

  * and the JIRA ticket is still **unresolved** (i.e. not fixed), the test result is **xfail** (e.g. known failure).
  * and the JIRA ticket is **resolved** (i.e. fixed), the test result is **fail** (e.g. unexpected failure).

* If the test passed ...

  * and the JIRA ticket is still **unresolved** (i.e. not fixed), the test result is **xpassed** (e.g. unexpected pass).
  * and the JIRA ticket is **resolved**, the test result is **passed** (e.g. everything works).

The plugin does not close JIRA tickets, or create them. It just allows you to link tests to existing tickets.

This plugin currently assumes the following workflow:

A JIRA issue with status in ['Closed', 'Resolved'] is assumed to be resolved.
All other issues are considered unresolved.

Please feel free to contribute by forking and submitting pull requests or by
submitting feature requests or issues to [issues][githubissues].

## Requires
* pytest >= 2.2.3
* jira >= 0.43

## Installation
``pip install pytest_jira``

## Usage
1. Create a `pytest.ini` in the root of your tests

    ```ini
    [pytest]
    jira_url = https://jira.atlassian.com
    jira_username = USERNAME (or blank for no authentication)
    jira_password = PASSWORD (or blank for no authentication)
    # jira_ssl_verification = True/False

    ```

Options can be overridden with command line options.

More information about ini files can be found [here](https://pytest.org/latest/customize.html#inifiles)

 ``py.test --help``

2. Mark your tests with jira marker and issue id.
 ``@pytest.mark.jira('issue_id')``

3. Run py.test with jira option to enable the plugin.
 ``py.test --jira``

[pytest]: http://pytest.org/latest/
[githubissues]: https://github.com/jlaska/pytest_jira/issues
