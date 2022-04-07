from typing import List, Optional, Tuple, Dict, Any
import os
from pathlib import Path
import re
import subprocess
from time import strftime, localtime, struct_time

from jinja2 import Template
import markdown
from markdown.extensions.wikilinks import WikiLinkExtension


def split_front_matter(buf: str) -> Tuple[str, str]:
    parts = re.split(r"^\s*---(.*?)\n---\n", buf, 1, re.S)
    if len(parts) == 1:
        return ("", parts[0])
    else:
        return (parts[1], parts[2])


def outname(fname: str) -> str:
    """Turn a markdown filename into an html file name"""
    fname = re.sub(r"[^\w\-\._~]", "_", fname)
    return re.sub(r"\.md$", ".html", fname)


def pathname(dname: str) -> str:
    """Sanitize a name"""
    return re.sub(r"[^\w\-\._~\\\/]", "_", dname)


def mkdir(dir_: str) -> str:
    """Recursively make dir_ if it does not exist"""
    if not os.path.isdir(dir_):
        os.makedirs(dir_, exist_ok=True)
    return dir_


def mtime(f: str) -> struct_time:
    """Return a string representing the mtime of the file"""
    return localtime(os.stat(f).st_mtime)


def formatted_time(t: struct_time) -> str:
    return strftime("%b %d, %Y", t)


pageT = Template(open("templates/page.html").read())


def render_page(**kwargs) -> str:
    """Render the page template"""
    return pageT.render(**kwargs)


indexT = Template(open("templates/index.html").read())


def render_index(**kwargs) -> str:
    return indexT.render(**kwargs)


def generate_stylesheet(style: str = "default") -> None:
    """Use pygments to generate a stylesheet"""
    subprocess.call(
        f"pygmentize -S {style} -f html -a .codehilite > output/pygments.css",
        shell=True,
    )


def strip_fancy_name(link: str) -> str:
    """Return the part of a link before the pipe, if present"""
    if "|" in link:
        return link.split("|")[0]
    return link


def findlinks(md: str) -> List[str]:
    """Find all links in a markdown document"""
    # XXX: right now this grabs some "links" from code blocks; i.e. pandas lets
    #      you do stuff like df[["columnA", "columnB"]]. Fix the regex so it
    #      doesn't match that
    return list(map(strip_fancy_name, re.findall(r"\[\[(.*?)\]\]", md)))


def canonicalize(title: str) -> str:
    """return the canonical form of a title"""
    return title.lower()


# TODO: type the page object... for now I'm just calling it "Any"
def find(pages: Dict[str, Any], link: str) -> Optional[Dict[str, Any]]:
    """find a page referred to by `link`

    Pages can be linked in two ways:
        - By their title
            - Titles may not be unique and this function will just return the
              first result in our random search if there are multiple pages
              with the same title
        - By their path+title
    """
    link = canonicalize(link)
    for relpath, page in pages.items():
        if page["canon_title"] == link or relpath == link:
            return page


def split_files(files: List[str]) -> Tuple[List[str], List[str]]:
    """Split a file list into markdown and non-markdown files"""
    return (
        [f for f in files if f.endswith(".md")],
        [f for f in files if not f.endswith(".md")],
    )


def parse(mddir: str, ignore: Optional[List[str]] = None):
    # make the type checker happy
    ignore = ignore if ignore else []
    mddir = os.path.normpath(os.path.expanduser(mddir))

    pages = {}
    for root, dirs, files in os.walk(mddir):
        for dir_ in dirs:
            if dir_ in ignore:
                dirs.remove(dir_)

        markdown_files, attachments = split_files(files)
        for file in markdown_files:
            fullpath = os.path.join(root, file)
            title = os.path.splitext(file)[0]
            with open(fullpath) as f:
                buf = f.read()
                # TODO: do something with the front matter - rn none of my
                # files actually have any
                # https://help.obsidian.md/Advanced+topics/YAML+front+matter
                _, source = split_front_matter(buf)
                links = findlinks(source)
                relpath = pathname(root.removeprefix(mddir).lstrip("/"))
                titlepath = os.path.join(relpath, canonicalize(title))
                mt = mtime(fullpath)
                pages[titlepath] = {
                    # `title` contains the title, cased as the author cased it
                    "title": title,
                    # `canon_title` contains the canonicalized title
                    "canon_title": canonicalize(title),
                    "links": links,
                    "fullpath": fullpath,
                    "link_path": os.path.join(relpath, outname(file)),
                    "file": file,
                    "relpath": relpath,
                    "titlepath": titlepath,
                    "source": source,
                    "backlinks": [],
                    "mtime": mt,
                    "updated_date": formatted_time(mt),
                }

        for file in attachments:
            fullpath = os.path.join(root, file)
            relpath = pathname(root.removeprefix(mddir).lstrip("/"))
            pages[os.path.join(relpath, file)] = {
                "title": file,
                "canon_title": canonicalize(file),
                "fullpath": fullpath,
                "link_path": os.path.join(relpath, file),
                "file": file,
                "relpath": relpath,
                "links": [],
                "backlinks": [],
            }

    # calculate backlinks
    for page in pages.values():
        for link in page["links"]:
            linked_page = find(pages, link)
            if not linked_page:
                print(f"unable to find link {link}")
                continue
            linked_page["backlinks"].append(page)

    outdir = Path(mkdir("./output"))
    generate_stylesheet()

    # generate index page
    content_pages = list(
        sorted(
            [(k, v) for k, v in pages.items() if "source" in v],
            key=lambda x: x[0].lower(),
        )
    )
    by_mtime = list(
        reversed(sorted([v for _, v in content_pages], key=lambda x: x["mtime"]))
    )

    class Node:
        def __init__(self, dir=None, page=None):
            self.dir = dir
            self.page = page
            self.children = []

        def find(self, dir=None):
            for c in self.children:
                if c.dir == dir:
                    return c

    def insert(node, parts, page):
        if len(parts) == 1:
            leaf = Node(page=page)
            node.children.append(leaf)
            return leaf

        child = node.find(parts[0])
        if not child:
            child = Node(dir=parts[0])
            node.children.append(child)
        return insert(child, parts[1:], page)

    root = Node()
    for path, page in content_pages:
        parts = path.split("/")
        insert(root, parts, page)

    open(outdir / "index.html", "w").write(
        render_index(
            pages=[v for _, v in content_pages],
            recently_updated=by_mtime[:10],
            tree=root,
        )
    )

    # output HTML for each page
    for title, page in content_pages:
        # https://python-markdown.github.io/extensions/
        # - extra: gets us code blocks rendered properly (and lots of
        #   other stuff - do I want all of it?
        # - WikiLinkExtension - [[link]] support
        # - mdx_linkify - search for URLs in text and link them
        # - tables - markdown table support
        # - codehilite - code highlighting with pygments
        #   - to generate a stylesheet:
        #   pygmentize -S default -f html -a .codehilite > output/styles.css
        # https://python-markdown.github.io/extensions/code_hilite/#step-2-add-css-classes
        # - mdx_math for latex support
        #   - https://github.com/mitya57/python-markdown-math
        # - third party extensions:
        #   https://github.com/Python-Markdown/markdown/wiki/Third-Party-Extensions
        html = markdown.markdown(
            page["source"],
            output_format="html",
            extensions=[
                "mdx_math",
                "codehilite",
                "extra",
                WikiLinkExtension(base_url="/", end_url=".html"),
                "tables",
                "mdx_linkify",
            ],
            extension_configs={"mdx_math": {"enable_dollar_delimiter": True}},
        )

        mkdir(str(outdir / page["relpath"]))
        with open(outdir / page["link_path"], "w") as fout:
            fout.write(render_page(content=html, **page))


# TODO:
# - fix attachment links
#   - example page with no pdf: http://devd.io:8000/visualization/Franke_s_computer_graphics.html
#   - example embedded image fail: http://devd.io:8000/visualization/color_schemes.html
# - better code highlighting
#   - the first chart on this page is completely busto:
#     - http://devd.io:8000/book_notes/Understanding_Software_Dynamics/Chapter_1_-_My_program_is_too_slow.html
#   - it shouldn't highlight at all
#     - could disable language guessing? But generally I like it?
#     - maybe just add a language annotation for every block?
# - navigation pane?
#     - skipping it for now, but some sort of collapsible sidebar sounds nice?
# - better source code block formatting
#   - nicer colors (syntax and bg)
#   - proper overflow out of parent container
# - better table formatting
#   - borders
# - table of contents for big pages
#   - https://python-markdown.github.io/extensions/toc/
#   - apparently the toc extension will do anchor links... would I need a toc
#     on every page to get that though?
# - set up DNS
# - sync to CDN
# - add command line arguments for mddir and default_ignores
# - admonitions might be nice?
#   - https://python-markdown.github.io/extensions/admonition/
# - RSS feed
if __name__ == "__main__":
    mddir = "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal"
    default_ignores = [".DS_Store", "private"]
    parse(mddir, ignore=default_ignores)
