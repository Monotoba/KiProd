class FixtureAdapter:
    def __init__(self, http=None):
        self.http = http

    def health_check(self):
        return {"ok": True}

    def search(self, query):
        response = self.http.get(
            f"https://parts.example.test/v1/search?mpn={query}",
            headers={"accept": "application/json"},
        )
        payload = response.json()
        return payload["offers"] if payload["query"] == query else []
