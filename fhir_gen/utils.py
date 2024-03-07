import inspect
from typing import Generic, TypeVar, Deque


_T = TypeVar("_T")


__all__ = ["Visitor"]


class Visitor(Generic[_T]):
    def visit(self, node: _T):
        classes = inspect.getmro(type(node) if not isinstance(node, type) else node)
        for cls in classes:
            visitor = getattr(self, "visit_%s" % cls.__name__, None)
            if visitor is None:
                continue
            out = visitor(node)
            if out is NotImplemented:
                continue
            assert out is None
            return

        return NotImplemented
