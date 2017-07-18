import requests


class JiraSiteConnection(object):
    def __init__(
            self, url,
            username=None,
            password=None,
            verify=True,
    ):
        self.url = url
        self.username = username
        self.password = password
        self.verify = verify

        # Setup basic_auth
        if self.username and self.password:
            self.basic_auth = (self.username, self.password)
        else:
            self.basic_auth = None

    def _jira_request(self, url, method='get', **kwargs):
        if 'verify' not in kwargs:
            kwargs['verify'] = self.verify
        if self.basic_auth:
            return requests.request(
                method, url, auth=self.basic_auth, **kwargs
            )
        else:
            return requests.request(method, url, **kwargs)

    def check_connection(self):
        # This URL work for both anonymous and logged in users
        auth_url = '{url}/rest/api/2/mypermissions'.format(url=self.url)
        r = self._jira_request(auth_url)
        # Handle connection errors
        r.raise_for_status()

        # For some reason in case on invalid credentials the status is still
        # 200 but the body is empty
        if not r.text:
            raise Exception(
                'Could not connect to {url}. Invalid credentials'.format(
                    url=self.url)
            )

        # If the user does not have sufficient permissions to browse issues
        elif not r.json()['permissions']['BROWSE']['havePermission']:
            raise Exception('Current user does not have sufficient permissions'
                            ' to view issue')
        else:
            return True

    def is_connected(self):
        return self.check_connection()

    def get_issue(self, issue_id):
        issue_url = '{url}/rest/api/2/issue/{issue_id}'.format(
            url=self.url, issue_id=issue_id
        )
        issue = self._jira_request(issue_url).json()
        field = issue['fields']
        return {
            'components': set(
                c['name'] for c in field.get('components', set())
            ),
            'versions': set(
                v['name'] for v in field.get('versions', set())
            ),
            'fixed_versions': set(
                v['name'] for v in field.get('fixVersions', set())
            ),
            'status': field['status']['name'].lower(),
        }

    def get_url(self):
        return self.url
