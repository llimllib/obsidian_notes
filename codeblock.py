from markdown import Extension
from markdown.postprocessors import Postprocessor
import re


class CodeInlineClass(Postprocessor):
    """Wrap entire output in <pre> tags as a diagnostic."""

    def run(self, text):
        # this is slow, but I mean are you really in a rush? What's so
        # important?
        return re.sub(r"<code>(.*?)</code>", r'<code class="oneline">\1</code>', text)


class InlineCodeClassExtension(Extension):
    def __init__(self):
        pass

    def extendMarkdown(self, md):
        md.postprocessors.register(CodeInlineClass(self), "inlineclass", 25)
