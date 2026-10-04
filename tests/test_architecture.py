import ast
from pathlib import Path


def test_domain_and_geometry_do_not_import_infrastructure() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "architect_ai"
    forbidden = {
        "fastapi",
        "starlette",
        "mcp",
        "openai",
        "sqlalchemy",
        "httpx",
        "httpx2",
        "pydantic_settings",
    }
    forbidden_local = {"api", "mcp", "providers", "storage", "config", "services"}
    for layer in ("domain", "geometry"):
        for source in (root / layer).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        # Keep imports absolute so boundaries remain easy to audit.
                        raise AssertionError(f"Use absolute imports in {source}")
                    names = [node.module or ""]
                for name in names:
                    parts = name.split(".")
                    assert parts[0] not in forbidden, (source, name)
                    if len(parts) > 1 and parts[0] == "architect_ai":
                        assert parts[1] not in forbidden_local, (source, name)
