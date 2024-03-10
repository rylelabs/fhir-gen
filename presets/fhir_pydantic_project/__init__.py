from typing import Mapping
import itertools
import collections
import os.path
import jinja2
import keyword
from black import format_str, FileMode

from fhir_gen import rendering, parsing
from fhir_gen.rendering import RenderInput
from fhir_gen.utils import isinstance_predicate


ROOT_DIR = os.path.dirname(__file__)


def module_name_for_type(type: parsing.FHIRType):
    if isinstance(type, parsing.FHIRPrimitiveType):
        return "primitives"

    return type.url.split("/")[-1].lower()


@jinja2.pass_context
def type_reference(context: Mapping, type: parsing.FHIRType):
    assert "module_name" in context
    module_name = module_name_for_type(type)
    reference = type.name
    if module_name != context["module_name"]:
        reference = f"{module_name}.{reference}"
    return reference


@jinja2.pass_context
def prop_type_annotation(context: Mapping, prop: parsing.FHIRProperty):
    choices = [f'"{type_reference(context, type)}"' for type in prop.type]
    if len(choices) == 1:
        return choices[0]
    return f"Union[{','.join(choices)}]"


def prop_name(prop: parsing.FHIRProperty):
    name = prop.name
    if keyword.iskeyword(name):
        name = f"{name}_"
        assert not keyword.iskeyword(name)

    return name


class InitContext(rendering.Context):

    def __call__(self, input: RenderInput, variables: Mapping):
        return [{**variables}]


class PrimitivesContext(rendering.Context):

    def __call__(self, input: RenderInput, variables: Mapping):

        types = list(
            filter(isinstance_predicate(parsing.FHIRPrimitiveType), input.types)
        )

        return [
            {
                "types": types,
                "module_name": module_name_for_type(types[0]),
                **variables,
            }
        ]


class ComplexTypeContext(rendering.Context):

    def __call__(self, input: RenderInput, variables: Mapping):
        complex_types = list(
            filter(isinstance_predicate(parsing.FHIRComplexType), input.types)
        )

        grouped_complex_types = collections.defaultdict(list)
        for type in complex_types:
            grouped_complex_types[type.url].append(type)

        for url, types in grouped_complex_types.items():

            dependencies = set(itertools.chain(*(type.dependencies for type in types)))

            grouped_dependencies = collections.defaultdict(list)
            for type in dependencies:
                grouped_dependencies[module_name_for_type(type)].append(type)
            module_name = module_name_for_type(types[0])
            yield {
                "types": types,
                "import_modules": set(grouped_dependencies.keys()) - {module_name},
                "module_name": module_name,
                **variables,
            }


def post_process_py(value: str) -> str:
    return format_str(value, mode=FileMode())


class FHIRPydanticPreset(rendering.Preset):

    root_dir = ROOT_DIR

    artifacts = [
        rendering.Artifact(
            template_file="__init__.py.tmpl",
            output_file="{{ package_name }}/__init__.py",
            context=InitContext(),
            post_process=post_process_py,
        ),
        rendering.Artifact(
            template_file="complex_type.py.tmpl",
            output_file="{{ package_name }}/{{ module_name }}.py",
            context=ComplexTypeContext(),
            post_process=post_process_py,
        ),
        rendering.Artifact(
            template_file="primitives.py.tmpl",
            output_file="{{ package_name }}/{{ module_name }}.py",
            context=PrimitivesContext(),
            post_process=post_process_py,
        ),
    ]

    def setup(self, env: rendering.Environment):
        env.filters.update(
            dict(
                module_name_for_type=module_name_for_type,
                type_reference=type_reference,
                prop_type_annotation=prop_type_annotation,
                prop_name=prop_name,
            )
        )
