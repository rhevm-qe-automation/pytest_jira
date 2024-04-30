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

   -  and the *run=False*, the test is **skipped**

   -  and the *run=True* or not set, the test is executed and based on it
      the result is **xpassed** (e.g. unexpected pass) or **xfailed** (e.g. expected fail).
      Interpretation of **xpassed** result depends on the py.test ini-file **xfail_strict** value,
      i.e. with *xfail_strict=true* **xpassed** results will fail the test suite.
      More information about strict xfail available on the py.test `doc <https://docs.pytest.org/en/latest/skipping.html#strict-parameter>`__

-  If the test **resolved** ...

   -  the test is executed and based on it
      the result is **passed** or **failed**

- If the **skipif** parameter is provided ...

  -  with value *False* or *callable returning False-like value* jira marker line is **ignored**


**NOTE:** You can set default value for ``run`` parameter globally in config
file (option ``run_test_case``) or from CLI
``--jira-do-not-run-test-case``. Default value is ``run=True``.

Marking tests
-------------
You can specify jira issue ID in docstring or in pytest.mark.jira decorator.

By default the regular expression pattern for matching jira issue ID is ``[A-Z]+-[0-9]+``,
it can be changed by ``--jira-issue-regex=REGEX`` or in a config file by
``jira_regex=REGEX``.

It's also possible to change behavior if issue ID was not found
by setting ``--jira-marker-strategy=STRATEGY`` or in config file
as ``marker_strategy=STRATEGY``.

Strategies for dealing with issue IDs that were not found:

- **open** - issue is considered as open (default)
- **strict** - raise an exception
- **ignore** - issue id is ignored
- **warn** - write error message and ignore

Issue ID in decorator
~~~~~~~~~~~~~~~~~~~~~
If you use decorator you can specify optional parameters ``run`` and ``skipif``.
If ``run`` is false and issue is unresolved, the test will be skipped.
If ``skipif`` is is false jira marker line will be ignored.

.. code:: python

  @pytest.mark.jira("ORG-1382", run=False)
  def test_skip(): # will be skipped if unresolved
      assert False

  @pytest.mark.jira("ORG-1382")
  def test_xfail(): # will run and xfail if unresolved
      assert False

  @pytest.mark.jira("ORG-1382", skipif=False)
  def test_fail():  # will run and fail as jira marker is ignored
      assert False

Using lambda value for skipif
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
You can use lambda value for ``skipif`` parameter. Lambda function must take
issue JSON as input value and return boolean-like value. If any JIRA ID
gets False-like value marker for that issue will be ignored.

.. code:: python

  @pytest.mark.jira("ORG-1382", skipif=lambda i: 'my component' in i['components'])
  def test_fail():  # Test will run if 'my component' is not present in Jira issue's components
      assert False

  @pytest.mark.jira("ORG-1382", "ORG-1412", skipif=lambda i: 'to do' == i['status'])
  def test_fail():  # Test will run if either of JIRA issue's status differs from 'to do'
      assert False


Issue ID in docstring
~~~~~~~~~~~~~~~~~~~~~

You can disable searching for issue ID in doc string by using
``--jira-disable-docs-search`` parameter or by ``docs_search=False``
in ``jira.cfg``.

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

If you specify fixed resolutions closed issues will be **unresolved** if they do not also have a **resolved** resolution.

Fixture usage
-------------

Besides a test marker, you can also use the added ``jira_issue`` fixture. This enables examining issue status mid test
and not just at the beginning of a test. The fixture return a boolean representing the state of the issue.
If the issue isn't found, or the jira plugin isn't loaded, it returns ``None``.

.. code:: python

    NICE_ANIMALS = ["bird", "cat", "dog"]

    def test_stuff(jira_issue):
        animals = ["dog", "cat"]
        for animal in animals:
            if animal == "dog" and jira_issue("ORG-1382") is True:
                print("Issue is still open, cannot check for dogs!")
                continue
            assert animal in NICE_ANIMALS

Requires
========

-  pytest >= 2.2.3
-  requests >= 2.13.0
-  six
-  retry2>=0.9.5
-  marshmallow>=3.2.0

Installation
============

``pip install pytest_jira``

Usage
=====


1. Create a ``jira.cfg`` and put it at least in one of following places.

   * /etc/jira.cfg
   * ~/jira.cfg
   * tests\_root\_dir/jira.cfg
   * tests\_test\_dir/jira.cfg

   The configuration file is loaded in that order mentioned above.
   That means that first options from global configuration are loaded,
   and might be overwritten by options from user's home directory and
   finally these might be overwritten by options from test's root directory.

   See example bellow, you can use it as template, and update it according
   to your needs.

   .. code:: ini

     [DEFAULT]
     url = https://jira.atlassian.com
     username = USERNAME (or blank for no authentication)
     password = PASSWORD (or blank for no authentication)
     token = TOKEN (either use token or username and password)
     # ssl_verification = True/False
     # version = foo-1.0
     # components = com1,second component,com3
     # strategy = [open|strict|warn|ignore] (dealing with not found issues)
     # docs_search = False (disable searching for issue id in docs)
     # issue_regex = REGEX (replace default `[A-Z]+-[0-9]+` regular expression)
     # resolved_statuses = comma separated list of statuses (closed, resolved)
     # resolved_resolutions = comma separated list of resolutions (done, fixed)
     # run_test_case = True (default value for 'run' parameter)
     # connection_error_strategy [strict|skip|ignore] Choose how to handle connection errors
     # return_jira_metadata = False (return Jira issue with metadata instead of boolean result)

   Alternatively, you can set the url, password, username and token fields using relevant environment variables:

    .. code:: sh

      export PYTEST_JIRA_URL="https://..."
      export PYTEST_JIRA_PASSWORD="FOO"
      export PYTEST_JIRA_USERNAME="BAR"
      export PYTEST_JIRA_TOKEN="TOKEN"

   Configuration options can be overridden with command line options as well.
   For all available command line options run following command.

   .. code:: sh

     py.test --help

2. Mark your tests with jira marker and issue id.

   ``@pytest.mark.jira('issue_id')``

   You can put Jira ID into doc string of test case as well.

3. Run py.test with jira option to enable the plugin.

   ``py.test --jira``

Tests
=====

In order to execute tests run

.. code:: sh

  $ tox
