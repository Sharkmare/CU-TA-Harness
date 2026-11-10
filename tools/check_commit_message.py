import sys
from pathlib import Path

SUBJECT_LIMIT = 72
BODY_LINES_LIMIT = 5
BODY_WIDTH_LIMIT = 100
VAGUE_SUBJECTS = {"update", "updates", "fix", "fixes", "change", "changes", "wip", "misc", "stuff", "commit", "tweaks", "cleanup", "more"}
ROUGH_PREFIXES = ("fixup!", "squash!", "merge ")
LONG_DASHES = (chr(0x2014), chr(0x2013))


def message_lines(text):
    return [line.rstrip() for line in text.splitlines() if not line.startswith("#")]


def problems(text):
    lines = message_lines(text)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ["the message is empty; write one line saying what changed"]
    found = []
    subject, rest = lines[0], lines[1:]
    if len(subject) > SUBJECT_LIMIT:
        found.append("the first line is %d characters; keep it to %d or fewer" % (len(subject), SUBJECT_LIMIT))
    if subject.strip().lower().rstrip(".") in VAGUE_SUBJECTS:
        found.append("%r says nothing; name what changed" % subject.strip())
    if subject.lower().startswith(ROUGH_PREFIXES):
        found.append("merge, fixup and squash commits do not belong in this history")
    if rest:
        if rest[0].strip():
            found.append("leave a blank line after the first line")
        body = [line for line in rest if line.strip()]
        if len(body) > BODY_LINES_LIMIT:
            found.append("the body has %d lines; keep it to %d or fewer" % (len(body), BODY_LINES_LIMIT))
        if any(len(line) > BODY_WIDTH_LIMIT for line in body):
            found.append("a body line is longer than %d characters" % BODY_WIDTH_LIMIT)
    if any(dash in "\n".join(lines) for dash in LONG_DASHES):
        found.append("use a comma, a colon or two sentences instead of a long dash")
    return found


def main(argv):
    text = Path(argv[1]).read_text(encoding="utf-8")
    found = problems(text)
    for problem in found:
        print("commit message: " + problem, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
