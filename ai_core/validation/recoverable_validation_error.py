class RecoverableValidationError(Exception):
    def __init__(self, message: str, node_id: str, result: dict | None = None, schema_path: str | None = None):
        super().__init__(message)
        self.message = message
        self.node_id = node_id
        self.result = result or {}
        self.schema_path = schema_path
