# Agent Preferences for `tex2canvas`

## Purpose
Keep this repo focused on converting LaTeX homework to Canvas-ready HTML and publishing assignments to Canvas with safe defaults.

## Canvas Secrets
- Store Canvas secrets only in `/Users/seanbartz/tex2canvas/.canvas_config.json`.
- Never commit real tokens or private course URLs.
- Keep a sanitized template in `canvas_config.example.json`.

## Publishing Defaults
- Use `publish_canvas_assignment.py` for Canvas assignment creation/updates.
- If `--due-at` is not provided, prompt for a due date interactively.
- Accept natural-language due dates (example: `next Friday`).
- When date is provided without a time, default to `11:59 PM` in local time.
- Default submission type is `on_paper` unless explicitly overridden.

## Duplicate Assignment Handling
- When creating without `--assignment-id`, check for existing assignments with the same title.
- If a matching title exists, update it instead of creating a duplicate.
- If due date is supplied, prefer a title match with the same due date/time.

## CLI Usage Expectations
- If an HTML filename is given without a path, treat it as relative to the current working directory.
- Provide clear, non-traceback style errors for common user mistakes when possible (missing files, missing config fields).

## Workflow
- Prefer `--dry-run` first when changing publish behavior.
- Commit and push only when explicitly requested.
