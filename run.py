#!/usr/bin/env python
from custom_pygments_style import LlimllibStyle

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
from time import strftime, localtime, time
from typing import Any, Callable, DefaultDict, Generator, Optional

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt
import yaml

from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from pygments import highlight as pygmentize
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter

from strict_rfc3339 import timestamp_to_rfc3339_utcoffset, rfc3339_to_timestamp

JINJA = Environment(loader=FileSystemLoader("templates"))


@dataclass
class GitStat:
    st_mtime: float
    st_ctime: float


@dataclass
class FileStat:
    st_mtime: float
    st_ctime: float


@dataclass
class Attachment:
    title: str
    canon_title: str
    fullpath: str
    link_path: str
    file: str
    relpath: str
    links: list[str]
    backlinks: set["Page | Attachment"]

    def __eq__(self, b) -> bool:
        return b.title == self.title

    def __hash__(self) -> int:
        return hash(("title", self.title))


@dataclass
class Page:
    # the page's title
    title: str
    canon_title: str

    # the file path
    file: str

    # the relative path to the markdown source
    relpath: str

    # the absolute path to the markdown source
    fullpath: str

    # titlepath is the relative path and the file name of the page stripped of
    # its extension, for example it might be 'visualization/bar_charts'
    titlepath: str
    link_path: str

    # links is a list of (what, exactly?)
    links: list[str]

    backlinks: set["Page | Attachment"]

    frontmatter: dict[str, Any]

    # the mtime of the file
    mtime: float
    ctime: float

    # file creation and modification time, ISO timestamped
    rfc3339_ctime: str
    rfc3339_mtime: str

    # created and updated dates, formatted for humans
    created_date: str
    updated_date: str

    # the contents of the page, in markdown
    source: str

    # the contents of the page, rendered to HTML
    html: str = ""

    # the same HTML, escaped for use in the atom feed
    html_escaped_content: str = ""

    def __eq__(self, b) -> bool:
        return b.title == self.title

    def __hash__(self) -> int:
        return hash(("title", self.title))

    def dirlinks(self) -> Generator[str, None, None]:
        """yield a link to each dir page, all the way back to the root"""
        pathparts = self.titlepath.split("/")[:-1]
        for i in range(len(pathparts)):
            link = "/" + "/".join(pathparts[: i + 1])
            yield f'<a href="{ link }.html">{ pathparts[i] }</a>'


def info(msg: str, *args) -> None:
    yellow = "\033[0;33m"
    reset = "\033[0m"
    print(f"{yellow}{msg}{reset}", *args)


def err(msg: str, *args) -> None:
    red = "\033[0;31m"
    reset = "\033[0m"
    print(f"{red}{msg}{reset}", *args)


FRONT_MATTER_RE = re.compile(r"^\s*---(.*?)\n---\n", re.S)


def parse_frontmatter(raw_fm: str) -> dict[str, Any]:
    """parse yaml frontmatter and return a dictionary. yaml could be any data
    type, but in this context we're expecting to get a dict out of this, so
    throw an exception if we find anything else"""
    anything = yaml.safe_load(raw_fm)
    if not anything:
        return {}
    elif type(anything) != dict:
        raise Exception(f"Expected dict, got {type(anything)}")
    return anything


def split_front_matter(buf: str) -> tuple[dict[str, Any], str]:
    """split the front matter from the rest of the markdown document's content.
    Parse the front matter if present."""
    parts = FRONT_MATTER_RE.split(buf, 1)
    if len(parts) == 1:
        return ({}, parts[0])
    else:
        return (parse_frontmatter(parts[1]), parts[2])


WHITESPACE_RE = re.compile(r"[^\w\-\._~]")
MARKDOWN_RE = re.compile(r"\.md$")


def outname(fname: str) -> str:
    """Turn a markdown filename into an html file name"""
    clean = WHITESPACE_RE.sub("_", fname)
    return MARKDOWN_RE.sub(".html", clean)


SANITIZE_PATH = re.compile(r"[^\w\-\._~\\\/]")


def pathname(dname: str) -> str:
    """Sanitize a name"""
    return SANITIZE_PATH.sub("_", dname)


def mkdir(dir_: str | Path) -> str | Path:
    """Recursively make dir_ if it does not exist"""
    if not os.path.isdir(dir_):
        os.makedirs(dir_, exist_ok=True)
    return dir_


def formatted_time(t: float) -> str:
    return strftime("%b %d, %Y", localtime(t))


def rfc3339_time(t: float) -> str:
    return timestamp_to_rfc3339_utcoffset(t)


def render(template: str, **kwargs) -> str:
    return JINJA.get_template(template).render(**kwargs)


def generate_stylesheet() -> None:
    """Use pygments to generate a stylesheet"""
    with open(f"output/pygments.css", "w") as f:
        f.write(HtmlFormatter(style=LlimllibStyle).get_style_defs())


def copy_static(from_dir: Path, to_dir: Path) -> None:
    """Copy stylesheet from the templates dir to output"""
    for ext in ["*.css", "*.svg"]:
        for f in from_dir.glob(ext):
            shutil.copy(f, to_dir)


def strip_fancy_name(link: str) -> str:
    """Return the name of a link

    Strip a pipe, which is used in a link like [[Some long title|link text]]

    or a hash, which is used like [[Somepage#anchor]]
    """
    if "|" in link:
        return link.split("|")[0]
    if "#" in link:
        return link.split("#")[0]
    return link


LINK_RE = re.compile(r"\[\[(.*?)\]\]")


def findlinks(md: str) -> list[str]:
    """Find all links in a markdown document"""
    # XXX: right now this grabs some "links" from code blocks; i.e. pandas lets
    #      you do stuff like df[["columnA", "columnB"]]. Fix the regex so it
    #      doesn't match that
    return list(map(strip_fancy_name, LINK_RE.findall(md)))


def canonicalize(title: str) -> str:
    """return the canonical form of a title"""
    return title.lower()


def canonical_path(relative_path: str) -> str:
    """Given a relative path, return the canonical form

    For example, if you pass "Data Analytics/Duckdb", this returns
    "Data_Analytics/duckdb". The value returned by this will match the
    "titlepath" attribute of a page
    """
    path, page = os.path.split(relative_path)
    if path:
        return pathname(path) + "/" + canonicalize(page)
    return page.lower()


def find(
    pages: dict[str, Page], attachments: dict[str, Attachment], link: str
) -> Optional[Page | Attachment]:
    """find a page referred to by `link`

    Pages can be linked in two ways:
        - By their title
            - Titles may not be unique and this function will just return the
              first result in our random search if there are multiple pages
              with the same title
        - By their path+title
    """
    clink = canonical_path(link)
    for relpath, page in pages.items():
        if page.canon_title == clink or relpath == clink:
            return page
    for link_path, attach in attachments.items():
        if attach.file == link or link_path == link:
            return attach


def split_files(files: list[str]) -> tuple[list[str], list[str]]:
    """Split a file list into markdown and non-markdown files"""
    return (
        [f for f in files if f.endswith(".md")],
        [f for f in files if not f.endswith(".md")],
    )


class FileTree:
    def __init__(
        self, dir: Optional[str] = None, page: Optional[Page | Attachment] = None
    ):
        self.dir = dir
        if isinstance(self.dir, str):
            self.basename = os.path.basename(self.dir)
            self.reldir = pathname(self.dir)
            self.dirparts = self.dir.split("/")
            self.reldirparts = self.reldir.split("/")
        self.page = page
        self.children: list[FileTree] = []

    def child_pages(self, idx=None) -> dict[str, Page]:
        if not isinstance(idx, dict):
            idx = {}
        for c in self.children:
            if isinstance(c.page, Page):
                idx[c.page.titlepath] = c.page
            elif c.dir:
                c.child_pages(idx)
        return idx

    def find_dir(self, dir: str) -> Optional["FileTree"]:
        if self.reldirparts[-1] == dir:
            return self
        for subdir in (c for c in self.children if c.dir):
            d = subdir.find_dir(dir)
            if d:
                return d

    def dir_backlinks(self) -> set[Page | Attachment]:
        """return backlinks for all direct children of this node"""
        return set(
            backlink
            for child in self.children
            if child.page
            for backlink in child.page.backlinks
        )

    def has_child_dirs(self) -> bool:
        """return true if there are child dirs"""
        return any(child.dir for child in self.children)

    def dirlinks(self) -> Generator[str, None, None]:
        """yield a link to each dir page, all the way back to the root"""
        assert self.dir

        for i in range(len(self.dirparts)):
            link = "/" + "/".join(self.reldirparts[: i + 1])
            yield f'<a href="{ link }.html">{ self.dirparts[i] }</a>'

    def dirlink(self) -> str:
        """return a link to this directory"""
        assert self.dir
        href = "/" + "/".join(self.reldirparts) + ".html"
        return f'<a href="{ href }" class="dirlink">🔗</a>'

    def __str__(self) -> str:
        if self.dir:
            return os.path.basename(self.dir)
        elif self.page:
            return self.page.title
        raise AssertionError("either page or dir must be true")

    def __repr__(self) -> str:
        return self.__str__()


def gitstat(dir: str, path: str) -> GitStat:
    """return the created and modified times for a file from git"""
    # Here's an example of what the output looks like for this:
    #
    # $ git -C . log --pretty="format:%cI %aI" README.md
    # 2023-10-30T08:18:52-04:00 2023-10-30T08:18:52-04:00
    # 2022-04-28T21:54:00-04:00 2022-04-28T21:54:00-04:00
    # 2022-04-09T22:09:23-04:00 2022-04-09T22:09:23-04:00
    # 2022-04-08T21:36:48-04:00 2022-04-08T21:36:48-04:00
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
            ["git", "-C", dir, "log", "--pretty=format:%aI %cI", "--", path]
        )
        .decode("utf8")
        .split("\n")
    )

    # The modified time is the second timestamp on the first line
    mtime = rfc3339_to_timestamp(times[0].split(" ")[1])

    # ctime is not useful, I should remove this from here
    ctime = rfc3339_to_timestamp(times[-1].split(" ")[0])

    return GitStat(st_mtime=mtime, st_ctime=ctime)


def parse_fm_datetime(d: str | datetime) -> float:
    """
    parse a datetime from frontmatter, which may be a string or datetime, into
    a timestamp

    I don't quite understand why the yaml lib seems to be converting it
    sometimes, but not others
    """
    if isinstance(d, str):
        return rfc3339_to_timestamp(d)
    return d.timestamp()


def handle_file(path: str, root: str, use_git_times: bool) -> Page | Attachment:
    """given a full path and the root of the tree, return a page dict

    path: full path to a file
    root: the root of the tree we're building
    """
    _, extension = os.path.splitext(path)
    if extension == ".md":
        with open(path) as f:
            buf = f.read()
            frontmatter, source = split_front_matter(buf)
            links = findlinks(source)
            dir, filename = os.path.split(path)
            relpath = pathname(dir.removeprefix(root).lstrip("/"))
            title, _ = os.path.splitext(filename)
            titlepath = os.path.join(relpath, canonicalize(title))

            # get created and modified times for the file. Preference order:
            # - updated time in frontmatter
            # - file info from git (if gistat is enabled)
            # - file modified time from the file system
            if "updated" in frontmatter and "created" in frontmatter:
                t = FileStat(
                    parse_fm_datetime(frontmatter["updated"]),
                    parse_fm_datetime(frontmatter["created"]),
                )
            # if use_git_times is true, assume that the file is stored in git,
            # and get ctime and mtime from git.
            elif use_git_times:
                try:
                    t = gitstat(dir, path)
                # if the file is not in git, the function currently throws an
                # IndexError. Take the mtime in that case instead, rather
                # than failing
                except IndexError:
                    t = os.stat(path)
            else:
                t = os.stat(path)

            return Page(
                # `title` contains the title, cased as the author cased it
                title=title,
                # `canon_title` contains the canonicalized title
                canon_title=canonicalize(title),
                links=links,
                fullpath=path,
                link_path=os.path.join(relpath, outname(filename)),
                file=filename,
                relpath=relpath,
                titlepath=titlepath,
                source=source,
                backlinks=set(),
                frontmatter=frontmatter,
                ctime=t.st_ctime,
                mtime=t.st_mtime,
                # would be better to put file creation time in front matter
                # at file create time and pull it from there, but this will
                # do for now
                rfc3339_ctime=rfc3339_time(t.st_ctime),
                rfc3339_mtime=rfc3339_time(t.st_mtime),
                created_date=formatted_time(t.st_ctime),
                updated_date=formatted_time(t.st_mtime),
            )

    # if it's not a markdown file, parse it as an attachment
    dir, filename = os.path.split(path)
    title, _ = os.path.splitext(filename)
    relpath = pathname(dir.removeprefix(root).lstrip("/"))
    return Attachment(
        title=title,
        canon_title=canonicalize(title),
        fullpath=path,
        link_path=os.path.join(relpath, filename),
        file=filename,
        relpath=relpath,
        links=[],
        backlinks=set(),
    )


def build_file_tree(
    dir: str, ignore: set[str], use_git_times: bool
) -> tuple[FileTree, dict[str, Page], dict[str, Attachment]]:
    """build a file tree from a given directory

    dir: the directory to build the file tree from
    ignore: a set of directory names to ignore

    returns a FileTree, an index of pages, and an index of attachments.

    The page index is keyed on titlepath, which is the relative path plus the
    canonicalized title, so something like 'visualization/bar_charts'. The
    index contains only content pages.

    The attachments dictionary is keyed on relative path + filename, so
    something like 'images/some image 2928984588.png'
    """
    index = {}
    attachments = {}
    return (
        build_file_tree_helper(
            FileTree(dir=dir), ignore, dir, index, attachments, use_git_times
        ),
        index,
        attachments,
    )


def isEmptyFile(path: str) -> bool:
    """return true if a file is empty

    more precisely, if it doesn't have any non-whitespace characters in the
    first 16 bytes

    must open the file in binary mode because if it's a binary file it may not
    be decodable to unicode
    """
    return not open(path, "rb").read(16).strip()


def build_file_tree_helper(
    node: FileTree,
    ignore: set[str],
    root_path: str,
    index: dict[str, Page],
    attachments: dict[str, Attachment],
    use_git_times: bool,
) -> FileTree:
    assert node.dir
    for de in sorted(
        os.scandir(os.path.join(root_path, node.dir)),
        key=lambda x: x.path.lower(),
    ):
        if de.name in ignore:
            info(f"Ignoring file", de)
            continue

        # ignore untitled files or directories
        if de.name == "Untitled.md" or de.name == "Untitled":
            info(f"Ignoring untitled object", de)
            continue

        if de.is_dir():
            path = de.path.removeprefix(root_path).lstrip("/")
            node.children.append(
                build_file_tree_helper(
                    FileTree(dir=path),
                    ignore,
                    root_path,
                    index,
                    attachments,
                    use_git_times,
                )
            )
        else:
            if isEmptyFile(de.path):
                info(f"Ignoring empty file", de)
                continue
            page = handle_file(de.path, root_path, use_git_times)

            # we want to index each page by its titlepath, which is something
            # like 'visualization/bar_charts'. If the page does not have a
            # titlepath attribute, assume that it's not a content page
            if isinstance(page, Page):
                # if a page has frontmatter, and that frontmatter contains a
                # "draft" key that is non-empty, consider it a draft and don't
                # render it
                if type(page) == Page and page.frontmatter.get("draft"):
                    continue

                index[page.titlepath] = page
            else:
                attachments[page.link_path] = page

            node.children.append(FileTree(page=page))

    return node


def calculate_backlinks(
    pages: dict[str, Page], attachments: dict[str, Attachment]
) -> None:
    for page in pages.values():
        for link in page.links:
            linked_page = find(pages, attachments, link)
            if not linked_page:
                info(f"unable to find link", link, page.title)
                continue
            linked_page.backlinks.add(page)


def generate_lastweek_page(pages: dict[str, Page], outdir: Path) -> None:
    today = datetime.today()
    pages_by_weeks_ago: DefaultDict[int, list[Page]] = defaultdict(list)
    for p in reversed(sorted(pages.values(), key=lambda x: x.mtime)):
        daysago = (today - datetime.fromtimestamp(p.mtime)).days
        pages_by_weeks_ago[(daysago - 1) // 7].append(p)
        if daysago > 21:
            break

    open(outdir / "lastweek.html", "w").write(
        render("lastweek.html", pages_by_weeks_ago=pages_by_weeks_ago)
    )


def generate_search(pages: dict[str, Page], outdir: Path) -> None:
    index = [
        {
            "id": i,
            "title": page.title,
            "contents": BeautifulSoup(page.html, features="html.parser").get_text(),
            "title_path": page.titlepath,
            "link_path": page.link_path,
        }
        for (i, page) in enumerate(pages.values())
    ]

    open(outdir / "search.html", "w").write(render("search.html", index=index))


def generate_index_page(
    tree: FileTree, pages: dict[str, Page], outdir: Path, recent: int
) -> None:
    # get the most recently created files
    by_ctime = list(reversed(sorted(pages.values(), key=lambda x: x.ctime)))[:recent]
    recently_created = [p.link_path for p in by_ctime]
    by_mtime = list(
        reversed(
            sorted(
                (
                    p
                    for p in pages.values()
                    if p.link_path not in recently_created and p.mtime != p.ctime
                ),
                key=lambda x: x.mtime,
            )
        )
    )[:recent]
    open(outdir / "index.html", "w").write(
        render(
            "index.html",
            recently_created=by_ctime,
            recently_updated=by_mtime,
            tree=tree,
        )
    )


def generate_feed(pages: dict[str, Page], outfile: Path, recent: int) -> None:
    """generate a single feed file from the atom.xml template"""
    by_mtime = list(reversed(sorted(pages.values(), key=lambda x: x.mtime)))

    posts = by_mtime[:recent]
    for p in posts:
        if not p.html_escaped_content:
            p.html_escaped_content = escape(render_content(p))

    open(outfile, "w").write(
        render("atom.xml", posts=by_mtime[:recent], timestamp=rfc3339_time(time()))
    )


def generate_feeds(
    tree: FileTree, pages: dict[str, Page], feeds: list[str], outdir: Path, recent: int
) -> None:
    """
    generate an atom feed for the root tree, then go through each sub-feed in
    the feeds array, find the directory with that name, and generate a feed for
    it
    """
    generate_feed(pages, outdir / "atom.xml", recent)

    for feed in feeds:
        subtree = tree.find_dir(feed)
        if not subtree:
            raise ValueError(f"unable to find {feed}")
        generate_feed(subtree.child_pages(), outdir / f"{feed}.atom.xml", recent)


def generate_dir_pages(root: FileTree, pages: dict[str, Page], outdir: Path) -> None:
    for child in root.children:
        if child.dir:
            open(outdir / f"{child.reldir}.html", "w").write(
                render("dir.html", tree=child)
            )
            generate_dir_pages(child, pages, outdir)


def highlight(code, name, _) -> str:
    """Highlight a block of code"""
    if not name:
        return f'<div class="highlight">{escape(code)}</div>'

    # admonishment adapted from mkdocs-material
    # https://squidfunk.github.io/mkdocs-material/reference/admonitions/
    if name == "warning":
        return f'<div class="admon-warning"><p class="warning">{escape(code)}</p></div>'

    try:
        lexer = get_lexer_by_name(name)
    except:
        print(f"failed to get lexer for {name}")
        return f'<div class="highlight">{escape(code)}</div>'
    formatter = HtmlFormatter()

    return pygmentize(code, lexer, formatter)


MD = (
    MarkdownIt("gfm-like", {"breaks": True, "html": True, "highlight": highlight})
    .use(anchors_plugin, max_level=6)
    .use(front_matter_plugin)
    .use(footnote_plugin)
)


def render_link(self, tokens, idx, options, env):
    # don't count anchor links as external
    if not tokens[idx].attrs["href"].startswith("#"):
        tokens[idx].attrSet("class", "external-link")
    return self.renderToken(tokens, idx, options, env)


MD.add_render_rule("link_open", render_link)


def render_content(page: Page) -> str:
    """
    Given a "page" object, render the markdown within to escaped HTML
    """
    return MD.render(page.source)


def generate_html_pages(pages: dict[str, Page], outdir: Path) -> None:
    for page in pages.values():
        output_path = outdir / page.link_path

        # Optimization: If the file has already been converted to HTML and the
        # HTML is newer than the source, don't regenerate the file. Do convert
        # the markdown to HTML because we'll need that
        if os.path.isfile(output_path) and page.mtime < os.stat(output_path).st_mtime:
            page.html = render_content(page)
            continue

        page.html = render_content(page)
        page.html_escaped_content = escape(page.html)

        mkdir(str(outdir / page.relpath))
        with open(output_path, "w") as fout:
            text = render("page.html", page=page)
            fout.write(text)


def copy_attachments(attachments: dict[str, Attachment], outdir: Path) -> None:
    for page in attachments.values():
        mkdir(outdir / page.relpath)
        shutil.copy(page.fullpath, outdir / page.link_path)


def attachment_replacer(pages: dict[str, Page], attachments: dict[str, Attachment]):
    def _attachment_replacer(m: re.Match) -> str:
        filename = m.group(1)
        linked_attch = find(pages, attachments, filename)
        if not linked_attch:
            err(f"Unable to find attachment", filename)
            return ""
        path = linked_attch.link_path
        # assume it's an image unless it ends with pdf, mov, mp4 or webm
        if filename.endswith(".pdf"):
            return f'<iframe src="/{path}" width="800" height="1200"></iframe>'
        elif filename.endswith(".mov"):
            return f'<video controls><source src="/{path}" type="video/quicktime" /><a href="/{path}">download</a></video>'
        elif filename.endswith(".mp4"):
            return f'<video controls><source src="/{path}" type="video/mp4" /><a href="/{path}">download</a></video>'
        elif filename.endswith(".webm"):
            return f'<video controls><source src="/{path}" type="video/webm" /><a href="/{path}">download</a></video>'
        return f'<a href="/{path}"><img class="bodyimg" src="/{path}"></a>'

    return _attachment_replacer


IMAGE_LINK_RE = re.compile(r"!\[\[(.*?)\]\]")


def substitute_images(
    pages: dict[str, Page], attachments: dict[str, Attachment]
) -> None:
    replacer = attachment_replacer(pages, attachments)
    for page in pages.values():
        page.source = IMAGE_LINK_RE.sub(replacer, page.source)


def sanitize(s: str) -> str:
    """Replace non-alphanum-characters with dash and lowercase

    I'm sure this doesn't quite match the ids we're giving to section headers,
    but it seems to be close enough for now. Ultimately, I should look into the
    generation function and figure out exactly how it's turning:

        ## Day 2

    into

        <h2 id="day-2">Day 2</h2>

    so that I can match it precisely.
    """
    return re.sub(r"[^\w]", "-", s.rstrip()).lower()


# maybe move to https://github.com/jsepia/markdown-it-wikilinks eventually?
def crosslink_replacer(pages: dict[str, Page]) -> Callable[[re.Match], str]:
    def _crosslink_replacer(m: re.Match) -> str:
        rawlink = m.group(1)
        title = rawlink
        nicetitle = None
        anchor = None

        # [[page|nice title]] -> title: page, nicetitle: nice title
        if "|" in rawlink:
            title, nicetitle = rawlink.split("|")

        # [[page#anchor]] -> title: page, anchor: anchor
        if "#" in title:
            title, anchor = title.split("#")

        linked_page = find(pages, {}, title)

        # if we don't find the linked page, assume that the group is not in
        # fact a link. There are several places in my notes where we use the
        # string `[[` but it's not a link; leave them be
        if not linked_page:
            err(f"Unable to find page", title)
            return m.group(0)

        linktitle = nicetitle if nicetitle else title
        anchor = f"#{sanitize(anchor)}" if anchor else ""

        return f'<a href="/{linked_page.link_path}{anchor}" class="internal-link">{linktitle}</a>'

    return _crosslink_replacer


# match:
# - two open square brackets [[
# - capture anything up to the closing square bracket pair ]]
CROSSLINK_RE = re.compile(r"\[\[(.*?)\]\]")


def substitute_crosslinks(pages: dict[str, Page]) -> None:
    replacer = crosslink_replacer(pages)
    for page in pages.values():
        page.source = CROSSLINK_RE.sub(replacer, page.source)


def parse(
    mddir: str,
    recent: int,
    use_git_times: bool,
    ignore: Optional[set[str]] = None,
    feeds: list[str] = [],
) -> None:
    """parse a directory of markdown files, ignoring a list of folder names

    mddir: the name of the directory to parse files in
    recent: how many posts to show in the "recently updated" section
    ignore: an optional list of directory names to ignore. Will be ignored at
    any level in the tree.
    """
    # make the type checker happy
    ignore = ignore if ignore else set()
    dir = os.path.normpath(os.path.expanduser(mddir))

    tree, pages, attachments = build_file_tree(dir, ignore, use_git_times)
    calculate_backlinks(pages, attachments)

    outdir = Path(mkdir("./output"))

    generate_stylesheet()
    copy_static(Path("./templates"), outdir)
    copy_attachments(attachments, outdir)

    substitute_images(pages, attachments)
    substitute_crosslinks(pages)

    # should come before generate_index_page because it generates the HTML that
    # is necessary for the atom file output
    generate_html_pages(pages, outdir)
    generate_search(pages, outdir)
    generate_index_page(tree, pages, outdir, recent)
    generate_feeds(tree, pages, feeds, outdir, recent)
    generate_dir_pages(tree, pages, outdir)
    generate_lastweek_page(pages, outdir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recent",
        help="number of recent entries to show",
        type=int,
        default=15,
    )
    parser.add_argument(
        "--path",
        help="path to folder of .md files to publish. This must be an absolute path",
        type=str,
        default="~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal",
    )
    parser.add_argument(
        "--use-git-times",
        action="store_true",
        help="use git modified time instead of mtime for file timestamps",
    )
    parser.add_argument(
        "--feed",
        action="append",
        default=[],
        help="a directory to generate a separate feed for. Can be given multiple times",
    )
    args = parser.parse_args(sys.argv[1:])

    default_ignores = {
        ".DS_Store",
        "private",
        ".obsidian",
        ".github",
        ".git",
        ".gitignore",
    }
    parse(
        args.path,
        args.recent,
        args.use_git_times,
        ignore=default_ignores,
        feeds=args.feed,
    )
