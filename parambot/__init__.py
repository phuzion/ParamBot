"""ParamBot: re-applies template parameter renames that reverts have undone."""

from pathlib import Path


def commit() -> str | None:
    """The short hash of the git commit the running code is checked out
    at, or None if it isn't running from a git checkout."""
    return git_commit(Path(__file__).resolve().parent.parent)


def git_commit(root: Path) -> str | None:
    """The short hash of the commit checked out in root, or None if root
    isn't a git checkout.  Read from .git itself, since the git program
    may not be installed where the bot runs."""
    git = root / '.git'
    try:
        if git.is_file():   # a worktree's .git says "gitdir: <where its own files are>"
            git = root / git.read_text(encoding='utf-8').split(':', 1)[1].strip()
        head = (git / 'HEAD').read_text(encoding='utf-8').strip()
        if not head.startswith('ref:'):
            return head[:7] or None   # a detached HEAD is the commit itself
        ref = head.removeprefix('ref:').strip()
        common = git   # where the branches are: a worktree shares them
        if (git / 'commondir').is_file():
            common = git / (git / 'commondir').read_text(encoding='utf-8').strip()
        for base in (git, common):
            if (base / ref).is_file():
                return (base / ref).read_text(encoding='utf-8').strip()[:7] or None
        for line in (common / 'packed-refs').read_text(encoding='utf-8').splitlines():
            commit, _, name = line.partition(' ')
            if name == ref:
                return commit[:7]
    except (OSError, IndexError):
        pass
    return None
