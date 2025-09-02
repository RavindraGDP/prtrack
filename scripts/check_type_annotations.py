#!/usr/bin/env python3
"""
Pre-commit hook to check and convert old-style typing imports and annotations
to modern Python 3.10+ syntax.

Checks for:
- from typing import Dict, List, Optional, Union, Tuple, Set
- Converts Dict[str, int] -> dict[str, int]
- Converts Optional[str] -> str | None
- Converts Union[str, int] -> str | int
- Converts List[str] -> list[str]
- Converts Tuple[str, int] -> tuple[str, int]
- Converts Set[str] -> set[str]
"""

import ast
import sys
from pathlib import Path
from typing import Any


class TypeAnnotationConverter(ast.NodeTransformer):
    """AST transformer to convert old typing annotations to modern syntax."""

    def __init__(self):
        self.changes_made = False
        self.old_imports = set()

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        """Check for typing imports that can be converted."""
        if node.module == "typing" and node.names:
            old_typing_names = {
                "Dict",
                "List",
                "Optional",
                "Union",
                "Tuple",
                "Set",
                "FrozenSet",
                "Callable",
                "Any",
            }

            # Check if we're importing any old-style typing constructs
            old_names = []
            new_names = []

            for alias in node.names:
                if alias.name in old_typing_names:
                    old_names.append(alias.name)
                    self.old_imports.add(alias.name)
                else:
                    new_names.append(alias)

            # If we found old imports, mark that changes were made
            if old_names:
                self.changes_made = True

            # Remove the old imports, keep the new ones
            if new_names:
                node.names = new_names
                return node
            else:
                # Remove the entire import if all names are old-style
                return None

        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        """Convert type annotations in variable assignments."""
        if node.annotation:
            node.annotation = self._convert_annotation(node.annotation)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Convert type annotations in function definitions."""
        # Convert return annotation
        if node.returns:
            node.returns = self._convert_annotation(node.returns)

        # Convert parameter annotations
        for arg in node.args.args:
            if arg.annotation:
                arg.annotation = self._convert_annotation(arg.annotation)

        # Convert vararg and kwarg annotations
        if node.args.vararg and node.args.vararg.annotation:
            node.args.vararg.annotation = self._convert_annotation(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            node.args.kwarg.annotation = self._convert_annotation(node.args.kwarg.annotation)

        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        """Convert type annotations in async function definitions."""
        return self.visit_FunctionDef(node)  # Same logic as regular functions

    def _convert_annotation(self, node: ast.AST) -> ast.AST:
        """Convert a single annotation node."""
        if isinstance(node, ast.Subscript):
            return self._convert_subscript(node)
        elif isinstance(node, ast.Name):
            return self._convert_name(node)
        elif isinstance(node, ast.Attribute):
            return self._convert_attribute(node)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # Already using | syntax, keep as is
            return node
        else:
            return self.generic_visit(node)

    def _convert_subscript(self, node: ast.Subscript) -> ast.AST:  # noqa: PLR0912
        """Convert subscript annotations like Dict[str, int]."""
        if isinstance(node.value, ast.Name):
            name = node.value.id

            # Convert Dict, List, Set, Tuple
            if name in self.old_imports:
                if name == "Dict":
                    # Dict[str, int] -> dict[str, int]
                    node.value.id = "dict"
                    self.changes_made = True
                elif name == "List":
                    node.value.id = "list"
                    self.changes_made = True
                elif name == "Set":
                    node.value.id = "set"
                    self.changes_made = True
                elif name == "Tuple":
                    node.value.id = "tuple"
                    self.changes_made = True
                elif name == "FrozenSet":
                    node.value.id = "frozenset"
                    self.changes_made = True
                elif name == "Optional":
                    # Optional[str] -> str | None
                    if isinstance(node.slice, ast.Name):
                        # Create str | None
                        node = ast.BinOp(
                            left=node.slice,
                            op=ast.BitOr(),
                            right=ast.Constant(value=None),
                        )
                        self.changes_made = True
                    elif isinstance(node.slice, ast.Subscript):
                        # Handle nested like Optional[List[str]] -> list[str] | None
                        converted_slice = self._convert_subscript(node.slice)
                        node = ast.BinOp(
                            left=converted_slice,
                            op=ast.BitOr(),
                            right=ast.Constant(value=None),
                        )
                        self.changes_made = True
                elif name == "Union":
                    # Union[str, int] -> str | int
                    if isinstance(node.slice, ast.Tuple):
                        if len(node.slice.elts) == 2:  # noqa: PLR2004
                            # Convert Union[A, B] to A | B
                            left = self._convert_annotation(node.slice.elts[0])
                            right = self._convert_annotation(node.slice.elts[1])
                            node = ast.BinOp(left=left, op=ast.BitOr(), right=right)
                            self.changes_made = True
                        else:
                            # For Union[A, B, C], keep as is for now
                            pass
        return self.generic_visit(node)

    def _convert_name(self, node: ast.Name) -> ast.AST:
        """Convert simple name annotations."""
        return node

    def _convert_attribute(self, node: ast.Attribute) -> ast.AST:
        """Convert attribute annotations."""
        return node


def convert_file(file_path: Path) -> tuple[bool, str]:
    """
    Convert old-style type annotations in a Python file.

    Returns:
        tuple: (changes_made, error_message)
    """
    try:
        # Read the file
        content = file_path.read_text(encoding="utf-8")

        # Parse the AST
        tree = ast.parse(content)

        # Convert the annotations
        converter = TypeAnnotationConverter()
        converted_tree = converter.visit(tree)

        if converter.changes_made:
            # Convert back to source code
            new_content = ast.unparse(converted_tree)

            # Write back to file
            file_path.write_text(new_content, encoding="utf-8")

            return True, ""

        return False, ""

    except Exception as e:
        return False, f"Error processing {file_path}: {e!s}"


def check_file(file_path: Path) -> tuple[bool, str]:
    """
    Check if a file contains old-style type annotations.

    Returns:
        tuple: (has_old_annotations, error_message)
    """
    try:
        content = file_path.read_text(encoding="utf-8")

        # Check for old typing imports
        old_imports = [
            "from typing import.*Dict.*",
            "from typing import.*List.*",
            "from typing import.*Optional.*",
            "from typing import.*Union.*",
            "from typing import.*Tuple.*",
            "from typing import.*Set.*",
            "from typing import.*FrozenSet.*",
        ]

        for pattern in old_imports:
            if pattern.replace(".*", "") in content:
                return True, ""

        return False, ""

    except Exception as e:
        return False, f"Error checking {file_path}: {e!s}"


def main():
    """Main entry point for the pre-commit hook."""
    if len(sys.argv) < 2:  # noqa: PLR2004
        print("Usage: python check_typing_annotations.py [--fix] <files...>")
        sys.exit(1)

    fix_mode = "--fix" in sys.argv
    if fix_mode:
        sys.argv.remove("--fix")

    files = sys.argv[1:]
    has_issues = False

    for file_path_str in files:
        file_path = Path(file_path_str)

        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue

        if file_path.suffix != ".py":
            continue

        if fix_mode:
            changes_made, error = convert_file(file_path)
            if error:
                print(f"Error: {error}")
                has_issues = True
            elif changes_made:
                print(f"Converted: {file_path}")
        else:
            has_old, error = check_file(file_path)
            if error:
                print(f"Error: {error}")
                has_issues = True
            elif has_old:
                print(f"Found old typing annotations in: {file_path}")
                has_issues = True

    if has_issues and not fix_mode:
        print("\nTo automatically fix these issues, run:")
        print("  python scripts/check_typing_annotations.py --fix <files...>")
        sys.exit(1)


if __name__ == "__main__":
    main()
