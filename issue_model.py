from marshmallow import Schema, fields, EXCLUDE


class Basic(Schema):
    id = fields.String()
    name = fields.String()


class Components(Schema):
    name = fields.String()


class Version(Schema):
    name = fields.String()


class Priority(Basic):
    pass


class Resolution(Basic):
    description = fields.String()


class Status(Basic):
    description = fields.String()


class Type(Basic):
    subtask = fields.Boolean()


class User(Schema):
    key = fields.String()
    name = fields.String()
    displayName = fields.String()
    active = fields.Boolean()


class JiraIssueSchema(Schema):
    class Meta:
        unknown = EXCLUDE # exclude unknown fields
    # Default set to None for fields that are not filled
    issuetype = fields.Nested(Type(), default=None)
    status = fields.Nested(Status(), default=None)
    priority = fields.Nested(Priority(), default=None)
    reporter = fields.Nested(User(), default=None)
    creator = fields.Nested(User(), default=None)
    versions = fields.List(fields.Nested(Version()), default=None)
    summary = fields.String(default=None)
    updated = fields.String(default=None)
    created = fields.String(default=None)
    resolutiondate = fields.String(default=None)
    duedate = fields.String(default=None)
    fixVersions = fields.List(fields.Nested(Version()), default=None)
    components = fields.List(fields.Nested(Components()), default=None)
    resolution = fields.Nested(Resolution(), default=None)
    assignee = fields.Nested(User(), default=None)
    labels = fields.List(fields.String())


class JiraIssue:
    def __init__(self, issue_id, **entries):
        self.__dict__.update(entries)
        self.issue_id = issue_id

    def __repr__(self):
        return 'JiraIssue {}'.format(self.issue_id)

    @property
    def components_list(self):
        return set(component['name'] for component in self.components)

    @property
    def fixed_versions(self):
        return set(version['name'] for version in self.fix_versions)

    @property
    def versions_list(self):
        return set(version['name'] for version in self.versions)
