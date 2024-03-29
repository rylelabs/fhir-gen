from typing import Optional, List, Sequence, Literal, Union, Iterator, Dict, overload
from urllib.parse import urlsplit
import requests
import os.path
import tempfile
import zipfile
import contextlib
import json

import dataclasses
from dataclass_wizard import JSONWizard


class Base:
    pass


class Path(Sequence):
    def __init__(self, value: Union[str, Sequence[str]]) -> None:
        self._parts = value.split(".") if isinstance(value, str) else list(value)

    def __str__(self) -> str:
        return ".".join(self._parts)

    @overload
    def __getitem__(self, key: int) -> str: ...

    @overload
    def __getitem__(self, key: slice) -> "Path": ...

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._parts[key]
        return Path(self._parts[key])

    def __len__(self):
        return len(self._parts)

    def __repr__(self):
        return repr(self._parts)

    def __eq__(self, other: object):
        if isinstance(other, (Path, str)):
            return str(self) == str(other)
        raise TypeError(type(other))

    def __gt__(self, other: object):
        if isinstance(other, (Path, str)):
            other = Path(str(other))
            return len(self) > len(other) and self[: len(other)] == other

        raise TypeError(type(other))

    def __gte__(self, other: object):
        if isinstance(other, (Path, str)):
            other = Path(str(other))
            return len(self) >= len(other) and self[: len(other)] == other

        raise TypeError(type(other))

    def __add__(self, other: object):
        if isinstance(other, (Path, str)):
            return Path([*self, *Path(other)])

        raise TypeError(type(other))


@dataclasses.dataclass(kw_only=True)
class Resource(Base):
    id: str
    resourceType: str
    meta: Dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True)
class Element(Base):
    id: Optional[str] = None


@dataclasses.dataclass(kw_only=True)
class ElementDefinition(Element):

    @dataclasses.dataclass(kw_only=True)
    class Type(Element):
        code: str

    @dataclasses.dataclass(kw_only=True)
    class Base(Element):
        path: str
        min: int
        max: str

    path: str  # type: ignore
    _path: Path = dataclasses.field(repr=False, init=False)

    @property
    def path(self) -> Path:
        return self._path

    @path.setter
    def path(self, value: str):
        self._path = Path(str(value))

    min: int
    max: str
    base: Optional[Base] = None
    comment: Optional[str] = None
    type: List[Type] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(
    kw_only=True,
)
class StructureDefinition(Resource):

    @dataclasses.dataclass(kw_only=True)
    class Snapshot(Base):
        element: List[ElementDefinition]

    url: str
    name: str
    type: str
    snapshot: Snapshot
    abstract: bool
    kind: Union[
        Literal["primitive-type"],
        Literal["complex-type"],
        Literal["logical"],
        Literal["resource"],
    ]

    derivation: Optional[Union[Literal["specialization"], Literal["constraint"]]] = None
    baseDefinition: Optional[str] = None


@dataclasses.dataclass(kw_only=True)
class ValueSet(Resource):
    url: str


@dataclasses.dataclass(kw_only=True)
class CodeSystem(Resource):
    pass


@dataclasses.dataclass(kw_only=True)
class CapabilityStatement(Resource):
    pass


@dataclasses.dataclass(kw_only=True)
class OperationDefinition(Resource):
    pass


@dataclasses.dataclass(kw_only=True)
class CompartmentDefinition(Resource):
    pass


@dataclasses.dataclass(kw_only=True)
class BundleEntry(Element):
    resource: Union[
        StructureDefinition,
        CodeSystem,
        ValueSet,
        CapabilityStatement,
        OperationDefinition,
        CompartmentDefinition,
    ]


@dataclasses.dataclass(kw_only=True)
class Bundle(Resource):

    type: Literal["collection"]
    entry: List[BundleEntry]


@dataclasses.dataclass(kw_only=True)
class Container(JSONWizard):
    class _(JSONWizard.Meta):
        tag_key = "resourceType"
        auto_assign_tags = True

    root: Union[StructureDefinition, Bundle]


class Definitions:

    def __init__(
        self,
        url: str,
        sources: Sequence[str],
        version: Optional[str] = None,
    ) -> None:
        self.url = url
        self.version = version
        self.sources = list(sources)

    def iter_containers(
        self, *, cache_dir: Optional[str], chunk_size: int = 512
    ) -> Iterator[Container]:

        if cache_dir is not None and not os.path.exists(cache_dir):
            os.mkdir(cache_dir)

        with (
            tempfile.TemporaryDirectory()
            if not cache_dir
            else contextlib.nullcontext(cache_dir)
        ) as dir:
            path = urlsplit(self.url).path
            if not path:
                raise ValueError(self.url)

            fname = os.path.join(dir, os.path.split(path)[-1])

            if not os.path.exists(fname):
                with requests.get(self.url, stream=True) as res:
                    if not res.status_code == 200:
                        raise ValueError(self.url)

                    with open(fname, "wb") as f:
                        for chunk in res.iter_content(chunk_size):
                            f.write(chunk)

            assert os.path.exists(fname)

            with zipfile.ZipFile(fname, mode="r") as zip:
                for name in self.sources:
                    root = json.load(zip.open(name))

                    container = Container.from_dict({"root": root})
                    assert isinstance(container, Container)

                    yield container

    def iter_resources(self, *args, **kwargs):
        for container in self.iter_containers(*args, **kwargs):
            if isinstance(container.root, StructureDefinition):
                yield container.root
            elif isinstance(container.root, Bundle):
                for entry in container.root.entry:
                    yield entry.resource
