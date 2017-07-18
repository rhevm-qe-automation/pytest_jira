import sys
import re


class JiraMarkerReporter(object):
    issue_re = r"([A-Z]+-[0-9]+)"

    def __init__(self, strategy, docs, pattern):
        self.issue_pattern = re.compile(pattern or self.issue_re)
        self.docs = docs
        self.strategy = strategy.lower()

    def get_jira_issues(self, item):
        jira_ids = []
        # Was the jira marker used?
        if 'jira' in item.keywords:
            marker = item.keywords['jira']
            if len(marker.args) == 0:
                raise TypeError('JIRA marker requires one, or more, arguments')
            jira_ids.extend(item.keywords['jira'].args)

        # Was a jira issue referenced in the docstr?
        if self.docs and item.function.__doc__:
            jira_ids.extend(
                [
                    m.group(0)
                    for m in self.issue_pattern.finditer(item.function.__doc__)
                ]
            )

        # Filter valid issues, and return unique issues
        for jid in set(jira_ids):
            if not self.issue_pattern.match(jid):
                raise ValueError(
                    'JIRA marker argument `%s` does not match pattern' % jid
                )
        return list(
            set(jira_ids)
        )

    def get_default(self, jid):
        if self.strategy == 'open':
            return {'status': 'open'}
        if self.strategy == 'strict':
            raise ValueError(
                'JIRA marker argument `%s` was not found' % jid
            )
        if self.strategy == 'warn':
            sys.stderr.write(
                'JIRA marker argument `%s` was not found' % jid
            )
        return None
