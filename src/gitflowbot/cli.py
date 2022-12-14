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


async def sleep_quanta(quantum_seconds, quanta):
    await asyncio.sleep(quantum_seconds * quanta)


class Dev:
    def __init__(self, name, time_passes: Callable[[float], Awaitable[None]]):
        self.name = name
        self.time_passes: Callable[[float], Awaitable[None]] = time_passes

    async def some_work_async(self, dev_repo, feature_name):
        await self.time_passes(len(self.name))


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


def git_merge(cwd, branch, dest, message):
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
    before_merge: Callable,
):
    branch, dev_repo = await clone_and_branch_async(
        dev, feature_name, play_dir, repo, source_branch
    )
    for c in range(commits):
        await dev.some_work_async(dev_repo, feature_name)
        git_add_file(
            cwd=dev_repo, name=f"{feature_name}.{c}.txt", content=f"{dev.name} was here"
        )
        git_commit(cwd=dev_repo, message=f"{feature_name} {c}/{commits}")
        git_push(dev_repo)
        await update_view()
    before_merge(origin=repo, repo=dev_repo, source_branch=source_branch, branch=branch)
    git_merge(dev_repo, branch, destination_branch, f"add {feature_name}")
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
    remote.fetch()
    await asyncio.sleep(0)
    input(">>>>>>>> press enter to continue")


async def default_no_interact(remote: "Remote", time_passes):
    print(f"pausing; update {remote.clone}")
    remote.fetch()
    await time_passes(1)


class Remote:
    def __init__(self, bare, clone, interact):
        self.bare = bare
        self.clone = clone
        self.interact = interact

    def fetch(self):
        check_call(self.clone, git, "fetch")

    async def update_view(self):
        self.fetch()
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
    git_clone(Dev("admin", asyncio.sleep), clone, repo)
    git_add_file(clone, str(clone / "README.md"), "just some text")
    git_commit(clone, "a first commit")
    git_push(clone)

    return Remote(repo, clone, interact)


async def in_sequence(*tasks):
    for task in tasks:
        await task


def git_rebase(origin: Path, repo: Path, source_branch: str, branch: str):
    do_git = functools.partial(check_call, str(repo), git)
    do_git("fetch")
    do_git("rebase", f"origin/{source_branch}")
    do_git("push", "--force-with-lease")


def no_rebase(origin: Path, repo: Path, source_branch: str, branch: str):
    pass


async def play(play_dir: Path, repo_name: str, interact, time_passes, rebase):

    bob, alice, crusty = tuple(
        Dev(name, time_passes) for name in ("Bob", "Alice", "Crusty")
    )

    repo = play_dir / repo_name
    remote = await git_init(repo, interact)

    task_on_master = functools.partial(
        task_for,
        play_dir,
        repo=repo,
        source_branch="master",
        destination_branch="master",
        update_view=remote.update_view,
        before_merge=rebase,
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
@click.option("--play-dir", type=Path, default=None)
@click.option("--step-seconds", type=float, default=0.5)
@click.option("--repo-name", type=str)
@click.option("--rebase/--no-rebase", type=bool, default=True)
def run(play_dir: Path, repo_name: str, step_seconds: float, rebase: bool):
    if play_dir is None:
        play_dir = Path(tempfile.TemporaryDirectory().name)
    if repo_name is None:
        repo_name = "repo"
    time_passes = functools.partial(sleep_quanta, step_seconds)
    asyncio.run(
        play(
            play_dir,
            repo_name,
            functools.partial(default_no_interact, time_passes=time_passes),
            time_passes=time_passes,
            rebase=git_rebase if rebase else no_rebase,
        )
    )


if __name__ == "__main__":
    run()
