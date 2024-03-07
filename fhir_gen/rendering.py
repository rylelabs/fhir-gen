from typing import TypeVar, Mapping, Optional, Dict, Sequence, Type
import os.path
import dataclasses
import importlib
from dataclass_wizard import YAMLWizard
from jinja2 import Environment, FileSystemLoader

from . import parsing


T_Target = TypeVar("T_Target")


RenderInput = parsing.ParseOutput


@dataclasses.dataclass
class RenderConfig:
    output_dir: str
    template: str
    variables: Mapping = dataclasses.field(default_factory=dict)


class Context:

    def __call__(self, input: RenderInput, variables: Mapping) -> Optional[Mapping]:
        return None


class FHIRTypeContext(Context):

    cursor: int = 0

    def __call__(self, input: RenderInput, variables: Mapping):
        if len(input.types) <= self.cursor:
            return

        current = list(input.types.values())[self.cursor]
        self.cursor += 1
        return {"type_name": current.name, "dependencies": []}


@dataclasses.dataclass
class TemplateManifest(YAMLWizard):

    @dataclasses.dataclass
    class FileEntry:

        context: Optional[str]  # type: ignore
        _context: Type[Context] = dataclasses.field(repr=False, init=False)

        @property
        def context(self) -> Type[Context]:
            return self._context

        @context.setter
        def context(self, value: Optional[str] = None):
            if value:
                parts = value.split(".")
                mod = importlib.import_module(".".join(parts[:-1]))
                self._context = getattr(mod, parts[-1])
            else:
                self._context = Context

        output_file: Optional[str] = None

    files: Dict[str, FileEntry]


def output_file_from_template_file(filename: str, suffix: str = ".tmpl"):
    if not filename.endswith(suffix):
        raise ValueError(filename)

    return filename[: -len(suffix)]


class Renderer:

    @dataclasses.dataclass
    class Handler:
        context: Type[Context]
        template_file: str
        output_file: str

    _handlers: Sequence[Handler]

    def __init__(self, config: RenderConfig) -> None:
        self.root_dir = os.path.abspath(config.template)
        self.variables = dict(config.variables)
        manifest = TemplateManifest.from_yaml_file(
            os.path.join(self.root_dir, "manifest.yaml")
        )

        assert isinstance(manifest, TemplateManifest)

        self._handlers = [
            self.Handler(
                context=entry.context,
                template_file=template_file,
                output_file=entry.output_file
                or output_file_from_template_file(template_file),
            )
            for template_file, entry in manifest.files.items()
        ]

    def __call__(self, input: RenderInput):

        env = Environment(loader=FileSystemLoader(self.root_dir))

        for handler in self._handlers:
            context = handler.context()
            template = env.get_template(os.path.join(handler.template_file))
            while True:
                template_variables = context(input, self.variables)
                if template_variables is None:
                    break

                output_file = env.from_string(handler.output_file).render(
                    template_variables
                )

                template.render(template_variables)
