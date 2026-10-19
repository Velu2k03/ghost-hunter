#!/usr/bin/env python3
"""exorcise.py - Safely banish one ghost: diff preview, confirm, remove, undo.

Usage:
    python exorcise.py --species WRAITH --file haunted.py --line 22 --symbol "dead_wraith()"
    python exorcise.py --species SPECTER --file haunted.py --line 3 --symbol "json" --yes
    python exorcise.py --undo --file haunted.py        # resurrect the backup

Before touching anything it shows a unified diff and asks for confirmation
(unless --yes). The original file is backed up to <file>.ghostbak so any
exorcism can be undone with --undo. If the ghost cannot be matched exactly,
it fails safe and changes nothing.
"""

import ast
import difflib
import os
import shutil
import sys


def _fail(msg):
    print("Exorcism aborted (fail-safe): %s" % msg, file=sys.stderr)
    return None


def _read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _parse(path):
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _remove_lines(lines, start, end):
    """Remove 1-based inclusive line range [start, end]."""
    new = lines[: start - 1] + lines[end:]
    # collapse 3+ blank lines left behind into max 2
    out, blanks = [], 0
    for line in new:
        if line.strip():
            blanks = 0
            out.append(line)
        else:
            blanks += 1
            if blanks <= 2:
                out.append(line)
    return out


def exorcise_wraith(lines, tree, lineno, symbol):
    """Delete the whole function definition."""
    name = symbol[:-2] if symbol.endswith("()") else symbol
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == lineno:
            if node.name != name:
                return _fail("line %d holds '%s', not '%s'" % (lineno, node.name, name))
            end = node.end_lineno or lineno
            return _remove_lines(lines, lineno, end), \
                "Banished wraith '%s' (deleted lines %d-%d)." % (name, lineno, end)
    return _fail("no function definition found at line %d" % lineno)


def exorcise_specter(lines, tree, lineno, symbol):
    """Remove the unused import. If the line imports several names, only the
    unused one is cut out; a lone import loses the whole line."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.lineno == lineno:
            bound = [( (a.asname or a.name).split(".")[0], a) for a in node.names]
            if symbol not in [b for b, _ in bound]:
                return _fail("line %d does not import '%s'" % (lineno, symbol))
            keep = [(b, a) for b, a in bound if b != symbol]
            if not keep:
                return _remove_lines(lines, lineno, lineno), \
                    "Banished specter '%s' (removed import line %d)." % (symbol, lineno)
            # surgical: rebuild the line with only the used names
            parts = []
            for _b, a in keep:
                parts.append(a.name + (" as " + a.asname if a.asname else ""))
            if isinstance(node, ast.Import):
                new_line = "import " + ", ".join(parts) + "\n"
            else:
                dots = "." * node.level
                mod = node.module or ""
                new_line = "from %s%s import %s\n" % (dots, mod, ", ".join(parts))
            new = lines[: lineno - 1] + [new_line] + lines[lineno:]
            return new, \
                "Banished specter '%s' (trimmed from import line %d)." % (symbol, lineno)
    return _fail("no import statement found at line %d" % lineno)


def exorcise_poltergeist(lines, tree, lineno, symbol):
    """Delete the unreachable statement."""
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno == lineno:
            end = node.end_lineno or lineno
            return _remove_lines(lines, lineno, end), \
                "Banished poltergeist at line %d (deleted lines %d-%d)." % (lineno, lineno, end)
    return _fail("no statement found at line %d" % lineno)


def exorcise_shade(lines, tree, lineno, symbol):
    """Remove the assignment of an unread variable.

    The finding line points at the enclosing function; the actual assignment
    is located by matching the symbol name inside it.
    """
    func = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == lineno:
            func = node
            break
    if func is None:
        return _fail("no function found at line %d" % lineno)
    for node in ast.walk(func):
        if node is func:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue  # nested scopes are not ours to touch
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = set()
            for t in targets:
                names.update(n.id for n in ast.walk(t)
                             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
            if symbol in names:
                end = node.end_lineno or node.lineno
                return _remove_lines(lines, node.lineno, end), \
                    "Banished shade '%s' (deleted lines %d-%d)." % (symbol, node.lineno, end)
    return _fail("no assignment of '%s' found in function at line %d" % (symbol, lineno))


EXORCISTS = {
    "WRAITH": exorcise_wraith,
    "SPECTER": exorcise_specter,
    "POLTERGEIST": exorcise_poltergeist,
    "SHADE": exorcise_shade,
}


def resurrect(path):
    bak = path + ".ghostbak"
    if not os.path.exists(bak):
        print("No backup found for %s; nothing to resurrect." % path, file=sys.stderr)
        return 2
    shutil.copy(bak, path)
    os.remove(bak)
    print("Resurrected %s from backup. The ghost lives again." % path)
    return 0


def main(argv):
    if "--undo" in argv:
        path = argv[argv.index("--file") + 1] if "--file" in argv else None
        if not path:
            print("usage: python exorcise.py --undo --file <path>", file=sys.stderr)
            return 2
        return resurrect(path)

    args = {}
    flags = set()
    it = iter(argv[1:])
    for a in it:
        if a.startswith("--"):
            name = a[2:]
            if name in ("yes", "dry-run", "undo"):
                flags.add(name)
            else:
                try:
                    args[name] = next(it)
                except StopIteration:
                    print("error: %s needs a value" % a, file=sys.stderr)
                    return 2
    for key in ("species", "file", "line", "symbol"):
        if key not in args:
            print("usage: python exorcise.py --species X --file F --line N "
                  "--symbol S [--yes] [--undo --file F]", file=sys.stderr)
            return 2

    species = args["species"].upper()
    path = args["file"]
    lineno = int(args["line"])
    symbol = args["symbol"]

    if species not in EXORCISTS:
        print("error: unknown species '%s'" % species, file=sys.stderr)
        return 2
    if not os.path.isfile(path):
        print("error: not a file: %s" % path, file=sys.stderr)
        return 2

    lines = _read_lines(path)
    try:
        tree = _parse(path)
    except SyntaxError as e:
        print("error: cannot parse %s: %s" % (path, e), file=sys.stderr)
        return 2

    result = EXORCISTS[species](lines, tree, lineno, symbol)
    if result is None:
        return 1
    new_lines, msg = result

    diff = "".join(difflib.unified_diff(
        lines, new_lines, fromfile=path, tofile=path + " (exorcised)"))
    print(diff if diff else "(no changes)")
    if "--yes" not in argv and "yes" not in flags:
        answer = input("Exorcise this ghost? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("The ghost remains. Wise caution.")
            return 0

    shutil.copy(path, path + ".ghostbak")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(msg + " Backup at %s.ghostbak (use --undo to resurrect)." % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
