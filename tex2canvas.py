#!/usr/bin/env python3
# Convert LaTeX homework into Canvas-ready HTML with equation images.
import argparse
import html
import hashlib
import re
import shutil
import subprocess
import tempfile
from urllib.parse import quote
from pathlib import Path


def split_unescaped_percent(line: str):
    # Split a LaTeX line into code and comment, ignoring escaped percent signs.
    match = re.search(r"(?<!\\)%", line)
    if match:
        return line[: match.start()], line[match.start() + 1 :]
    return line, None


def strip_braces(s: str) -> str:
    # Remove a single pair of surrounding braces if present.
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s[1:-1].strip()
    return s


def split_options(opts: str):
    # Split LaTeX option lists like "width=..., alt={...}" safely on commas.
    parts = []
    current = []
    depth = 0
    for ch in opts:
        if ch == "{" and depth >= 0:
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def parse_alt_from_options(opts: str):
    # Read alt text from \includegraphics options if supplied.
    if not opts:
        return None
    for part in split_options(opts):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        if key in {"alt", "alttext", "description"}:
            return strip_braces(val.strip())
    return None


def resolve_image_path(image_path: str, tex_dir: Path) -> str:
    # If no extension is provided, try common image extensions on disk.
    path = Path(image_path)
    if path.suffix:
        return image_path
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg"):
        candidate = tex_dir / f"{image_path}{ext}"
        if candidate.exists():
            return f"{image_path}{ext}"
    return image_path


def extract_title_author(text: str):
    # Pull title/author from the preamble for HTML heading output.
    title = None
    author = None
    m = re.search(r"\\title\{(.+?)\}", text, re.DOTALL)
    if m:
        title = m.group(1).strip()
    m = re.search(r"\\author\{(.+?)\}", text, re.DOTALL)
    if m:
        author = m.group(1).strip()
    return title, author


def extract_body(text: str):
    # Extract content inside \begin{document}...\end{document}.
    m = re.search(r"\\begin\{document\}", text)
    n = re.search(r"\\end\{document\}", text)
    if not m or not n:
        return text
    return text[m.end() : n.start()]


def extract_preamble(text: str):
    # Extract content before \begin{document} for rebuilding standalone TikZ files.
    m = re.search(r"\\begin\{document\}", text)
    if not m:
        return text
    return text[: m.start()]


def build_tikz_standalone_doc(tikz_code: str, preamble: str) -> str:
    # Build a minimal standalone document that keeps package/library config.
    preserved = []
    for line in preamble.splitlines():
        stripped = line.strip()
        if not stripped:
            preserved.append(line)
            continue
        if stripped.startswith(r"\documentclass"):
            continue
        if stripped.startswith(r"\begin{document}") or stripped.startswith(r"\end{document}"):
            continue
        if stripped.startswith(r"\title") or stripped.startswith(r"\author") or stripped.startswith(r"\date"):
            continue
        preserved.append(line)

    parts = [r"\documentclass[tikz,border=4pt]{standalone}"]
    if preserved:
        parts.extend(preserved)
    parts.extend([r"\begin{document}", tikz_code, r"\end{document}", ""])
    return "\n".join(parts)


def render_tikz_to_png(tikz_code: str, preamble: str, out_dir: Path, basename: str):
    # Render a tikzpicture into a PNG and return its filename, or None on failure.
    if shutil.which("pdflatex") is None:
        return None

    digest = hashlib.sha1(tikz_code.encode("utf-8")).hexdigest()[:10]
    png_name = f"{basename}_{digest}.png"
    png_path = out_dir / png_name
    if png_path.exists():
        return png_name

    with tempfile.TemporaryDirectory(prefix="tex2canvas_tikz_", dir=str(out_dir)) as tmp:
        tmp_dir = Path(tmp)
        tex_file = tmp_dir / "tikz_figure.tex"
        pdf_file = tmp_dir / "tikz_figure.pdf"
        png_file = tmp_dir / "tikz_figure.png"
        tex_file.write_text(build_tikz_standalone_doc(tikz_code, preamble), encoding="utf-8")

        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_file.name],
                cwd=tmp_dir,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None

        if shutil.which("pdftocairo"):
            try:
                subprocess.run(
                    [
                        "pdftocairo",
                        "-png",
                        "-singlefile",
                        "-transp",
                        str(pdf_file),
                        str(tmp_dir / "tikz_figure"),
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except subprocess.CalledProcessError:
                return None
        elif shutil.which("magick"):
            try:
                subprocess.run(
                    [
                        "magick",
                        "-density",
                        "300",
                        f"{pdf_file}[0]",
                        "-background",
                        "none",
                        str(png_file),
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except subprocess.CalledProcessError:
                return None
        else:
            return None

        if not png_file.exists():
            return None
        png_file.replace(png_path)
    return png_name


def canvas_equation_img(latex: str) -> str:
    # Canvas expects equation images rather than MathJax scripts.
    encoded = quote(latex, safe="")
    escaped = html.escape(latex, quote=True)
    return (
        f'<img class="equation_image" title="{escaped}" '
        f'src="/equation_images/{encoded}?scale=1" '
        f'alt="LaTeX: {escaped}" data-equation-content="{escaped}" '
        f'data-ignore-a11y-check="" />'
    )


def convert_math_to_canvas(text: str) -> str:
    # Convert display and inline math delimiters into Canvas equation images.
    def display_repl(match):
        latex = match.group(1).strip()
        return f"<p>{canvas_equation_img(latex)}</p>"

    text = re.sub(r"\$\$(.+?)\$\$", display_repl, text, flags=re.DOTALL)
    text = re.sub(r"\\\[(.+?)\\\]", display_repl, text, flags=re.DOTALL)

    def inline_repl(match):
        latex = match.group(1).strip()
        return canvas_equation_img(latex)

    text = re.sub(
        r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$(?!\$)", inline_repl, text, flags=re.DOTALL
    )
    return text


def convert_tex_to_html(tex_path: Path, out_dir: Path) -> str:
    raw = tex_path.read_text(encoding="utf-8")
    title, author = extract_title_author(raw)
    body = extract_body(raw)
    preamble = extract_preamble(raw)
    lines = body.splitlines()

    output_lines = []
    pending_alt = None
    subsec_counter = 0
    list_stack = []
    open_li_stack = []
    tikz_counter = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        code, comment = split_unescaped_percent(line)
        if comment:
            # Allow alt text to be supplied in a preceding comment line.
            alt_match = re.search(r"\balt\s*:\s*(.+)", comment, re.IGNORECASE)
            if alt_match:
                pending_alt = alt_match.group(1).strip()
        line = code.rstrip()

        if r"\begin{tikzpicture}" in line:
            # Render TikZ blocks to PNG so Canvas can display them as regular images.
            tikz_lines = []
            if r"\end{tikzpicture}" in line:
                start = line.find(r"\begin{tikzpicture}")
                end = line.find(r"\end{tikzpicture}") + len(r"\end{tikzpicture}")
                tikz_lines.append(line[start:end])
            else:
                start = line.find(r"\begin{tikzpicture}")
                tikz_lines.append(line[start:])
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    code2, comment2 = split_unescaped_percent(next_line)
                    if comment2:
                        alt_match = re.search(r"\balt\s*:\s*(.+)", comment2, re.IGNORECASE)
                        if alt_match:
                            pending_alt = alt_match.group(1).strip()
                    tikz_lines.append(code2.rstrip())
                    if r"\end{tikzpicture}" in code2:
                        break
                    i += 1

            tikz_code = "\n".join(tikz_lines).strip()
            tikz_counter += 1
            alt = pending_alt or f"TikZ figure {tikz_counter}"
            png_name = render_tikz_to_png(
                tikz_code,
                preamble,
                out_dir,
                f"{tex_path.stem}_tikz_{tikz_counter}",
            )

            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            if png_name:
                escaped_alt = html.escape(alt, quote=True)
                output_lines.append(f'<img src="{png_name}" alt="{escaped_alt}">')
            else:
                output_lines.append(tikz_code)
            output_lines.append("")
            pending_alt = None
            i += 1
            continue

        if r"\begin{eqnarray}" in line:
            # Convert eqnarray into separate display equations for Canvas.
            inner = []
            # Capture any content after \begin{eqnarray} on the same line.
            after_begin = line.split(r"\begin{eqnarray}", 1)[1].strip()
            if after_begin:
                inner.append(after_begin)
            i += 1
            while i < len(lines):
                next_line = lines[i]
                code2, comment2 = split_unescaped_percent(next_line)
                if comment2:
                    alt_match = re.search(r"\balt\s*:\s*(.+)", comment2, re.IGNORECASE)
                    if alt_match:
                        pending_alt = alt_match.group(1).strip()
                if r"\end{eqnarray}" in code2:
                    before_end = code2.split(r"\end{eqnarray}", 1)[0].strip()
                    if before_end:
                        inner.append(before_end)
                    break
                inner.append(code2.rstrip())
                i += 1

            inner = [l for l in (l.strip() for l in inner) if l]
            math_lines = []
            for idx, l in enumerate(inner):
                l = l.rstrip()
                if l.endswith(r"\\"):
                    l = l[:-2].rstrip()
                # Remove alignment markers from eqnarray lines.
                l = l.replace("&", "")
                if l:
                    math_lines.append(l)

            block = "\n".join(f"$$\n{l}\n$$" for l in math_lines)
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            output_lines.append(block)
            output_lines.append("")
            pending_alt = None
            i += 1
            continue

        env_match = re.search(r"\\begin\{(equation\*?|cases|array)\}", line)
        if env_match:
            env = env_match.group(1)
            inner = []
            after_begin = line.split(f"\\begin{{{env}}}", 1)[1].strip()
            if after_begin:
                inner.append(after_begin)
            i += 1
            while i < len(lines):
                next_line = lines[i]
                code2, comment2 = split_unescaped_percent(next_line)
                if comment2:
                    alt_match = re.search(r"\balt\s*:\s*(.+)", comment2, re.IGNORECASE)
                    if alt_match:
                        pending_alt = alt_match.group(1).strip()
                end_token = f"\\end{{{env}}}"
                if end_token in code2:
                    before_end = code2.split(end_token, 1)[0].strip()
                    if before_end:
                        inner.append(before_end)
                    break
                inner.append(code2.rstrip())
                i += 1

            inner = [l for l in (l.strip() for l in inner) if l]
            if env in {"cases", "array"}:
                latex = "\n".join(inner)
                block = "$$\n" + f"\\begin{{{env}}}\n{latex}\n\\end{{{env}}}\n" + "$$"
            else:
                latex = "\n".join(inner)
                block = "$$\n" + latex + "\n$$"
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            output_lines.append(block)
            output_lines.append("")
            pending_alt = None
            i += 1
            continue

        if not line:
            if not list_stack:
                output_lines.append("")
            i += 1
            continue

        if re.search(r"\\section\{", line):
            subsec_counter = 0

        begin_list = re.match(
            r"^\s*\\begin\{(itemize|enumerate)\}(?:\[[^\]]*\])?\s*$", line
        )
        if begin_list:
            tag = "ul" if begin_list.group(1) == "itemize" else "ol"
            output_lines.append(f"<{tag}>")
            list_stack.append(tag)
            open_li_stack.append(False)
            i += 1
            continue

        end_list = re.match(r"^\s*\\end\{(itemize|enumerate)\}\s*$", line)
        if end_list and list_stack:
            if open_li_stack[-1]:
                output_lines.append("</li>")
                open_li_stack[-1] = False
            output_lines.append(f"</{list_stack.pop()}>")
            open_li_stack.pop()
            i += 1
            continue

        if re.match(r"^\s*\\item\b", line) and list_stack:
            item_text = re.sub(r"^\s*\\item\b\s*", "", line).strip()
            if open_li_stack[-1]:
                output_lines.append("</li>")
            if item_text:
                item_text = re.sub(r"\\emph\{(.*?)\}", r"<em>\1</em>", item_text)
                item_text = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", item_text)
                item_text = re.sub(r"\{\\bf\s+(.*?)\}", r"<strong>\1</strong>", item_text)
                if "\\includegraphics" in item_text:
                    def repl(m):
                        opts = m.group(1)
                        path = m.group(2).strip()
                        alt = parse_alt_from_options(opts) or pending_alt
                        resolved = resolve_image_path(path, tex_path.parent)
                        if not alt:
                            alt = f"Image: {Path(resolved).stem}"
                        return f'<img src="{resolved}" alt="{alt}">' 
                    item_text = re.sub(r"\\includegraphics(?:\[(.*?)\])?\{(.*?)\}", repl, item_text)
                    pending_alt = None
                output_lines.append(f"<li>{item_text}")
            else:
                output_lines.append("<li>")
            open_li_stack[-1] = True
            i += 1
            continue

        line = re.sub(r"\\section\*?\{(.*?)\}", r"<h3>\1</h3>", line)

        def replace_subsection(match):
            nonlocal subsec_counter
            content = match.group(1).strip()
            if not content:
                subsec_counter += 1
                return f"<h4>Part {subsec_counter}</h4>"
            return f"<h4>{content}</h4>"

        line = re.sub(r"\\subsection\*?\{(.*?)\}", replace_subsection, line)
        line = re.sub(r"\\subsubsection\*?\{(.*?)\}", r"<h5>\1</h5>", line)
        line = re.sub(r"\\emph\{(.*?)\}", r"<em>\1</em>", line)
        line = re.sub(r"\\textbf\{(.*?)\}", r"<strong>\1</strong>", line)
        line = re.sub(r"\{\\bf\s+(.*?)\}", r"<strong>\1</strong>", line)
        line = re.sub(r"\\begin\{enumerate\}(?:\[[^\]]*\])?", r"<ol>", line)
        line = re.sub(r"\\end\{enumerate\}", r"</ol>", line)
        line = re.sub(r"\\begin\{itemize\}(?:\[[^\]]*\])?", r"<ul>", line)
        line = re.sub(r"\\end\{itemize\}", r"</ul>", line)
        if re.match(r"^\s*\\item\b", line):
            item_text = re.sub(r"^\s*\\item\b\s*", "", line).strip()
            line = f"<li>{item_text}</li>"

        if "\\includegraphics" in line:
            def repl(m):
                # Map \includegraphics to <img> with any supplied alt text.
                opts = m.group(1)
                path = m.group(2).strip()
                alt = parse_alt_from_options(opts) or pending_alt
                resolved = resolve_image_path(path, tex_path.parent)
                if not alt:
                    alt = f"Image: {Path(resolved).stem}"
                return f'<img src="{resolved}" alt="{alt}">' 

            line = re.sub(r"\\includegraphics(?:\[(.*?)\])?\{(.*?)\}", repl, line)
            pending_alt = None

        if re.search(r"\\begin\{minipage\}", line) or re.search(r"\\end\{minipage\}", line):
            # Drop minipage container commands (layout-only).
            line = ""

        if line == "\\maketitle":
            line = ""

        output_lines.append(line)
        i += 1

    while list_stack:
        if open_li_stack[-1]:
            output_lines.append("</li>")
        output_lines.append(f"</{list_stack.pop()}>")
        open_li_stack.pop()

    blocks = []
    current = []
    for line in output_lines:
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    rendered = []

    if title:
        # Title/author block if provided.
        rendered.append(f"<h2>{title}</h2>")
        if author:
            rendered.append(f"<p><em>{author}</em></p>")

    for block in blocks:
        # Convert math delimiters to Canvas equation images.
        block = convert_math_to_canvas(block)
        stripped = block.strip()
        if not stripped:
            continue
        is_block = stripped.startswith("<h") or stripped.startswith("<img") or stripped.startswith("<blockquote")
        is_block = is_block or stripped.startswith("<ul") or stripped.startswith("<ol") or stripped.startswith("<div")
        is_block = is_block or stripped.startswith("<li") or stripped.startswith("</ol") or stripped.startswith("</ul")
        is_block = is_block or stripped.startswith("<p><img class=\"equation_image\"")
        if is_block:
            rendered.append(stripped)
            continue
        block = block.replace("\\\\", "<br>")
        rendered.append(f"<p>{block}</p>")

    html_doc = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\(', '\\)']],
        displayMath: [['$$', '$$'], ['\\[', '\\]']],
        processEscapes: true
      }}
    }};
  </script>
  <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
  <style>
    body {{
      font-family: "Georgia", "Times New Roman", serif;
      max-width: 900px;
      margin: 24px auto;
      padding: 0 16px;
      line-height: 1.5;
    }}
    img {{ max-width: 100%; height: auto; }}
    h2, h3, h4, h5 {{ margin-top: 1.2em; }}
  </style>
</head>
<body>
{body}
</body>
</html>
""".format(title=title or tex_path.stem, body="\n".join(rendered))

    return html_doc


def main():
    parser = argparse.ArgumentParser(description="Convert LaTeX homework to Canvas HTML (including TikZ image rendering).")
    parser.add_argument("inputs", nargs="+", help="TeX file(s) to convert")
    parser.add_argument("-o", "--out-dir", default=None, help="Output directory (default: alongside input)")
    args = parser.parse_args()

    for input_path in args.inputs:
        tex_path = Path(input_path)
        if not tex_path.exists():
            raise SystemExit(f"File not found: {tex_path}")
        out_dir = Path(args.out_dir) if args.out_dir else tex_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        html = convert_tex_to_html(tex_path, out_dir)
        out_path = out_dir / f"{tex_path.stem}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
