from typing import (
    Iterable,
    Sequence,
    Mapping,
    Optional,
    TypeVar,
    Hashable,
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
import itertools

from . import definitions
from .utils import Visitor


T_Ref = TypeVar("T_Ref")


class RefUnresolvedError(Exception):
    pass


class Ref(Generic[T_Ref]):

    _value: Optional[T_Ref] = None
    _is_resolved: bool = False

    def __init__(self, repr: Optional[str] = None) -> None:
        self._repr = repr

    def __call__(self) -> T_Ref:
        if not self._is_resolved:
            raise RefUnresolvedError(self._repr)
        return cast(T_Ref, self._value)

    @property
    def is_resolved(self):
        return self._is_resolved

    def resolve(self, value: T_Ref):
        if self._is_resolved:
            raise RuntimeError()
        self._value = value
        self._is_resolved = True

    @classmethod
    def resolved(cls, value: T_Ref) -> "Ref[T_Ref]":
        ref = Ref()
        ref.resolve(value)
        return ref

    def __repr__(self) -> str:
        if self._is_resolved:
            return repr(self._value)
        return f"Unresolved Ref: '{self._repr}'"


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRType(Hashable):
    url: str
    name: str
    inline: bool = False
    _base: Optional[Ref["FHIRType"]] = None

    @property
    def base(self):
        return self._base() if self._base else None

    @property
    def dependencies(self):
        return set([self.base] if self.base else [])

    def __hash__(self) -> int:
        return hash((self.url, self.name))


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRPrimitiveType(FHIRType):
    def __hash__(self) -> int:
        return super().__hash__()


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRProperty:
    name: str
    min: int
    max: int

    _type: Sequence[Ref[FHIRType]]

    @property
    def type(self):
        return [elt() for elt in self._type]


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRComplexType(FHIRType):
    properties: List[FHIRProperty] = dataclasses.field(default_factory=list)

    def __hash__(self) -> int:
        return super().__hash__()

    @property
    def dependencies(self):
        return set(
            [
                *super().dependencies,
                *itertools.chain(*(prop.type for prop in self.properties)),
            ]
        )


@dataclasses.dataclass(kw_only=True)
class Context:
    path: definitions.Path = dataclasses.field(
        default_factory=lambda: definitions.Path([])
    )
    stack: Deque = dataclasses.field(default_factory=collections.deque)
    scope: Any = None


@dataclasses.dataclass(kw_only=True)
class Output:
    types: List[FHIRType]


@dataclasses.dataclass
class Config:
    base_url: str
    mappings: Mapping[str, str] = dataclasses.field(default_factory=dict)


class Parser(Visitor[definitions.Base]):

    _contexts: Deque[Context]
    _type_refs: Dict[str, Ref[FHIRType]]
    _types: List[FHIRType]

    def __init__(self, config: Config) -> None:
        self._base_url = config.base_url
        if self._base_url.endswith("/"):
            raise ValueError(self._base_url)
        self._mappings = config.mappings

    @property
    def context(self):
        return self._contexts[-1]

    def new_context(self, **updates):
        return Context(**{**dataclasses.asdict(self.context), **updates})

    def require_type(self, url: str) -> Ref[FHIRType]:
        if url in self._mappings:
            url = self._mappings[url]

        if url in self._type_refs:
            ref = self._type_refs[url]
        else:
            ref = Ref(url)
            self._type_refs[url] = ref

        return ref

    @contextlib.contextmanager
    def with_context(self, context: Context):
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

            inline_property_values: List[Mapping] = []

            for node in nodes:
                if self.visit(node) is NotImplemented:
                    if self.context.stack:
                        inline_property_values.append(self.context.stack.pop())
                    else:
                        remaining.append(node)

            for prop_values in inline_property_values:
                name = f"{current.name}{prop_values['name'].capitalize()}"
                inline = FHIRComplexType(name=name, url=current.url, inline=True)
                path = self.context.path + prop_values["name"]
                nodes = list(filter(lambda elt: elt.path > path, remaining))

                self.parse_FHIRComplexType_ElementDefinitions(
                    inline,
                    nodes,
                    path=path,
                )

                self.context.scope.properties.append(
                    FHIRProperty(
                        _type=[Ref.resolved(inline)],  # type: ignore
                        **prop_values,
                    )
                )

                self._types.append(inline)

    def visit_StructureDefinition(self, node: definitions.StructureDefinition):

        current: Optional[FHIRType] = None

        values: Mapping[str, Any] = {
            "name": node.name,
            "url": node.url,
        }
        if node.baseDefinition:
            values["_base"] = self.require_type(node.baseDefinition)

        if node.kind == "complex-type":
            current = FHIRComplexType(**values)
        elif node.kind == "primitive-type":
            current = FHIRPrimitiveType(**values)
        elif node.kind == "resource":
            current = FHIRComplexType(**values)

        if isinstance(current, FHIRComplexType):
            self.parse_FHIRComplexType_ElementDefinitions(
                current,
                filter(
                    lambda node: isinstance(node, definitions.ElementDefinition),
                    node.snapshot.element,
                ),
            )

        if isinstance(current, FHIRType):
            self._types.append(current)

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

                property_name = node.path[-1]
                property_name = property_name.removesuffix("[x]")

                values: Mapping = dict(
                    name=property_name,
                    min=0,
                    max=1,
                )

                for child in node.type:
                    if child.code == "BackboneElement":
                        assert len(node.type) == 1
                        self.context.stack.append(values)
                        return NotImplemented
                    elif self.visit(child) is not NotImplemented:
                        types.append(self.require_type(self.context.stack.pop()))

                if types:
                    self.context.scope.properties.append(
                        FHIRProperty(_type=types, **values)
                    )

                return

        return NotImplemented

    def visit_Type(self, node: definitions.ElementDefinition.Type):
        if isinstance(self.context.scope, FHIRType):
            assert node.code != "BackboneElement"
            if node.code.startswith("http://"):
                url = node.code
            else:
                url = f"{self._base_url}/StructureDefinition/{node.code}"
            self.context.stack.append(url)

    def __call__(self, nodes: Iterable[definitions.Base]) -> Output:

        self._contexts = collections.deque([Context()])
        self._type_refs = {}
        self._types = []

        for node in nodes:
            self.visit(node)

        for type in self._types:
            if not type.inline and type.url in self._type_refs:
                self._type_refs[type.url].resolve(type)

        for ref in self._type_refs.values():
            if not ref.is_resolved:
                ref()

        return Output(types=list(self._types))
