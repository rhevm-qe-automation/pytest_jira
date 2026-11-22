"""
This plugin integrates pytest with jira; allowing the tester to mark a test
with a bug id.  The test will then be skipped unless the issue status matches
at least one of resolved statuses.

The url comes from --jira-url, the PYTEST_JIRA_URL environment variable or
jira.cfg. Jira Cloud takes either a user (username = your email, token = an
API token) or an OAuth 2.0 service account (--jira-oauth-client-id,
--jira-oauth-client-secret and --jira-cloud-id); Jira Server/DC takes a
personal access token as the token. See the README "Authentication" section.

Author: James Laska
"""

import collections
import hashlib
import os
import re
import sys
import time
from json import JSONDecodeError
from urllib.parse import unquote, urlparse

import pytest
import requests
import six
import urllib3
from packaging.version import Version
from retry import retry

from issue_model import JiraIssue, JiraIssueSchema

DEFAULT_RESOLVE_STATUSES = "closed", "resolved"
DEFAULT_RUN_TEST_CASE = True
CONNECTION_SKIP_MESSAGE = "Jira connection issue, skipping test: %s"
CONNECTION_ERROR_FLAG_NAME = "--jira-connection-error-strategy"
STRICT = "strict"
SKIP = "skip"
IGNORE = "ignore"
PLUGIN_NAME = "jira_plugin"
AUTH_BASIC = "basic"
AUTH_OAUTH = "oauth"
AUTH_PAT = "pat"
# pytest's usage-error code, spelled out rather than read from pytest.ExitCode
# so that an old pytest without the enum still fails instead of exiting 0.
USAGE_ERROR_CODE = getattr(getattr(pytest, "ExitCode", None), "USAGE_ERROR", 4)
# Upper bound for one Jira request attempt, so a stalled server cannot hang
# the whole test session (retries multiply it).
JIRA_REQUEST_TIMEOUT = 30
# Longest wait a Retry-After header may impose on one attempt (both the mint
# and the Jira session cap it).
MAX_RETRY_AFTER = 10


def _clean(value):
    """Strip whitespace and a matched pair of surrounding quotes.

    .env style files often quote a value (PYTEST_JIRA_URL="https://...").
    Only a matched pair goes: a password such as ``my"pass"`` must survive.
    """
    if not isinstance(value, str):
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value or None


def _get_setting(env_var, config, name):
    """Return the environment override or the ini value for name."""
    return _clean(os.getenv(env_var)) or _clean(config.getvalue(name))


# Inside a run any number of horizontal whitespace runs is crossed, never a
# newline; an "@" is part of the userinfo when another "@" follows, so the run
# ends at the last one. The second alternative takes a colon with no slashes.
# shortcut: a newline inside a userinfo is not crossed, so a url split across
# lines is not redacted; upgrade if a config can produce one
_USERINFO_RE = re.compile(
    r"(?:[^\s'\"@]*@)*(?:[a-zA-Z][\w+.-]*:)?/{1,}[^\s]*"
    r"(?:[^\S\n]+[^\s]*)*@[^\s'\"]*"
    r"|[^\s'\"/@()]*:[^\s/]*(?:[^\S\n]+[^\s/]*)*@[^\s'\"]*"
)
# Where the authority of such a run starts: after a scheme and its slashes.
_AUTHORITY_START_RE = re.compile(r"(?:[a-zA-Z][\w+.-]*:)?/+")
_AUTHORITY_END_RE = re.compile(r"[/?#]")
# What a run is replaced with when its userinfo cannot be bounded.
_URL_PLACEHOLDER = "<url>"


def _without_userinfo(match):
    """Return one url-ish run of text without the userinfo of its authority.

    A run is a candidate when it carries a scheme or leading slashes
    (``https://user:pw@host``, ``https:/user:pw@host`` which parses as a path,
    ``//user:pw@host``) or when a ``:`` sits before the ``@``
    (``user:pw@host``, the shape a scheme-less config produces). Any number of
    horizontal whitespace runs may sit inside the userinfo
    (``u:pa ss@host``); a newline never may, so a later ``@`` on another line
    is not folded in.
    Not detected: a bare address with no scheme, no slashes and no colon, so
    ``me@example.com`` in prose is untouched. The authority is then
    delimited by its own bounds instead of a ``://`` anchor. An ``@`` in the
    authority with no ``@`` after it is userinfo: it is split on its LAST
    ``@`` (an unescaped ``@`` in the password belongs to the credentials),
    and the raw ``host[:port]`` is kept as written, so a malformed port
    survives.

    Any other ``@`` cannot be bounded, so the run fails closed and becomes
    ``<url>``. That covers a path or query ``@``
    (``https://host/p?email=me@example.com``) as well as a raw ``/`` inside
    the password (``https://u:pw/x@h``): a wrongly redacted link is better
    than a leaked credential.
    """
    text = match.group()
    slashed = _AUTHORITY_START_RE.match(text)
    start = slashed.end() if slashed else 0
    found = _AUTHORITY_END_RE.search(text, start)
    end = found.start() if found else len(text)
    authority = text[start:end]
    if "@" in authority and "@" not in text[:start] + text[end:]:
        return text[:start] + authority.rpartition("@")[2] + text[end:]
    # _USERINFO_RE only matches runs carrying an "@", so this always redacts.
    return _URL_PLACEHOLDER


def _strip_userinfo(text):
    """Remove any userinfo from the urls in text, keeping host and port."""
    return _USERINFO_RE.sub(_without_userinfo, text)


def _split_url_userinfo(url):
    """Return ``(url_without_userinfo, user, password)``.

    Credentials embedded in a URL would end up in tracebacks and reports, so
    they are lifted out and used as basic-auth credentials instead.
    """
    # urlparse drops these from the netloc, which would make the replace below
    # miss; removing them up front keeps netloc verbatim in the url.
    url = re.sub(r"[\t\n\r]", "", url or "")
    parsed = urlparse(url)
    if "@" not in parsed.netloc:
        return url, None, None
    user = parsed.username
    password = parsed.password
    clean = url.replace(parsed.netloc, parsed.netloc.rpartition("@")[2], 1)
    clean = clean.rstrip("/")
    return (
        clean,
        unquote(user) if user else None,
        (unquote(password) if password else None),
    )


def _is_gateway_url(url):
    """Return True for the API gateway, which always carries a cloud id."""
    return (
        _host(url) == "api.atlassian.com"
        and "/ex/jira/" in urlparse((url or "").lower()).path
    )


def _host(url):
    """Return the bare host of url, tolerating a missing scheme.

    Netloc would keep a port and any userinfo, which would hide the host.
    """
    url = (url or "").lower()
    host = urlparse(url).hostname
    if host:
        return host
    return url.split("/")[0].split(":")[0]


class JiraConfigError(ValueError):
    """A Jira configuration that cannot work: shown to the user, so its
    message must stay free of secrets."""


class JiraOAuthMintError(RuntimeError):
    """An OAuth 2.0 access token cannot be minted; the message is safe to
    show, it never contains the client secret."""


class _CappedRetry(urllib3.Retry):
    """Retry that will not wait longer than MAX_RETRY_AFTER seconds.

    urllib3 honours ``Retry-After`` verbatim, so a 429 carrying an hour
    would block one attempt for an hour. Capping the parsed value bounds the
    wait without sleeping here. Both the mint and the Jira session mount it.
    """

    def get_retry_after(self, response):
        try:
            seconds = super().get_retry_after(response)
        except (ValueError, TypeError, urllib3.exceptions.InvalidHeader):
            # An unparseable value raises inside urllib3's sleep, escaping
            # every handler: treat it as no header at all.
            return None
        if not seconds:
            return seconds
        return min(seconds, MAX_RETRY_AFTER)


ResolvedAuth = collections.namedtuple(
    "ResolvedAuth",
    "mode api_url site_url warnings username password",
)


UNUSED_CLOUD_ID_WARNING = (
    "pytest-jira: cloud_id only applies to a Jira Cloud service account; "
    "without an OAuth 2.0 credential it is ignored and %s is used as "
    "given. Remove it (--jira-cloud-id, PYTEST_JIRA_CLOUD_ID or cloud_id in "
    "jira.cfg) if this is a Server/DC instance."
)
CLOUD_OAUTH_NEEDS_CLOUD_ID = (
    "An OAuth 2.0 service account needs the cloud id: pass --jira-cloud-id "
    "<cloudId> (or set cloud_id in jira.cfg / PYTEST_JIRA_CLOUD_ID). The "
    "plugin builds https://api.atlassian.com/ex/jira/<cloudId> from it."
)
GATEWAY_URL = "https://api.atlassian.com/ex/jira/{cloud_id}"


def _resolve_auth(
    url, username, password, token, cloud_id, oauth_client_id, oauth_secret
):
    """Decide the auth mode once and derive the URL for API requests.

    Returns a :class:`ResolvedAuth`: ``mode`` (one of the ``AUTH_*``
    constants, or ``None`` when no credentials are configured), ``api_url``
    (where requests go), ``site_url`` (what browse links use, empty when it
    cannot be derived), ``warnings`` (messages for stderr) and the effective
    ``username``/``password`` (which may come from the url's userinfo).

    Only a service account without a cloud id raises
    :class:`JiraConfigError`: every other combination is left to fail at
    request time, the way a plain token or a plain url always has.
    """
    url = (url or "").rstrip("/")
    warnings = []
    url, url_user, url_password = _split_url_userinfo(url)
    if url_user:
        warnings.append(
            "pytest-jira: credentials embedded in the url are used for "
            "basic auth; prefer --jira-user/--jira-token (or the "
            "PYTEST_JIRA_USERNAME/PYTEST_JIRA_TOKEN variables)."
        )
        if not username:
            username = url_user
            password = password or url_password
    has_user = bool(username and (token or password))
    if bool(oauth_client_id) != bool(oauth_secret):
        # A leftover half-pair must not break a working user connection.
        warnings.append(
            "pytest-jira: The OAuth 2.0 credential is incomplete: set both "
            "--jira-oauth-client-id and --jira-oauth-client-secret (or "
            "neither). Ignoring it."
        )
    has_oauth = bool(oauth_client_id and oauth_secret)
    if has_user and has_oauth:
        warnings.append(
            "pytest-jira: the OAuth 2.0 credential is ignored because a "
            "username with a token/password is configured; remove one of "
            "the two."
        )
        has_oauth = False
    if password and not username:
        warnings.append(
            "pytest-jira: a password without a username is ignored; Jira "
            "needs --jira-user <email> with --jira-token (or "
            "--jira-password on Server/DC)."
        )
    if has_user:
        mode = AUTH_BASIC
    elif has_oauth:
        mode = AUTH_OAUTH
        for name, value in (
            ("token", token),
            ("username", username),
            ("password", password),
        ):
            if value:
                warnings.append(
                    "pytest-jira: the %s is ignored because an OAuth 2.0 "
                    "service account is configured." % name
                )
    elif token:
        mode = AUTH_PAT
    else:
        mode = None

    if mode != AUTH_OAUTH:
        if cloud_id:
            warnings.append(UNUSED_CLOUD_ID_WARNING % _strip_userinfo(url))
        return ResolvedAuth(mode, url, url, warnings, username, password)

    if not cloud_id:
        raise JiraConfigError(CLOUD_OAUTH_NEEDS_CLOUD_ID)
    api_url = GATEWAY_URL.format(cloud_id=cloud_id)
    site_url = "" if _is_gateway_url(url) else url
    if not site_url:
        warnings.append(
            "pytest-jira: url is the API gateway, which is not browsable, "
            "so skip/xfail reasons cannot link to an issue page. Use the "
            "site URL plus cloud_id for clickable links."
        )
    return ResolvedAuth(mode, api_url, site_url, warnings, username, password)


def _unauthorized_status(exc):
    """Return 401 for an authentication failure, or None for anything else.

    A 403 authenticated the caller (it just may not read the resource), so
    only 401 means the credentials are wrong.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if status == 401 else None


OAUTH_AUTH_ERROR_HINT = (
    "Jira rejected the credentials for %s (HTTP %s).\n"
    "The access token was minted from the OAuth 2.0 credential, so check "
    "PYTEST_JIRA_OAUTH_CLIENT_ID / PYTEST_JIRA_OAUTH_CLIENT_SECRET "
    "(--jira-oauth-client-id / --jira-oauth-client-secret) and the cloud "
    "id, and that the service account has product access to Jira plus "
    "Browse projects on every project you mark tests with."
)


def _hint(exc, conn):
    """Return actionable guidance for a failed request, or None.

    Only an OAuth 2.0 service account gets a hint: a user or a Server/DC
    connection keeps the behaviour it always had. A 401 is always about the
    credential (a permission problem on a single issue is a 403, and a token
    can be revoked between two calls); a failed probe with any other status
    means the url, the cloud id or the network is wrong. Silence would leave a
    run skipping every test with no explanation.
    """
    if not conn.oauth_mode:
        return None
    url = _strip_userinfo(conn.site_url or conn.get_url())
    status = _unauthorized_status(exc)
    if status:
        return OAUTH_AUTH_ERROR_HINT % (url, status)
    if conn.is_connected:
        return None
    if getattr(getattr(exc, "response", None), "status_code", None) == 404:
        advice = "Check --jira-url and --jira-cloud-id."
    else:
        advice = "Check the Jira url, network access and the service account."
    return (
        "Could not authenticate the OAuth 2.0 service account against "
        "%s (%s): %s\n%s"
        % (url, type(exc).__name__, _strip_userinfo(str(exc)), advice)
    )


def _write_stderr(message, config=None):
    """Write to the real stderr, bypassing pytest's capture.

    A hint raised while a test runs is captured and thrown away for a skipped
    or passing test, which is exactly when it matters. It never raises: it
    runs from a ``finally`` where a ``Skipped`` or an ``Exit`` may already be
    in flight, and a failure here would replace it with an ERROR.
    """
    try:
        capture = None
        if config is not None:
            capture = config.pluginmanager.getplugin("capturemanager")
        if capture is not None:
            with capture.global_and_fixture_disabled():
                print(message, file=sys.stderr)
                return
    except Exception:
        # A torn-down capture manager, or a pytest without the hook.
        pass
    try:
        print(message, file=sys.stderr)
    except Exception:  # pragma: no cover - stderr is unusable
        pass


PROBE_FORBIDDEN_WARNING = (
    "pytest-jira: Jira answered 403 for /rest/api/2/myself. The service "
    "account may lack read:jira-user, which is fine, but if every marked "
    "issue looks missing (404) grant it Browse projects on those projects."
)
TOKEN_REMINT_WARNING = (
    "pytest-jira: Jira answered 401 for %s with the cached access token; "
    "dropping it and retrying with a freshly minted one."
)


def _report_notices(conn, config=None):
    """Emit the warnings a request only records, where a config exists.

    ``check_connection`` and ``_jira_request`` run without a config when a
    fixture calls them, and only a drain from a ``finally`` can report what
    they recorded (``_write_stderr`` never raises, so this cannot mask the
    exception in flight). Each notice is printed once per connection.
    """
    if conn.probe_forbidden:
        conn.probe_forbidden = False
        _write_stderr(PROBE_FORBIDDEN_WARNING, config)
    if conn.remint_url and not conn.remint_warned:
        conn.remint_warned = True
        _write_stderr(TOKEN_REMINT_WARNING % conn.remint_url, config)


def _report(exc, conn, strategy, config=None):
    """Report a failed request once: warn, exit or re-raise.

    Only the OAuth 2.0 service-account path gets fail-fast diagnostics: a user
    or a Server/DC connection keeps the behaviour it always had (raise under
    ``strict``, skip/ignore otherwise). Must be called from an ``except``
    handler: the strict path re-raises so the traceback stays intact.
    """
    mint_failure = isinstance(exc, JiraOAuthMintError)
    hint = None if mint_failure else _hint(exc, conn)
    # Redact at the reporting boundary: a requests message embeds the raw url,
    # userinfo included. Rewriting ``args`` in place keeps this very exception
    # object (.response/.request stay usable) and chains no unredacted copy
    # into the traceback.
    exc.args = (_strip_userinfo(str(exc)),)
    # A mint error is the whole story: the probe wording would misdiagnose it
    # as a wrong url or cloud id.
    notice = str(exc) if mint_failure else hint
    if strategy == STRICT:
        if mint_failure:
            # No request can succeed without a token: nothing to retry.
            pytest.exit(str(exc), returncode=USAGE_ERROR_CODE)
        if hint and getattr(exc, "response", None) is not None:
            # Not the default INTERRUPTED (2): a broken credential setup is a
            # usage error, not a Ctrl-C, and CI should not retry it. A network
            # failure is not a usage error: warned below, then raised.
            pytest.exit(hint, returncode=USAGE_ERROR_CODE)
    # Under skip or ignore every test would skip, and a green run would hide a
    # credential that cannot work. One line per connection.
    if notice and notice not in conn.warned:
        conn.warned.add(notice)
        _write_stderr(notice, config)
    if strategy == STRICT:
        raise


class JiraHooks(object):
    def __init__(
        self,
        connection,
        marker,
        version=None,
        components=None,
        resolved_statuses=None,
        resolved_resolutions=None,
        run_test_case=DEFAULT_RUN_TEST_CASE,
        strict_xfail=False,
        connection_error_strategy=None,
        return_jira_metadata=False,
    ):
        self.conn = connection
        self.mark = marker
        self.components = set(components) if components else None
        self.version = version
        if resolved_statuses:
            self.resolved_statuses = resolved_statuses
        else:
            self.resolved_statuses = DEFAULT_RESOLVE_STATUSES
        if resolved_resolutions:
            self.resolved_resolutions = resolved_resolutions
        else:
            self.resolved_resolutions = []
        self.run_test_case = run_test_case
        self.connection_error_strategy = connection_error_strategy
        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

        self.strict_xfail = strict_xfail
        self.return_jira_metadata = return_jira_metadata

    def is_issue_resolved(self, issue_id):
        """
        Returns whether the provided issue ID is resolved (True|False).  Will
        cache issues to speed up subsequent calls for the same issue.
        """
        # Access Jira issue (may be cached)
        if issue_id not in self.issue_cache:
            try:
                self.issue_cache[issue_id] = self.conn.get_issue(
                    issue_id, self.return_jira_metadata
                )
            except requests.RequestException as e:
                # A 404 means "this issue is not visible" only after the
                # connection itself authenticated. A 404 from the probe is a
                # wrong url or cloud id, and must not be mistaken for a
                # missing issue (which degrades into a silent skip).
                missing = (
                    self.conn.is_connected
                    and getattr(e.response, "status_code", None) == 404
                )
                if not missing:
                    raise
                self.issue_cache[issue_id] = self.mark.get_default(issue_id)
        if self.return_jira_metadata:
            issue = JiraIssueSchema().dump(self.issue_cache[issue_id])
            return JiraIssue(issue_id, **issue)

        # Skip test if issue remains unresolved
        if self.issue_cache[issue_id] is None:
            return True
        if self.issue_cache[issue_id]["status"] in self.resolved_statuses and (
            # Issue is resolved if resolutions are not specified
            # Or if the issue's resolution mathces a resolved_resolution
            len(self.resolved_resolutions) == 0
            or self.issue_cache[issue_id]["resolution"]
            in self.resolved_resolutions
        ):
            return self.fixed_in_version(issue_id)
        else:
            return not self.is_affected(issue_id)

    def get_marker(self, item):
        if Version(pytest.__version__) >= Version("3.6.0"):
            return item.get_closest_marker("jira")
        else:
            return item.keywords.get("jira")

    def pytest_collection_modifyitems(self, config, items):
        for item in items:
            try:
                jira_ids = self.mark.get_jira_issues(item)
            except Exception as exc:
                pytest.exit(exc)

            jira_run = self.run_test_case

            marker = self.get_marker(item)
            if marker:
                jira_run = marker.kwargs.get("run", jira_run)

            for issue_id, skipif in jira_ids:
                try:
                    issue = self.is_issue_resolved(issue_id)
                    if config.option.return_jira_metadata:
                        # Get the resolution resolution status
                        issue = issue.resolution in self.resolved_resolutions
                    if not issue:
                        if callable(skipif):
                            if not skipif(self.issue_cache[issue_id]):
                                continue
                        else:
                            if not skipif:
                                continue
                        site_url = self.conn.site_url
                        # The API gateway has no browsable site url, and a
                        # redacted one is not a link either: a bare issue id
                        # beats a useless "<url>/browse/ORG-1".
                        redacted = _strip_userinfo(site_url)
                        reason = (
                            "%s/browse/%s" % (redacted, issue_id)
                            if site_url and redacted != _URL_PLACEHOLDER
                            else issue_id
                        )
                        if jira_run:
                            item.add_marker(pytest.mark.xfail(reason=reason))
                        else:
                            item.add_marker(pytest.mark.skip(reason=reason))
                except (requests.RequestException, JiraOAuthMintError) as e:
                    _report(
                        e, self.conn, self.connection_error_strategy, config
                    )
                    if self.connection_error_strategy == SKIP:
                        item.add_marker(
                            pytest.mark.skip(
                                reason=CONNECTION_SKIP_MESSAGE
                                % _strip_userinfo(str(e))
                            )
                        )
                    else:
                        return
                finally:
                    # A recorded notice must survive a raising issue check
                    # (and the exit the strict strategy raises).
                    _report_notices(self.conn, config)

    def fixed_in_version(self, issue_id):
        """
        Return True if:
            jira_product_version was not specified
            OR issue was fixed for jira_product_version
        else return False
        """
        if not self.version:
            return True
        affected = self.issue_cache[issue_id].get("versions")
        fixed = self.issue_cache[issue_id].get("fixed_versions")
        return self.version not in (affected - fixed)

    def is_affected(self, issue_id):
        """
        Return True if:
            at least one component affected (or not specified)
            version is affected (or not specified)
        else return False
        """
        return self._affected_version(issue_id) and self._affected_components(
            issue_id
        )

    def _affected_version(self, issue_id):
        affected = self.issue_cache[issue_id].get("versions")
        if not self.version or not affected:
            return True
        return self.version in affected

    def _affected_components(self, issue_id):
        affected = self.issue_cache[issue_id].get("components")
        if not self.components or not affected:
            return True
        return bool(self.components.intersection(affected))


# "OAuth 2.0 credentials for service accounts": the client secret is
# exchanged here for a short-lived access token. The secret itself is never
# sent to the API gateway.
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
# Re-mint this many seconds before a cached access token expires.
SA_TOKEN_REFRESH_MARGIN = 120
# Floor for a cached lifetime reported as 0 or as something shorter than
# SA_TOKEN_REFRESH_MARGIN: such an entry would be dead on arrival and turn
# every Jira request into another mint.
SA_TOKEN_MIN_LIFETIME = 300
# The token endpoint is a fixed Atlassian service and answers quickly.
TOKEN_REQUEST_TIMEOUT = 15
# Retry policy for the token endpoint only.
TOKEN_RETRY_TOTAL = 3
TOKEN_RETRY_BACKOFF_FACTOR = 0.5
# Lifetime assumed when the token endpoint reports none.
SA_TOKEN_ASSUMED_LIFETIME = 3600
# What a transport failure looks like, at both layers the mint can see.
_TRANSPORT_ERRORS = (
    requests.RequestException,
    urllib3.exceptions.HTTPError,
)
_SA_TOKEN_CACHE = {}
_SA_TOKEN_FAILURES = {}


def _credential_key(client_id, client_secret):
    """Return a cache key that does not retain the client secret."""
    digest = hashlib.sha256((client_secret or "").encode()).hexdigest()
    return client_id, digest


def _forget_access_token(client_id, client_secret):
    """Drop a cached token and any remembered mint failure."""
    key = _credential_key(client_id, client_secret)
    _SA_TOKEN_CACHE.pop(key, None)
    _SA_TOKEN_FAILURES.pop(key, None)


def _token_session():
    """Return a session that retries the token endpoint on 429/5xx.

    A transient mint failure should not kill the run: it is one extra request
    next to the Jira calls, and ``Retry-After`` is honoured.
    """
    session = requests.Session()
    retries = _CappedRetry(
        total=TOKEN_RETRY_TOTAL,
        backoff_factor=TOKEN_RETRY_BACKOFF_FACTOR,
        respect_retry_after_header=True,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods={"POST"},
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    return session


def _mint_access_token(client_id, client_secret):
    """Return a short-lived access token for an OAuth 2.0 credential.

    POSTs ``client_credentials`` to the Atlassian token endpoint and caches
    the result until ``SA_TOKEN_REFRESH_MARGIN`` seconds before it expires.
    TLS verification stays on and redirects are not followed, because the
    request carries the client secret.
    """
    key = _credential_key(client_id, client_secret)
    now = time.monotonic()
    cached = _SA_TOKEN_CACHE.get(key)
    if cached and cached[1] - SA_TOKEN_REFRESH_MARGIN > now:
        return cached[0]
    remembered = _SA_TOKEN_FAILURES.get(key)
    if remembered:
        raise JiraOAuthMintError(remembered)
    session = _token_session()
    try:
        try:
            response = session.post(
                ATLASSIAN_TOKEN_URL,
                json={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                verify=True,
                allow_redirects=False,
                timeout=TOKEN_REQUEST_TIMEOUT,
            )
        except _TRANSPORT_ERRORS as exc:
            # Transient: do not remember it, the next call may well succeed.
            raise JiraOAuthMintError(
                "Could not mint an Atlassian access token from the OAuth "
                "2.0 credential (%s: %s)." % (type(exc).__name__, exc)
            ) from exc
        if response.status_code != 200:
            message = (
                "Could not mint an Atlassian access token from the OAuth "
                "2.0 credential (HTTP %s): check "
                "PYTEST_JIRA_OAUTH_CLIENT_ID and "
                "PYTEST_JIRA_OAUTH_CLIENT_SECRET." % response.status_code
            )
            if response.status_code in (400, 401, 403):
                # A rejected credential will not heal: remember it to save a
                # POST per marked issue. A 429/5xx that survived the retries is
                # transient, so it is raised uncached and can retry.
                _SA_TOKEN_FAILURES[key] = message
            raise JiraOAuthMintError(message)
        try:
            payload = response.json()
            access_token = payload["access_token"]
            raw_expires = payload.get("expires_in")
            # absent or null: assume the usual hour. An explicit 0 or negative
            # keeps meaning "no usable lifetime" and falls to the short floor.
            expires_in = (
                SA_TOKEN_ASSUMED_LIFETIME
                if raw_expires is None
                else float(raw_expires)
            )
        except (ValueError, KeyError, TypeError) as exc:
            # A garbled response says nothing about the credential: retry.
            raise JiraOAuthMintError(
                "Could not mint an Atlassian access token: unexpected "
                "response from %s." % ATLASSIAN_TOKEN_URL
            ) from exc
        if not isinstance(access_token, str) or not access_token:
            raise JiraOAuthMintError(
                "Could not mint an Atlassian access token: no access token "
                "in the response from %s." % ATLASSIAN_TOKEN_URL
            )
        # A lifetime shorter than the refresh margin would make the entry
        # dead on arrival and turn every Jira request into another mint.
        expires_in = max(expires_in, SA_TOKEN_MIN_LIFETIME)
        _SA_TOKEN_CACHE[key] = (access_token, now + expires_in)
        return access_token
    finally:
        session.close()


class JiraSiteConnection(object):
    def __init__(
        self,
        url,
        username=None,
        password=None,
        verify=True,
        token=None,
        oauth_client_id=None,
        oauth_client_secret=None,
        cloud_id=None,
    ):
        self.verify = verify
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        resolved = _resolve_auth(
            url,
            username,
            password,
            token,
            cloud_id,
            oauth_client_id,
            oauth_client_secret,
        )
        (
            self.mode,
            self.url,
            site_url,
            self.warnings,
            username,
            password,
        ) = resolved
        # The URL the user configured: the API gateway is not browsable, so
        # human-facing links (skip/xfail reasons) use the site URL instead.
        self.site_url = (site_url or "").rstrip("/")
        self.is_connected = False
        # Recorded by check_connection / _jira_request, drained by a caller
        # that has a config (see _report_notices): pytest capture would
        # otherwise swallow them.
        self.probe_forbidden = False
        # First request whose 401 got a fresh token; one slot, it is reported
        # once per connection.
        self.remint_url = None
        # A freshly minted token was itself rejected. It replays nothing
        # (unlike auth_dead) and is cleared only by a response that proves the
        # credential authenticated, so a 5xx or 429 cannot re-arm the heal and
        # mint once per issue.
        self.remint_rejected = False
        # One stderr line per distinct notice for the diagnostics of _report.
        self.warned = set()
        self.remint_warned = False
        # The probe's 401 once it survived a fresh mint: no retry can heal it,
        # so later attempts *replay* it instead of spending 2 token POSTs and
        # 2 gateway calls per marked issue (the opposite of remint_rejected:
        # do not turn this into a bare flag). Only check_connection sets it.
        self.auth_dead = None

        self.basic_auth = None
        self.headers = None
        self.oauth_mode = False
        if self.mode in (AUTH_BASIC, AUTH_PAT) and self.url.lower().startswith(
            "http://"
        ):
            # verify=False *is* the documented opt-in for insecure transport
            # (--jira-no-ssl-verify): it is the only way to allow cleartext.
            if not verify:
                self.warnings.append(
                    "pytest-jira: credentials are sent over plain http "
                    "because --jira-no-ssl-verify is set. Use an https url "
                    "if you can."
                )
            else:
                raise JiraConfigError(
                    "Refusing to send credentials over plain http: use an "
                    "https url, or pass --jira-no-ssl-verify (or "
                    "ssl_verification = False) to send them in clear text "
                    "anyway."
                )
        if self.mode == AUTH_BASIC:
            self.basic_auth = (username, token or password)
        elif self.mode == AUTH_PAT:
            self.headers = {"Authorization": "Bearer %s" % token}
        elif self.mode == AUTH_OAUTH:
            if not (
                _is_gateway_url(self.url)
                and self.url.lower().startswith("https://")
            ):
                # Defence in depth: _resolve_auth already builds the gateway
                # url, so this only guards direct use of this class, where an
                # Atlassian access token must never reach another host.
                raise JiraConfigError(
                    "An OAuth 2.0 service account must talk to "
                    "https://api.atlassian.com/ex/jira/<cloudId>, not %s."
                    % _strip_userinfo(self.url)
                )
            if not verify:
                self.warnings.append(
                    "pytest-jira: --jira-no-ssl-verify is ignored for an "
                    "OAuth 2.0 service account: its access token is only "
                    "sent over verified TLS."
                )
                self.verify = True
            self.oauth_mode = True

        self.session = requests.Session()

    def _authorization_headers(self):
        """Return the headers for one request.

        In OAuth mode the client secret is exchanged for a short-lived access
        token on first use (and cached): the secret never goes on the wire.
        """
        if not self.oauth_mode:
            return self.headers
        token = _mint_access_token(
            self.oauth_client_id, self.oauth_client_secret
        )
        return {"Authorization": "Bearer %s" % token}

    def setup_retries(self, total, backoff_factor):
        # _CappedRetry, not urllib3.Retry: an uncapped Retry-After (a 429
        # carrying an hour) would otherwise stall an attempt for an hour.
        retries = _CappedRetry(
            total=total,
            backoff_factor=backoff_factor,
            respect_retry_after_header=True,  # use retry-after header
            status_forcelist=urllib3.Retry.RETRY_AFTER_STATUS_CODES,
            allowed_methods={
                "GET",
            },
        )
        self.session.mount(
            self.url, requests.adapters.HTTPAdapter(max_retries=retries)
        )

    def _send(self, url, method, kwargs):
        """Send one request with whichever credentials this mode uses."""
        kwargs.setdefault("timeout", JIRA_REQUEST_TIMEOUT)
        headers = self._authorization_headers()
        if self.basic_auth:
            return self.session.request(
                method, url, auth=self.basic_auth, **kwargs
            )
        if headers:
            return self.session.request(method, url, headers=headers, **kwargs)
        return self.session.request(method, url, **kwargs)

    def _jira_request(self, url, method="get", **kwargs):
        if "verify" not in kwargs:
            kwargs["verify"] = self.verify

        if self.auth_dead is not None:
            # Already definitive (see check_connection): replay the remembered
            # failure without touching the network. with_traceback(None) keeps
            # the object (.response/.request stay usable) without growing its
            # traceback on every replay.
            raise self.auth_dead.with_traceback(None)

        rsp = self._send(url, method, kwargs)
        if (
            rsp.status_code == 401
            and self.oauth_mode
            and not self.remint_rejected
        ):
            # A cached access token can be revoked or rotated server side:
            # drop it and retry with a fresh one, saying so once.
            _forget_access_token(self.oauth_client_id, self.oauth_client_secret)
            if not self.remint_url:
                self.remint_url = _strip_userinfo(url)
            rsp = self._send(url, method, kwargs)
            if rsp.status_code == 401:
                # Deterministic: one heal only, see remint_rejected.
                self.remint_rejected = True
        if rsp.status_code not in (401, 429) and not (
            500 <= rsp.status_code < 600
        ):
            # A 403 proves the credential authenticated; 5xx and 429 do not.
            self.remint_rejected = False
        rsp.raise_for_status()
        return rsp

    def check_connection(self):
        """Validate authentication and reachability. Does not verify browse
        permissions.

        Only 401 means the credentials are wrong: a 403 from ``/myself`` means
        the token authenticated but may not read its own profile, which a
        scoped service account often cannot (``read:jira-work`` alone).
        """
        auth_url = "{url}/rest/api/2/myself".format(url=self.url)
        try:
            self._jira_request(auth_url)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 401 and self.oauth_mode and not self.is_connected:
                # The probe's 401 outlived a fresh mint: no retry can heal
                # that, so remember it (later requests replay it).
                self.auth_dead = exc
                raise
            # Only a service account tolerates a 403: a user or Server/DC
            # connection keeps its previous failure behaviour.
            if status != 403 or not self.oauth_mode:
                raise
            # Tolerated, but recorded: without read:jira-user the profile probe
            # is forbidden, and if the account also lacks Browse projects every
            # issue answers 404 and looks merely "missing".
            self.probe_forbidden = True
        self.is_connected = True
        return True

    @retry(JSONDecodeError, tries=3, delay=2)
    def get_issue(self, issue_id, return_jira_metadata):
        if not self.is_connected:
            self.check_connection()
        issue_url = "{url}/rest/api/2/issue/{issue_id}".format(
            url=self.url, issue_id=issue_id
        )
        issue = self._jira_request(issue_url).json()
        field = issue["fields"]
        return (
            field
            if return_jira_metadata
            else {
                "components": set(
                    c["name"] for c in field.get("components", set())
                ),
                "versions": set(
                    v["name"] for v in field.get("versions", set())
                ),
                "fixed_versions": set(
                    v["name"] for v in field.get("fixVersions", set())
                ),
                "status": field["status"]["name"].lower(),
                "resolution": (
                    field["resolution"]["name"].lower()
                    if field["resolution"]
                    else None
                ),
            }
        )

    def get_url(self):
        return self.url


class JiraMarkerReporter(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(self, strategy, docs, pattern):
        self.issue_pattern = re.compile(pattern or self.issue_re)
        self.docs = docs
        self.strategy = strategy.lower()

    def _get_marks(self, item):
        marks = []
        if Version(pytest.__version__) >= Version("3.6.0"):
            for mark in item.iter_markers("jira"):
                marks.append(mark)
        else:
            if "jira" in item.keywords:
                marker = item.keywords["jira"]
                # process markers independently
                if not isinstance(marker, (list, tuple)):
                    marker = [marker]
                for mark in marker:
                    marks.append(mark)
        return marks

    def get_jira_issues(self, item):
        jira_ids = []
        for mark in self._get_marks(item):
            skip_if = mark.kwargs.get("skipif", True)

            if len(mark.args) == 0:
                raise TypeError("JIRA marker requires one, or more, arguments")

            for arg in mark.args:
                jira_ids.append((arg, skip_if))

        # Was a jira issue referenced in the docstr?
        if self.docs and item.function.__doc__:
            jira_ids.extend(
                [
                    (m.group(0), True)
                    for m in self.issue_pattern.finditer(item.function.__doc__)
                ]
            )

        # Filter valid issues, and return unique issues
        for jid, _ in set(jira_ids):
            if not self.issue_pattern.match(jid):
                raise ValueError(
                    "JIRA marker argument `%s` does not match pattern" % jid
                )
        return list(set(jira_ids))

    def get_default(self, jid):
        if self.strategy == "open":
            return {"status": "open"}
        if self.strategy == "strict":
            raise ValueError("JIRA marker argument `%s` was not found" % jid)
        if self.strategy == "warn":
            sys.stderr.write("JIRA marker argument `%s` was not found" % jid)
        return None


def _get_value(config, section, name, default=None):
    # raw=True: an ini value is not a template. Interpolating it would raise
    # InterpolationSyntaxError on a token holding a literal '%'.
    if config.has_option(section, name):
        return config.get(section, name, raw=True)
    return default


def _get_bool(config, section, name, default=False):
    if config.has_option(section, name):
        return config.getboolean(section, name, raw=True)
    return default


def pytest_addoption(parser):
    """
    Add a options section to py.test --help for jira integration.
    Parse configuration file, jira.cfg and / or the command line options
    passed.

    :param parser: Command line options.
    """
    group = parser.getgroup("JIRA integration")
    group.addoption(
        "--jira",
        action="store_true",
        default=False,
        dest="jira",
        help="Enable JIRA integration.",
    )

    # FIXME - Change to a credentials.yaml ?
    config = six.moves.configparser.ConfigParser()
    config.read(
        [
            os.path.join("/", "etc", "jira.cfg"),
            os.path.join(str(parser.extra_info["rootdir"]), "jira.cfg"),
            os.path.expanduser(os.path.join("~", "jira.cfg")),
            "jira.cfg",
        ]
    )

    group.addoption(
        "--jira-url",
        action="store",
        dest="jira_url",
        default=_get_value(config, "DEFAULT", "url"),
        metavar="url",
        # No %(default)s: jira.cfg may hold https://user:pw@host, and
        # --help is not the place to print a credential.
        help="JIRA url, e.g. https://<site>.atlassian.net",
    )
    group.addoption(
        "--jira-user",
        action="store",
        dest="jira_username",
        default=_get_value(config, "DEFAULT", "username"),
        metavar="username",
        help="JIRA username (your email on Jira Cloud)",
    )
    group.addoption(
        "--jira-password",
        action="store",
        dest="jira_password",
        default=_get_value(config, "DEFAULT", "password"),
        metavar="password",
        help="JIRA password, for basic auth on Server/Data Center; Jira "
        "Cloud requires an API token instead (--jira-token).",
    )
    group.addoption(
        "--jira-token",
        action="store",
        dest="jira_token",
        default=_get_value(config, "DEFAULT", "token"),
        metavar="token",
        help="JIRA token: the API token of --jira-user on Jira Cloud, or a "
        "personal access token on Jira Server/DC.",
    )
    group.addoption(
        "--jira-cloud-id",
        action="store",
        dest="jira_cloud_id",
        default=_get_value(config, "DEFAULT", "cloud_id"),
        metavar="cloud_id",
        help="JIRA Cloud id, used to build the API gateway URL of an "
        "OAuth 2.0 service account. Ignored for a user or a Server/DC "
        "connection.",
    )
    group.addoption(
        "--jira-oauth-client-id",
        action="store",
        dest="jira_oauth_client_id",
        default=_get_value(config, "DEFAULT", "oauth_client_id"),
        metavar="client_id",
        help="Atlassian OAuth 2.0 client id of a service account "
        "credential; a short-lived access token is minted with the client "
        "secret and sent as a bearer token.",
    )
    group.addoption(
        "--jira-oauth-client-secret",
        action="store",
        dest="jira_oauth_client_secret",
        default=_get_value(config, "DEFAULT", "oauth_client_secret"),
        metavar="client_secret",
        help="Atlassian OAuth 2.0 client secret for --jira-oauth-client-id. "
        "Prefer the PYTEST_JIRA_OAUTH_CLIENT_SECRET environment variable or "
        "jira.cfg: a command line value is visible in the process list.",
    )
    group.addoption(
        "--jira-no-ssl-verify",
        action="store_false",
        dest="jira_verify",
        default=_get_bool(
            config,
            "DEFAULT",
            "ssl_verification",
            True,
        ),
        help="Disable TLS verification for Jira requests; also allows a "
        "plain http url (insecure). Ignored for an OAuth 2.0 service "
        "account, whose access token is only sent over verified TLS.",
    )
    group.addoption(
        "--jira-components",
        action="store",
        nargs="+",
        dest="jira_components",
        default=_get_value(config, "DEFAULT", "components", ""),
        help="Used components",
    )
    group.addoption(
        "--jira-product-version",
        action="store",
        dest="jira_product_version",
        default=_get_value(config, "DEFAULT", "version"),
        help="Used version",
    )
    group.addoption(
        "--jira-marker-strategy",
        action="store",
        dest="jira_marker_strategy",
        default=_get_value(config, "DEFAULT", "marker_strategy", "open"),
        choices=["open", "strict", "ignore", "warn"],
        help="""Action if issue ID was not found
                    open - issue is considered as open (default)
                    strict - raise an exception
                    ignore - issue id is ignored
                    warn - write error message and ignore
                    """,
    )
    group.addoption(
        "--jira-disable-docs-search",
        action="store_false",
        dest="jira_docs",
        default=_get_bool(config, "DEFAULT", "docs_search", True),
        help="Issue ID in doc strings will be ignored",
    )
    group.addoption(
        "--jira-issue-regex",
        action="store",
        dest="jira_regex",
        default=_get_value(config, "DEFAULT", "issue_regex"),
        help="Replace default `[A-Z]+-[0-9]+` regular expression",
    )
    group.addoption(
        "--jira-resolved-statuses",
        action="store",
        dest="jira_resolved_statuses",
        default=_get_value(
            config,
            "DEFAULT",
            "resolved_statuses",
            ",".join(DEFAULT_RESOLVE_STATUSES),
        ),
        help="Comma separated list of resolved statuses (closed, " "resolved)",
    )
    group.addoption(
        "--jira-resolved-resolutions",
        action="store",
        dest="jira_resolved_resolutions",
        default=_get_value(config, "DEFAULT", "resolved_resolutions"),
        help="Comma separated list of resolved resolutions (done, " "fixed)",
    )
    group.addoption(
        "--jira-do-not-run-test-case",
        action="store_false",
        dest="jira_run_test_case",
        default=_get_bool(
            config,
            "DEFAULT",
            "run_test_case",
            DEFAULT_RUN_TEST_CASE,
        ),
        help="If set and test is marked by Jira plugin, such "
        "test case is not executed.",
    )
    group.addoption(
        CONNECTION_ERROR_FLAG_NAME,
        action="store",
        dest="jira_connection_error_strategy",
        default=_get_value(config, "DEFAULT", "error_strategy", "strict"),
        choices=[STRICT, SKIP, IGNORE],
        help="""Action if there is a connection issue
                    strict - raise an exception
                    ignore - marker is ignored
                    skip - skip any test that has a marker
                    """,
    )
    group.addoption(
        "--jira-connection-retry-total",
        action="store",
        type=int,
        dest="jira_connection_retry_total",
        default=_get_value(config, "DEFAULT", "connection_retry_total", 5),
        help="Number of connection retries",
    )
    group.addoption(
        "--jira-connection-retry-backoff-factor",
        action="store",
        type=float,
        dest="jira_connection_retry_backoff_factor",
        default=_get_value(
            config, "DEFAULT", "connection_retry_backoff_factor", 0.2
        ),
        help="Number of connection retries",
    )
    group.addoption(
        "--jira-return-metadata",
        action="store_true",
        dest="return_jira_metadata",
        default=_get_value(config, "DEFAULT", "return_jira_metadata"),
        help="If set, will return Jira issue with ticket metadata",
    )


def pytest_unconfigure(config):
    """Drop cached service-account tokens when the session ends."""
    _SA_TOKEN_CACHE.clear()
    _SA_TOKEN_FAILURES.clear()


MISSING_URL_ERROR = (
    "--jira needs a Jira url: pass --jira-url, set PYTEST_JIRA_URL or put "
    "url in jira.cfg. Without it no issue check can run."
)


def pytest_configure(config):
    """Register the plugin, resolving the Jira auth mode for this run.

    Always registers the ``jira`` marker. With ``--jira`` it resolves the auth
    mode from the options and their ``PYTEST_JIRA_*`` overrides, raises
    ``pytest.UsageError`` when no url is configured, prints the derived
    connection warnings to stderr, mounts the retry policy and registers the
    :class:`JiraHooks` plugin under :data:`PLUGIN_NAME`.

    :param config: configuration object
    """
    config.addinivalue_line(
        "markers",
        "jira([issue_id,...], run=True): xfail the test if the provided JIRA "
        "issue(s) remains unresolved.  When 'run' is True, the test will be "
        "executed.  If a failure occurs, the test will xfail. "
        "When 'run' is False, the test will be skipped prior to execution. "
        "See https://github.com/rhevm-qe-automation/pytest_jira",
    )
    components = config.getvalue("jira_components")
    if isinstance(components, six.string_types):
        components = [c for c in components.split(",") if c]

    resolved_statuses = config.getvalue("jira_resolved_statuses")
    if isinstance(resolved_statuses, six.string_types):
        resolved_statuses = [
            s.strip().lower() for s in resolved_statuses.split(",") if s.strip()
        ]
    if not resolved_statuses:
        resolved_statuses = list(DEFAULT_RESOLVE_STATUSES)

    resolved_resolutions = config.getvalue("jira_resolved_resolutions")
    if isinstance(resolved_resolutions, six.string_types):
        resolved_resolutions = [
            s.strip().lower()
            for s in resolved_resolutions.split(",")
            if s.strip()
        ]
    if not resolved_resolutions:
        resolved_resolutions = []

    if config.getvalue("jira"):
        jira_url = _get_setting("PYTEST_JIRA_URL", config, "jira_url")
        if not jira_url:
            raise pytest.UsageError(MISSING_URL_ERROR)
        try:
            jira_connection = JiraSiteConnection(
                jira_url,
                _get_setting("PYTEST_JIRA_USERNAME", config, "jira_username"),
                _get_setting("PYTEST_JIRA_PASSWORD", config, "jira_password"),
                config.getvalue("jira_verify"),
                _get_setting("PYTEST_JIRA_TOKEN", config, "jira_token"),
                oauth_client_id=_get_setting(
                    "PYTEST_JIRA_OAUTH_CLIENT_ID",
                    config,
                    "jira_oauth_client_id",
                ),
                oauth_client_secret=_get_setting(
                    "PYTEST_JIRA_OAUTH_CLIENT_SECRET",
                    config,
                    "jira_oauth_client_secret",
                ),
                cloud_id=_get_setting(
                    "PYTEST_JIRA_CLOUD_ID", config, "jira_cloud_id"
                ),
            )
        except JiraConfigError as exc:
            raise pytest.UsageError(str(exc))
        for warning in jira_connection.warnings:
            _write_stderr(warning, config)
        jira_connection.setup_retries(
            config.getvalue("jira_connection_retry_total"),
            config.getvalue("jira_connection_retry_backoff_factor"),
        )
        jira_marker = JiraMarkerReporter(
            config.getvalue("jira_marker_strategy"),
            config.getvalue("jira_docs"),
            config.getvalue("jira_regex"),
        )

        jira_plugin = JiraHooks(
            jira_connection,
            jira_marker,
            config.getvalue("jira_product_version"),
            components,
            resolved_statuses,
            resolved_resolutions,
            config.getvalue("jira_run_test_case"),
            config.getini("xfail_strict"),
            config.getvalue("jira_connection_error_strategy"),
            config.getvalue("return_jira_metadata"),
        )
        ok = config.pluginmanager.register(jira_plugin, PLUGIN_NAME)
        assert ok


def _jira_issue_checker(request):
    """Return a callable that reports whether a JIRA issue is still open."""

    def wrapper_jira_issue(issue_id):
        jira_plugin = request.config.pluginmanager.getplugin(PLUGIN_NAME)
        if jira_plugin:
            try:
                result = jira_plugin.is_issue_resolved(issue_id)
                if request.config.option.return_jira_metadata:
                    return result
                return not result  # return boolean representing of issue state
            except (requests.RequestException, JiraOAuthMintError) as e:
                strategy = request.config.getoption(CONNECTION_ERROR_FLAG_NAME)
                _report(e, jira_plugin.conn, strategy, request.config)
                if strategy == SKIP:
                    pytest.skip(
                        CONNECTION_SKIP_MESSAGE % _strip_userinfo(str(e))
                    )
            finally:
                # A recorded notice must survive a raising issue check (and
                # the skip/exit the strategy raises).
                _report_notices(jira_plugin.conn, request.config)

    return wrapper_jira_issue


@pytest.fixture
def jira_issue(request):
    """
    Returns a bool representing the state of the issue, or None if no
    connection could be made. See
    https://github.com/rhevm-qe-automation/pytest_jira#fixture-usage
    for more details
    """
    return _jira_issue_checker(request)


@pytest.fixture(scope="class")
def jira_issue_scope_class(request):
    """Class-scoped variant of :func:`jira_issue`."""
    return _jira_issue_checker(request)


@pytest.fixture(scope="module")
def jira_issue_scope_module(request):
    """Module-scoped variant of :func:`jira_issue`."""
    return _jira_issue_checker(request)


@pytest.fixture(scope="package")
def jira_issue_scope_package(request):
    """Package-scoped variant of :func:`jira_issue`."""
    return _jira_issue_checker(request)


@pytest.fixture(scope="session")
def jira_issue_scope_session(request):
    """Session-scoped variant of :func:`jira_issue`."""
    return _jira_issue_checker(request)
