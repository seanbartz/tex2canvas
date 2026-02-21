#!/usr/bin/env python3
"""Create or update-and-publish Canvas assignments using a local secrets file."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    from dateutil import parser as date_parser
except ImportError:  # pragma: no cover
    date_parser = None

WEEKDAY_ALIASES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

SUBMISSION_TYPES = (
    "on_paper",
    "none",
    "online_text_entry",
    "online_url",
    "online_upload",
    "media_recording",
    "student_annotation",
    "external_tool",
)


def load_config(config_path: Path):
    if not config_path.exists():
        raise SystemExit(
            f"Config file not found: {config_path}\n"
            "Create it from canvas_config.example.json and keep it private."
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in config file {config_path}: {exc}") from exc

    token = str(data.get("access_token", "")).strip()
    course_url = str(data.get("course_url", "")).strip()
    if not token:
        raise SystemExit(f"Missing 'access_token' in {config_path}")
    if not course_url:
        raise SystemExit(f"Missing 'course_url' in {config_path}")
    return token, course_url


def parse_canvas_course(course_url: str):
    parsed = urllib.parse.urlparse(course_url)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit(
            "course_url must be a full URL, e.g. https://school.instructure.com/courses/12345"
        )

    m = re.search(r"/(?:api/v1/)?courses/(\d+)", parsed.path)
    if not m:
        raise SystemExit(
            "Could not find course id in course_url. Expected .../courses/<id>."
        )

    course_id = m.group(1)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    api_base = f"{base_url}/api/v1"
    return api_base, course_id


def extract_body_if_full_html(text: str):
    m = re.search(r"<body[^>]*>(.*?)</body>", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def load_description(args):
    if args.description and args.html_file:
        raise SystemExit("Use either --description or --html-file, not both.")
    if args.description:
        return args.description
    if args.html_file:
        html_path = Path(args.html_file)
        if not html_path.exists():
            raise SystemExit(f"HTML file not found: {html_path}")
        html_text = html_path.read_text(encoding="utf-8")
        return extract_body_if_full_html(html_text)
    return ""


def parse_time_part(time_text: str, default_dt: datetime):
    cleaned = time_text.strip().lower()
    if cleaned == "noon":
        return 12, 0
    if cleaned == "midnight":
        return 0, 0

    if date_parser:
        parsed = date_parser.parse(cleaned, fuzzy=True, default=default_dt)
        return parsed.hour, parsed.minute

    for fmt in ("%H:%M", "%H%M", "%I:%M%p", "%I%p"):
        try:
            parsed = datetime.strptime(cleaned.replace(" ", ""), fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    raise ValueError(f"Could not parse time '{time_text}'")


def localize_datetime(dt: datetime, local_tz):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=local_tz)
    return dt.astimezone(local_tz)


def parse_due_date_natural(user_text: str, now: datetime):
    text = user_text.strip()
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if normalized in {"none", "no", "skip", "n/a"}:
        return None

    local_now = now.astimezone()
    local_tz = local_now.tzinfo
    default_dt = local_now.replace(hour=23, minute=59, second=0, microsecond=0)

    m = re.match(r"^(today|tomorrow)(?:\s+at\s+(.+))?$", normalized)
    if m:
        day_word = m.group(1)
        time_part = m.group(2)
        target_date = local_now.date()
        if day_word == "tomorrow":
            target_date += timedelta(days=1)
        hour, minute = 23, 59
        if time_part:
            hour, minute = parse_time_part(time_part, default_dt)
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            0,
            tzinfo=local_tz,
        )

    weekday_words = "|".join(sorted(WEEKDAY_ALIASES.keys(), key=len, reverse=True))
    m = re.match(
        rf"^(?:(next|this)\s+)?({weekday_words})(?:\s+at\s+(.+))?$", normalized
    )
    if m:
        qualifier = m.group(1)
        weekday_word = m.group(2)
        time_part = m.group(3)
        target_weekday = WEEKDAY_ALIASES[weekday_word]
        days_ahead = (target_weekday - local_now.weekday()) % 7
        if qualifier == "next" and days_ahead == 0:
            days_ahead = 7
        target_date = local_now.date() + timedelta(days=days_ahead)
        hour, minute = 23, 59
        if time_part:
            hour, minute = parse_time_part(time_part, default_dt)
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            0,
            tzinfo=local_tz,
        )

    if date_parser:
        try:
            parsed = date_parser.parse(text, fuzzy=True, default=default_dt)
            return localize_datetime(parsed, local_tz).replace(second=0, microsecond=0)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Could not parse due date '{user_text}'") from exc

    try:
        parsed = datetime.fromisoformat(text)
        return localize_datetime(parsed, local_tz).replace(second=0, microsecond=0)
    except ValueError as exc:
        raise ValueError(f"Could not parse due date '{user_text}'") from exc


def resolve_due_at_arg(args):
    if args.due_at:
        parsed = parse_due_date_natural(args.due_at, datetime.now().astimezone())
        args.due_at = parsed.isoformat(timespec="seconds") if parsed else None
        return

    if not sys.stdin.isatty():
        return

    while True:
        raw = input(
            "Due date (e.g., next Friday; default time 11:59 PM; blank for none): "
        ).strip()
        if not raw:
            return
        try:
            parsed = parse_due_date_natural(raw, datetime.now().astimezone())
        except ValueError as exc:
            print(f"Could not parse due date: {exc}")
            continue
        if parsed is None:
            return
        args.due_at = parsed.isoformat(timespec="seconds")
        print(f"Using due date: {args.due_at}")
        return


def canvas_request(
    url: str, token: str, fields: list[tuple[str, str]], dry_run: bool, method: str
):
    encoded = urllib.parse.urlencode(fields, doseq=True).encode("utf-8")
    if dry_run:
        print(f"DRY RUN: {method} {url}")
        for k, v in fields:
            print(f"  {k}={v}")
        return {"id": None, "html_url": None, "published": True}

    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Canvas API error {err.code}: {body}") from err
    except urllib.error.URLError as err:
        raise SystemExit(f"Network error calling Canvas API: {err}") from err


def build_fields(args, description: str):
    fields = [
        ("assignment[published]", "true"),
        ("assignment[submission_types][]", args.submission_type),
    ]

    if args.title:
        fields.append(("assignment[name]", args.title))
    if description:
        fields.append(("assignment[description]", description))
    if args.points is not None:
        fields.append(("assignment[points_possible]", str(args.points)))
    if args.due_at:
        fields.append(("assignment[due_at]", args.due_at))
    if args.unlock_at:
        fields.append(("assignment[unlock_at]", args.unlock_at))
    if args.lock_at:
        fields.append(("assignment[lock_at]", args.lock_at))
    return fields


def create_assignment(api_base: str, course_id: str, token: str, args, description: str):
    if not args.title:
        raise SystemExit("--title is required when creating a new assignment.")
    url = f"{api_base}/courses/{course_id}/assignments"
    fields = build_fields(args, description)
    result = canvas_request(url, token, fields, args.dry_run, method="POST")
    print("Created and published assignment.")
    print(f"Assignment ID: {result.get('id')}")
    print(f"Published: {result.get('published')}")
    if result.get("html_url"):
        print(f"URL: {result['html_url']}")


def update_assignment(api_base: str, course_id: str, token: str, args, description: str):
    url = f"{api_base}/courses/{course_id}/assignments/{args.assignment_id}"
    fields = build_fields(args, description)
    result = canvas_request(url, token, fields, args.dry_run, method="PUT")
    print("Updated and published assignment.")
    print(f"Assignment ID: {result.get('id') or args.assignment_id}")
    print(f"Published: {result.get('published')}")
    if result.get("html_url"):
        print(f"URL: {result['html_url']}")


def main():
    parser = argparse.ArgumentParser(
        description="Create or publish Canvas assignments using a private local config file."
    )
    parser.add_argument(
        "--config",
        default=".canvas_config.json",
        help="Path to private config JSON (default: ./.canvas_config.json)",
    )
    parser.add_argument(
        "--assignment-id",
        help="If set, update this existing assignment ID instead of creating a new one.",
    )
    parser.add_argument("--title", help="Assignment title (required for create).")
    parser.add_argument("--description", help="HTML description string for Canvas.")
    parser.add_argument("--html-file", help="Path to HTML file for assignment description.")
    parser.add_argument("--points", type=float, help="Points possible (optional).")
    parser.add_argument(
        "--submission-type",
        default="on_paper",
        choices=SUBMISSION_TYPES,
        help=(
            "Canvas submission type. Defaults to 'on_paper'. "
            "Choices: " + ", ".join(SUBMISSION_TYPES)
        ),
    )
    parser.add_argument(
        "--due-at",
        help="Due date/time in ISO-8601 or natural language, e.g. 'next Friday'",
    )
    parser.add_argument(
        "--unlock-at",
        help="Unlock date/time in ISO-8601, e.g. 2026-02-20T08:00:00-06:00",
    )
    parser.add_argument(
        "--lock-at",
        help="Lock date/time in ISO-8601, e.g. 2026-03-01T23:59:00-06:00",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show request payload without calling Canvas.",
    )
    args = parser.parse_args()

    token, course_url = load_config(Path(args.config))
    api_base, course_id = parse_canvas_course(course_url)
    resolve_due_at_arg(args)
    description = load_description(args)

    if args.assignment_id:
        update_assignment(api_base, course_id, token, args, description)
    else:
        create_assignment(api_base, course_id, token, args, description)


if __name__ == "__main__":
    main()
