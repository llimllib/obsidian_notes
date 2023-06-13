#!/usr/bin/env python
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from html import escape
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
from time import strftime, localtime, time
from typing import List, Optional, Tuple, Dict, Any

from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from pygments import highlight as pygmentize
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from strict_rfc3339 import timestamp_to_rfc3339_utcoffset

JINJA = Environment(loader=FileSystemLoader("templates"))


def info(msg: str) -> None:
    print(msg)


def err(msg: str) -> None:
    print(msg)


FRONT_MATTER_RE = re.compile(r"^\s*---(.*?)\n---\n", re.S)


def split_front_matter(buf: str) -> Tuple[str, str]:
    parts = FRONT_MATTER_RE.split(buf, 1)
    if len(parts) == 1:
        return ("", parts[0])
    else:
        return (parts[1], parts[2])


WHITESPACE_RE = re.compile(r"[^\w\-\._~]")
MARKDOWN_RE = re.compile(r"\.md$")


def outname(fname: str) -> str:
    """Turn a markdown filename into an html file name"""
    fname = WHITESPACE_RE.sub("_", fname)
    return MARKDOWN_RE.sub(".html", fname)


SANITIZE_PATH = re.compile(r"[^\w\-\._~\\\/]")


def pathname(dname: str) -> str:
    """Sanitize a name"""
    return SANITIZE_PATH.sub("_", dname)


def mkdir(dir_: str) -> str:
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


def generate_stylesheet(style: str = "default") -> None:
    """Use pygments to generate a stylesheet"""
    subprocess.call(
        f"pygmentize -S {style} -f html -a div.highlight > output/pygments.css",
        shell=True,
    )


def copy_stylesheet(from_dir: Path, to_dir: Path) -> None:
    """Copy stylesheet from the templates dir to output"""
    for f in from_dir.glob("*.css"):
        shutil.copy(f, to_dir)


def strip_fancy_name(link: str) -> str:
    """Return the part of a link before the pipe, if present"""
    if "|" in link:
        return link.split("|")[0]
    return link


LINK_RE = re.compile(r"\[\[(.*?)\]\]")


def findlinks(md: str) -> List[str]:
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
        return f"{pathname(path)}/{canonicalize(page)}"
    return canonicalize(page)


# TODO: type the page object... for now I'm just calling it "Any"
def find(
    pages: Dict[str, Any], attachments: Dict[str, Any], link: str
) -> Optional[Dict[str, Any]]:
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
        if page["canon_title"] == clink or relpath == clink:
            return page
    for link_path, page in attachments.items():
        if page["file"] == link or link_path == link:
            return page


def split_files(files: List[str]) -> Tuple[List[str], List[str]]:
    """Split a file list into markdown and non-markdown files"""
    return (
        [f for f in files if f.endswith(".md")],
        [f for f in files if not f.endswith(".md")],
    )


class FileTree:
    def __init__(self, dir=None, page=None):
        self.dir = dir
        if self.dir:
            self.basename = os.path.basename(dir)
        self.page = page
        self.children = []

    def __str__(self):
        return os.path.basename(self.dir) if self.dir else self.page["title"]

    def __repr__(self):
        return self.__str__()


def handle_file(path: str, root: str) -> Dict[str, Any]:
    """given a full path and the root of the tree, return a page dict

    path: full path to a file
    root: the root of the tree we're building
    """
    _, extension = os.path.splitext(path)
    if extension == ".md":
        with open(path) as f:
            buf = f.read()
            # TODO: do something with the front matter - rn none of my
            # files actually have any
            # https://help.obsidian.md/Advanced+topics/YAML+front+matter
            _, source = split_front_matter(buf)
            links = findlinks(source)
            dir, filename = os.path.split(path)
            relpath = pathname(dir.removeprefix(root).lstrip("/"))
            title, _ = os.path.splitext(filename)
            titlepath = os.path.join(relpath, canonicalize(title))
            t = os.stat(path)
            return {
                # `title` contains the title, cased as the author cased it
                "title": title,
                # `canon_title` contains the canonicalized title
                "canon_title": canonicalize(title),
                "links": links,
                "fullpath": path,
                "link_path": os.path.join(relpath, outname(filename)),
                "file": filename,
                "relpath": relpath,
                "titlepath": titlepath,
                "source": source,
                "backlinks": [],
                "mtime": t.st_mtime,
                # would be better to put file creation time in front matter
                # at file create time and pull it from there, but this will
                # do for now
                "rfc3339_ctime": rfc3339_time(t.st_ctime),
                "rfc3339_mtime": rfc3339_time(t.st_mtime),
                "created_date": formatted_time(t.st_ctime),
                "updated_date": formatted_time(t.st_mtime),
                "attachment": False,
            }

    # if it's not a markdown file, parse it as an attachment
    dir, filename = os.path.split(path)
    title, _ = os.path.splitext(filename)
    relpath = pathname(dir.removeprefix(root).lstrip("/"))
    return {
        "title": title,
        "canon_title": canonicalize(title),
        "fullpath": path,
        "link_path": os.path.join(relpath, filename),
        "file": filename,
        "relpath": relpath,
        "links": [],
        "backlinks": [],
        "attachment": True,
    }


def build_file_tree(
    dir: str, ignore: set[str]
) -> Tuple[FileTree, Dict[str, Any], Dict[str, Any]]:
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
        build_file_tree_helper(FileTree(dir=dir), ignore, dir, index, attachments),
        index,
        attachments,
    )


def build_file_tree_helper(
    node: FileTree,
    ignore: set[str],
    root_path: str,
    index: Dict[str, Any],
    attachments: Dict[str, Any],
) -> FileTree:
    # XXX: sorting the whole path is kind of janky, is it right?
    for de in sorted(
        os.scandir(os.path.join(root_path, node.dir)), key=lambda x: x.path.lower()
    ):
        if de.name in ignore:
            continue

        if de.is_dir():
            path = de.path.removeprefix(root_path).lstrip("/")
            node.children.append(
                build_file_tree_helper(
                    FileTree(dir=path), ignore, root_path, index, attachments
                )
            )
        else:
            page = handle_file(de.path, root_path)

            # we want to index each page by its titlepath, which is something
            # like 'visualization/bar_charts'. If the page does not have a
            # titlepath attribute, assume that it's not a content page
            if "titlepath" in page:
                index[page["titlepath"]] = page
            else:
                attachments[page["link_path"]] = page

            node.children.append(FileTree(page=page))

    return node


def calculate_backlinks(pages: Dict[str, Any], attachments: Dict[str, Any]) -> None:
    for page in pages.values():
        for link in page["links"]:
            linked_page = find(pages, attachments, link)
            if not linked_page:
                print(f"unable to find link {link} in {page['title']}")
                continue
            linked_page["backlinks"].append(page)


def generate_lastweek_page(pages: Dict[str, Any], outdir: Path) -> None:
    today = datetime.today()
    pages_by_weeks_ago = defaultdict(list)
    for p in reversed(sorted(pages.values(), key=lambda x: x["mtime"])):
        daysago = (today - datetime.fromtimestamp(p["mtime"])).days
        pages_by_weeks_ago[(daysago - 1) // 7].append(p)
        if daysago > 21:
            break

    open(outdir / "lastweek.html", "w").write(
        render("lastweek.html", pages_by_weeks_ago=pages_by_weeks_ago)
    )


def generate_index_page(
    tree: FileTree, pages: Dict[str, Any], outdir: Path, recent: int
) -> None:
    by_mtime = list(reversed(sorted(pages.values(), key=lambda x: x["mtime"])))
    open(outdir / "index.html", "w").write(
        render(
            "index.html",
            pages=pages,
            recently_updated=by_mtime[:recent],
            tree=tree,
        )
    )

    # the posts may not have been rendered - if so, render them. We need to
    # have the rendered HTML so we can generate the atom summaries
    posts = by_mtime[:recent]
    for p in posts:
        if "html_escaped_content" not in p:
            p["html_escaped_content"] = escape(render_content(p))

    open(outdir / "atom.xml", "w").write(
        render("atom.xml", posts=by_mtime[:recent], timestamp=rfc3339_time(time()))
    )


def highlight(code, name, _):
    """Highlight a block of code"""
    if not name:
        return f'<div class="highlight">{code}</div>'

    try:
        lexer = get_lexer_by_name(name)
    except:
        print(f"failed to get lexer for {name}")
        return f'<div class="highlight">{code}</div>'
    formatter = HtmlFormatter()

    return pygmentize(code, lexer, formatter)


MD = (
    MarkdownIt("gfm-like", {"breaks": True, "html": True, "highlight": highlight})
    .use(anchors_plugin)
    .use(front_matter_plugin)
    .use(footnote_plugin)
    .use(dollarmath_plugin)
)


def render_content(page: Any) -> str:
    """
    Given a "page" object, render the markdown within to escaped HTML
    """
    return MD.render(page["source"])


def generate_html_pages(pages: Dict[str, Any], outdir: Path) -> None:
    for page in pages.values():
        output_path = outdir / page["link_path"]

        # Optimization: If the file has already been converted to HTML and the
        # HTML is newer than the source, don't regenerate the file
        if (
            os.path.isfile(output_path)
            and page["mtime"] < os.stat(output_path).st_mtime
        ):
            continue

        # XXX: this is a mess. make a real page object
        page["html"] = render_content(page)
        page["html_escaped_content"] = escape(page["html"])

        mkdir(str(outdir / page["relpath"]))
        with open(output_path, "w") as fout:
            text = render("page.html", content=page["html"], **page)
            fout.write(text)
            page["html_content"] = text


def copy_attachments(attachments: Dict[str, Any], outdir: Path) -> None:
    for page in attachments.values():
        mkdir(outdir / page["relpath"])
        shutil.copy(page["fullpath"], outdir / page["link_path"])


def attachment_replacer(pages: Dict[str, Any], attachments: Dict[str, Any]):
    def _attachment_replacer(m: re.Match) -> str:
        filename = m.group(1)
        linked_attch = find(pages, attachments, filename)
        if not linked_attch:
            err(f"Unable to find attachment {filename}")
            return ""
        path = linked_attch["link_path"]
        # assume it's an image unless it ends with PDF
        if filename.endswith(".pdf"):
            return f'<iframe src="/{path}" width="800" height="1200"></iframe>'
        return f'<a href="/{path}"><img src="/{path}" style="max-width: 800px"></a>'

    return _attachment_replacer


IMAGE_LINK_RE = re.compile(r"!\[\[(.*?)\]\]")


def substitute_images(pages: Dict[str, Any], attachments: Dict[str, Any]) -> None:
    replacer = attachment_replacer(pages, attachments)
    for page in pages.values():
        page["source"] = IMAGE_LINK_RE.sub(replacer, page["source"])


# maybe move to https://github.com/jsepia/markdown-it-wikilinks eventually?
def crosslink_replacer(pages: Dict[str, Any]):
    def _crosslink_replacer(m: re.Match) -> str:
        title = m.group(1)
        linked_page = find(pages, {}, title)
        if not linked_page:
            err(f"Unable to find page {title}")
            return ""
        return f'<a href="/{linked_page["link_path"]}">{title}</a>'

    return _crosslink_replacer


# match:
# - two open square brackets [[
# - capture anything up to the next pipe (|) or closing square bracket pair ]]
# - discard anything after the pipe if present
CROSSLINK_RE = re.compile(r"\[\[(.*?)(?:\|.*?)?\]\]")


def substitute_crosslinks(pages: Dict[str, Any]) -> None:
    replacer = crosslink_replacer(pages)
    for page in pages.values():
        page["source"] = CROSSLINK_RE.sub(replacer, page["source"])


def parse(mddir: str, recent: int, ignore: Optional[set[str]] = None):
    """parse a directory of markdown files, ignoring a list of folder names

    mddir: the name of the directory to parse files in
    recent: how many posts to show in the "recently updated" section
    ignore: an optional list of directory names to ignore. Will be ignored at
    any level in the tree.
    """
    # make the type checker happy
    ignore = ignore if ignore else set()
    mddir = os.path.normpath(os.path.expanduser(mddir))

    tree, pages, attachments = build_file_tree(mddir, ignore)
    calculate_backlinks(pages, attachments)

    outdir = Path(mkdir("./output"))

    generate_stylesheet()
    copy_stylesheet(Path("./templates"), outdir)
    copy_attachments(attachments, outdir)

    substitute_images(pages, attachments)
    substitute_crosslinks(pages)

    # should come before generate_index_page because it generates the HTML that
    # is necessary for the atom file output
    generate_html_pages(pages, outdir)
    generate_index_page(tree, pages, outdir, recent)
    generate_lastweek_page(pages, outdir)


# TODO:
# - better code highlighting
#   - the first chart on this page is completely busto:
#     - http://devd.io:8000/book_notes/Understanding_Software_Dynamics/Chapter_1_-_My_program_is_too_slow.html
#   - it shouldn't highlight at all
#     - could disable language guessing? But generally I like it?
#     - maybe just add a language annotation for every block?
#   - nicer colors (syntax and bg)
#   - proper overflow out of parent container
# - navigation pane?
#     - skipping it for now, but some sort of collapsible sidebar sounds nice?
# - better table formatting
#   - borders
# - table of contents for big pages
#   - https://python-markdown.github.io/extensions/toc/
#   - apparently the toc extension will do anchor links... would I need a toc
#     on every page to get that though?
# - add command line arguments for mddir and default_ignores
# - admonitions might be nice?
#   - https://python-markdown.github.io/extensions/admonition/
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recent",
        help="number of recent entries to show",
        type=int,
        default=15,
    )
    args = parser.parse_args(sys.argv[1:])

    mddir = "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal"
    default_ignores = {".DS_Store", "private", ".obsidian"}
    parse(mddir, args.recent, ignore=default_ignores)
