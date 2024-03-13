from typing import (
    Iterable,
    Sequence,
    Mapping,
    Dict,
    Optional,
    Callable,
    Hashable,
    List,
    Any,
    Deque,
    Generator,
    Tuple,
)
import dataclasses
import collections
import contextlib
import itertools

from . import definitions
from .utils import Visitor


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRType(Hashable):
    url: str
    name: str
    inline: bool = False
    base: Optional["FHIRType"] = None

    def __post_init__(self):
        if not self.name.isidentifier():
            raise ValueError(self.name)

    @property
    def dependencies(self):
        return set([self.base] if self.base else [])

    def __hash__(self) -> int:
        return hash((self.url, self.name))


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False)
class FHIRPrimitiveType(FHIRType):
    pass


@dataclasses.dataclass(kw_only=True, frozen=True)
class FHIRProperty:
    name: str
    min: int
    max: int

    type: Sequence[FHIRType]


@dataclasses.dataclass(kw_only=True, frozen=True, eq=False)
class FHIRComplexType(FHIRType):
    properties: List[FHIRProperty] = dataclasses.field(default_factory=list)

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


class Instruction:
    pass


class Requirement(Instruction):
    def __init__(self, predicate: Callable[[], bool]) -> None:
        self._predicate = predicate

    def __call__(self) -> bool:
        return self._predicate()


VisitOutput = Generator[Instruction, Any, Any]


Task = Tuple[definitions.Base, VisitOutput, Optional[Instruction]]


class Parser(Visitor[definitions.Base, VisitOutput]):

    _contexts: Deque[Context]
    _types: List[FHIRType]
    _resolved_types: Dict[str, FHIRType]

    def __init__(self, config: Config) -> None:
        self._base_url = config.base_url
        if self._base_url.endswith("/"):
            raise ValueError(self._base_url)
        self._mappings = config.mappings

    @property
    def context(self):
        return self._contexts[-1]

    def append_type(self, type: FHIRType):
        assert type not in self._types, type.name
        self._types.append(type)
        self.resolve_type(type)

    def resolve_type(self, type: FHIRType):
        if not type.inline:
            self._resolved_types[type.url] = type

    def new_context(self, **updates):
        return Context(**{**dataclasses.asdict(self.context), **updates})

    def require_type(self, url: str) -> VisitOutput:
        if url in self._mappings:
            url = self._mappings[url]

        if url not in self._resolved_types:
            yield Requirement(lambda: url in self._resolved_types)

        return self._resolved_types[url]

    @contextlib.contextmanager
    def with_context(self, context: Context):
        self._contexts.append(context)
        yield None
        assert self._contexts.pop() is context

    def visit_CodeSystem(self, node: definitions.CodeSystem) -> VisitOutput:
        yield from ()

    def visit_ValueSet(self, node: definitions.ValueSet) -> VisitOutput:
        yield from ()

    def parse_FHIRComplexType_ElementDefinitions(
        self,
        current: FHIRComplexType,
        nodes: Iterable[definitions.ElementDefinition],
        path: definitions.Path,
    ) -> VisitOutput:
        remaining: List[definitions.ElementDefinition] = []

        with self.with_context(self.new_context(scope=current, path=path)):

            inline_properties: Dict[str, List[Mapping]] = collections.defaultdict(list)

            for node in nodes:
                out = yield from self.visit(node)
                if out is NotImplemented:
                    if self.context.stack:
                        prop_values = self.context.stack.pop()
                        inline_properties[prop_values["name"]].append(prop_values)
                    else:
                        remaining.append(node)

            for prop_name, prop_values in inline_properties.items():
                prop_values = prop_values[0]
                if len(prop_values) > 1:
                    # TODO: handle this
                    pass
                name = f"{current.name}{prop_name.capitalize()}"
                inline = FHIRComplexType(name=name, url=current.url, inline=True)
                path = self.context.path + prop_name
                nodes = list(filter(lambda elt: elt.path > path, remaining))
                remaining = [node for node in remaining if node not in nodes]

                remaining += yield from self.parse_FHIRComplexType_ElementDefinitions(
                    inline,
                    nodes,
                    path=path,
                )

                self.context.scope.properties.append(
                    FHIRProperty(type=[inline], **prop_values)
                )

                self.append_type(inline)

        return remaining

    def visit_StructureDefinition(
        self, node: definitions.StructureDefinition
    ) -> VisitOutput:

        current: Optional[FHIRType] = None

        values: Mapping[str, Any] = {
            "name": node.type,
            "url": node.url,
        }

        if node.derivation == "constraint":
            if node.kind == "resource":
                values["name"] = node.name
            else:
                return NotImplemented

        if node.baseDefinition:
            values["base"] = yield from self.require_type(node.baseDefinition)

        if node.kind == "complex-type":
            current = FHIRComplexType(**values)
        elif node.kind == "primitive-type":
            current = FHIRPrimitiveType(**values)
        elif node.kind == "resource":
            current = FHIRComplexType(**values)

        if isinstance(current, FHIRComplexType):
            nodes = list(
                filter(
                    lambda node: isinstance(node, definitions.ElementDefinition),
                    node.snapshot.element,
                )
            )

            cursor = current
            while cursor is not None and nodes:
                nodes = yield from self.parse_FHIRComplexType_ElementDefinitions(
                    current,
                    nodes,
                    path=self.context.path + cursor.name,
                )
                cursor = cursor.base

        if isinstance(current, FHIRType):
            self.append_type(current)

    def visit_ElementDefinition(
        self, node: definitions.ElementDefinition
    ) -> VisitOutput:
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
                    min=node.min,
                    max=-1 if node.max == "*" else int(node.max),
                )

                for child in node.type:
                    if child.code == "BackboneElement":
                        assert len(node.type) == 1
                        self.context.stack.append(values)
                        return NotImplemented

                    out = yield from self.visit(child)

                    if out is not NotImplemented:
                        type = yield from self.require_type(self.context.stack.pop())
                        types.append(type)

                if types:
                    self.context.scope.properties.append(
                        FHIRProperty(type=types, **values)
                    )

                return

        return NotImplemented

    def visit_Type(self, node: definitions.ElementDefinition.Type) -> VisitOutput:
        if isinstance(self.context.scope, FHIRType):
            assert node.code != "BackboneElement"
            if node.code.startswith("http://"):
                url = node.code
            else:
                url = f"{self._base_url}/StructureDefinition/{node.code}"
            self.context.stack.append(url)

        yield from ()

    def __call__(self, nodes: Iterable[definitions.Base]) -> Output:

        self._contexts = collections.deque([Context()])
        self._resolved_types = {}
        self._types = []

        tasks: Sequence[Task] = [(node, self.visit(node), None) for node in nodes]

        while tasks:
            next_tasks: Sequence[Task] = []
            for node, gen, prev in tasks:
                if not isinstance(gen, Generator):
                    assert gen is NotImplemented
                    continue

                instruction = next(gen, None) if prev is None else prev
                if instruction is None:
                    continue

                if isinstance(instruction, Requirement) and instruction():
                    # Requirement met
                    instruction = None

                next_tasks.append((node, gen, instruction))

            if tasks == next_tasks:
                raise RuntimeError()

            tasks = next_tasks

        return Output(types=list(self._types))
