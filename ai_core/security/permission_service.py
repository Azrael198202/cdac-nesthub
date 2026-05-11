class PermissionService:
    def allow(self, action: str, approved: bool) -> bool:
        return approved or action in {"read_file", "list_files"}
