[![Build Status][travisimg]][travis]
[![Code Health][codehealthimg]][codehealth]
[![Code Coverage][codecovimg]][codecov]

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
* jira >= 0.13
* six

## Installation
``pip install pytest_jira``

## Usage
1. Create a `jira.cfg` in the root of your tests

  ```ini
  [DEFAULT]
  url = https://jira.atlassian.com
  username = USERNAME (or blank for no authentication)
  password = PASSWORD (or blank for no authentication)
  ```

  Options can be overridden with command line options.

  ``py.test --help``

2. Mark your tests with jira marker and issue id.
  ``@pytest.mark.jira('issue_id')``

  You can put Jira ID into doc string of test case as well.

3. Run py.test with jira option to enable the plugin.
  ``py.test --jira``

[pytest]: http://pytest.org/latest/
[githubissues]: https://github.com/jlaska/pytest_jira/issues
[travisimg]: https://travis-ci.org/rhevm-qe-automation/pytest_jira.svg?branch=master
[travis]: https://travis-ci.org/rhevm-qe-automation/pytest_jira
[codehealthimg]: https://landscape.io/github/rhevm-qe-automation/pytest_jira/master/landscape.svg?style=flat
[codehealth]: https://landscape.io/github/rhevm-qe-automation/pytest_jira/master
[codecovimg]: https://codecov.io/gh/rhevm-qe-automation/pytest_jira/branch/master/graph/badge.svg
[codecov]: https://codecov.io/gh/rhevm-qe-automation/pytest_jira
