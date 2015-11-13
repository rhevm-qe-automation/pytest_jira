# Intro
A [pytest][pytest] plugin for JIRA integration.

This plugin links tests with JIRA tickets. The plugin behaves similar to the [pytest-bugzilla](https://pypi.python.org/pypi/pytest-bugzilla) plugin.



| CONDITION | Test Passed | Test Failed |
|---------|:---------:|:---------:|
| | **Basic** | |
| Run = False | skipped | skipped
| Unresolved | xpassed | xfailed |
| Resolved | passed | failed |
| Not found  | passed | failed |
| Not specified | passed | failed |
| | **Advanced** | |
| *Resolved:* |
| Your version was not affected | passed | failed |
| Your version was affected and fixed | passed | failed |
| Your version was affected but not fixed | xpassed | xfailed |
| *Unresolved:*|
| Your components are affected | xpassed | xfailed |
| Your components are affected in your version | xpassed | xfailed |
| Your components are affected in different version | passed | failed |
| Your components are not affected | passed | failed |


The plugin does not close JIRA tickets, or create them. It just allows you to link tests to existing tickets.

This plugin currently assumes the following workflow:

A JIRA issue with status in ['Closed', 'Resolved'] is assumed to be resolved.
All other issues are considered unresolved.

Please feel free to contribute by forking and submitting pull requests or by
submitting feature requests or issues to [issues][githubissues].

## Requires
* pytest >= 2.2.3
* jira-python >= 0.43

## Installation
``pip install pytest_jira``

## Usage
1. Create a `setup.cfg` in the root of your tests. This INI file is shared for all pytest plugins.

    ```ini
    [pytest]
    jira_url = https://jira.atlassian.com
    jira_username = USERNAME (or blank for no authentication)
    jira_password = PASSWORD (or blank for no authentication)
    # jira_ssl_verification = yes
    # jira_version = foo0.43
    # jira_components = someComponent "Different Component"

    ```

Options can be overridden with command line options.

 ``py.test --help``

2. Mark your tests with jira marker and issue id.
 ``@pytest.mark.jira('issue_id')``

3. Run py.test with jira option to enable the plugin.
 ``py.test --jira``

[pytest]: http://pytest.org/latest/
[githubissues]: https://github.com/jlaska/pytest_jira/issues
