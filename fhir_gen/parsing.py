from typing import (
    Iterable,
    Sequence,
    Mapping,
    Type,
    Optional,
    TypeVar,
    Generic,
    cast,
    List,
    Dict,
    Any,
    Deque,
)
import dataclasses
import collections
import contextlib

from . import definitions
from .utils import Visitor


T_Ref = TypeVar("T_Ref")


class RefUnresolvedError(Exception):
    pass


class Ref(Generic[T_Ref]):

    _value: Optional[T_Ref] = None
    _resolved: bool = False

    def __init__(self, id: str, type: Type[T_Ref]) -> None:
        self.id = id
        self._type = type

    def __call__(self) -> T_Ref:
        if not self._resolved:
            raise RefUnresolvedError(self.id)
        return cast(T_Ref, self._value)

    def resolve(self, value: T_Ref):
        if self._resolved:
            raise RuntimeError()
        self._value = value
        self._resolved = True

    def __repr__(self) -> str:
        if self._resolved:
            return repr(self._value)
        return f"Unresolved Ref: '{self.id}'"


@dataclasses.dataclass(kw_only=True)
class FHIRType:
    name: str


@dataclasses.dataclass(kw_only=True)
class FHIRPrimitiveType(FHIRType): ...


@dataclasses.dataclass(kw_only=True)
class FHIRProperty:
    name: str
    type: Sequence[Ref[FHIRType]]


@dataclasses.dataclass(kw_only=True)
class FHIRComplexType(FHIRType):
    properties: List[FHIRProperty] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(kw_only=True)
class ParseContext:
    path: definitions.Path = dataclasses.field(
        default_factory=lambda: definitions.Path([])
    )
    scope: Any = None


@dataclasses.dataclass(kw_only=True)
class ParseOutput:
    types: Dict[str, FHIRType]


class Parser(Visitor[definitions.Base]):

    _contexts: Deque[ParseContext]
    _refs: Dict[str, Ref]
    _types: Dict[str, FHIRType]

    def __init__(self, mappings: Optional[Mapping[str, Type]] = None) -> None:
        self._mappings = dict(mappings or {})

    @property
    def context(self):
        return self._contexts[-1]

    def new_context(self, **updates):
        return ParseContext(**{**dataclasses.asdict(self.context), **updates})

    def require(self, id: str, type: Type[T_Ref]) -> Ref[T_Ref]:
        if id in self._refs:
            ref = self._refs[id]
            assert issubclass(type, ref._type)
        else:
            ref = Ref(id, type)
            self._refs[id] = ref

        return ref

    @contextlib.contextmanager
    def with_context(self, context: ParseContext):
        self._contexts.append(context)
        yield None
        assert self._contexts.pop() is context

    def visit_CodeSystem(self, node: definitions.CodeSystem):
        pass

    def visit_ValueSet(self, node: definitions.ValueSet):
        pass

    def parse_FHIRComplexType_ElementDefinitions(
        self,
        current: FHIRComplexType,
        nodes: Iterable[definitions.ElementDefinition],
        path: Optional[definitions.Path] = None,
    ):
        remaining: List[definitions.ElementDefinition] = []
        with self.with_context(
            self.new_context(
                scope=current,
                path=path or self.context.path + current.name,
            )
        ):
            for node in nodes:
                if self.visit(node) is NotImplemented:
                    remaining.append(node)

            inlines = list(filter(lambda elt: elt.path > self.context.path, remaining))

            if inlines:
                part = inlines[0].path[len(self.context.path)]
                current = FHIRComplexType(name=f"{current.name}{part.capitalize()}")
                self.parse_FHIRComplexType_ElementDefinitions(
                    current, inlines, path=self.context.path + part
                )

    def visit_StructureDefinition(self, node: definitions.StructureDefinition):
        assert node.id not in self._types

        current: Optional[FHIRType] = None

        if node.kind == "complex-type":
            current = FHIRComplexType(name=node.id)
        elif node.kind == "primitive-type":
            current = FHIRPrimitiveType(name=node.id)
        elif node.kind == "resource":
            current = FHIRComplexType(name=node.id)

        if isinstance(current, FHIRComplexType):
            self.parse_FHIRComplexType_ElementDefinitions(
                current,
                filter(
                    lambda node: isinstance(node, definitions.ElementDefinition),
                    node.snapshot.element,
                ),
            )

        if isinstance(current, FHIRType):
            self._types[current.name] = current

    def visit_ElementDefinition(self, node: definitions.ElementDefinition):
        assert node.id
        assert self.context.path
        assert self.context.scope is not None

        if node.path == self.context.path:
            return
        elif node.path > self.context.path:
            parts = node.path[len(self.context.path) :]
            if len(parts) == 1:
                assert isinstance(self.context.scope, FHIRComplexType)
                types = []
                for child in node.type:
                    if self.visit(child) is not NotImplemented:
                        types.append(self.require(child.code, FHIRType))

                self.context.scope.properties.append(
                    FHIRProperty(name=node.path[-1], type=types)
                )

                return

        return NotImplemented

    def visit_Type(self, node: definitions.ElementDefinition.Type):
        if node.code == "http://hl7.org/fhirpath/System.String":
            return NotImplemented

    def __call__(self, nodes: Iterable[definitions.Base]) -> ParseOutput:

        self._contexts = collections.deque([ParseContext()])
        self._refs = {}
        self._types = {}

        for node in nodes:
            self.visit(node)

        for type in self._types.values():
            if type.name in self._refs:
                self._refs[type.name].resolve(type)

        for ref in self._refs.values():
            ref()

        return ParseOutput(types=dict(self._types))
