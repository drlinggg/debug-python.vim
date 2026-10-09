"""Tests for pydbg.describer.Describer."""
import os

from describer import Describer


class Point:
    """A user-defined class used to check attribute expansion."""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def test_describe_value_reports_true_type() -> None:
    d = Describer()
    assert d.describe_value(10) == {"type": "int", "value": "10"}
    assert d.describe_value("hi") == {"type": "str", "value": "'hi'"}


def test_describe_value_expands_user_class_attributes() -> None:
    d = Describer()
    desc = d.describe_value(Point(1, 2))
    assert desc["type"] == "Point"
    assert desc["attributes"] == {
        "x": {"type": "int", "value": "1"},
        "y": {"type": "int", "value": "2"},
    }


class Leaf:
    """Innermost object holding a scalar."""

    def __init__(self) -> None:
        self.n = 7


class Node:
    """Object whose attribute is another user object."""

    def __init__(self) -> None:
        self.leaf = Leaf()


def test_describe_value_expands_nested_user_objects() -> None:
    d = Describer()
    desc = d.describe_value(Node())
    assert desc["type"] == "Node"
    leaf = desc["attributes"]["leaf"]
    assert leaf["type"] == "Leaf"
    assert leaf["attributes"]["n"] == {"type": "int", "value": "7"}


def test_describe_value_survives_reference_cycle() -> None:
    d = Describer()
    a = Node()
    a.leaf = a  # cycle: must not recurse forever
    desc = d.describe_value(a)
    assert desc["type"] == "Node"


def test_describe_globals_hides_modules_functions_and_builtins() -> None:
    d = Describer()
    g = {
        "__name__": "m",
        "os": os,                 # module -> hidden
        "helper": len,            # builtin function -> hidden
        "Point": Point,           # class -> hidden
        "CONST": 42,              # user data -> shown
        "names": ["a", "b"],      # container -> shown
    }
    out = d.describe_globals(g)
    assert set(out) == {"CONST", "names"}
    assert out["CONST"] == {"type": "int", "value": "42"}


def test_describe_locals_shows_all_but_dunders() -> None:
    d = Describer()
    out = d.describe_locals({"x": 1, "__hidden__": 9})
    assert set(out) == {"x"}
