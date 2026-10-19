# 👻 Ghost in the Repo

**The dead-code hunter that turns cleanup into a Halloween ghost hunt.**

Every dead-code finding is a ghost with a species, lore, a haunting
(`file:line`), and an exorcism. Built for Hackyard Yard #5: Haunted.

## The 3 features

1. **Haunt** — `ghost_hunter.py` scans any Python repo and reports 4 ghost species:
   - 👻 **Wraith** — a function defined but never called (two-pass analysis, so
     cross-file calls never cause false positives)
   - 🌫️ **Specter** — an import that is never used
   - ⛓️ **Poltergeist** — code after a `return`/`raise` that can never run
   - 🌑 **Shade** — a variable assigned but never read

   Dunder methods, `test_` functions, decorated functions (routes, tasks),
   `__all__` exports, and `TYPE_CHECKING` imports are exempt.
2. **Haunting issues** — `hauntings.py` files each ghost as a spooky GitHub
   issue, lore included, so cleanup becomes trackable work. `--dry-run` previews
   without touching the API.
3. **Exorcise** — `exorcise.py` banishes one ghost at a time: unified diff
   preview, confirmation prompt, automatic backup, and `--undo` to resurrect.
   Fails safe if the ghost can't be matched exactly.

## Quickstart

```bash
# Hunt
python ghost_hunter.py /path/to/your/repo

# File the ghosts as GitHub issues (dry run first)
python ghost_hunter.py /path/to/your/repo --json \
  | python hauntings.py <owner>/<repo> --dry-run

# File them for real (needs a token with repo scope)
export GHOST_TOKEN=ghp_your_token_here
python ghost_hunter.py /path/to/your/repo --json \
  | python hauntings.py <owner>/<repo>

# Exorcise one ghost (diff preview + confirm)
python exorcise.py --species WRAITH --file app.py --line 42 --symbol "old_func()"

# Changed your mind?
python exorcise.py --undo --file app.py
```

Requirements: Python 3.8+. `ghost_hunter.py` and `exorcise.py` are standard
library only. `hauntings.py` needs `requests` (`pip install requests`).

## Before / after: real numbers

Ran the hunter on the author's own video-pipeline scripts
(`storm-work/`, 3 files, written before this project existed):

| | Before | After exorcism |
|---|---|---|
| Ghosts | **8** (1 wraith, 1 specter, 6 shades) | 0 |
| Dead lines removed | — | **9** |

Confirmed true positives, not guesses: `hp()` was defined but called zero
times, `import math` was never referenced, and 7 variables were assigned and
never read. Every exorcism showed a diff preview first, and the rescan came
back clean with the code still parsing.

## Why it matters

Engineers spend **13.5 hours a week** on technical debt (Stripe Developer
Coefficient, Harris Poll of 1,000+ developers) — roughly a third of engineering
capacity. Technical debt was the **#1 workplace frustration** in the Stack
Overflow 2024 survey (62%). AI coding tools make it worse: generated snippets
encourage copy-paste over refactoring, breeding dead code nobody understands.
Ghost in the Repo makes the invisible visible, one ghost at a time.

## License

MIT — see [LICENSE](LICENSE).
