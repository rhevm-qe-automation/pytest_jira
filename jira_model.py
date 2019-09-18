import platform
from distutils.version import LooseVersion
from typing import List, Union

# import pydantic in supported python versions only
if LooseVersion(platform.python_version()) >= LooseVersion("3.6.0"):
    from pydantic import BaseModel, Schema
else:
    class BaseModel:
        pass

    class Schema:
        def __init__(self, *args, **kwargs):
            pass


class Basic(BaseModel):
    id: str
    name: str


class Components(BaseModel):
    name: str


class Version(BaseModel):
    name: str


class Priority(Basic):
    pass


class Resolution(Basic):
    description: str = None


class Status(Basic):
    description: str = None


class Type(Basic):
    subtask: str


class User(BaseModel):
    key: str
    name: str
    display_name: str = Schema(..., alias='displayName')
    active: bool


class JiraIssue(BaseModel):
    # Default set to None for issues that are not found
    issue_type: Type = Schema(None, alias='issuetype')
    status: Union[str, Status] = None
    priority: Priority = None
    reporter: User = None
    creator: User = None
    versions: List[Version] = None
    summary: str = None
    updated: str = None
    created: str = None
    resolution_date: str = Schema(None, alias='resolutiondate')
    due_date: str = Schema(None, alias='duedate')
    fix_versions: List[Version] = Schema(None, alias='fixVersions')
    components: List[Components] = None
    resolution: Resolution = None
    assignee: User = None
    labels: list = None

    @property
    def component_list(self):
        return set(component.name for component in self.components)

    @property
    def fixed_versions(self):
        return set(version.name for version in self.fix_versions)

    @property
    def version_list(self):
        return set(version.name for version in self.versions)
