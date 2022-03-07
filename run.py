from typing import List, Optional, Tuple
import os
from pathlib import Path
import re
import subprocess
from time import strftime, localtime

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
    fname = re.sub(r"[^\w\-\._~]", "_", fname)
    return re.sub(r"\.md$", ".html", fname)


def pathname(dname: str) -> str:
    return re.sub(r"[^\w\-\._~\\\/]", "_", dname)


def mkdir(dir_: str) -> str:
    if not os.path.isdir(dir_):
        os.makedirs(dir_, exist_ok=True)
    return dir_


def mtime(f: str) -> str:
    t = localtime(os.stat(f).st_mtime)
    return strftime("%b %d, %Y", t)


T = Template(open("template.html").read())


def template(**kwargs) -> str:
    return T.render(**kwargs)


def generate_stylesheet() -> None:
    subprocess.call(
        "pygmentize -S default -f html -a .codehilite > output/pygments.css",
        shell=True,
    )


def strip_fancy_name(link: str) -> str:
    if "|" in link:
        return link.split("|")[0]
    return link


def findlinks(md: str) -> List[str]:
    # XXX: right now this grabs some "links" from code blocks; i.e. pandas lets
    #      you do stuff like df[["columnA", "columnB"]]. Fix the regex so it
    #      doesn't match that
    return list(map(strip_fancy_name, re.findall(r"\[\[(.*?)\]\]", md)))


def canonicalize(title: str) -> str:
    """return the canonical form of a title"""
    return title.lower()


def parse(mddir: str, ignore: Optional[List[str]] = None):
    # make the type checker happy
    ignore = ignore if ignore else []
    mddir = os.path.normpath(os.path.expanduser(mddir))

    pages = {}
    for root, dirs, files in os.walk(mddir):
        for dir_ in dirs:
            if dir_ in ignore:
                dirs.remove(dir_)

        for file in [f for f in files if f.endswith(".md")]:
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
                pages[canonicalize(title)] = {
                    "title": title,
                    "links": links,
                    "fullpath": fullpath,
                    "file": file,
                    "relpath": relpath,
                    "source": source,
                    "backlinks": [],
                }

    for canon_title, page in pages.items():
        for link in page["links"]:
            try:
                # TODO: we need a path to the backlink, not just the title;
                # otherwise we can't make a link
                pages[canonicalize(link)]["backlinks"].append(
                    {
                        "title": page["title"],
                        "relpath": os.path.join(page["relpath"], page[""]),
                    }
                )
                print(canon_title, pages[canon_title]["backlinks"])
            except KeyError:
                print(
                    f"Unable to find {canonicalize(link)} in {list(sorted(pages.keys()))}"
                )

    outdir = Path(mkdir("./output"))
    generate_stylesheet()

    for title, page in pages.items():
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
        with open(outdir / page["relpath"] / outname(page["file"]), "w") as fout:
            fout.write(
                template(
                    title=title,
                    content=html,
                    mtime=mtime(page["fullpath"]),
                    backlinks=page["backlinks"] or None,
                )
            )


# TODO:
# - backlinks
#   - i.e. typography page should show what links to it
#   - might require a two-step process; parse the files (and build a graph)
#     then build the output?
# - some sort of navigation?
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
if __name__ == "__main__":
    mddir = "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/personal"
    default_ignores = [".DS_Store", "private"]
    parse(mddir, ignore=default_ignores)
