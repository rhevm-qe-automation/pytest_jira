import os
import re
import time
from urllib.parse import urlunparse

import pytest
import requests
import urllib3
from packaging.version import Version

import pytest_jira as plugin
from pytest_jira import JiraOAuthMintError


def _http_error(status):
    """Return a requests HTTPError carrying the given status code."""
    error = requests.HTTPError()
    error.response = type("R", (), {"status_code": status})()
    return error


def _env(name):
    """Read one TEST_JIRA_* value, stripping a matched pair of quotes.

    Deliberately independent of the plugin's own helper: the suite must not
    normalize its inputs with the code it is testing.
    """
    value = (os.environ.get(name) or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


PUBLIC_JIRA_SERVER = _env("TEST_JIRA_URL") or "https://redhat.atlassian.net"
CLOUD_ID = _env("TEST_JIRA_CLOUD_ID")
OAUTH_CLIENT_ID = _env("TEST_JIRA_OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = _env("TEST_JIRA_OAUTH_CLIENT_SECRET")
HAS_OAUTH = bool(OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET)

# The plugin supports exactly two Jira Cloud ways: a user (email + API
# token, basic auth) or an OAuth 2.0 service account (client id + secret,
# which the plugin turns into a short-lived bearer token for the gateway).
URL_ARGS = ("--jira-url", PUBLIC_JIRA_SERVER)
if HAS_OAUTH and CLOUD_ID:
    URL_ARGS += ("--jira-cloud-id", CLOUD_ID)
CFG_URL_LINES = ["url = " + PUBLIC_JIRA_SERVER]
if HAS_OAUTH and CLOUD_ID:
    CFG_URL_LINES.append("cloud_id = " + CLOUD_ID)
# A Jira Cloud site and the API gateway built from its cloud id. Fictional:
# nothing in this module reaches them over the network.
CLOUD_SITE = "https://example.atlassian.net"
CLOUD_GATEWAY = "https://api.atlassian.com/ex/jira/abc-123"
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
    "ORG-1513": {
        "components": set(['component1', 'component2']),
        "versions": set(),
        "fixed_versions": set(),
        "status": "custom-status",
    },
    "ORG-1514": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
    },
    "ORG-1515": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
        "resolution": "won't fix"
    },
    "ORG-1516": {
        "components": set(['component2', 'component3']),
        "versions": set(["foo-0.1", "foo-0.2"]),
        "fixed_versions": set(["foo-0.2"]),
        "status": "closed",
        "resolution": "done"
    },
}


@pytest.mark.tryfirst
def pytest_collection_modifyitems(session, config, items):
    plug = config.pluginmanager.getplugin("jira_plugin")
    assert plug is not None
    plug.issue_cache.update(FAKE_ISSUES)
"""

PLUGIN_ARGS = ("--jira",) + URL_ARGS


TOKEN = _env("TEST_JIRA_TOKEN")
JIRA_USER = _env("TEST_JIRA_USER")
CREDS_CONFIGURED = HAS_OAUTH or bool(TOKEN)
MISSING_CREDS_REASON = (
    "Neither TEST_JIRA_OAUTH_CLIENT_ID/_SECRET nor TEST_JIRA_TOKEN is set"
)
JIRA_ACCESSIBLE_REASON = "Jira is not accessible with the configured creds"
TOKEN_SKIP_REASON = (
    "Jira credentials not configured or not accessible (see README)"
)

_JIRA_ACCESSIBLE = None
_JIRA_ACCESS_ERROR = None


def _jira_token_accessible():
    """Return True if we can connect to Jira with the current credentials."""
    global _JIRA_ACCESSIBLE, _JIRA_ACCESS_ERROR
    if _JIRA_ACCESSIBLE is not None:
        return _JIRA_ACCESSIBLE
    if not CREDS_CONFIGURED:
        _JIRA_ACCESSIBLE = False
        return False
    try:
        # Resolve the connection exactly the way the plugin does: one place
        # (JiraSiteConnection/_resolve_auth) decides the mode and the URL.
        if HAS_OAUTH:
            conn = plugin.JiraSiteConnection(
                url=PUBLIC_JIRA_SERVER,
                cloud_id=CLOUD_ID or None,
                oauth_client_id=OAUTH_CLIENT_ID,
                oauth_client_secret=OAUTH_CLIENT_SECRET,
            )
        else:
            conn = plugin.JiraSiteConnection(
                url=PUBLIC_JIRA_SERVER,
                username=JIRA_USER or None,
                token=TOKEN,
            )
        conn.check_connection()
        _JIRA_ACCESSIBLE = True
        return True
    except (
        requests.RequestException,
        ValueError,
        pytest.UsageError,
        JiraOAuthMintError,
    ) as e:
        # This runs at collection time from a skipif decorator, so any
        # unreachable/misconfigured Jira has to turn into a skip with a
        # reason rather than a collection error for the whole module.
        _JIRA_ACCESSIBLE = False
        _JIRA_ACCESS_ERROR = str(e)
        return False


def _token_skip_reason():
    if not CREDS_CONFIGURED:
        return MISSING_CREDS_REASON
    if not _jira_token_accessible():
        return "%s (%s)" % (JIRA_ACCESSIBLE_REASON, _JIRA_ACCESS_ERROR)
    return None


OAUTH_ARGS = (
    "--jira-oauth-client-id",
    "cid",
    "--jira-oauth-client-secret",
    "secret",
)


def _auth_args():
    """Return pytest args for the configured Jira credentials."""
    if HAS_OAUTH:
        return (
            "--jira-oauth-client-id",
            OAUTH_CLIENT_ID,
            "--jira-oauth-client-secret",
            OAUTH_CLIENT_SECRET,
        )
    if JIRA_USER:
        return ("--jira-user", JIRA_USER, "--jira-token", TOKEN)
    return ("--jira-token", TOKEN)


def _run_oauth_pytest(testdir, *extra, url=CLOUD_SITE):
    """Run pytest in-process as a Jira Cloud OAuth 2.0 service account.

    Every caller mocks the transport it needs; the argument list that
    describes the service-account setup is spelled out once here.
    """
    return testdir.runpytest(
        "--jira",
        "--jira-url",
        url,
        "--jira-cloud-id",
        "abc-123",
        *OAUTH_ARGS,
        *extra,
    )


@pytest.fixture(autouse=True)
def clean_jira_env(monkeypatch):
    for var in (
        "PYTEST_JIRA_URL",
        "PYTEST_JIRA_USERNAME",
        "PYTEST_JIRA_PASSWORD",
        "PYTEST_JIRA_TOKEN",
        "PYTEST_JIRA_CLOUD_ID",
        "PYTEST_JIRA_OAUTH_CLIENT_ID",
        "PYTEST_JIRA_OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def clean_token_cache():
    """No test inherits a minted token or a remembered mint failure."""
    plugin._SA_TOKEN_CACHE.clear()
    plugin._SA_TOKEN_FAILURES.clear()
    yield
    plugin._SA_TOKEN_CACHE.clear()
    plugin._SA_TOKEN_FAILURES.clear()


class TestJiraSiteConnectionAuth:
    """Unit tests for JiraSiteConnection auth modes."""

    def test_username_and_token_uses_basic_auth(self):
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
            username="user@example.com",
            token="api-token",
        )
        assert conn.basic_auth == ("user@example.com", "api-token")
        assert conn.headers is None

    def test_token_only_uses_bearer(self):
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
            token="my-token",
        )
        assert conn.basic_auth is None
        assert conn.headers == {"Authorization": "Bearer my-token"}

    def test_username_and_password_uses_basic_auth(self):
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
            username="user",
            password="pass",
        )
        assert conn.basic_auth == ("user", "pass")
        assert conn.headers is None

    def test_no_credentials(self):
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
        )
        assert conn.basic_auth is None
        assert conn.headers is None
        assert conn.mode is None

    def test_username_without_credentials(self):
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
            username="user",
        )
        assert conn.basic_auth is None
        assert conn.headers is None

    def test_password_without_a_username_warns(self):
        """A lone password authenticates nothing, so say so."""
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com",
            password="pw",
        )
        assert conn.basic_auth is None
        assert any(
            "password without a username" in w for w in conn.warnings
        ), conn.warnings

    def test_gateway_url_warns_that_it_is_not_browsable(self):
        """The gateway has no issue pages, so skip reasons cannot link."""
        conn = plugin.JiraSiteConnection(
            CLOUD_GATEWAY,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.site_url == ""
        assert any("not browsable" in w for w in conn.warnings), conn.warnings

    def test_setup_retries_caps_retry_after(self):
        """A 429 carrying an hour must not stall an attempt for an hour."""
        conn = plugin.JiraSiteConnection(
            url="https://jira.example.com", token="tok"
        )
        conn.setup_retries(total=3, backoff_factor=0.5)
        retries = conn.session.get_adapter(conn.url).max_retries
        assert isinstance(retries, plugin._CappedRetry)
        assert retries.total == 3
        assert retries.backoff_factor == 0.5
        assert retries.respect_retry_after_header is True
        response = type("R", (), {"headers": {"Retry-After": "3600"}})
        assert retries.get_retry_after(response) == 10


class TestJiraCloudAuth:
    """Jira Cloud: a user (email+token) or an OAuth service account."""

    def test_unauthorized_status_only_for_401(self):
        # a probe 403 is tolerated and later 403s arrive after the
        # connection authenticated
        assert plugin._unauthorized_status(_http_error(403)) is None
        assert plugin._unauthorized_status(_http_error(401)) == 401
        assert plugin._unauthorized_status(_http_error(500)) is None
        assert (
            plugin._unauthorized_status(plugin.requests.ConnectionError())
            is None
        )

    def test_bare_token_on_cloud_is_rejected(self):
        """Cloud accepts a user (email+token) or an OAuth service account."""
        for url in (CLOUD_SITE, CLOUD_GATEWAY):
            with pytest.raises(plugin.JiraConfigError) as exc:
                plugin.JiraSiteConnection(url, token="ATATT-token")
            message = str(exc.value)
            assert "--jira-user" in message, message
            assert "--jira-oauth-client-id" in message, message

    def test_request_error_text_hides_url_credentials(self):
        # built rather than written out: a literal credentials-in-URL would
        # be flagged by the repo's secret scanner, which is the point of it
        userinfo = "%s:%s@" % ("svc", "pw-for-test")
        url = urlunparse(
            (
                "https",
                userinfo + "site.atlassian.net",
                "/rest/api/2/myself",
                "",
                "",
                "",
            )
        )
        error = plugin.requests.ConnectionError(
            "Max retries exceeded with url: " + url
        )
        text = plugin._request_error_text(error)
        assert "pw-for-test" not in text, text
        assert userinfo not in text, text
        assert "site.atlassian.net" in text, text

    def test_cloud_host_without_scheme_is_recognized(self):
        assert plugin._is_cloud_site("example.atlassian.net")
        assert plugin._is_cloud_or_gateway("api.atlassian.com/ex/jira/x")
        assert not plugin._is_cloud_or_gateway("jira.example.com")

    def test_host_ignores_port_and_userinfo(self):
        assert plugin._host("https://example.atlassian.net:443") == (
            "example.atlassian.net"
        )
        assert plugin._is_cloud_or_gateway("https://example.atlassian.net:8443")
        assert plugin._is_gateway_url(
            "https://api.atlassian.com:443/ex/jira/abc-123"
        )
        userinfo = "%s:%s@" % ("user", "pw-for-test")
        assert plugin._host(
            "https://" + userinfo + "example.atlassian.net"
        ) == ("example.atlassian.net")

    def test_redacted_hides_userinfo_but_keeps_the_url(self):
        userinfo = "%s:%s@" % ("user", "pw-for-test")
        assert plugin._redacted("https://" + userinfo + "host.example/x") == (
            "https://host.example/x"
        )
        assert plugin._redacted(
            "https://" + userinfo + "host.example:8443/x"
        ) == ("https://host.example:8443/x")
        # no userinfo: untouched, including an '@' in the path
        plain = "https://host.example/x@suffix"
        assert plugin._redacted(plain) == plain
        assert plugin._redacted("") == ""

    def test_clean_keeps_unbalanced_quotes(self):
        """Only a matched pair of quotes is stripped from a value."""
        assert plugin._clean('my"pass"') == 'my"pass"'
        assert plugin._clean("'abc") == "'abc"
        assert plugin._clean('"from-env"') == "from-env"

    def test_credentials_are_refused_over_plain_http(self):
        with pytest.raises(plugin.JiraConfigError) as exc:
            plugin.JiraSiteConnection("http://jira.example.com", token="pat")
        assert "plain http" in str(exc.value)

    def test_plain_http_allowed_when_insecure_transport_is_accepted(self):
        conn = plugin.JiraSiteConnection(
            "http://jira.example.com", token="pat", verify=False
        )
        assert conn.mode == plugin.AUTH_PAT
        assert any("plain http" in w for w in conn.warnings)

    def test_oauth_never_uses_unverified_tls(self):
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            verify=False,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.verify is True
        assert any("no-ssl-verify is ignored" in w for w in conn.warnings)

    def test_probe_403_is_tolerated_only_for_a_service_account(
        self, monkeypatch
    ):
        """A 403 from /myself is tolerated for a scoped SA, not for a PAT."""
        sent = []

        def forbidden(self, url, method="get", **kwargs):
            sent.append(url)
            raise _http_error(403)

        monkeypatch.setattr(
            plugin.JiraSiteConnection, "_jira_request", forbidden
        )

        pat = plugin.JiraSiteConnection("https://jira.example.com", token="pat")
        with pytest.raises(plugin.requests.HTTPError):
            pat.check_connection()
        assert pat.is_connected is False

        sa = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert sa.check_connection() is True
        assert sa.is_connected is True

    def test_tolerated_probe_403_is_recorded(self, monkeypatch, capsys):
        """The probe has no config here, so it records instead of printing."""

        def forbidden(self, url, method="get", **kwargs):
            raise _http_error(403)

        monkeypatch.setattr(
            plugin.JiraSiteConnection, "_jira_request", forbidden
        )
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.check_connection() is True
        assert conn.probe_forbidden is True
        # printing here would be swallowed by pytest's capture
        assert capsys.readouterr().err == ""

    def test_tolerated_probe_403_is_not_memoized_as_auth_dead(
        self, monkeypatch
    ):
        """Only a probe 401 may freeze the connection.

        A 403 authenticated the caller, so the issue fetch must still run:
        memoizing it would break a scoped service account that may read
        issues but not its own profile.
        """

        def transport(self, url, method="get", **kwargs):
            if url.endswith("/rest/api/2/myself"):
                raise _http_error(403)
            return type(
                "R",
                (),
                {
                    "status_code": 200,
                    "json": lambda s: {
                        "fields": {
                            "status": {"name": "open"},
                            "resolution": None,
                        }
                    },
                },
            )()

        monkeypatch.setattr(
            plugin.JiraSiteConnection, "_jira_request", transport
        )
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.check_connection() is True
        assert conn.is_connected is True
        assert conn.auth_dead is None
        issue = conn.get_issue("ORG-1", False)
        assert issue["status"] == "open"

    def test_probe_403_warning_survives_a_green_run(self, testdir, monkeypatch):
        """The warning is worthless if pytest's capture eats it."""
        seen = []

        def transport(self, url, method="get", **kwargs):
            seen.append(url)
            if url.endswith("/rest/api/2/myself"):
                raise _http_error(403)
            raise _http_error(404)

        monkeypatch.setattr(
            plugin.JiraSiteConnection, "_jira_request", transport
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        # green run: the issue 404 is a missing issue, not a broken setup
        assert result.ret == 0, output
        assert any(u.endswith("/rest/api/2/myself") for u in seen), seen
        stderr = result.stderr.str()
        assert "403 for /rest/api/2/myself" in stderr, stderr
        assert "Browse projects" in stderr, stderr

    def test_requests_carry_the_configured_timeout(self, monkeypatch):
        sent = {}

        class Session(object):
            def request(self, method, url, **kwargs):
                sent.update(kwargs)
                return type(
                    "R",
                    (),
                    {"status_code": 200, "raise_for_status": lambda s: None},
                )()

        conn = plugin.JiraSiteConnection(
            "https://jira.example.com", token="pat"
        )
        conn.session = Session()
        conn._jira_request("https://jira.example.com/rest/api/2/myself")
        assert sent.get("timeout") == plugin.JIRA_REQUEST_TIMEOUT, sent

    def test_jira_without_a_url_is_a_usage_error(self, testdir):
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest("--jira")
        assert result.ret == 4, result.stdout.str()
        assert "needs a Jira url" in (result.stdout.str() + result.stderr.str())

    def test_cloud_password_auth_is_a_config_error(self):
        with pytest.raises(plugin.JiraConfigError) as exc:
            plugin.JiraSiteConnection(CLOUD_SITE, "me@example.com", "pw")
        assert "API token" in str(exc.value)

    def test_at_sign_in_the_url_path_is_not_a_credential(self):
        """Only an authority userinfo holds credentials, not a path."""
        conn = plugin.JiraSiteConnection("https://site.atlassian.net/x@y")
        assert conn.site_url == "https://site.atlassian.net/x@y"

    def test_credentials_glued_to_the_scheme_are_rejected(self, testdir):
        """A url whose authority cannot be split is refused, not guessed."""
        # built rather than written out: a literal credentials-in-URL would
        # be flagged by the repo's secret scanner, which is the point of it
        userinfo = "%s:%s@" % ("svc", "pw-for-test")
        url = urlunparse(("https", userinfo, "/", "", "", ""))
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira", "--jira-url", url, "--jira-token", "pat"
        )
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert "%40" in output, output
        assert userinfo not in output, output

    def test_unsupported_scheme_names_the_scheme(self, testdir):
        """A non-http(s) scheme is named, not reported as missing."""
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        for url, scheme in (
            ("ftp://jira.example.com", "ftp"),
            ("htps://jira.example.com", "htps"),
        ):
            result = testdir.runpytest(
                "--jira", "--jira-url", url, "--jira-token", "pat"
            )
            assert result.ret == 4, result.stdout.str()
            output = result.stdout.str() + result.stderr.str()
            assert "scheme is %s" % scheme in output, output
            assert "its scheme is none" not in output, output

    def test_url_without_a_scheme_is_a_usage_error(self, testdir):
        """A missing scheme is a different mistake than glued credentials."""
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            "jira.example.com",
            "--jira-token",
            "pat",
        )
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert "must start with http" in output, output
        assert "glued to the scheme" not in output, output

    def test_ipv6_userinfo_keeps_brackets(self):
        userinfo = "%s:%s@" % ("svc", "pw-for-test")
        conn = plugin.JiraSiteConnection("https://" + userinfo + "[::1]:8443/x")
        assert conn.url == "https://[::1]:8443/x", conn.url

    def test_token_with_cloud_id_on_a_server_host_is_rejected(self):
        """A cloud id marks the site as Cloud, where a bare token is invalid."""
        with pytest.raises(plugin.JiraConfigError) as exc:
            plugin.JiraSiteConnection(
                "https://jira.custom.example", token="tok", cloud_id="abc"
            )
        assert "token on its own means nothing" in str(exc.value)

    def test_oauth_hint_on_the_gateway(self):
        """Behind the gateway only the OAuth credential can be wrong."""
        conn = plugin.JiraSiteConnection(
            CLOUD_GATEWAY,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        error = _http_error(401)
        hint = plugin._auth_hint(error, conn)
        assert "PYTEST_JIRA_OAUTH_CLIENT_ID" in hint, hint
        assert "Browse projects" in hint, hint

    def test_auth_error_uses_a_usage_exit_code(self, testdir, monkeypatch):
        """A credential error must not look like a Ctrl-C to CI."""

        def boom(self, issue_id, return_jira_metadata):
            error = _http_error(401)
            raise error

        monkeypatch.setattr(plugin.JiraSiteConnection, "get_issue", boom)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382", run=True)
            def test_pass():
                assert True
            """
        )
        result = _run_oauth_pytest(testdir)
        assert result.ret == 4, result.ret

    def test_warn_on_auth_error_is_visible_for_a_skipped_fixture_test(
        self, testdir, monkeypatch
    ):
        """The hint must survive pytest's capture for a green skip."""

        def boom(self, issue_id, return_jira_metadata):
            error = _http_error(401)
            raise error

        monkeypatch.setattr(plugin.JiraSiteConnection, "get_issue", boom)
        testdir.makepyfile(
            """
            def test_uses_fixture(jira_issue):
                assert jira_issue("ORG-1382")
        """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip"
        )
        assert result.ret == 0, result.stdout.str()
        assert "Jira rejected" in result.stderr.str(), result.stderr.str()

    def test_warn_on_auth_error_is_visible_for_a_skipped_marker_test(
        self, testdir, monkeypatch
    ):
        """The collection-path hint must reach stderr too."""

        def boom(self, issue_id, return_jira_metadata):
            error = _http_error(401)
            raise error

        monkeypatch.setattr(plugin.JiraSiteConnection, "get_issue", boom)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip"
        )
        assert result.ret == 0, result.stdout.str()
        assert "Jira rejected" in result.stderr.str(), result.stderr.str()

    def test_auth_dead_memo_stops_per_issue_reprobing(
        self, testdir, monkeypatch
    ):
        """A 401 that outlived a fresh mint is remembered per connection.

        Without the memo every marked issue mints twice and probes the
        gateway twice before reaching the same conclusion.
        """
        posts = []
        gateway = []

        class TokenSession(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "json": lambda s: {
                            "access_token": "tok",
                            "expires_in": 3600,
                        },
                    },
                )()

            def close(self):
                pass

        class GatewaySession(object):
            def request(self, method, url, **kwargs):
                gateway.append(url)

                class Response(object):
                    status_code = 401

                    def raise_for_status(self):
                        error = requests.HTTPError("401 Client Error")
                        error.response = self
                        raise error

                return Response()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: TokenSession())
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "setup_retries",
            lambda self, total, backoff: setattr(
                self, "session", GatewaySession()
            ),
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1001")
            def test_one():
                assert True

            @pytest.mark.jira("ORG-1002")
            def test_two():
                assert True

            @pytest.mark.jira("ORG-1003")
            def test_three():
                assert True
            """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip", "-rs"
        )
        assert result.ret == 0, result.stdout.str()
        assert "SKIPPED" in result.stdout.str(), result.stdout.str()
        # one mint plus one deliberate drop-and-remint on the probe, then
        # the memo: no token POST and no gateway call per further issue
        assert len(posts) == 2, posts
        assert len(gateway) == 2, gateway

    def test_post_probe_401_heals_once_however_many_issues(
        self, testdir, monkeypatch
    ):
        """A 401 after a green probe must not cost a mint per issue.

        The probe authenticated, so nothing is definitive yet: the first
        401 is healed with a fresh token, and when that token is rejected
        too every later request answers 401 without paying for another
        mint and another gateway round trip.
        """
        posts = []
        gateway = []

        class TokenSession(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "json": lambda s: {
                            "access_token": "tok-%d" % len(posts),
                            "expires_in": 3600,
                        },
                    },
                )()

            def close(self):
                pass

        class GatewaySession(object):
            def request(self, method, url, **kwargs):
                gateway.append(url)
                # the probe works, every issue answers 401
                status = 200 if url.endswith("/rest/api/2/myself") else 401

                class Response(object):
                    status_code = status

                    def raise_for_status(self):
                        if self.status_code >= 400:
                            error = requests.HTTPError("401 Client Error")
                            error.response = self
                            raise error

                return Response()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: TokenSession())
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "setup_retries",
            lambda self, total, backoff: setattr(
                self, "session", GatewaySession()
            ),
        )
        issues = ["ORG-1001", "ORG-1002", "ORG-1003", "ORG-1004", "ORG-1005"]
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1001")
            def test_one():
                assert True

            @pytest.mark.jira("ORG-1002")
            def test_two():
                assert True

            @pytest.mark.jira("ORG-1003")
            def test_three():
                assert True

            @pytest.mark.jira("ORG-1004")
            def test_four():
                assert True

            @pytest.mark.jira("ORG-1005")
            def test_five():
                assert True
            """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip", "-rs"
        )
        assert result.ret == 0, result.stdout.str()
        assert_outcomes(result, 0, len(issues), 0)
        stderr = result.stderr.str()
        # two mints: the one the heal spent and the retry that rejected it
        assert len(posts) == 2, posts
        # the probe, the two calls of that heal, then one call per issue
        assert len(gateway) == len(issues) + 2, gateway
        # ... and the notice is one line per connection, not one per issue
        assert stderr.count("freshly minted one") == 1, stderr

    @pytest.mark.parametrize(
        "mid_status, outcomes",
        [
            pytest.param(200, (2, 1), id="success-clears-then-heals"),
            pytest.param(403, (1, 2), id="permission-403-clears-then-heals"),
            pytest.param(503, (0, 3), id="503-blip-keeps-flag"),
            pytest.param(429, (0, 3), id="429-keeps-flag"),
        ],
    )
    def test_auth_proving_status_clears_the_rejection_flag(
        self, testdir, monkeypatch, mid_status, outcomes
    ):
        """Only an auth-proving status clears the "freshly minted token was
        rejected" flag, so a later 401 heals again.

        Issue one's 401 survives the heal, which sets the flag and makes that
        issue fail as a real 401. Issue two answers ``mid_status``: a 200 or a
        403 proves the token authenticated (a 403 merely lacks permission) and
        forgets the rejection, so issue three's 401 is a genuinely new
        revocation and is healed with a new token. A 5xx or a 429 is returned
        before any credential check, so it proves nothing: the flag stays and
        issue three's 401 fails fast instead of spending another mint.
        """
        posts = []
        gateway = []

        class TokenSession(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "json": lambda s: {
                            "access_token": "tok-%d" % len(posts),
                            "expires_in": 3600,
                        },
                    },
                )()

            def close(self):
                pass

        class GatewaySession(object):
            """Scripted issue answers: 401, 401, mid_status, 401, 200.

            setup_retries is replaced below, so a 429 is consumed once here;
            a real transport would retry it before giving up.
            """

            def __init__(self):
                self.plan = [401, 401, mid_status, 401, 200]

            def request(self, method, url, **kwargs):
                gateway.append(url)
                status = 200
                if not url.endswith("/rest/api/2/myself"):
                    status = self.plan.pop(0)

                class Response(object):
                    status_code = status

                    def raise_for_status(self):
                        if self.status_code >= 400:
                            error = requests.HTTPError(
                                "%d Client Error" % self.status_code
                            )
                            error.response = self
                            raise error

                    def json(self):
                        return {
                            "fields": {
                                "components": [],
                                "versions": [],
                                "fixVersions": [],
                                "status": {"name": "Closed"},
                                "resolution": None,
                            }
                        }

                return Response()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: TokenSession())
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "setup_retries",
            lambda self, total, backoff: setattr(
                self, "session", GatewaySession()
            ),
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1001")
            def test_one():
                assert True

            @pytest.mark.jira("ORG-1002")
            def test_two():
                assert True

            @pytest.mark.jira("ORG-1003")
            def test_three():
                assert True
            """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip", "-rs"
        )
        assert result.ret == 0, result.stdout.str()
        assert_outcomes(result, outcomes[0], outcomes[1], 0)
        # the probe's mint, the heal issue one spent, then issue three's heal
        # only when issue two proved the token: a 5xx or a 429 clears nothing
        heals_again = mid_status < 500 and mid_status != 429
        assert len(posts) == (3 if heals_again else 2), posts
        # the probe, two calls for issue one, one for issue two, then one or
        # two for issue three depending on whether its 401 was healed
        assert len(gateway) == (6 if heals_again else 5), gateway
        # the remint notice stays once per connection, not once per heal
        stderr = result.stderr.str()
        assert stderr.count("freshly minted one") == 1, stderr

    def test_mint_failure_under_skip_is_reported_once(
        self, testdir, monkeypatch
    ):
        """A mint error must not be re-told as a probe (url/cloud id) error."""

        def no_token(*args, **kwargs):
            raise JiraOAuthMintError(
                "Could not mint an Atlassian access token from the OAuth "
                "2.0 credential (HTTP 401): check "
                "PYTEST_JIRA_OAUTH_CLIENT_ID and "
                "PYTEST_JIRA_OAUTH_CLIENT_SECRET."
            )

        monkeypatch.setattr(plugin, "_mint_access_token", no_token)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1001")
            def test_one():
                assert True

            @pytest.mark.jira("ORG-1002")
            def test_two():
                assert True

            @pytest.mark.jira("ORG-1003")
            def test_three():
                assert True
            """
        )
        result = _run_oauth_pytest(
            testdir, "--jira-connection-error-strategy", "skip", "-rs"
        )
        assert result.ret == 0, result.stdout.str()
        assert_outcomes(result, 0, 3, 0)
        stderr = result.stderr.str()
        # one warning, however many issues hit the same mint
        assert (
            stderr.count("Could not mint an Atlassian access token") == 1
        ), stderr
        # the probe wording would misdiagnose a rejected client secret
        output = result.stdout.str() + stderr
        assert "Could not authenticate" not in output, output
        assert "Check --jira-url and --jira-cloud-id" not in output, output

    def test_cloud_id_with_a_user_warns_on_a_cloud_site(self, testdir):
        """A user ignores the cloud id, and says so."""
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            CLOUD_SITE,
            "--jira-cloud-id",
            "abc-123",
            "--jira-user",
            "me@example.com",
            "--jira-token",
            "api-token",
        )
        assert result.ret == 0, result.stdout.str()
        assert "cloud_id only applies" in result.stderr.str()

    def test_cloud_id_with_a_pat_is_rejected_on_a_server_url(self, testdir):
        """A cloud id says "Jira Cloud", where a bare token means nothing.

        A custom-domain Cloud site would otherwise accept the token as a
        Server/DC PAT Bearer and fail later with an opaque 401.
        """
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            "https://jira.example.com",
            "--jira-token",
            "pat",
            "--jira-cloud-id",
            "abc-123",
        )
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert plugin.CLOUD_CREDENTIALS_ERROR in output, output
        assert "cloud_id only applies" not in output, output

    def test_cloud_id_without_credentials_warns_on_a_server_url(self, testdir):
        """With nothing to authenticate, the cloud id is inert: just warn."""
        testdir.makepyfile(
            """
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            "https://jira.example.com",
            "--jira-cloud-id",
            "abc-123",
        )
        assert result.ret == 0, result.stdout.str()
        assert "cloud_id only applies" in result.stderr.str()

    def test_browse_links_use_the_site_url(self, testdir, monkeypatch):
        """Skip/xfail reasons must stay browsable behind the gateway."""
        monkeypatch.setattr(
            plugin.JiraHooks, "is_issue_resolved", lambda self, issue_id: False
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382", run=True)
            def test_pass():
                assert False
        """
        )
        result = _run_oauth_pytest(testdir, "-rx")
        output = result.stdout.str()
        assert CLOUD_SITE + "/browse/ORG-1382" in output, output
        assert "api.atlassian.com" not in output, output

    def test_gateway_reason_is_the_bare_issue_id(self, testdir, monkeypatch):
        """The gateway is not browsable, so a /browse/ link would be dead."""
        monkeypatch.setattr(
            plugin.JiraHooks, "is_issue_resolved", lambda self, issue_id: False
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382", run=True)
            def test_pass():
                assert False
        """
        )
        result = _run_oauth_pytest(testdir, "-rx", url=CLOUD_GATEWAY)
        assert result.ret == 0, result.stdout.str()
        output = result.stdout.str()
        assert "/browse/" not in output, output
        assert "XFAIL" in output, output
        assert "ORG-1382" in output, output

    def test_unused_cloud_id_warning(self):
        # a user ignores the cloud id, and says so
        warnings = plugin._resolve_auth(
            CLOUD_SITE, "me@example.com", None, "tok", "abc-123", None, None
        ).warnings
        assert any("cloud_id only applies" in w for w in warnings), warnings
        # an OAuth service account uses it, silently
        warnings = plugin._resolve_auth(
            CLOUD_SITE, None, None, None, "abc-123", "cid", "sec"
        ).warnings
        assert warnings == [], warnings

    def test_auth_error_exits_with_hint(self, testdir, monkeypatch):
        """A credential-level 401 exits with guidance, not a traceback."""

        def boom(self, issue_id, return_jira_metadata):
            error = _http_error(401)
            raise error

        monkeypatch.setattr(plugin.JiraSiteConnection, "get_issue", boom)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382", run=True)
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str()
        assert result.ret == 4, output
        assert "Jira rejected the credentials" in output, output
        assert "INTERNALERROR" not in output, output

    def test_issue_401_after_a_green_probe_exits_with_hint(
        self, testdir, monkeypatch
    ):
        """A token revoked between probe and issue check is a usage error.

        The probe succeeded, so the connection is not auth_dead: the 401 is
        still credential-level and must exit 4 with a hint, not die as
        INTERNALERROR.
        """

        class Response(object):
            def __init__(self, status):
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise _http_error(self.status_code)

        def send(self, url, method, kwargs):
            if url.endswith("/rest/api/2/myself"):
                return Response(200)
            return Response(401)

        monkeypatch.setattr(plugin.JiraSiteConnection, "_send", send)
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "_authorization_headers",
            lambda self: {"Authorization": "Bearer tok"},
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        assert result.ret == 4, output
        assert "Jira rejected the credentials" in output, output
        assert "INTERNALERROR" not in output, output
        # the heal is reported once, and the exit does not swallow it
        assert output.count("freshly minted one") == 1, output

    def test_probe_403_notice_survives_a_strict_exit(
        self, testdir, monkeypatch
    ):
        """A recorded 403 must still be printed when solid exit 4 unwinds.

        The probe's 403 is only recorded, not raised, so the pending-notice
        drain in ``finally`` is the only thing that can report it.
        """

        class Response(object):
            def __init__(self, status):
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise _http_error(self.status_code)

        def send(self, url, method, kwargs):
            if url.endswith("/rest/api/2/myself"):
                return Response(403)
            return Response(401)

        monkeypatch.setattr(plugin.JiraSiteConnection, "_send", send)
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "_authorization_headers",
            lambda self: {"Authorization": "Bearer tok"},
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
            """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        assert result.ret == 4, output
        assert output.count("answered 403 for /rest/api/2/myself") == 1, output
        assert "INTERNALERROR" not in output, output

    def test_remint_notice_survives_a_green_run(self, testdir, monkeypatch):
        """An unexplained extra mint is a mystery in the logs."""
        calls = []

        class Response(object):
            def __init__(self, status):
                self.status_code = status

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise _http_error(self.status_code)

        def send(self, url, method, kwargs):
            calls.append(url)
            if url.endswith("/rest/api/2/myself"):
                # the cached token is rejected once, the fresh one works
                return Response(401 if calls.count(url) == 1 else 200)
            return Response(404)

        monkeypatch.setattr(plugin.JiraSiteConnection, "_send", send)
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "_authorization_headers",
            lambda self: {"Authorization": "Bearer tok"},
        )
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        # green: the issue 404 is a missing issue, not a broken setup
        assert result.ret == 0, result.stdout.str()
        stderr = result.stderr.str()
        assert "freshly minted one" in stderr, stderr
        assert any(u.endswith("/rest/api/2/myself") for u in calls), calls

    def test_pat_keeps_legacy_behaviour_without_oauth_hints(
        self, testdir, monkeypatch
    ):
        """A Server/DC PAT must fail the way it always did."""

        def boom(self, issue_id, return_jira_metadata):
            raise _http_error(401)

        monkeypatch.setattr(plugin.JiraSiteConnection, "get_issue", boom)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
        """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            "https://jira.example.com",
            "--jira-token",
            "pat",
            "--jira-connection-error-strategy",
            "skip",
        )
        assert result.ret == 0, result.stdout.str()
        # the diagnostics belong to the OAuth path only
        assert "Jira rejected" not in result.stderr.str()

    def test_clean_strips_quotes_and_whitespace(self):
        assert plugin._clean(' "https://x.atlassian.net" ') == (
            "https://x.atlassian.net"
        )
        assert plugin._clean("'token'") == "token"
        assert plugin._clean("") is None
        assert plugin._clean(None) is None

    def test_option_prefers_environment_over_ini(self, monkeypatch):
        class Config(object):
            def getvalue(self, name):
                return "from-ini"

        monkeypatch.setenv("PYTEST_JIRA_TOKEN", '"from-env"')
        value = plugin._get_setting("PYTEST_JIRA_TOKEN", Config(), "jira_token")
        assert value == "from-env"

        monkeypatch.setenv("PYTEST_JIRA_TOKEN", '""')
        value = plugin._get_setting("PYTEST_JIRA_TOKEN", Config(), "jira_token")
        assert value == "from-ini"

    def test_quoted_env_values_are_sanitized(self, testdir, monkeypatch):
        monkeypatch.setenv("PYTEST_JIRA_URL", '"https://jira.example.com"')
        monkeypatch.setenv("PYTEST_JIRA_USERNAME", '"user@example.com"')
        monkeypatch.setenv("PYTEST_JIRA_TOKEN", '"api-token"')
        testdir.makeconftest(
            """
        def pytest_collection_modifyitems(config, items):
            plug = config.pluginmanager.getplugin("jira_plugin")
            print("URL=%s" % plug.conn.url)
            print("BASIC=%s" % repr(plug.conn.basic_auth))
    """
        )
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest("--jira", "-s")
        result.stdout.fnmatch_lines(["*URL=https://jira.example.com*"])
        result.stdout.fnmatch_lines(
            ["*BASIC=('user@example.com', 'api-token')*"]
        )

    def test_basic_auth_keeps_the_site_url(self, testdir, monkeypatch):
        """A user must never be sent to the API gateway (OAuth only)."""
        monkeypatch.setenv("PYTEST_JIRA_URL", CLOUD_SITE)
        monkeypatch.setenv("PYTEST_JIRA_USERNAME", "me@example.com")
        monkeypatch.setenv("PYTEST_JIRA_TOKEN", '"api-token"')
        monkeypatch.setenv("PYTEST_JIRA_CLOUD_ID", '"abc-123"')
        testdir.makeconftest(
            """
        def pytest_collection_modifyitems(config, items):
            plug = config.pluginmanager.getplugin("jira_plugin")
            print("URL=%s" % plug.conn.url)
            print("BASIC=%s" % repr(plug.conn.basic_auth))
    """
        )
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest("--jira", "-s")
        result.stdout.fnmatch_lines(["*URL=" + CLOUD_SITE + "*"])
        result.stdout.fnmatch_lines(["*BASIC=('me@example.com', 'api-token')*"])
        # the cloud id cannot apply to a user, so it is reported
        assert "cloud_id only applies" in result.stderr.str()


class TestServiceAccountToken:
    """Minting and caching the OAuth 2.0 access token."""

    def test_minted_token_is_sent_as_bearer(self, monkeypatch):
        monkeypatch.setattr(
            plugin, "_mint_access_token", lambda *a, **kw: "minted-token"
        )
        sent = []

        class Session(object):
            def request(self, method, url, **kwargs):
                sent.append(kwargs.get("headers"))
                status = type("S", (), {"status_code": 200})
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "raise_for_status": lambda s: None,
                        "_s": status,
                    },
                )()

        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        conn.session = Session()
        conn._jira_request(CLOUD_GATEWAY + "/rest/api/2/myself")
        assert sent == [{"Authorization": "Bearer minted-token"}]

    def test_mint_result_is_cached_until_the_margin(self, monkeypatch):
        posts = []

        class Response(object):
            status_code = 200

            def __init__(self, token):
                self._token = token

            def json(self):
                return {"access_token": self._token, "expires_in": 3600}

        class Session(object):
            def post(self, url, **kwargs):
                posts.append((url, kwargs))
                return Response("tok%d" % len(posts))

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: Session())
        assert plugin._mint_access_token("cid", "s3cr3t") == "tok1"
        assert plugin._mint_access_token("cid", "s3cr3t") == "tok1"
        assert len(posts) == 1, posts
        url, kwargs = posts[0]
        assert url == plugin.ATLASSIAN_TOKEN_URL
        assert kwargs["json"]["grant_type"] == "client_credentials"
        assert kwargs["json"]["client_id"] == "cid"
        # the secret is always sent over verified TLS, without redirects
        assert kwargs["verify"] is True
        assert kwargs["allow_redirects"] is False

        # close to expiry it re-mints instead of returning a dying token
        key = plugin._credential_key("cid", "s3cr3t")
        token, expires_at = plugin._SA_TOKEN_CACHE[key]
        plugin._SA_TOKEN_CACHE[key] = (
            token,
            expires_at - 3600 + plugin.SA_TOKEN_REFRESH_MARGIN - 1,
        )
        assert plugin._mint_access_token("cid", "s3cr3t") == "tok2"
        assert len(posts) == 2

    def test_mint_failure_says_what_to_check(self, monkeypatch):
        class Response(object):
            status_code = 401

        class Session(object):
            def post(self, url, **kwargs):
                return Response()

            def close(self):
                pass

        posts = []

        class CountingSession(Session):
            def post(self, url, **kwargs):
                posts.append(url)
                return super().post(url, **kwargs)

        monkeypatch.setattr(plugin, "_token_session", lambda: CountingSession())
        with pytest.raises(plugin.JiraOAuthMintError) as exc:
            plugin._mint_access_token("cid", "s3cr3t-value-not-a-flag")
        message = str(exc.value)
        assert "PYTEST_JIRA_OAUTH_CLIENT_ID" in message, message
        assert "s3cr3t-value-not-a-flag" not in message, message
        # the failure is remembered: no second POST per marked issue
        with pytest.raises(plugin.JiraOAuthMintError):
            plugin._mint_access_token("cid", "s3cr3t-value-not-a-flag")
        assert len(posts) == 1, posts

    def test_token_without_lifetime_is_cached_briefly(self, monkeypatch):
        posts = []

        class Response(object):
            status_code = 200

            def json(self):
                return {"access_token": "dead", "expires_in": 0}

        class Session(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return Response()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: Session())
        assert plugin._mint_access_token("cid", "sec") == "dead"
        # an explicit 0 means "no usable lifetime": cache only briefly
        key = plugin._credential_key("cid", "sec")
        _token, expires_at = plugin._SA_TOKEN_CACHE[key]
        cached_for = expires_at - time.monotonic()
        assert 0 < cached_for <= plugin.SA_TOKEN_MIN_LIFETIME, cached_for
        assert plugin._mint_access_token("cid", "sec") == "dead"
        assert len(posts) == 1

    def test_short_lifetime_still_caches_the_token(self, monkeypatch):
        """A lifetime under the refresh margin must not mint per request."""
        posts = []

        class Session(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "json": lambda s: {
                            "access_token": "tok",
                            "expires_in": 60,
                        },
                    },
                )()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: Session())
        assert plugin._mint_access_token("cid", "sec") == "tok"
        assert plugin._mint_access_token("cid", "sec") == "tok"
        assert len(posts) == 1, posts
        key = plugin._credential_key("cid", "sec")
        assert key in plugin._SA_TOKEN_CACHE

    def test_mint_failure_exits_in_strict_mode(self, testdir, monkeypatch):
        def boom(*args, **kwargs):
            raise plugin.JiraOAuthMintError("mint failed for test")

        monkeypatch.setattr(plugin, "_mint_access_token", boom)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382", run=True)
            def test_pass():
                assert True
            """
        )
        result = _run_oauth_pytest(testdir)
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str()
        assert "mint failed for test" in output, output

    def test_token_session_caps_retry_after(self):
        """A 429 with a huge Retry-After must not stall the mint."""
        session = plugin._token_session()
        retries = session.get_adapter("https://x.example").max_retries
        assert retries.total == plugin.TOKEN_RETRY_TOTAL
        response = type("R", (), {"headers": {"Retry-After": "3600"}})()
        # capped, and therefore the sleep urllib3 derives from it too
        assert retries.get_retry_after(response) == (plugin.MAX_RETRY_AFTER)
        assert urllib3.Retry.get_retry_after(retries, response) == 3600

    def test_gateway_401_drops_the_token_and_remints(self, monkeypatch):
        """A revoked cached token heals itself instead of failing forever.

        Uses the real cache: without dropping it, the retry would replay the
        same Bearer token and no second POST would happen.
        """
        posts = []
        seen = []

        class TokenSession(object):
            def post(self, url, **kwargs):
                posts.append(url)
                token = "tok%d" % len(posts)
                return type(
                    "R",
                    (),
                    {
                        "status_code": 200,
                        "json": lambda s, t=token: {
                            "access_token": t,
                            "expires_in": 3600,
                        },
                    },
                )()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: TokenSession())

        class Session(object):
            def request(self, method, url, **kwargs):
                seen.append(kwargs.get("headers"))
                status = 401 if len(seen) == 1 else 200
                return type(
                    "R",
                    (),
                    {
                        "status_code": status,
                        "raise_for_status": lambda s: None,
                    },
                )()

        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        conn.session = Session()
        conn._jira_request(CLOUD_GATEWAY + "/rest/api/2/myself")
        assert len(posts) == 2, posts  # the cached token was dropped
        assert seen[0] == {"Authorization": "Bearer tok1"}, seen
        assert seen[1] == {"Authorization": "Bearer tok2"}, seen
        # a healed 401 is not a dead credential, so nothing is memoized
        assert conn.auth_dead is None

    def test_unconfigure_clears_the_token_caches(self):
        plugin._SA_TOKEN_CACHE[("cid", "hash")] = ("tok", 1e18)
        plugin._SA_TOKEN_FAILURES[("cid", "hash")] = "boom"
        plugin.pytest_unconfigure(None)
        assert plugin._SA_TOKEN_CACHE == {}
        assert plugin._SA_TOKEN_FAILURES == {}

    def test_null_expires_in_still_caches_the_token(self, monkeypatch):
        """A null lifetime must not invalidate a good access token."""
        posts = []

        class Response(object):
            status_code = 200

            def json(self):
                return {"access_token": "tok", "expires_in": None}

        class Session(object):
            def post(self, url, **kwargs):
                posts.append(url)
                return Response()

            def close(self):
                pass

        monkeypatch.setattr(plugin, "_token_session", lambda: Session())
        assert plugin._mint_access_token("cid", "sec") == "tok"
        assert plugin._mint_access_token("cid", "sec") == "tok"
        assert len(posts) == 1, posts
        assert plugin._SA_TOKEN_FAILURES == {}

    def test_only_credential_failures_are_remembered(self, monkeypatch):
        """An outage at the token endpoint must not poison the session."""
        posts = []

        class Response(object):
            def __init__(self, status, payload=None):
                self.status_code = status
                self.payload = payload or {}

            def json(self):
                return self.payload

        def use_token_session(*replies):
            queue = list(replies)

            class Session(object):
                def post(self, url, **kwargs):
                    posts.append(url)
                    return queue.pop(0)

                def close(self):
                    pass

            monkeypatch.setattr(plugin, "_token_session", lambda: Session())

        use_token_session(Response(500))
        with pytest.raises(plugin.JiraOAuthMintError):
            plugin._mint_access_token("cid", "sec")
        # transient: not remembered, so the next mint tries again
        assert plugin._SA_TOKEN_FAILURES == {}, plugin._SA_TOKEN_FAILURES
        use_token_session(
            Response(200, {"access_token": "tok", "expires_in": 3600})
        )
        assert plugin._mint_access_token("cid", "sec") == "tok"
        assert len(posts) == 2, posts

        # a credential failure is remembered: no second POST
        use_token_session(Response(401), Response(200, {"access_token": "x"}))
        with pytest.raises(plugin.JiraOAuthMintError):
            plugin._mint_access_token("cid2", "sec2")
        key = plugin._credential_key("cid2", "sec2")
        assert key in plugin._SA_TOKEN_FAILURES
        with pytest.raises(plugin.JiraOAuthMintError):
            plugin._mint_access_token("cid2", "sec2")
        assert len(posts) == 3, posts


class TestOAuthServiceAccount:
    """How an OAuth 2.0 service-account run is resolved and reported.

    The mint/Bearer mechanics live in :class:`TestServiceAccountToken`.
    What is pinned here is the configuration side: mode resolution, the
    gateway and host rules, usage errors, env/ini resolution and the
    wording of the hints a failed connection prints.
    """

    def test_oauth_mode_needs_both_halves_of_the_credential(self):
        for kwargs in (
            {"oauth_client_id": "cid"},
            {"oauth_client_secret": "sec"},
        ):
            with pytest.raises(plugin.JiraConfigError) as exc:
                plugin.JiraSiteConnection(
                    CLOUD_SITE, cloud_id="abc-123", **kwargs
                )
            assert "incomplete" in str(exc.value)

    def test_oauth_mode_needs_a_cloud_id(self):
        with pytest.raises(plugin.JiraConfigError) as exc:
            plugin.JiraSiteConnection(
                CLOUD_SITE,
                oauth_client_id="cid",
                oauth_client_secret="sec",
            )
        assert "--jira-cloud-id" in str(exc.value)

    def test_oauth_service_account_uses_the_gateway(self):
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.mode == plugin.AUTH_OAUTH
        assert conn.oauth_mode
        assert conn.url == CLOUD_GATEWAY
        # browse links keep the site name, never the gateway
        assert conn.site_url == CLOUD_SITE
        assert conn.warnings == []

    def test_user_credentials_win_over_a_stray_oauth_pair(self):
        """A leftover env credential must not hijack a working config."""
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            "me@example.com",
            token="tok",
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.mode == plugin.AUTH_BASIC
        assert conn.basic_auth == ("me@example.com", "tok")
        # the user stays on the site URL: credentials never go to the gateway
        assert conn.url == CLOUD_SITE
        ignored = "OAuth 2.0 credential is ignored"
        assert any(ignored in w for w in conn.warnings), conn.warnings

    def test_oauth_env_vars_reach_the_connection(self, testdir, monkeypatch):
        """The new env vars behave like the other five."""
        monkeypatch.setenv("PYTEST_JIRA_URL", CLOUD_SITE)
        monkeypatch.setenv("PYTEST_JIRA_CLOUD_ID", "abc-123")
        monkeypatch.setenv("PYTEST_JIRA_OAUTH_CLIENT_ID", '"cid"')
        monkeypatch.setenv("PYTEST_JIRA_OAUTH_CLIENT_SECRET", '"secret"')
        testdir.makeconftest(
            """
        def pytest_collection_modifyitems(config, items):
            plug = config.pluginmanager.getplugin("jira_plugin")
            print("URL=%s" % plug.conn.url)
            print("OAUTH=%s" % plug.conn.oauth_mode)
            print("CID=%s" % plug.conn.oauth_client_id)
    """
        )
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest("--jira", "-s")
        result.stdout.fnmatch_lines(["*URL=" + CLOUD_GATEWAY + "*"])
        result.stdout.fnmatch_lines(["*OAUTH=True*"])
        result.stdout.fnmatch_lines(["*CID=cid*"])

    def test_url_userinfo_becomes_basic_auth(self):
        """Credentials in the url are lifted out, so they cannot leak."""
        userinfo = "%s:%s@" % ("svc", "pw-for-test")
        conn = plugin.JiraSiteConnection(
            "https://" + userinfo + "jira.example.com"
        )
        assert conn.basic_auth == ("svc", "pw-for-test")
        assert userinfo not in conn.url
        assert any("embedded in the url" in w for w in conn.warnings)

    def test_probe_404_is_not_taken_for_a_missing_issue(
        self, testdir, monkeypatch
    ):
        """A wrong cloud id / url must fail, not silently skip every test."""

        def boom(self, *args, **kwargs):
            raise _http_error(404)

        monkeypatch.setattr(plugin.JiraSiteConnection, "check_connection", boom)
        monkeypatch.setattr(plugin, "_mint_access_token", lambda *a, **k: "tok")
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1382")
            def test_pass():
                assert True
            """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        assert result.ret == 4, output
        assert "Could not authenticate" in output, output
        assert "Check --jira-url and --jira-cloud-id" in output, output

    def test_bare_cloud_token_is_a_usage_error_at_session_level(self, testdir):
        """The user-facing path: configure -> UsageError -> exit 4."""
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest(
            "--jira", "--jira-url", CLOUD_SITE, "--jira-token", "ATATT-token"
        )
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert "token on its own means nothing" in output, output
        # both supported ways are named
        assert "--jira-user" in output, output
        assert "--jira-oauth-client-id" in output, output
        assert "INTERNALERROR" not in output, output

    def test_url_without_a_host_is_a_usage_error(self, testdir):
        """No host means no request, so fail as a usage error, not a crash."""
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest("--jira", "--jira-url", "https://")
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert plugin.URL_WITHOUT_HOST_ERROR in output, output
        assert "INTERNALERROR" not in output, output

    def test_gateway_url_with_a_user_is_a_usage_error(self, testdir):
        """Only an OAuth service account may talk to the API gateway."""
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        result = testdir.runpytest(
            "--jira",
            "--jira-url",
            CLOUD_GATEWAY,
            "--jira-user",
            "me@example.com",
            "--jira-token",
            "api-token",
        )
        assert result.ret == 4, result.stdout.str()
        output = result.stdout.str() + result.stderr.str()
        assert plugin.GATEWAY_NEEDS_OAUTH_ERROR in output, output
        # a Server/DC PAT is no better: the gateway needs an OAuth token
        with pytest.raises(plugin.JiraConfigError) as exc:
            plugin.JiraSiteConnection(CLOUD_GATEWAY, token="pat")
        assert plugin.CLOUD_CREDENTIALS_ERROR in str(exc.value)

    def test_oauth_configured_through_jira_cfg(self, testdir):
        """The ini keys work too, not only env vars and CLI options."""
        testdir.makefile(
            ".cfg",
            jira="\n".join(
                [
                    "[DEFAULT]",
                    "url = " + CLOUD_SITE,
                    "cloud_id = abc-123",
                    "oauth_client_id = cid",
                    "oauth_client_secret = secret",
                ]
            ),
        )
        testdir.makepyfile(
            """
        def test_pass():
            assert True
    """
        )
        testdir.makeconftest(
            """
        def pytest_collection_modifyitems(config, items):
            plug = config.pluginmanager.getplugin("jira_plugin")
            print("URL=%s" % plug.conn.url)
            print("OAUTH=%s" % plug.conn.oauth_mode)
    """
        )
        result = testdir.runpytest("--jira", "-s")
        result.stdout.fnmatch_lines(["*URL=" + CLOUD_GATEWAY + "*"])
        result.stdout.fnmatch_lines(["*OAUTH=True*"])

    def test_gateway_detection_requires_the_ex_jira_path(self):
        assert plugin._is_gateway_url("https://api.atlassian.com") is False
        assert plugin._is_gateway_url(
            "https://api.atlassian.com/ex/jira/abc-123"
        )
        assert plugin._is_cloud_or_gateway(
            "https://api.atlassian.com/ex/jira/abc-123"
        )
        assert not plugin._is_cloud_or_gateway("https://api.atlassian.com")

    def test_token_next_to_oauth_is_ignored_with_a_warning(self):
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            token="ATATT-token",
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        assert conn.mode == plugin.AUTH_OAUTH
        assert any("token is ignored" in w for w in conn.warnings)

    def test_partial_oauth_pair_does_not_break_a_user_config(self):
        """A leftover single env var must not hijack a working setup."""
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            "me@example.com",
            token="tok",
            oauth_client_id="only-id",
        )
        assert conn.mode == plugin.AUTH_BASIC
        assert any("incomplete" in w for w in conn.warnings)

    def test_warn_on_auth_error_prints_once(self, capsys):
        """The OAuth hint is printed once per connection, not per test."""
        conn = plugin.JiraSiteConnection(
            CLOUD_SITE,
            oauth_client_id="cid",
            oauth_client_secret="sec",
            cloud_id="abc-123",
        )
        error = _http_error(401)
        plugin._warn_on_auth_error(error, conn)
        plugin._warn_on_auth_error(error, conn)
        stderr = capsys.readouterr().err
        assert stderr.count("Jira rejected") == 1, stderr

    def test_strict_issue_500_redacts_and_keeps_the_response(
        self, testdir, monkeypatch
    ):
        """A failure with no hint still goes through the redaction boundary.

        Probe 200 plus a non-401 issue error is the only path that reaches
        ``exc.args = (_request_error_text(exc),)`` and the bare raise: the
        hint is None, so nothing exits. The rewritten message must not leak
        the url userinfo, and ``.response`` must survive for a classifier.
        """
        # built rather than written out: a literal credentials-in-URL would
        # be flagged by the repo's secret scanner, which is the point of it
        userinfo = "%s:%s@" % ("svc", "pw-for-test")
        leaked = (
            "https://" + userinfo + "site.atlassian.net/rest/api/2/issue/ORG-1"
        )

        class Response(object):
            def __init__(self, status, url):
                self.status_code = status
                self.url = url

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(
                        "500 Server Error: boom for url: %s" % leaked,
                        response=self,
                    )

        def send(self, url, method, kwargs):
            if url.endswith("/rest/api/2/myself"):
                return Response(200, url)
            return Response(500, leaked)

        raised = []
        boundary = plugin._handle_connection_error

        def spy(exc, conn, strategy, config=None):
            try:
                return boundary(exc, conn, strategy, config)
            except BaseException as error:
                raised.append(error)
                raise

        monkeypatch.setattr(plugin.JiraSiteConnection, "_send", send)
        monkeypatch.setattr(
            plugin.JiraSiteConnection,
            "_authorization_headers",
            lambda self: {"Authorization": "Bearer tok"},
        )
        monkeypatch.setattr(plugin, "_handle_connection_error", spy)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        assert result.ret != 0, output
        assert userinfo not in output, output
        assert "pw-for-test" not in output, output
        # the redaction rewrote the message of the very same exception
        assert len(raised) == 1, output
        assert raised[0].response.status_code == 500, output
        assert "pw-for-test" not in str(raised[0]), str(raised[0])
        assert "site.atlassian.net" in str(raised[0]), str(raised[0])

    def test_strict_transport_failure_prints_the_hint(
        self, testdir, monkeypatch
    ):
        """An unreachable host under strict must say what to check.

        The exception has no response, so it is re-raised rather than
        turned into a usage error; without the hint the run would die on a
        traceback with nothing actionable in it.
        """

        def send(self, url, method, kwargs):
            raise requests.ConnectionError("gateway is unreachable")

        monkeypatch.setattr(plugin.JiraSiteConnection, "_send", send)
        testdir.makepyfile(
            """
            import pytest

            @pytest.mark.jira("ORG-1")
            def test_pass():
                assert True
        """
        )
        result = _run_oauth_pytest(testdir)
        output = result.stdout.str() + result.stderr.str()
        assert result.ret != 0, output
        assert (
            "Check the Jira url, network access and the service account"
            in result.stderr.str()
        ), output

    def test_partial_oauth_pair_does_not_break_a_pat_config(self):
        """A leftover half credential must not kill a Server/DC PAT setup."""
        conn = plugin.JiraSiteConnection(
            "https://jira.example.com",
            token="pat",
            oauth_client_id="only-id",
        )
        assert conn.mode == plugin.AUTH_PAT
        assert any("incomplete" in w for w in conn.warnings)

    def test_redacted_survives_a_malformed_port(self):
        assert plugin._redacted("https://user:pw@host.example:notaport/x") == (
            "https://host.example/x"
        )

    def test_oauth_hint_names_the_client_credentials(self):
        fake_secret = "not-a-real-credential"
        conn = plugin.JiraSiteConnection(
            CLOUD_GATEWAY,
            oauth_client_id="cid",
            oauth_client_secret=fake_secret,
            cloud_id="abc-123",
        )
        error = _http_error(401)
        hint = plugin._auth_hint(error, conn)
        assert "PYTEST_JIRA_OAUTH_CLIENT_ID" in hint, hint
        # the secret VALUE must never be echoed, only the flag name
        assert fake_secret not in hint, hint


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


def test_jira_plugin_disabled(testdir):
    testdir.makepyfile(
        """
        import pytest
        @pytest.mark.jira("ORG-1382", run=True)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest()
    assert_outcomes(result, 1, 0, 0)


def test_jira_marker_no_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest
        @pytest.mark.jira
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    text = "JIRA marker requires one, or more, arguments"
    assert text in result.stdout.str()


def test_jira_marker_bad_args(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("there is no issue here")
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    text = (
        "JIRA marker argument `there is no issue here` "
        "does not match pattern"
    )
    assert text in result.stdout.str()


def test_jira_marker_bad_args2(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira(None)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert "expected string or " in result.stdout.str()


def test_jira_marker_no_run(testdir):
    """Expected skip due to run=False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 1, 0)


def test_open_jira_marker_pass(testdir):
    """Expected skip due to unresolved JIRA"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 0, 1)


def test_open_jira_marker_with_skipif_pass(testdir):
    """Expected skip due to unresolved JIRA when skipif is True"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=True)
        def test_pass():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_marker_without_skipif_fail(testdir):
    """Expected test to fail as unresolved JIRA marker
    is parametrized with False skipif"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_open_jira_marker_with_callable_skipif_pass(testdir):
    """
    Expected skip as skipif value is a lambda returning True. Expected
    component 'component2' is present on both closed and open JIRA issue
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1513", "ORG-1514",
            skipif=lambda i: 'component2' in i.get('components'))
        def test_pass():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_marker_with_callable_skipif_fail(testdir):
    """
    Expected fail as skipif value for open issue is a lambda returning False.
    Expected component 'component3' is present only on closed JIRA issue
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1513", "ORG-1514",
            skipif=lambda i: 'component3' in i.get('components'))
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_with_skipif_pass(testdir):
    """Expected test to skip due to multiple JIRA lines with skipif set"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=True)
        @pytest.mark.jira("ORG-1412", skipif=True)
        def test_pass():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_multiple_jira_markers_open_without_skipif_fail(testdir):
    """Expected to fail as skipif for open JIRA is False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", skipif=False)
        @pytest.mark.jira("ORG-1412", skipif=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_without_skipif_fail(testdir):
    """Expected to fail as skipif is False"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", "ORG-1412", skipif=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_multiple_jira_markers_with_one_skipif_pass(testdir):
    """Expected to skip as skipif for JIRA tickets is True"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", "ORG-1412", skipif=True)
        def test_pass():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_docstr_pass(testdir):
    """Expected skip due to unresolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_pass():
            \"\"\"
            ORG-1382
            \"\"\"
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, 0, 1)


# Should increase code coverage around return-metadata
def test_return_metadata(testdir):
    """Expected skip due to unresolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_xpassed():
            \"\"\"
            ORG-1382
            \"\"\"
            assert True
    """
    )
    ARGS = PLUGIN_ARGS + ("--jira-return-metadata",)
    result = testdir.runpytest(*ARGS)
    assert_outcomes(result, 0, 0, 0, xpassed=1)


def test_open_jira_marker_fail(testdir):
    """Expected skip due to unresolved JIRA"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_open_jira_docstr_fail(testdir):
    """Expected skip due to unresolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_fail():
            \"\"\"
            ORG-1382
            \"\"\"
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_closed_jira_marker_pass(testdir):
    """Expected PASS due to resolved JIRA Issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_jira_docstr_pass(testdir):
    """Expected PASS due to resolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_fail():
            \"\"\"
            ORG-1412
            \"\"\"
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_jira_marker_fail(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_closed_jira_docstr_fail(testdir):
    """Expected xfail due to resolved JIRA Issue %s"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_fail():
            \"\"\"
            ORG-1412
            \"\"\"
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_pass_without_jira(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_pass():
            \"\"\"
            some description
            \"\"\"
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_fail_without_jira_marker(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_fail_without_jira_docstr(testdir):
    """docstring with no jira issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        def test_pass():
            \"\"\"
            some description
            \"\"\"
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_invalid_configuration_exception(testdir):
    """Invalid option in config file, exception should be rised"""
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                "ssl_verification = something",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        def test_pass():
            pass
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert "ValueError: Not a boolean: something" in result.stderr.str()


def test_invalid_authentication_exception(testdir):
    """Failed authentication raises (legacy behaviour for basic auth)"""
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira('FOO-1234')
        def test_pass():
            pass
    """
    )
    ARGS = (
        "--jira",
        *URL_ARGS,
        "--jira-user",
        "user123@example.com",
        "--jira-token",
        "not-a-valid-api-token",
    )
    result = testdir.runpytest(*ARGS)
    assert result.ret != 0, "Invalid auth should cause pytest to fail"
    assert re.search(
        r"4(01|29)\s+Client Error", result.stdout.str(), re.MULTILINE
    ), f"Expected an auth error in output: {result.stdout.str()}"


def test_disabled_ssl_verification_pass(testdir):
    """Expected PASS due to resolved JIRA Issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                *CFG_URL_LINES,
                "ssl_verification = false",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1412", run=True)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest("--jira")
    result.assert_outcomes(1, 0, 0)


def test_config_file_paths_xfail(testdir):
    """Jira url set in ~/jira.cfg"""
    testdir.makeconftest(CONFTEST)
    homedir = testdir.mkdir("home")
    os.environ["HOME"] = os.getcwd() + "/home"
    homedir.ensure("jira.cfg").write(
        "[DEFAULT]\n" + "\n".join(CFG_URL_LINES),
    )
    assert os.path.isfile(os.getcwd() + "/home/jira.cfg")
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest("--jira")
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_closed_for_different_version_skipped(testdir):
    """Skiped, closed for different version"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                "components = com1,com3",
                "version = foo-0.1",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1501", run=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 1, 0)


def test_open_for_different_version_failed(testdir):
    """Failed, open for different version"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                "components = com1,com3",
                "version = foo-1.1",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1511", run=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, 1)


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
def test_get_issue_info_from_remote_passed(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
            def test_pass():
                \"\"\"
                XNIO-250
                \"\"\"
                assert True
        """
    )
    ARGS = PLUGIN_ARGS + _auth_args()
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(1, 0, 0)


def test_affected_component_skiped(testdir):
    """Skiped, affected component"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1511", run=False)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-components",
        "com3",
        "com1",
    )
    assert_outcomes(result, 0, 1, 0)


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
def test_strategy_ignore_failed(testdir):
    """Invalid issue ID is ignored and test fails"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                *CFG_URL_LINES,
                "marker_strategy = ignore",
                "docs_search = False",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1412789456148865", run=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest("--jira", *_auth_args())
    result.assert_outcomes(0, 0, 1)


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
def test_strategy_strict_exception(testdir):
    """Invalid issue ID, exception is rised"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_fail():
            \"\"\"
            issue: 89745-1412789456148865
            \"\"\"
            assert False
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        *_auth_args(),
        "--jira-marker-strategy",
        "strict",
        "--jira-issue-regex",
        "[0-9]+-[0-9]+",
    )
    assert "89745-1412789456148865" in result.stdout.str()


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
def test_strategy_warn_fail(testdir):
    """Invalid issue ID is ignored and warning is written"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                *CFG_URL_LINES,
                "marker_strategy = warn",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1511786754387", run=True)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest("--jira", *_auth_args())
    assert "ORG-1511786754387" in result.stderr.str()
    result.assert_outcomes(0, 0, 1)


def test_ignored_docs_marker_fail(testdir):
    """Issue is open but docs is ignored"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_fail():
            \"\"\"
            open issue: ORG-1382
            ignored
            \"\"\"
            assert False
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-disable-docs-search",
    )
    assert_outcomes(result, 0, 0, 1)


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
def test_issue_not_found_considered_open_xfailed(testdir):
    """Issue is open but docs is ignored"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_fail():
            \"\"\"
            not existing issue: ORG-13827864532876523
            considered open by default
            \"\"\"
            assert False
    """
    )
    ARGS = PLUGIN_ARGS + _auth_args()
    result = testdir.runpytest(*ARGS)
    assert_outcomes(result, 0, 0, 0, xfailed=1)


def test_jira_marker_bad_args_due_to_changed_regex(testdir):
    """Issue ID in marker doesn't match due to changed regex"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-issue-regex",
        "[0-9]+-[0-9]+",
    )
    text = "JIRA marker argument `ORG-1382` does not match pattern"
    assert text in result.stdout.str()


def test_invalid_jira_marker_strategy_parameter(testdir):
    """Invalid parameter for --jira-marker-strategy"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382", run=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-marker-strategy",
        "invalid",
    )
    assert "invalid choice: 'invalid'" in result.stderr.str()


def test_custom_resolve_status_fail(testdir):
    """
    Test case matches custom status and do not skip it because it is considered
    as closed, in additional test fails because of some regression.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1512", run=True)
        def test_fail():
            assert False  # some regression
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-resolved-statuses",
        "custom-status",
    )
    assert_outcomes(result, 0, 0, 1)


def test_custom_resolve_status_pass(testdir):
    """
    Test case matches custom status and do not skip it because it is considered
    as closed, in additional test passes.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1512", run=True)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-resolved-statuses",
        "custom-status",
    )
    assert_outcomes(result, 1, 0, 0)


def test_custom_resolve_status_skipped_on_closed_status(testdir):
    """
    Test case is marked by issue with status 'closed' which is one of defaults
    resolved statuses. But test-case gets skipped because custom resolved
    statuses are set.
    """
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1501", run=False)
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(
        "--jira",
        *URL_ARGS,
        "--jira-resolved-statuses",
        "custom-status,some-other",
    )
    assert_outcomes(result, 0, 1, 0)


def test_run_test_case_false1(testdir):
    """Test case shouldn't get executed"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                "run_test_case = False",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=1, failed=0, error=0)


def test_run_test_case_false2(testdir):
    """Test case shouldn't get executed"""
    testdir.makeconftest(CONFTEST)
    plugin_args = (
        "--jira",
        *URL_ARGS,
        "--jira-do-not-run-test-case",
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*plugin_args)
    assert_outcomes(result, passed=0, skipped=1, failed=0, error=0)


def test_run_test_case_true1(testdir):
    """Test case should get executed"""
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".cfg",
        jira="\n".join(
            [
                "[DEFAULT]",
                "run_test_case = True",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_fail():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=0, failed=0, error=0, xfailed=1)


def test_jira_fixture_plugin_disabled(testdir):
    testdir.makepyfile(
        """
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("ORG-1382") is None
    """
    )
    result = testdir.runpytest()
    assert_outcomes(result, 1, 0, 0)


def test_jira_fixture_run_positive(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("ORG-1382")
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_jira_fixture_run_negative(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_pass(jira_issue):
            assert not jira_issue("ORG-1382")
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "jira_issue_scope_class",
        "jira_issue_scope_module",
        "jira_issue_scope_package",
        "jira_issue_scope_session",
    ],
)
def test_jira_fixture_scoped_run_positive(testdir, fixture_name):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_pass({fixture_name}):
            assert {fixture_name}("ORG-1382")
    """.format(
            fixture_name=fixture_name
        )
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_run_false_for_resolved_issue(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1412", run=False)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_xfail_strict(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makefile(
        ".ini",
        pytest="\n".join(
            [
                "[pytest]",
                "xfail_strict = True",
            ]
        ),
    )
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1382")
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, passed=0, skipped=0, failed=1, error=0, xfailed=0)


@pytest.mark.skipif(
    Version(pytest.__version__) < Version("3.0.0"),
    reason="requires pytest-3 or higher",
)
def test_jira_marker_with_parametrize_pytest3(testdir):
    """"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize('arg', [
            pytest.param(1, marks=pytest.mark.jira("ORG-1382", run=True)),
            2,
        ])
        def test_fail(arg):
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, failed=1, xfailed=1)


@pytest.mark.skipif(
    Version(pytest.__version__) >= Version("3.0.0"),
    reason="requires pytest-2 or lower",
)
def test_jira_marker_with_parametrize_pytest2(testdir):
    """"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize('arg', [
            pytest.mark.jira("ORG-1382", run=True)(1),
            2,
        ])
        def test_fail(arg):
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    assert_outcomes(result, 0, 0, failed=1, xfailed=1)


@pytest.mark.parametrize(
    "error_strategy, passed, skipped, failed, error",
    [
        ("strict", 0, 0, 0, 0),
        ("skip", 0, 1, 0, 0),
        ("ignore", 1, 0, 0, 0),
    ],
)
def test_marker_error_strategy(
    testdir, error_strategy, passed, skipped, failed, error
):
    """HTTP Error when trying to connect"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("FOO-1234")
        def test_pass():
            pass
    """
    )
    ARGS = (
        "--jira",
        "--jira-url",
        "https://foo.bar.com",
        "--jira-user",
        "user123",
        "--jira-password",
        "passwd123",
        "--jira-connection-error-strategy",
        error_strategy,
        "--jira-connection-retry-total",
        1,
        "--jira-connection-retry-backoff-factor",
        0.2,
    )
    result = testdir.runpytest(*ARGS)
    assert_outcomes(
        result, passed=passed, skipped=skipped, failed=failed, error=error
    )


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
@pytest.mark.parametrize(
    "passed, skipped, failed, error",
    [
        (1, 0, 1, 0),
    ],
)
def test_marker_authenticated_access(testdir, passed, skipped, failed, error):
    """Authenticated access to closed issue"""
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("CNV-21615")
        def test_pass():
            assert True

        @pytest.mark.jira("CNV-21615")
        def test_fail():
            assert False
    """
    )
    ARGS = (
        "--jira",
        *URL_ARGS,
        *_auth_args(),
    )
    result = testdir.runpytest(*ARGS)
    assert_outcomes(
        result,
        passed=passed,
        skipped=skipped,
        failed=failed,
        error=error,
    )


@pytest.mark.parametrize(
    "error_strategy, passed, skipped, failed, error",
    [
        ("strict", 0, 0, 1, 0),
    ],
)
def test_jira_fixture_request_exception(
    testdir, error_strategy, passed, skipped, failed, error
):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        def test_pass(jira_issue):
            assert jira_issue("FOO-1234")
    """
    )
    ARGS = (
        "--jira",
        "--jira-url",
        "https://foo.bar.com",
        "--jira-user",
        "user123",
        "--jira-password",
        "passwd123",
        "--jira-connection-error-strategy",
        error_strategy,
        "--jira-connection-retry-total",
        2,
        "--jira-connection-retry-backoff-factor",
        0.1,
    )
    result = testdir.runpytest(*ARGS)
    assert_outcomes(
        result, passed=passed, skipped=skipped, failed=failed, error=error
    )


@pytest.mark.skipif(
    not _jira_token_accessible(),
    reason=TOKEN_SKIP_REASON,
)
@pytest.mark.parametrize("ticket", ["ORG-1382", "Foo-Bar"])
@pytest.mark.parametrize(
    "return_method, _type",
    [
        ("--jira-return-metadata", "JiraIssue"),
        ("", "bool"),
    ],
)
def test_jira_fixture_return_metadata(testdir, return_method, _type, ticket):
    testdir.makepyfile(
        """
        import pytest
        from issue_model import JiraIssue

        def test_pass(jira_issue):
            issue = jira_issue('%s')
            assert isinstance(issue, %s)
    """
        % (ticket, _type)
    )
    ARGS = (
        "--jira",
        *URL_ARGS,
        *_auth_args(),
        return_method,
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_nofix_nooption(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1515", run=False)
        def test_pass():
            assert False
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(0, 0, 1)


def test_closed_nofix_option(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1515", run=False)
        def test_pass():
            assert False
    """
    )
    ARGS = (
        "--jira",
        *URL_ARGS,
        "--jira-resolved-resolutions",
        "done,fixed,completed",
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(0, 1, 0)


def test_closed_fixed_nooption(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1516", run=False)
        def test_pass():
            assert True
    """
    )
    result = testdir.runpytest(*PLUGIN_ARGS)
    result.assert_outcomes(1, 0, 0)


def test_closed_fixed_option(testdir):
    testdir.makeconftest(CONFTEST)
    testdir.makepyfile(
        """
        import pytest

        @pytest.mark.jira("ORG-1516", run=False)
        def test_pass():
            assert True
    """
    )
    ARGS = (
        "--jira",
        *URL_ARGS,
        "--jira-resolved-resolutions",
        "done,fixed,completed",
    )
    result = testdir.runpytest(*ARGS)
    result.assert_outcomes(1, 0, 0)
