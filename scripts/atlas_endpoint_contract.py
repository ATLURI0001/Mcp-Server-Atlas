"""atlas_endpoint_contract.py – validates MCP atlas endpoint contract."""


class AtlasEndpointContract:
    def __init__(self, allowed_methods: list[str]):
        self.allowed_methods = allowed_methods

    def validate(self, method: str) -> bool:
        return method.upper() in self.allowed_methods
