import pytest


PYTEST_MAJOR_VERSION = int(pytest.__version__.split(".")[0])


class JiraHooks(object):
    def __init__(
            self,
            connection,
            marker,
            version,
            components,
            resolved_statuses,
            run_test_case,
    ):
        self.conn = connection
        self.mark = marker
        self.components = set(components) if components else None
        self.version = version
        self.resolved_statuses = resolved_statuses
        self.run_test_case = run_test_case

        # Speed up JIRA lookups for duplicate issues
        self.issue_cache = dict()

    def is_issue_resolved(self, issue_id):
        """
        Returns whether the provided issue ID is resolved (True|False).  Will
        cache issues to speed up subsequent calls for the same issue.
        """
        # Access Jira issue (may be cached)
        if issue_id not in self.issue_cache:
            try:
                self.issue_cache[issue_id] = self.conn.get_issue(issue_id)
            except Exception:
                self.issue_cache[issue_id] = self.mark.get_default(issue_id)

        # Skip test if issue remains unresolved
        if self.issue_cache[issue_id] is None:
            return True

        if self.issue_cache[issue_id]['status'] in self.resolved_statuses:
            return self.fixed_in_version(issue_id)
        else:
            return not self.is_affected(issue_id)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        """
        Figure out how to mark JIRA test other than SKIPPED
        """

        outcome = yield
        rep = outcome.get_result()
        try:
            jira_ids = self.mark.get_jira_issues(item)
        except Exception:
            jira_ids = []

        if call.when == 'call' and jira_ids:
            for issue_id in jira_ids:
                if not self.is_issue_resolved(issue_id):
                    if call.excinfo:
                        rep.outcome = "skipped"
                    elif PYTEST_MAJOR_VERSION < 3:
                        rep.outcome = "failed"
                    rep.wasxfail = "failed"
                    break

    def pytest_runtest_setup(self, item):
        """
        Skip test if ...
          * the provided JIRA issue is unresolved
          * AND jira_run is False
        :param item: test being run.
        """
        jira_run = self.run_test_case
        if 'jira' in item.keywords:
            jira_run = item.keywords['jira'].kwargs.get('run', jira_run)
        jira_ids = self.mark.get_jira_issues(item)

        # Check all linked issues
        for issue_id in jira_ids:
            if not jira_run and not self.is_issue_resolved(issue_id):
                pytest.skip("%s/browse/%s" % (self.conn.get_url(), issue_id))

    def fixed_in_version(self, issue_id):
        """
        Return True if:
            jira_product_version was not specified
            OR issue was fixed for jira_product_version
        else return False
        """
        if not self.version:
            return True
        affected = self.issue_cache[issue_id].get('versions')
        fixed = self.issue_cache[issue_id].get('fixed_versions')
        return self.version not in (affected - fixed)

    def is_affected(self, issue_id):
        """
        Return True if:
            at least one component affected (or not specified)
            version is affected (or not specified)
        else return False
        """
        return (
            self._affected_version(issue_id) and
            self._affected_components(issue_id)
        )

    def _affected_version(self, issue_id):
        affected = self.issue_cache[issue_id].get('versions')
        if not self.version or not affected:
            return True
        return self.version in affected

    def _affected_components(self, issue_id):
        affected = self.issue_cache[issue_id].get('components')
        if not self.components or not affected:
            return True
        return bool(self.components.intersection(affected))
