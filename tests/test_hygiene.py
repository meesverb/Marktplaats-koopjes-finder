"""Elke module compileert en importeert niets wat hij niet gebruikt
(VERBETERPLAN A2). Met alleen de stdlib: pyflakes vond op 16-11-2026 een
twintigtal ongebruikte imports, en die komen vanzelf terug. Een import die
bewust blijft (alleen voor sys.path, of om een naam opnieuw aan te bieden)
krijgt `# noqa` op zijn regel."""
import ast
import unittest

from helpers import REPO_ROOT

FILES = sorted([*REPO_ROOT.glob("*.py"), *REPO_ROOT.glob("tests/*.py"),
                *REPO_ROOT.glob("catalog_tools/*.py"), *REPO_ROOT.glob("marktonderzoek/*.py")])


def unused_imports(path) -> list:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, str(path))
    lines = source.splitlines()
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # __all__
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or "noqa" in lines[node.lineno - 1]:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            if name != "*" and name not in used:
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {name}")
    return found


class HygieneTest(unittest.TestCase):
    def test_every_file_compiles(self):
        for path in FILES:
            with self.subTest(file=path.name):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_no_unused_imports(self):
        self.assertEqual([hit for path in FILES for hit in unused_imports(path)], [])


if __name__ == "__main__":
    unittest.main()
