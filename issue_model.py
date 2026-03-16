from marshmallow import EXCLUDE, Schema, fields


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
        unknown = EXCLUDE  # exclude unknown fields

    # Default set to None for fields that are not filled
    issuetype = fields.Nested(Type, load_default=None, dump_default=None)
    status = fields.Nested(Status, load_default=None, dump_default=None)
    priority = fields.Nested(Priority, load_default=None, dump_default=None)
    reporter = fields.Nested(User, load_default=None, dump_default=None)
    creator = fields.Nested(User, load_default=None, dump_default=None)
    versions = fields.List(
        fields.Nested(Version), load_default=None, dump_default=None
    )
    summary = fields.String(load_default=None, dump_default=None)
    updated = fields.String(load_default=None, dump_default=None)
    created = fields.String(load_default=None, dump_default=None)
    resolutiondate = fields.String(load_default=None, dump_default=None)
    duedate = fields.String(load_default=None, dump_default=None)
    fixVersions = fields.List(
        fields.Nested(Version), load_default=None, dump_default=None
    )
    components = fields.List(
        fields.Nested(Components), load_default=None, dump_default=None
    )
    resolution = fields.Nested(Resolution, load_default=None, dump_default=None)
    assignee = fields.Nested(User, load_default=None, dump_default=None)
    labels = fields.List(fields.String(), load_default=None, dump_default=None)


class JiraIssue:
    def __init__(self, issue_id, **entries):
        self.__dict__.update(entries)
        self.issue_id = issue_id

    def __repr__(self):
        return f"JiraIssue {self.issue_id}"

    @property
    def components_list(self):
        return set(component["name"] for component in (self.components or []))

    @property
    def fixed_versions(self):
        return set(
            version["name"]
            for version in (getattr(self, "fixVersions", None) or [])
        )

    @property
    def versions_list(self):
        return set(version["name"] for version in (self.versions or []))
