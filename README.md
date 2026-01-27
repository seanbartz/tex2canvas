```bash
./tex2canvas.py "Homework 1.tex"
```

Convert LaTeX homework files to HTML with Canvas-friendly equation images.

Usage
- Single file: `./tex2canvas.py "Homework 1.tex"`
- Multiple files: `./tex2canvas.py "Mac HW/Homework 1.tex" "Mac HW/Homework 2.tex"`
- Output directory: `./tex2canvas.py "Homework 1.tex" -o ./html`

Image alt text
- Use `\includegraphics[alt={...}]{file}` (or `alttext=...`) to set alt text.
- Or add a line comment like `% alt: A bead on a hoop diagram` before the image.
- If none is found, it falls back to `Image: <filename>`.

Note
- Canvas doesn’t honor MathJax from pasted HTML, so this script emits Canvas equation images.
- For images included in LaTeX, upload the image in Canvas and replace the `src` there.
