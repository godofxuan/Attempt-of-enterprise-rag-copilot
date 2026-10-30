"""Feed already parsed immutable originals into the existing index publisher."""
from pathlib import Path
from app.domain.documents import ParseResult


class SavedParseRegistry:
    def __init__(self,parses):self.parses=parses
    def parse(self,path):
        return ParseResult.model_validate(self.parses[Path(path).name])
