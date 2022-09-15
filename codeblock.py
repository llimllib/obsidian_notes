from markdown import Extension
from markdown.postprocessors import Postprocessor
import re


CODE_RE = re.compile(r"<code>(.*?)</code>")

class CodeInlineClass(Postprocessor):
    """Wrap entire output in <pre> tags as a diagnostic."""

    def run(self, text):
        # this is slow, but I mean are you really in a rush? What's so
        # important?
        return CODE_RE.sub(r'<code class="oneline">\1</code>', text)


class InlineCodeClassExtension(Extension):
    def __init__(self):
        pass

    def extendMarkdown(self, md):
        md.postprocessors.register(CodeInlineClass(self), "inlineclass", 25)
