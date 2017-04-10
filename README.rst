|Build Status| |Code Health| |Code Coverage|

Intro
=====

A `pytest <http://pytest.org/latest/>`__ plugin for JIRA integration.

This plugin links tests with JIRA tickets. The plugin behaves similar to
the `pytest-bugzilla <https://pypi.python.org/pypi/pytest-bugzilla>`__
plugin.

The plugin does not close JIRA tickets, or create them. It just allows
you to link tests to existing tickets.

Please feel free to contribute by forking and submitting pull requests
or by submitting feature requests or issues to
`issues <https://github.com/rhevm-qe-automation/pytest_jira/issues>`__.

Test results
------------
-  If the test **unresolved** ...

   -  and the *run=False*, the test is **skiped**

   -  and the *run=True* or not set, the test is executed and based on it
      the result is **xpassed** (e.g. unexpected pass) or **xfailed** (e.g. expected fail)

-  If the test **resolved** ...

   -  the test is executed and based on it
      the result is **passed** or **failed**

Marking tests
-------------
You can specify jira issue ID in docstring or in pytest.mark.jira decorator.

By default the regular expression pattern for matching jira issue ID is ``[A-Z]+-[0-9]+``,
it can be changed by ``--jira-issue-regex=REGEX`` or in a config file by
``jira_regex=REGEX``.

It's also possible to change behavior if issue ID was not found
by setting ``--jira-marker-strategy=STRATEGY`` or in config file
as `marker_strategy=STRATEGY`.

Strategies for dealing with issue IDs that were not found:

- open - issue is considered as open (default)
- strict - raise an exception
- ignore - issue id is ignored
- warn - write error message and ignore

Issue ID in decorator
~~~~~~~~~~~~~~~~~~~~~
If you use decorator you can specify optional parameter ``run``. If it's false
and issue is unresolved, the test will be skipped.

.. code:: python

  @pytest.mark.jira("ORG-1382", run=False)
  def test_skip(): # will be skipped if unresolved
      assert False

  @pytest.mark.jira("ORG-1382")
  def test_xfail(): # will run and xfail if unresolved
      assert False

Issue ID in docstring
~~~~~~~~~~~~~~~~~~~~~

You can disable searching for issue ID in doc string by using
``--jira-disable-docs-search`` parameter or by ``docs_search=False``
in `jira.cfg`.

.. code:: python

  def test_xpass(): # will run and xpass if unresolved
  """issue: ORG-1382"""
      assert True

Status evaluation
-----------------

Issues are considered as **resolved** if their status matches
``resolved_statuses``. By default it is ``Resolved`` or ``Closed``.

You can set your own custom resolved statuses on command line
``--jira-resolved-statuses``, or in config file.

If you specify components (in command line or jira.cfg), open issues will be considered
**unresolved** only if they are also open for at least one used component.

If you specify version, open issues will be **unresolved** only if they also affects your version.
Even when the issue is closed, but your version was affected and it was not fixed for your version,
the issue will be considered **unresolved**.

Requires
========

-  pytest >= 2.2.3
-  jira >= 0.43
-  six

Installation
============

``pip install pytest_jira``

Usage
=====


1. Create a ``jira.cfg`` in the root of your tests:

   Options can be overridden with command line options. The configuration
   file can also be placed in ``/etc/jira.cfg`` and ``~/jira.cfg``.

   .. code:: ini

    [DEFAULT]
    url = https://jira.atlassian.com
    username = USERNAME (or blank for no authentication
    password = PASSWORD (or blank for no authentication)
    # ssl_verification = True/False
    # version = foo-1.0
    # components = com1,second component,com3
    # strategy = [open|strict|warn|ignore] (dealing with not found issues)
    # docs_search = False (disable searching for issue id in docs)
    # issue_regex = REGEX (replace default `[A-Z]+-[0-9]+` regular expression)
    # resolved_statuses = comma separated list of statuses (closed, resolved)


2. Mark your tests with jira marker and issue id.

   ``@pytest.mark.jira('issue_id')``

   You can put Jira ID into doc string of test case as well.

3. Run py.test with jira option to enable the plugin.

   ``py.test --jira``

.. |Build Status| image:: https://travis-ci.org/rhevm-qe-automation/pytest_jira.svg?branch=master
   :target: https://travis-ci.org/rhevm-qe-automation/pytest_jira
.. |Code Health| image:: https://landscape.io/github/rhevm-qe-automation/pytest_jira/master/landscape.svg?style=flat
   :target: https://landscape.io/github/rhevm-qe-automation/pytest_jira/master
.. |Code Coverage| image:: https://codecov.io/gh/rhevm-qe-automation/pytest_jira/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/rhevm-qe-automation/pytest_jira
