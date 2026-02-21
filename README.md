```bash
./tex2canvas.py "Homework 1.tex"
```

Convert LaTeX homework files to HTML with Canvas-friendly equation images.

Usage
- Single file: `./tex2canvas.py "Homework 1.tex"`
- Multiple files: `./tex2canvas.py "Mac HW/Homework 1.tex" "Mac HW/Homework 2.tex"`
- Output directory: `./tex2canvas.py "Homework 1.tex" -o ./html`

Supported LaTeX environments/commands
- Math: `$$...$$`, `\[...\]`, and inline `$...$`
- `eqnarray` (converted to separate display equations)
- `enumerate`
- `itemize`
- `minipage` (container removed; contents kept)
- Nested `itemize`/`enumerate` lists
- `\section{}`, `\subsection{}`, `\subsubsection{}`
- `\includegraphics[...]{}`
- `\maketitle`

Other environments and LaTeX commands may not work or may be left as-is.

Image alt text
- Use `\includegraphics[alt={...}]{file}` (or `alttext=...`) to set alt text.
- Or add a line comment like `% alt: A bead on a hoop diagram` before the image.
- If none is found, it falls back to `Image: <filename>`.

Note
- Canvas doesn’t honor MathJax from pasted HTML, so this script emits Canvas equation images.
- For images included in LaTeX, upload the image in Canvas and replace the `src` there.

## Publish assignments to Canvas

Use `publish_canvas_assignment.py` to create (or update) and publish assignments via the Canvas API.

1. Create a private config file (never committed):
   - `cp canvas_config.example.json .canvas_config.json`
   - edit `.canvas_config.json` with your real `access_token` and `course_url`
2. Create and publish a new assignment from an HTML file:
   - `python3 publish_canvas_assignment.py --title "Homework 4" --html-file "Homework 4.html" --points 20`
3. Publish an existing assignment by ID:
   - `python3 publish_canvas_assignment.py --assignment-id 12345`
4. Preview request payload without calling Canvas:
   - `python3 publish_canvas_assignment.py --title "Homework 4" --html-file "Homework 4.html" --dry-run`
5. Due date input:
   - If `--due-at` is omitted, the script prompts for one interactively.
   - Natural language is accepted (for example, `next Friday`), and date-only input defaults to `11:59 PM` local time.
   - You can also pass natural language directly: `--due-at "next Friday"`.
6. Submission type:
   - Default is `on_paper`.
   - Override with `--submission-type` (for example, `online_upload`, `online_text_entry`, `online_url`, `media_recording`).

The private `.canvas_config.json` file is git-ignored in this repo.
