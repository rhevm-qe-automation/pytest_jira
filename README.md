# Intro
[PyTest][pytest] plugin for JIRA integration.  This plugin currently assumes the
following workflow:

A JIRA issue with status in ['Closed', 'Resolved'] is assumed to be resolved.
All other issues are considered unresolved.

Please feel free to contribute by forking and submitting pull requests or by
submitting feature requests or issues to [issues][githubissues].

## Requires
* pytest >= 2.2.3
* jira-python >= 0.13

## Installation
``pip install pytest_jira``

## Usage
1. Create a jira.cfg in the root of your tests

 [DEFAULT]
 url = https://jira.atlassian.com
 username = USERNAME (or blank for no authentication)
 password = PASSWORD (or blank for no authentication)

Options can be overridden with command line options.

 ``py.test --help``

2. Mark your tests with jira marker and issue id.
 ``@pytest.mark.jira('issue_id')``

3. Run py.test with jira option to enable the plugin.
 ``py.test --jira``

[pytest]: http://pytest.org/latest/
[githubissues]: https://github.com/jlaska/pytest_jira/issues
