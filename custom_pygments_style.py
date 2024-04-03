"""
    pygments.styles.default
    ~~~~~~~~~~~~~~~~~~~~~~~

    The default highlighting style.

    :copyright: Copyright 2006-2024 by the Pygments team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

from pygments.style import Style
from pygments.token import (
    Keyword,
    Name,
    Comment,
    String,
    Error,
    Number,
    Operator,
    Generic,
    Whitespace,
)


class LlimllibStyle(Style):
    """
    llimllib's custom style
    """

    name = "default"

    background_color = "#f8f8f8"

    styles = {
        Whitespace: "#bbbbbb",
        Comment: "italic #3D7B7B",
        Comment.Preproc: "noitalic #9C6500",
        Keyword: "bold #C500CC",
        Keyword.Pseudo: "nobold",
        Keyword.Type: "nobold #B00040",
        Operator: "#666666",
        Operator.Word: "bold #AA22FF",
        Name.Builtin: "#007093",
        Name.Function: "#4D44BB",
        Name.Class: "bold #4D44BB",
        Name.Namespace: "bold #4D44BB",
        Name.Exception: "bold #CB3F38",
        Name.Variable: "#19177C",
        Name.Constant: "#880000",
        Name.Label: "#767600",
        Name.Entity: "bold #717171",
        Name.Attribute: "#687822",
        Name.Tag: "bold #C500CC",
        Name.Decorator: "#AA22FF",
        String: "#4D44BB",
        String.Doc: "italic",
        String.Interpol: "bold #A45A77",
        String.Escape: "bold #AA5D1F",
        String.Regex: "#A45A77",
        # String.Symbol:             "#B8860B",
        String.Symbol: "#19177C",
        String.Other: "#C500CC",
        Number: "#666666",
        Generic.Heading: "bold #000080",
        Generic.Subheading: "bold #800080",
        Generic.Deleted: "#A00000",
        Generic.Inserted: "#008400",
        Generic.Error: "#E40000",
        Generic.Emph: "italic",
        Generic.Strong: "bold",
        Generic.EmphStrong: "bold italic",
        Generic.Prompt: "bold #000080",
        Generic.Output: "#717171",
        Generic.Traceback: "#04D",
        Error: "border:#FF0000",
    }
