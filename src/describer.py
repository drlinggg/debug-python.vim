"""Turn a Python frame into a compact, typed view of its variables.

The Describer is deliberately conservative. It never dumps every live object:

    * locals: every name in scope (minus dunders),
    * globals: only user data (primitives, containers, user-class instances);
      modules, functions and classes are hidden,
    * user-class instances: one level of their attributes is expanded.

Each value becomes a descriptor dict::

    {"type": "int", "value": "10"}
    {"type": "Point", "value": "<...>", "attributes": {"x": {...}, "y": {...}}}
"""

import inspect
from typing import Any, Dict

from config import MAX_DEPTH, MAX_REPR

JsonDict = Dict[str, Any]

# Scalars shown by value, never expanded.
_PRIMITIVES = (int, float, bool, str, bytes, complex, type(None))
# Standard containers shown as a whole, never treated as user instances.
_CONTAINERS = (list, tuple, dict, set, frozenset)


def _short_repr(obj: Any) -> str:
    """Return ``repr(obj)`` clipped to :data:`MAX_REPR` characters.

    Args:
        obj: Any object.

    Returns:
        A safe, length-limited repr string.
    """
    try:
        text = repr(obj)
    except Exception as exc:  # repr may raise for broken objects
        return f"<unreprable: {exc!r}>"
    if len(text) > MAX_REPR:
        return text[: MAX_REPR - 1] + "…"
    return text


class Describer:
    """Describe values and frame namespaces for the variables panel."""

    def describe_value(self, obj, depth=MAX_DEPTH, seen=None):
        # -- special-cased types: clean identifiers, no repr() noise -------- #
        if inspect.ismodule(obj):
            return {"type": "module", "value": obj.__name__}
        if isinstance(obj, type):
            return {"type": "class", "value": obj.__qualname__}
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            return {"type": "function", "value": obj.__qualname__}
        if inspect.isbuiltin(obj):
            return {"type": "builtin", "value": obj.__name__}
    
        # -- everything else: type + clipped repr --------------------------- #
        desc: JsonDict = {"type": type(obj).__name__, "value": _short_repr(obj)}
        seen = frozenset() if seen is None else seen
        if depth > 0 and self._is_user_instance(obj) and id(obj) not in seen:
            child_seen = seen | {id(obj)}
            desc["attributes"] = {
                name: self.describe_value(value, depth - 1, child_seen)
                for name, value in vars(obj).items()
                if not name.startswith("__")
            }
        return desc

    def describe_locals(self, namespace: Dict[str, Any]) -> JsonDict:
        """Describe every local name except dunders.

        Args:
            namespace: A frame's ``f_locals``.

        Returns:
            Mapping name -> descriptor.
        """
        return {
            name: self.describe_value(value)
            for name, value in namespace.items()
            if not name.startswith("__")
        }

    def describe_globals(self, namespace: Dict[str, Any]) -> JsonDict:
        """Describe only user data among the globals.

        Modules, functions and classes are hidden to avoid noise.

        Args:
            namespace: A frame's ``f_globals``.

        Returns:
            Mapping name -> descriptor.
        """
        out: JsonDict = {}
        for name, value in namespace.items():
            if name.startswith("__"):
                continue
            if self._is_shown_global(value):
                out[name] = self.describe_value(value)
        return out

    def describe(self, frame: Any) -> tuple[JsonDict, JsonDict]:
        """Describe a frame's locals and globals.

        Args:
            frame: A live Python frame object.

        Returns:
            A ``(locals, globals)`` tuple of descriptor mappings.
        """
        return self.describe_locals(frame.f_locals), self.describe_globals(
            frame.f_globals
        )

    # -- helpers ----------------------------------------------------------- #
    def _is_user_instance(self, obj: Any) -> bool:
        """Return True for an instance of a user-defined class."""
        if isinstance(obj, _PRIMITIVES) or isinstance(obj, _CONTAINERS):
            return False
        if isinstance(obj, type) or inspect.isroutine(obj) or inspect.ismodule(obj):
            return False
        if not hasattr(obj, "__dict__"):
            return False
        return getattr(type(obj), "__module__", "") != "builtins"

    def _is_shown_global(self, value: Any) -> bool:
        """Return True if a global is user data worth showing."""
        if isinstance(value, _PRIMITIVES) or isinstance(value, _CONTAINERS):
            return True
        if inspect.ismodule(value) or inspect.isroutine(value):
            return True      
        if isinstance(value, type):
            return True     
        return self._is_user_instance(value)
