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
it can be changed by ``--jira-issue-regex=REGEX`` or in the ``jira.cfg``
config file by ``issue_regex=REGEX`` (the ini key drops the ``--jira-``
prefix and turns hyphens into underscores, but it is not derived mechanically
from the option name: ``--jira-marker-strategy`` is ``marker_strategy`` while
``--jira-product-version`` is ``version``, ``--jira-connection-error-strategy``
is ``error_strategy`` and ``--jira-do-not-run-test-case`` is
``run_test_case``; ``jira.cfg.example`` lists them all).

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
and not just at the beginning of a test. The fixture returns a boolean representing the state of the issue.
An issue that is not found is answered by ``--jira-marker-strategy`` (``open`` by
default), exactly as a marked issue is. ``None`` is returned only when the jira
plugin isn't loaded, or when a connection error is ignored under
``--jira-connection-error-strategy=ignore``.

The same API is available at other pytest scopes via ``jira_issue_scope_class``,
``jira_issue_scope_module``, ``jira_issue_scope_package``, and ``jira_issue_scope_session``.

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

-  pytest >= 2.2.4
-  six
-  requests >= 2.13.0
-  retry2>=0.9.5
-  marshmallow>=4.0
-  packaging

Installation
============

``pip install pytest_jira``

Usage
=====


1. From a source checkout, copy the shipped ``jira.cfg.example`` to
   ``jira.cfg``. The wheel installs only ``pytest_jira.py`` and
   ``issue_model.py``, so ``pip install pytest_jira`` does not ship the file -
   use the template in the next block instead:

   .. code:: sh

     cp jira.cfg.example jira.cfg

   Then put your ``jira.cfg`` at least in one of following places. It is read
   from all of them, later files overriding earlier ones.

   * /etc/jira.cfg
   * tests\_root\_dir/jira.cfg
   * ~/jira.cfg
   * ./jira.cfg (current working directory)

   ``jira.cfg`` is git ignored, so credentials stay out of version control;
   ``jira.cfg.example`` is the template and is safe to commit.

   See the example below; use it as a template and adapt it to your needs.
   It lists the same options as the ``jira.cfg.example`` in a source checkout,
   which also documents the file search order.

   .. code:: ini

     [DEFAULT]
     url = https://jira.atlassian.com
     # Leave the credential fields empty for anonymous access.
     username =
     password =
     token =
     # cloud_id is only used by the OAuth 2.0 service account, where it is
     # required: the gateway URL is derived from it. With a user, a bare token
     # or no credentials at all it is ignored (a warning says so).
     cloud_id =
     oauth_client_id =
     oauth_client_secret =
     # oauth_client_secret is a long-lived credential: keep this file readable by
     # you only (`chmod 600 jira.cfg`) and prefer PYTEST_JIRA_OAUTH_CLIENT_SECRET,
     # which leaves nothing on disk.
     # ssl_verification = True/False  (True, the default, refuses credentials
     #                                over plain http; False disables TLS
     #                                verification and allows a plain http
     #                                url with a warning; ignored for an OAuth
     #                                service account)
     # version = foo-1.0
     # components = com1,second component,com3
     # marker_strategy = [open|strict|warn|ignore] (not found issues)
     # docs_search = False (disable searching for issue id in docs)
     # issue_regex = REGEX (replace default `[A-Z]+-[0-9]+` regular expression)
     # resolved_statuses = comma separated list of statuses (closed, resolved)
     # resolved_resolutions = comma separated list of resolutions (done, fixed)
     # run_test_case = True (default value for 'run' parameter)
     # error_strategy = [strict|skip|ignore] (how to handle connection errors)
     # return_jira_metadata = False (return Jira issue with metadata instead of boolean result)
     # connection_retry_total = 5 (number of retries)
     # connection_retry_backoff_factor = 0.2 (connection retry backoff factor)

   Alternatively, every connection field can come from an environment
   variable:

    .. code:: sh

      export PYTEST_JIRA_URL="https://..."
      export PYTEST_JIRA_PASSWORD="FOO"
      export PYTEST_JIRA_USERNAME="BAR"
      export PYTEST_JIRA_TOKEN="TOKEN"
      export PYTEST_JIRA_CLOUD_ID="CLOUD_ID"
      export PYTEST_JIRA_OAUTH_CLIENT_ID="CLIENT_ID"
      export PYTEST_JIRA_OAUTH_CLIENT_SECRET="CLIENT_SECRET"

   The ``PYTEST_JIRA_*`` environment variables win over both ``jira.cfg``
   and the command line options; every other option can also be given on
   the command line.
   For all available command line options run following command.

   .. code:: sh

     py.test --help

2. Mark your tests with jira marker and issue id.

   ``@pytest.mark.jira('issue_id')``

   You can put Jira ID into doc string of test case as well.

3. Run py.test with jira option to enable the plugin.

   ``py.test --jira``

Authentication (Jira Cloud and Server/DC)
==========================================

.. note::

   Breaking changes for existing setups:

   * a ``http://`` url with credentials is now refused instead of silently
     sending them in clear text (use ``https``, or ``--jira-no-ssl-verify``
     to opt into insecure transport);
   * ``--jira`` without a configured ``url`` is now a usage error instead of
     running every test without issue checks;
   * a ``404`` from the authentication probe is no longer mistaken for a
     missing issue: it raises under ``error_strategy=strict`` (the default)
     and skips under ``skip``. It used to be answered by the marker strategy,
     so a wrong url or cloud id made the issue look open and the test silently
     xfailed (``open``, the default) or skipped instead of reporting it.

There are exactly two ways to authenticate against Jira Cloud, plus the
Server/Data Center personal access token:

.. list-table::
   :header-rows: 1

   * - Who
     - Configure
     - Wire
   * - User (Jira Cloud)
     - ``url`` + ``username`` (your email) + ``token`` (API token)
     - basic auth to the site URL
   * - Service account (Jira Cloud)
     - ``url`` + ``cloud_id`` + ``oauth_client_id`` + ``oauth_client_secret``
     - OAuth 2.0 access token, Bearer to the API gateway
   * - Jira Server/Data Center
     - ``url`` + ``token`` (personal access token)
     - Bearer to the URL as configured

A bare ``token`` is sent as a Bearer token to the ``url`` as configured, with
no username and no cloud id: that is the Server/Data Center personal access
token. It is **not a valid Jira Cloud credential** - a Cloud token belongs
either to a user (then it needs the email as the username) or to a service
account (then it needs the OAuth 2.0 credential) - but the plugin does not
refuse the combination up front. Jira answers ``401`` on the first request and
``--jira-connection-error-strategy`` handles it like any other connection
failure. A ``cloud_id`` does not change that: with no OAuth 2.0 credential it
is ignored, on any host.

User (Jira Cloud)
-----------------

.. code:: sh

  export PYTEST_JIRA_URL="https://your-site.atlassian.net"
  export PYTEST_JIRA_USERNAME="you@example.com"
  export PYTEST_JIRA_TOKEN="<API token>"

  py.test --jira

Service account (Jira Cloud)
----------------------------

A service account uses an *OAuth 2.0 credential*: the client id and the
permanent client secret. The plugin exchanges them at
``https://auth.atlassian.com/oauth/token`` (``client_credentials``) for a
short-lived access token, caches it until shortly before it expires, and
sends it as a Bearer token to
``https://api.atlassian.com/ex/jira/<cloudId>``. The client secret never
reaches the API gateway.

.. code:: sh

  export PYTEST_JIRA_URL="https://your-site.atlassian.net"
  export PYTEST_JIRA_CLOUD_ID="<cloudId>"
  export PYTEST_JIRA_OAUTH_CLIENT_ID="<client id>"
  export PYTEST_JIRA_OAUTH_CLIENT_SECRET="<client secret>"

  py.test --jira

With the ``jira.cfg`` keys or command line options instead:
``--jira-cloud-id`` / ``cloud_id``, ``--jira-oauth-client-id`` /
``oauth_client_id`` and ``--jira-oauth-client-secret`` /
``oauth_client_secret``. Prefer the
environment variable or ``jira.cfg`` for the secret: a command line value is
visible in the process list.

Creating the credential
~~~~~~~~~~~~~~~~~~~~~~~

Both values come from an Atlassian app in the developer console, not from
the Jira site itself:

* Create an app and enable the ``client_credentials`` (OAuth 2.0) grant, so
  the plugin can mint a token without any user consent step. That app's
  client id and client secret are ``oauth_client_id`` and
  ``oauth_client_secret``.
* Grant the app access to your Jira site with the ``read:jira-work`` scope;
  ``read:jira-user`` is optional and only lets the startup probe
  (``/rest/api/2/myself``) answer instead of returning 403.
* ``cloud_id`` is the cloud id of that site - it is not the host name. Read
  the ``cloudId`` from the site's
  ``https://<site>.atlassian.net/_edge/tenant_info`` (open it in a browser),
  or from the app's API-access page in the Atlassian developer console. The
  plugin builds the gateway ``https://api.atlassian.com/ex/jira/<cloudId>``
  from it, so keep ``url`` as the site URL.

  The ``id`` field of
  ``GET https://api.atlassian.com/oauth/token/accessible-resources`` holds the
  same value, but that is an OAuth 2.0 three-legged endpoint: it only answers
  for a token minted after a *user* authorised an app. The
  ``client_credentials`` grant used here has no user, so use that endpoint
  only if you already have such a token.

Notes:

* Do not set a username or a token: the minted access token is sent as a
  Bearer token. A lone stray ``username`` or ``token`` is ignored with a
  warning, and an OAuth pair with a missing half is ignored with a warning
  too - it is never fatal. *Failure behaviour* lists every combination and
  its outcome.
* ``cloud_id`` is required together with the OAuth 2.0 credential: the plugin
  derives the gateway from it. ``url`` stays the site URL and is only used
  for browse links (``https://<site>.atlassian.net/browse/<issue>``);
  pointing ``url`` at ``https://api.atlassian.com/ex/jira/<cloudId>`` is
  accepted but then the skip/xfail reasons cannot link to an issue page (a
  warning says so).
* ``--jira-no-ssl-verify`` is ignored for a service account: its access
  token is only ever sent over verified TLS (a warning says so).
* A failed mint stops the run with the HTTP status and which value to check
  when the token endpoint answers, with the transport error and no status
  when it cannot be reached at all, and with an unexpected response and no
  status when it answers ``200`` with an unusable body, under the default
  ``error_strategy=strict``. With ``skip`` the marked tests
  are skipped with the connection message, with ``ignore`` no skip is added
  and they run; either way the reason is printed once on stderr. The client
  secret is never included in messages.
* Scopes are not permissions: the service account must also have product
  access to Jira and *Browse projects* on every project you mark tests with,
  or Jira answers ``404`` and the issue looks missing to the plugin.

Jira Server/Data Center
-----------------------

.. code:: sh

  export PYTEST_JIRA_URL="https://jira.example.com"
  export PYTEST_JIRA_TOKEN="<personal access token>"

  py.test --jira

A Bearer token is used as configured; no cloud id, no OAuth credential.
Server/Data Center also accepts ``username`` + ``password``
(``--jira-user`` / ``--jira-password``) for basic auth. Jira Cloud has
rejected password basic auth since 2019, so the combination is sent as given
and Jira answers ``401``: use an API token.

Failure behaviour
-----------------

Three configurations are rejected before any request is made. They end the
run with exit code 4 (``USAGE_ERROR``) and one message instead of a
traceback:

* ``--jira`` without any ``url`` (``--jira-url``, ``PYTEST_JIRA_URL`` or
  ``url`` in ``jira.cfg``) - without it no issue check can run,
* an OAuth 2.0 service account without a ``cloud_id``: the gateway
  ``https://api.atlassian.com/ex/jira/<cloudId>`` cannot be derived, so there
  is nothing to talk to,
* credentials (a token, or a username with a password) on a plain ``http://``
  url: they would be sent in clear text, so the plugin refuses to send them
  unless TLS verification is disabled.

Every other combination is taken as configured and only fails when the first
request is made - the same ``requests`` error or Jira status a misconfigured
setup always produced. Nothing else is checked up front about the host, how
the credentials are paired, or whether they match the host, so a url
without a scheme (``jira.example.com``), a url with no host (``https://`` on
its own), ``username`` + ``password`` on Jira Cloud, a bare token on a Jira
Cloud host or next to a ``cloud_id``, and the API gateway as ``url`` for a
user or a Server/DC token are all sent exactly as given. A url that cannot be
sent at all surfaces as a ``requests`` error (``MissingSchema``,
``InvalidURL``, ``InvalidSchema``), a credential Jira does not accept as an
HTTP error from Jira (usually ``401``).

What a failed request does is decided by
``--jira-connection-error-strategy``:

* ``strict`` (default) - the error is raised, so the run stops at the first
  marked issue,
* ``skip`` - the marked tests are skipped with the connection message,
* ``ignore`` - no skip is added and the marked tests run.

An OAuth 2.0 service account adds fail-fast diagnostics on top, so that a
credential that cannot work does not degrade into a run where every marked
test skips:

* a mint failure ends the run with exit code 4 under ``strict``: with the HTTP
  status and which value to check when the token endpoint answers, with the
  transport error and no status when it cannot be reached at all, with an
  unexpected response and no status when it answers ``200`` with an unusable
  body,
* credentials rejected by Jira - a ``401`` that carries a response - end the
  run with exit code 4 and the auth hint under ``strict``. This covers the
  authentication probe (``/rest/api/2/myself``) and a ``401`` on a single
  issue later in the run.

With ``skip`` the marked tests are skipped with the connection message, with
``ignore`` no skip is added and they run; the hint is printed once on stderr
either way. A transport failure with no response is not a usage error, not
even under ``strict``: it is warned and then raised. A 403 from that probe
still counts as authenticated (a scoped service account may only hold
``read:jira-work``); only 401 means wrong credentials.

A user or Server/DC connection keeps its previous behaviour: a failed
request raises under ``strict`` and skips under ``skip``, with no extra
diagnostics.

Several combinations are answerable rather than fatal, and are reported once
on stderr:

* an OAuth credential ignored because a username with a token or a password
  is set,
* a token, username or password ignored because an OAuth credential is set,
* a password without a username,
* an incomplete OAuth credential (a client id without its secret, or the
  other way round): it is ignored, so a leftover variable cannot break a
  working user, PAT or anonymous setup,
* a ``cloud_id`` with no OAuth credential (next to a username with a token or
  a password, next to a bare token, and with no credentials at all),
* a gateway ``url`` on an OAuth 2.0 service account, which cannot produce
  browsable skip/xfail links (a user or Server/DC connection gets no warning:
  its ``url`` is used as given),
* credentials embedded in the ``url`` (lifted into basic auth),
* credentials sent over plain ``http`` while ``--jira-no-ssl-verify`` is set,
* ``--jira-no-ssl-verify`` being ignored for a service account.

Errors on individual issues are split by status once the connection itself
succeeded: a ``404`` means the issue is not visible, so it is answered by
``--jira-marker-strategy`` (``open`` by default), and every other
post-connection 4xx keeps the ``--jira-connection-error-strategy``
behaviour. For an OAuth
service account a ``401`` on an issue is still a credential failure - a
permission problem on one issue is a ``403`` - so under ``strict`` it ends the
run with exit code 4 and the auth hint, even when the authentication probe
succeeded.

The re-mint heal is bounded per chain of ``401``s: a ``401`` is answered by one
re-mint, and if the freshly minted token is rejected too, no further re-mint
follows until another response proves a token valid - a 401 on a token minted
moments earlier is deterministic, so a second mint could only reach the same
401. A response that proves the token authenticated - a **sub-400 status**,
or a ``4xx`` other than ``401``/``429`` - resets that, so a later,
independent revocation still heals; a ``5xx`` or ``429`` does not, since
those are returned before the credential is checked, so a server incident
cannot turn into extra token requests. A persisting ``401`` still fails
loudly under ``strict`` and still warns once under ``skip``/``ignore``.

Common notes
------------

* Values read from environment variables may be quoted
  (``PYTEST_JIRA_URL="https://..."``); a matching pair of surrounding quotes
  and any whitespace are stripped.
* ``PYTEST_JIRA_*`` environment variables win over ``jira.cfg`` *and* the
  command line options.
* Every Jira request has a 30 s timeout, and a server-supplied
  ``Retry-After`` is capped at 10 s, so neither a stalled server nor a
  ``429``/``503`` carrying a long ``Retry-After`` can hold an attempt longer: a
  stall surfaces as a ``Read timed out`` failure instead of hanging the run.
* Keep credentials out of the ``url``. If you embed them, the plugin lifts
  them into basic auth and warns. Credentials glued to the scheme - an ``@``
  with no host behind it, ``https://user:pw@/`` - leave a url that cannot be
  sent, so the first request fails with a ``requests`` error, handled by
  ``--jira-connection-error-strategy``. A literal ``@`` in an embedded
  password must be percent-encoded as ``%40``. Prefer ``username``/``token``
  (or the environment variables).
* A url the plugin has to print - a message, a skip/xfail reason, a
  traceback - never shows embedded credentials: the userinfo of a clean url
  is stripped and the rest kept, and any other url-ish text that could carry
  credentials is printed as ``<url>``. When that redaction is what the site
  url comes back as, the reason carries the bare ticket key instead of
  ``<url>/browse/<key>``.
* Credentials are refused over plain ``http://``: a token, or a username
  with a password, would be sent in clear text. ``--jira-no-ssl-verify``
  (or ``ssl_verification = False``) is the explicit escape hatch: it allows
  a plain ``http`` url with a warning, and it disables TLS verification for
  the Jira requests. A plain ``http`` url without credentials is used as
  given. For an OAuth service account the flag is ignored - the access token
  is only sent over verified TLS.
* Running the plugin's own test suite: set either ``TEST_JIRA_USER`` and
  ``TEST_JIRA_TOKEN`` (user), or ``TEST_JIRA_OAUTH_CLIENT_ID``,
  ``TEST_JIRA_OAUTH_CLIENT_SECRET`` and ``TEST_JIRA_CLOUD_ID`` (service
  account); ``TEST_JIRA_URL`` selects the site. All of them are in
  ``tox.ini``'s ``passenv``, and the CI workflow forwards all six from the
  repository secrets, so both auth paths run in CI; when a secret is absent
  the corresponding tests skip.


Tests
=====

In order to execute tests run

.. code:: sh

  $ tox
