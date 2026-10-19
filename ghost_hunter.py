#!/usr/bin/env python3
"""ghost_hunter.py - Hunt dead code in Python repos and report it as ghosts.

Four ghost species:
  WRAITH      - a function defined but never called anywhere in the repo
  SPECTER     - an import that is never used
  POLTERGEIST - code sitting after a return/raise that can never run
  SHADE       - a variable assigned but never read

Usage:
    python ghost_hunter.py <directory> [--json]

The scan is two-pass: the first pass collects every name used across ALL
files (so cross-file calls never produce false wraiths), the second pass
flags the dead. Standard library only, zero dependencies.
"""

import ast
import json
import os
import sys

# ---------------------------------------------------------------------------
# Ghost lore, for reports and GitHub issues
# ---------------------------------------------------------------------------
LORE = {
    "WRAITH": (
        "A wraith is the spirit of a function that was written but never "
        "summoned. It lingers in the codebase, growing colder and more "
        "confusing with every passing month, until nobody dares to touch it."
    ),
    "SPECTER": (
        "A specter is an import that haunts the top of a file, promising "
        "functionality that never arrives. It slows every cold start and "
        "whispers false dependencies to anyone reading the code."
    ),
    "POLTERGEIST": (
        "A poltergeist is code trapped behind a return or raise, forever "
        "reaching for execution it will never get. It rattles its chains "
        "every time a reader scrolls past, wondering what it was for."
    ),
    "SHADE": (
        "A shade is a variable that was given a value but never asked for "
        "it back. It drifts through its function, half-remembered, making "
        "every future reader wonder if deleting it will break something."
    ),
}

EXORCISM_ADVICE = {
    "WRAITH": "Delete the function. If it was meant to be public API, export it via __all__ or call it somewhere first.",
    "SPECTER": "Remove the import line. If it is needed for type checking only, move it under `if TYPE_CHECKING:`.",
    "POLTERGEIST": "Delete the unreachable statements. If the logic was meant to run, it belongs before the return/raise.",
    "SHADE": "Remove the assignment. If the value has a side effect you rely on, keep the call but drop the name.",
}


class _FirstPass(ast.NodeVisitor):
    """Collect every name that is USED anywhere, plus exports and structure."""

    def __init__(self):
        self.used_names = set()      # Name(id) in Load context, repo-wide
        self.used_attrs = set()      # attribute names in Load context (obj.method())
        self.exports = set()         # names listed in __all__
        self.decorated = set()       # (file, lineno) of decorated defs
        self.type_checking_imports = set()  # bound import names under TYPE_CHECKING

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load):
            self.used_attrs.add(node.attr)
        self.generic_visit(node)

    def visit_Assign(self, node):
        # __all__ = ["a", "b"]
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                for elt in node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else []:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        self.exports.add(elt.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        # AugAssign has .target (singular); __all__ detection needs .targets,
        # so there is nothing to do here beyond visiting children.
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if node.decorator_list:
            self.decorated.add((node.lineno, node.col_offset))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node):
        # from typing import TYPE_CHECKING / if TYPE_CHECKING: imports...
        test = node.test
        is_tc = (
            isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
        ) or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if is_tc:
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Import):
                        for a in sub.names:
                            self.type_checking_imports.add((a.asname or a.name).split(".")[0])
                    elif isinstance(sub, ast.ImportFrom):
                        for a in sub.names:
                            if a.name != "*":
                                self.type_checking_imports.add(a.asname or a.name)
        self.generic_visit(node)


class _FunctionInfo:
    __slots__ = ("name", "lineno", "col_offset", "end_lineno", "is_method",
                 "decorated", "node")

    def __init__(self, name, lineno, col_offset, end_lineno, is_method, decorated, node):
        self.name = name
        self.lineno = lineno
        self.col_offset = col_offset
        self.end_lineno = end_lineno
        self.is_method = is_method
        self.decorated = decorated
        self.node = node


class _SecondPass(ast.NodeVisitor):
    """Collect definitions: functions, imports, and per-function assignments."""

    def __init__(self, filename):
        self.filename = filename
        self.functions = []          # _FunctionInfo
        self.imports = []            # (bound_name, lineno, col_offset, stmt_text)
        self._class_stack = []
        self.scopes = []             # per-function (assigned, loaded) name sets

    def visit_ClassDef(self, node):
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _record_function(self, node):
        decorated = bool(node.decorator_list)
        info = _FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            col_offset=node.col_offset,
            end_lineno=node.end_lineno or node.lineno,
            is_method=bool(self._class_stack),
            decorated=decorated,
            node=node,
        )
        self.functions.append(info)

    def visit_FunctionDef(self, node):
        self._record_function(node)
        self._scan_scope(node)
        # do NOT generic_visit: nested defs handled by _scan_scope's own walk

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan_scope(self, node):
        assigned, loaded = set(), set()

        class _ScopeWalk(ast.NodeVisitor):
            def visit_Name(s, n):
                if isinstance(n.ctx, ast.Store):
                    assigned.add(n.id)
                elif isinstance(n.ctx, ast.Load):
                    loaded.add(n.id)
                # nested function/class bodies are their own scopes:
                # only their bound name and evaluated expressions count here
            def visit_FunctionDef(s, n):
                assigned.add(n.name)
                for d in n.decorator_list:
                    s.visit(d)
                for d in list(n.args.defaults) + [x for x in n.args.kw_defaults if x]:
                    s.visit(d)
            def visit_AsyncFunctionDef(s, n):
                s.visit_FunctionDef(n)
            def visit_ClassDef(s, n):
                assigned.add(n.name)
                for b in n.bases:
                    s.visit(b)
                for kw in n.keywords:
                    s.visit(kw.value)
            def visit_Lambda(s, n):
                pass  # lambda body is its own scope

        walker = _ScopeWalk()
        for stmt in node.body:
            walker.visit(stmt)
        # NOTE: parameters are deliberately NOT counted as assigned. They are
        # part of the function's signature (its API contract), and removing
        # them changes every caller. Only real assignment statements in the
        # body can be shades, which keeps every finding exorcisable.
        self.scopes.append((node.name, node.lineno, assigned, loaded))

    def visit_Import(self, node):
        for alias in node.names:
            bound = (alias.asname or alias.name).split(".")[0]
            self.imports.append((bound, node.lineno, node.col_offset, alias.name))
        # no generic_visit needed

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self.imports.append((bound, node.lineno, node.col_offset,
                                 f"{node.module}.{alias.name}" if node.module else alias.name))


def _iter_py_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", ".git", ".venv", "venv", "node_modules", ".tox")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _poltergeists(tree, filename):
    """Statements unreachable after return/raise/continue/break in the same block."""
    findings = []
    TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)

    def check_block(stmts):
        dead = False
        for stmt in stmts:
            if dead:
                findings.append({
                    "species": "POLTERGEIST",
                    "file": filename,
                    "line": stmt.lineno,
                    "symbol": ast.unparse(stmt).splitlines()[0][:60] if hasattr(ast, "unparse") else type(stmt).__name__,
                    "detail": "Code after '%s' on line %d can never execute." % (
                        "return/raise/continue/break", prev_lineno),
                })
            elif isinstance(stmt, TERMINATORS):
                dead = True
                prev_lineno = stmt.lineno
            # recurse into nested blocks
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                for field in ("body", "orelse", "finalbody"):
                    block = getattr(child, field, None)
                    if isinstance(block, list) and block and all(isinstance(s, ast.stmt) for s in block):
                        check_block(block)

    check_block(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check_block(node.body)
    return findings


def scan(root):
    """Scan a directory. Returns a list of finding dicts."""
    files = list(_iter_py_files(root))
    trees = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                trees[path] = ast.parse(f.read(), filename=path)
        except (SyntaxError, UnicodeDecodeError):
            continue

    # ---- pass 1: repo-wide usage ----
    p1 = _FirstPass()
    for tree in trees.values():
        p1.visit(tree)

    findings = []

    # ---- pass 2: per-file definitions ----
    for path, tree in trees.items():
        p2 = _SecondPass(path)
        p2.visit(tree)

        # WRAITHS: functions never called
        for info in p2.functions:
            name = info.name
            if name.startswith("__") and name.endswith("__"):
                continue                      # dunder methods
            if name.startswith("test_"):
                continue                      # test functions
            if info.decorated:
                continue                      # registered by decorator (routes, tasks...)
            if name in p1.exports:
                continue                      # public API via __all__
            used = name in p1.used_names or (info.is_method and name in p1.used_attrs)
            if not used:
                findings.append({
                    "species": "WRAITH",
                    "file": path,
                    "line": info.lineno,
                    "symbol": name + "()",
                    "detail": "Function '%s' is defined but never called anywhere in the repo." % name,
                })

        # SPECTERS: imports never used
        for bound, lineno, _col, _orig in p2.imports:
            if bound in p1.type_checking_imports:
                continue
            if bound in p1.used_names or bound in p1.exports:
                continue
            findings.append({
                "species": "SPECTER",
                "file": path,
                "line": lineno,
                "symbol": bound,
                "detail": "Import '%s' is never used in this file." % bound,
            })

        # SHADES: assigned but never read, per function scope
        for _fname, _flineno, assigned, loaded in p2.scopes:
            for name in sorted(assigned - loaded):
                if name.startswith("_"):
                    continue                  # intentionally unused
                if name in ("self", "cls"):
                    continue
                findings.append({
                    "species": "SHADE",
                    "file": path,
                    "line": _flineno,
                    "symbol": name,
                    "detail": "Variable '%s' is assigned but never read." % name,
                })

    # POLTERGEISTS
    for path, tree in trees.items():
        findings.extend(_poltergeists(tree, path))

    findings.sort(key=lambda f: (f["file"], f["line"]))
    return findings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
GHOST_EMOJI = {"WRAITH": "\U0001F47B", "SPECTER": "\U0001F47B",
               "POLTERGEIST": "\U0001F47B", "SHADE": "\U0001F47B"}
SPECIES_EMOJI = {"WRAITH": "👻", "SPECTER": "🌫️", "POLTERGEIST": "⛓️", "SHADE": "🌑"}


def print_report(findings, root):
    print("=" * 64)
    print("  GHOST IN THE REPO  -  haunting report for %s" % os.path.abspath(root))
    print("=" * 64)
    if not findings:
        print("\n  No ghosts found. This repo is clean... suspiciously clean.")
        return
    counts = {}
    for f in findings:
        counts[f["species"]] = counts.get(f["species"], 0) + 1
    print("\n  %d ghost(s) detected: %s\n" % (
        len(findings),
        ", ".join("%d %s" % (c, s.lower() + "s") for s, c in sorted(counts.items()))))
    for f in findings:
        print("  %s [%s] %s haunts %s:%d" % (
            SPECIES_EMOJI.get(f["species"], "👻"), f["species"],
            f["symbol"], f["file"], f["line"]))
        print("      %s" % f["detail"])
    print("\n  Run exorcise.py to banish them, or hauntings.py to file them as issues.")


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    root = argv[1]
    if not os.path.isdir(root):
        print("error: not a directory: %s" % root, file=sys.stderr)
        return 2
    findings = scan(root)
    if "--json" in argv:
        print(json.dumps(findings, indent=2))
    else:
        print_report(findings, root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
