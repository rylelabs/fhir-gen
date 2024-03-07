from dataclass_wizard.parsers import LiteralParser, AbstractParser


class LiteralParserPatch:

    def __contains__(self, item) -> bool:
        return item in self.value_to_type.keys()  # type: ignore


LiteralParser.__bases__ = (LiteralParserPatch, AbstractParser)
