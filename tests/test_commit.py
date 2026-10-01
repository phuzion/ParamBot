"""Which commit of the bot is running."""

import re

from parambot import commit, git_commit

COMMIT = '24cef13a0b1c2d3e4f5061728394a5b6c7d8e9f0'


def checkout(tmp_path, head, **files):
    git = tmp_path / '.git'
    git.mkdir(parents=True)
    (git / 'HEAD').write_text(head + '\n', encoding='utf-8')
    for name, text in files.items():
        path = git / name.replace('__', '/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return tmp_path


def test_the_running_commit():
    # The tests run from a git checkout.
    assert re.fullmatch('[0-9a-f]{7}', commit() or '')


def test_a_branch(tmp_path):
    root = checkout(tmp_path, 'ref: refs/heads/main', refs__heads__main=COMMIT + '\n')
    assert git_commit(root) == '24cef13'


def test_a_packed_branch(tmp_path):
    # After git gc, branches can live only in packed-refs.
    root = checkout(tmp_path, 'ref: refs/heads/main', **{
        'packed-refs': f'# pack-refs with: peeled fully-peeled sorted\n'
                       f'{"0" * 40} refs/heads/other\n{COMMIT} refs/heads/main\n'})
    assert git_commit(root) == '24cef13'


def test_a_detached_head(tmp_path):
    assert git_commit(checkout(tmp_path, COMMIT)) == '24cef13'


def test_a_worktree(tmp_path):
    main = checkout(tmp_path / 'main', 'ref: refs/heads/main',
                    refs__heads__feature=COMMIT + '\n')
    (main / '.git' / 'worktrees' / 'w').mkdir(parents=True)
    (main / '.git' / 'worktrees' / 'w' / 'HEAD').write_text('ref: refs/heads/feature\n',
                                                            encoding='utf-8')
    (main / '.git' / 'worktrees' / 'w' / 'commondir').write_text('../..\n', encoding='utf-8')
    worktree = tmp_path / 'w'
    worktree.mkdir()
    (worktree / '.git').write_text(f'gitdir: {main / ".git" / "worktrees" / "w"}\n',
                                   encoding='utf-8')
    assert git_commit(worktree) == '24cef13'


def test_not_a_checkout(tmp_path):
    (tmp_path / 'parambot').mkdir()
    assert git_commit(tmp_path) is None
    # A branch with no commits yet.
    assert git_commit(checkout(tmp_path, 'ref: refs/heads/main')) is None
