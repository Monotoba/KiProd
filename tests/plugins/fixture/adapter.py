import json
from pathlib import Path


class FixtureAdapter:
    def __init__(self, http=None):
        self.root = Path(__file__).parent
        self.http = http

    def health_check(self):
        return {"ok": True}

    def search(self, query):
        fixture = json.loads((self.root / "fixtures" / "search.json").read_text())
        return fixture["offers"] if fixture["query"] == query else []
