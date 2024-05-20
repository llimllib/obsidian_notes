from dataclasses import dataclass
import os
import re
import subprocess

from strict_rfc3339 import timestamp_to_rfc3339_utcoffset, rfc3339_to_timestamp
import yaml

FRONT_MATTER = re.compile(r"^---(.*?)\n---\n", re.S)


def add_keys_to_front_matter(content, **kwargs):
    front_matter_match = FRONT_MATTER.search(content)

    if front_matter_match:
        front_matter = yaml.full_load(front_matter_match.group(1))
        front_matter |= kwargs
        new_front_matter = yaml.dump(front_matter, sort_keys=False)
        content = re.sub(
            FRONT_MATTER,
            f"---\n{new_front_matter.strip()}\n---\n",
            content,
        )
    else:
        new_front_matter = yaml.dump(kwargs, sort_keys=False)
        content = f"---\n{new_front_matter.strip()}\n---\n{content}"
    return content


@dataclass
class GitStat:
    st_mtime: float
    st_ctime: float


def gitstat(dir: str, path: str) -> GitStat:
    """return the created and modified times for a file from git"""
    # Here's an example of what the output looks like for this:
    #
    # $ git -C . log --pretty="format:%aI" README.md
    # 2023-10-30T08:18:52-04:00
    # 2022-04-28T21:54:00-04:00
    # 2022-04-09T22:09:23-04:00
    # 2022-04-08T21:36:48-04:00
    #
    # we need to use the -C argument to tell git to look in the notes
    # repository instead of this repository
    #
    # possibly I should add --follow so that this persists through renames?
    # though maybe I ought to consider a rename a recreation of a file? not
    # clear to me whether it's worth it or not.
    #
    # this is really slow, and I don't see a path to speeding it up a
    # tremendous amount
    times = (
        subprocess.check_output(
            [
                "git",
                "-C",
                dir,
                "log",
                "--follow",
                "--pretty=format:%aI",
                "-1",
                "--",
                path,
            ]
        )
        .decode("utf8")
        .split("\n")
    )

    # The modified time is the second timestamp on the first line
    print("mtime", times[0])
    mtime = rfc3339_to_timestamp(times[0])

    # to get the created date, we're going to get the authored time but with
    # --reverse, and we have to use the last line to get the appropriate time,
    # since limit is applied before ordering
    times = (
        subprocess.check_output(
            [
                "git",
                "-C",
                dir,
                "log",
                "--follow",
                "--reverse",
                "--format=%aI",
                "--",
                path,
            ]
        )
        .decode("utf8")
        .split("\n")
    )

    # The created time is the first timestamp on the last line
    print("ctime", [t.strip() for t in times if t.strip()][-1])
    ctime = rfc3339_to_timestamp(times[0])

    return GitStat(st_mtime=mtime, st_ctime=ctime)


def pt(t: float) -> str:
    return timestamp_to_rfc3339_utcoffset(t)


for root, dirs, files in os.walk(
    "/Users/llimllib/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal",
):
    # for root, dirs, files in os.walk(
    #     "/Users/llimllib/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal/link blog",
    # ):
    for f in (f for f in files if f.endswith(".md")):
        gs = gitstat(root, f)
        content = add_keys_to_front_matter(
            open(os.path.join(root, f)).read(),
            updated=pt(gs.st_mtime),
            created=pt(gs.st_ctime),
        )
        open(os.path.join(root, f), "w").write(content)
