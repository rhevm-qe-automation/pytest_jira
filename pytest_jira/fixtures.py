import pytest


@pytest.fixture
def jira_issue(request):
    def wrapper_jira_issue(issue_id):
        jira_plugin = getattr(request.config, '_jira')
        if jira_plugin and jira_plugin.conn.is_connected():
            return jira_plugin.is_issue_resolved(issue_id)
    return wrapper_jira_issue
