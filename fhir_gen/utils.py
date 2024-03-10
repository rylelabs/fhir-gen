import inspect
from typing import Generic, Type, TypeVar, TypeGuard, Callable, Any


__all__ = ["isinstance_predicate", "Visitor"]


T_Type = TypeVar("T_Type")


def isinstance_predicate(*types: Type[T_Type]) -> Callable[[Any], TypeGuard[T_Type]]:
    def fn(value) -> TypeGuard[T_Type]:
        return isinstance(value, types)

    return fn


T_Node = TypeVar("T_Node")


class Visitor(Generic[T_Node]):
    def visit(self, node: T_Node):
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
