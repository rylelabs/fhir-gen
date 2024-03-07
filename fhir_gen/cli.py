import os
import sys
import logging
from typing import Optional, Mapping, Type

from jsonargparse import CLI

from .definitions import Definitions
from .parsing import Parser
from .rendering import RenderConfig, Renderer


def generate(
    definitions: Definitions,
    rendering: RenderConfig,
    cache_dir: Optional[str] = None,
    mappings: Optional[Mapping[str, Type]] = None,
):
    parser = Parser(mappings=mappings)
    renderer = Renderer(rendering)

    renderer(
        parser(
            entry.resource
            for bundle in definitions.iter_bundles(cache_dir=cache_dir)
            for entry in bundle.entry
        )
    )


def main():
    sys.path.append(os.getcwd())
    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    CLI(generate)


if __name__ == "__main__":
    main()
