import asyncio
import os
import shutil
import subprocess
import tempfile
from asyncio import gather
from pathlib import Path
from textwrap import indent

import click as click


async def sleep(quanta):
    await asyncio.sleep(0.1 * quanta)


class Dev:
    def __init__(self, name):
        self.name = name


git = shutil.which("git")
if git is None:
    raise ImportError("git is not installed")


def check_call(cwd, *cmdline):
    cmdline_string = " ".join(map(str, cmdline))
    print(f"{cwd}$ {cmdline_string}")
    output = subprocess.check_output(cmdline, cwd=cwd).decode()
    print(indent(output, f"  [{cwd}] "))


def git_commit(cwd, message):
    check_call(cwd, git, "commit", "-m", message)


async def git_merge(cwd, branch, dest, message):
    await sleep(len(branch))
    check_call(cwd, git, "checkout", dest)
    check_call(cwd, git, "pull")
    check_call(cwd, git, "merge", "-m", message, "--no-ff", branch)


start_cwd = os.getcwd()


def git_push(cwd):
    check_call(cwd, git, "push")


async def some_work_async(dev_repo: Path, feature_name: str):
    await asyncio.sleep(len(feature_name))


async def task_for(
    play_dir: Path,
    dev: Dev,
    feature_name: str,
    commits: int,
    repo: Path,
    source_branch: str,
    destination_branch: str,
):
    assert " " not in feature_name, "that would be a problem for git branch names"
    branch = f"feature/{feature_name}"
    dev_repo = play_dir / f"{dev.name}--{feature_name}"
    git_clone(dev, dev_repo, repo)
    check_call(dev_repo, git, "checkout", "-b", branch, source_branch)
    for c in range(commits):
        await some_work_async(dev_repo, feature_name)
        git_add_file(
            cwd=dev_repo, name=f"{feature_name}.{c}.txt", content=f"{dev.name} was here"
        )
        git_commit(
            cwd=dev_repo, message=f"{feature_name} {c}/{commits}"
        )
    await git_merge(dev_repo, branch, destination_branch, f"add {feature_name}")
    git_push(dev_repo)


def git_clone(dev, dev_dir, repo):
    check_call(start_cwd, git, "clone", repo, dev_dir)
    check_call(dev_dir, git, "config", "user.name", dev.name)
    check_call(dev_dir, git, "config", "user.email", f"{dev.name}@play")


def git_add_file(cwd: Path, name: str, content: str):
    with (cwd / name).open("w") as f:
        f.write(content)
    check_call(cwd, git, "add", name)


async def git_init(repo: Path):
    assert not repo.exists(), "Can't work with an existing dir"
    check_call(".", git, "init", "--bare", repo)

    clone = repo / "admin"
    git_clone(Dev("admin"), clone, repo)
    git_add_file(clone, str(clone / "README.md"), "just some text")
    git_commit(clone, "a first commit")
    git_push(clone)


async def play(play_dir: Path, repo_name: str):

    bob, alice, crusty = tuple(map(Dev, ("Bob", "Alice", "Crusty")))

    repo = play_dir / repo_name
    await git_init(repo)

    tasks = (
        task_for(
            play_dir,
            bob,
            "feature-1",
            commits=2,
            repo=repo,
            source_branch="master",
            destination_branch="master",
        ),
        task_for(
            play_dir,
            alice,
            "feature-2",
            commits=3,
            repo=repo,
            source_branch="master",
            destination_branch="master",
        ),
    )

    await gather(*tasks)


@click.command("run")
def run(play_dir=None, repo=None):
    if play_dir is None:
        play_dir = Path(tempfile.TemporaryDirectory().name)
    if repo is None:
        repo = "repo"
    asyncio.run(play(play_dir, repo))


if __name__ == "__main__":
    run()
