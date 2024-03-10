import os
import sys
import logging
from typing import Optional

from jsonargparse import CLI

from .definitions import Definitions
from .parsing import Config as ParserConfig, Parser
from .rendering import Config as RendererConfig, Renderer


def generate(
    definitions: Definitions,
    renderer: RendererConfig,
    parser: ParserConfig,
    cache_dir: Optional[str] = None,
):
    parser_ = Parser(parser)
    renderer_ = Renderer(renderer)
    renderer_(parser_(definitions.iter_resources(cache_dir=cache_dir)))


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
