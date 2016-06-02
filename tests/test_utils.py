import six
from pytest_jira import _get_value


def init_config_parser():
    c = six.moves.configparser.ConfigParser()
    c.set("DEFAULT", "key", "value")
    return c


def test_get_value1():
    c = init_config_parser()
    assert _get_value(c, "DEFAULT", "key") == "value"


def test_get_value2():
    c = init_config_parser()
    assert _get_value(c, "DEFAULT", "nokey") is None


def test_get_value3():
    c = init_config_parser()
    assert _get_value(c, "DEFAULT", "nokey", "one") == "one"
