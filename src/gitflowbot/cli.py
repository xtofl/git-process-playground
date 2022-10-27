import asyncio
import functools
import os
import shutil
import subprocess
import tempfile
from asyncio import gather
from pathlib import Path
from textwrap import indent
from typing import Callable, Awaitable

import click as click


async def sleep_quanta(quanta):
    await asyncio.sleep(0.1 * quanta)


class Dev:
    def __init__(self, name):
        self.name = name

    async def some_work_async(self, dev_repo, feature_name):
        await sleep_quanta(len(self.name))


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
    await sleep_quanta(len(branch))
    check_call(cwd, git, "checkout", dest)
    check_call(cwd, git, "pull")
    check_call(cwd, git, "merge", "-m", message, "--no-ff", branch)


start_cwd = os.getcwd()


def git_push(cwd):
    check_call(cwd, git, "push")


async def some_work_async(dev: Dev, dev_repo: Path, feature_name: str):
    await dev.some_work_async(dev_repo, feature_name)


async def task_for(
    play_dir: Path,
    dev: Dev,
    feature_name: str,
    commits: int,
    repo: Path,
    source_branch: str,
    destination_branch: str,
    update_view: Callable[[], Awaitable[None]],
):
    branch, dev_repo = await clone_and_branch_async(
        dev, feature_name, play_dir, repo, source_branch
    )
    for c in range(commits):
        await some_work_async(dev, dev_repo, feature_name)
        git_add_file(
            cwd=dev_repo, name=f"{feature_name}.{c}.txt", content=f"{dev.name} was here"
        )
        git_commit(cwd=dev_repo, message=f"{feature_name} {c}/{commits}")
        git_push(dev_repo)
        await update_view()
    await git_merge(dev_repo, branch, destination_branch, f"add {feature_name}")
    git_push(dev_repo)
    check_call(dev_repo, git, "push", "origin", f":{branch}")
    await update_view()


async def clone_and_branch_async(dev, feature_name, play_dir, repo, source_branch):
    assert " " not in feature_name, "that would be a problem for git branch names"
    branch = f"feature/{feature_name}"
    dev_repo = play_dir / f"{dev.name}--{feature_name}"
    git_clone(dev, dev_repo, repo)
    check_call(dev_repo, git, "checkout", "-b", branch, source_branch)
    check_call(dev_repo, git, "push", "--set-upstream", "origin", branch)
    return branch, dev_repo


def git_clone(dev, dev_dir, repo):
    check_call(start_cwd, git, "clone", repo, dev_dir)
    check_call(dev_dir, git, "config", "user.name", dev.name)
    check_call(dev_dir, git, "config", "user.email", f"{dev.name}@play")


def git_add_file(cwd: Path, name: str, content: str):
    with (cwd / name).open("w") as f:
        f.write(content)
    check_call(cwd, git, "add", name)


async def default_interact(remote: "Remote"):
    print(f"pausing; update {remote.clone}")
    check_call(remote.clone, git, "fetch")
    await asyncio.sleep(0)
    input(">>>>>>>> press enter to continue")


async def default_no_interact(remote: "Remote", delay=1.0):
    print(f"pausing; update {remote.clone}")
    check_call(remote.clone, git, "fetch")
    await sleep_quanta(delay)


class Remote:
    def __init__(self, bare, clone, interact):
        self.bare = bare
        self.clone = clone
        self.interact = interact

    async def update_view(self):
        check_call(self.clone, git, "fetch")
        check_call(self.clone, git, "remote", "prune", "origin")
        await self.interact(self)

    async def show_view(self, tool=None):
        if tool is None:
            tool = (shutil.which("gitk"), "--all")
        process = subprocess.Popen(tool, cwd=self.clone)
        while process.poll():
            await asyncio.sleep(1)


async def git_init(repo: Path, interact):
    assert not repo.exists(), "Can't work with an existing dir"
    check_call(".", git, "init", "--bare", repo)

    clone = repo / "admin"
    git_clone(Dev("admin"), clone, repo)
    git_add_file(clone, str(clone / "README.md"), "just some text")
    git_commit(clone, "a first commit")
    git_push(clone)
    return Remote(repo, clone, interact)


async def in_sequence(*tasks):
    for task in tasks:
        await task


async def play(play_dir: Path, repo_name: str, interact):

    bob, alice, crusty = tuple(map(Dev, ("Bob", "Alice", "Crusty")))

    repo = play_dir / repo_name
    remote = await git_init(repo, interact)

    task_on_master = functools.partial(
        task_for,
        play_dir,
        repo=repo,
        source_branch="master",
        destination_branch="master",
        update_view=remote.update_view,
    )
    tasks = (
        task_on_master(
            dev=bob,
            feature_name="F1",
            commits=3,
        ),
        task_on_master(
            dev=crusty,
            feature_name="F4",
            commits=5,
        ),
        task_on_master(
            dev=crusty,
            feature_name="F5",
            commits=3,
        ),
        in_sequence(
            task_on_master(
                dev=alice,
                feature_name="F2",
                commits=2,
            ),
            task_on_master(
                dev=alice,
                feature_name="F3",
                commits=3,
            ),
        ),
    )

    await gather(remote.show_view(), *tasks)


@click.command("run")
def run(play_dir=None, repo=None):
    if play_dir is None:
        play_dir = Path(tempfile.TemporaryDirectory().name)
    if repo is None:
        repo = "repo"
    asyncio.run(play(play_dir, repo, functools.partial(default_no_interact, delay=1.5)))


if __name__ == "__main__":
    run()
