from typing import Mapping, Iterable, Sequence, Callable, Optional
import abc
import os
import os.path
from pathlib import Path
import shutil
import dataclasses


from jinja2 import Environment, FileSystemLoader

from . import parsing


RenderInput = parsing.Output


class Context(metaclass=abc.ABCMeta):

    def __call__(self, input: RenderInput, variables: Mapping) -> Iterable[Mapping]: ...


@dataclasses.dataclass
class Artifact:
    template_file: str
    output_file: str
    context: Context
    post_process: Optional[Callable[[str], str]] = None


class Preset:

    root_dir: str
    artifacts: Sequence[Artifact]

    def setup(self, env: Environment): ...


@dataclasses.dataclass
class Config:
    preset: Preset
    output_dir: str
    variables: Mapping = dataclasses.field(default_factory=dict)


class Renderer:

    def __init__(self, config: Config) -> None:
        self.output_dir = os.path.abspath(config.output_dir)
        self.variables = dict(config.variables)
        self.preset = config.preset

    def __call__(self, input: RenderInput):

        env = Environment(loader=FileSystemLoader(self.preset.root_dir))
        self.preset.setup(env)

        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

        for artifact in self.preset.artifacts:

            template = env.get_template(os.path.join(artifact.template_file))

            for template_variables in artifact.context(input, self.variables):

                output_file = env.from_string(artifact.output_file).render(
                    template_variables
                )

                output_file = os.path.join(self.output_dir, output_file)

                # Ensure output_file is located inside output_dir
                if not Path(self.output_dir) in Path(output_file).parents:
                    raise ValueError(output_file)

                if not os.path.exists(os.path.dirname(output_file)):
                    os.makedirs(os.path.dirname(output_file), exist_ok=True)

                with open(output_file, "w") as f:
                    out = template.render(template_variables)
                    if artifact.post_process is not None:
                        out = artifact.post_process(out)
                    f.write(out)
