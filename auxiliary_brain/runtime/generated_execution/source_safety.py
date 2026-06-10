from __future__ import annotations

import ast
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class _LoopBoundTransformer(ast.NodeTransformer):
    def __init__(self, max_iterations: int) -> None:
        self.max_iterations = max(1, int(max_iterations))
        self.index = 0

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        node.body = self._guarded_body(node.body)
        return node

    def visit_While(self, node: ast.While) -> ast.AST:
        self.generic_visit(node)
        node.body = self._guarded_body(node.body)
        return node

    def _guarded_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        self.index += 1
        name = f"__runtime_loop_counter_{self.index}"
        guard = ast.parse(
            f"{name} = globals().get('{name}', 0) + 1\n"
            f"globals()['{name}'] = {name}\n"
            f"if {name} > {self.max_iterations}:\n"
            f"    break\n"
        ).body
        return [*guard, *body]


def bound_python_source(source: str, *, max_iterations: int | None = None) -> str:
    """Return source with generic loop bounds for generated runtime execution.

    The transformer is intentionally domain-agnostic.  It does not look at task
    names, output text, or business concepts.  It only prevents generated code
    from running unbounded loops inside an interactive runtime window.
    """
    limit = max_iterations or int(os.getenv("RUNTIME_MAX_LOOP_ITERATIONS", "1"))
    try:
        tree = ast.parse(source)
        transformed = _LoopBoundTransformer(limit).visit(tree)
        ast.fix_missing_locations(transformed)
        return ast.unparse(transformed) if hasattr(ast, "unparse") else source
    except Exception:
        return source


def write_bounded_python_copy(path: Path, *, max_iterations: int | None = None) -> Path:
    source = Path(path).read_text(encoding="utf-8", errors="ignore")
    bounded = bound_python_source(source, max_iterations=max_iterations)
    if bounded == source:
        return Path(path)
    temp = NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix=Path(path).stem + "_bounded_",
        dir=str(Path(path).parent),
        delete=False,
    )
    with temp:
        temp.write(bounded)
    return Path(temp.name)
