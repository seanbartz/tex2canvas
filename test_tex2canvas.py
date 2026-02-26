"""Tests for tex2canvas.py"""
import tempfile
import textwrap
from pathlib import Path

import pytest

from tex2canvas import convert_tex_to_html, convert_math_to_canvas, canvas_equation_img


def _html_from_tex(tex: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "test.tex"
        p.write_text(textwrap.dedent(tex).strip())
        return convert_tex_to_html(p, Path(tmpdir))


# ---------------------------------------------------------------------------
# align environment
# ---------------------------------------------------------------------------

def test_align_produces_equation_image():
    html = _html_from_tex(r"""
        \documentclass{article}
        \begin{document}
        \begin{align}
          x &= 1 \\
          y &= 2
        \end{align}
        \end{document}
    """)
    assert "equation_image" in html
    assert r"\begin{align}" in html
    assert r"\end{align}" in html


def test_align_star_produces_equation_image():
    html = _html_from_tex(r"""
        \documentclass{article}
        \begin{document}
        \begin{align*}
          a &= b + c \\
          d &= e
        \end{align*}
        \end{document}
    """)
    assert "equation_image" in html
    assert r"\begin{align*}" in html
    assert r"\end{align*}" in html


def test_align_content_is_preserved():
    html = _html_from_tex(r"""
        \documentclass{article}
        \begin{document}
        \begin{align}
          f(x) &= x^2 + 1
        \end{align}
        \end{document}
    """)
    # The inner content should appear (URL-encoded) in the src attribute
    assert "f(x)" in html or "%66%28%78%29" in html.lower() or "f%28x%29" in html


def test_align_surrounded_by_text():
    html = _html_from_tex(r"""
        \documentclass{article}
        \begin{document}
        Before text.
        \begin{align}
          x &= 1
        \end{align}
        After text.
        \end{document}
    """)
    assert "Before text" in html
    assert "After text" in html
    assert "equation_image" in html


def test_align_star_multiline():
    html = _html_from_tex(r"""
        \documentclass{article}
        \begin{document}
        \begin{align*}
          \alpha &= \beta \\
          \gamma &= \delta + \epsilon
        \end{align*}
        \end{document}
    """)
    assert "equation_image" in html
    assert r"\begin{align*}" in html
    assert r"\end{align*}" in html
