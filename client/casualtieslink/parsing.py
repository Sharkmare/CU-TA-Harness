import json

ENVELOPE_OK = "ok"


class LinkError(Exception):

    def __init__(self, message, kind="LinkError", status=None):
        super().__init__(message)
        self.kind = kind
        self.status = status


def parse_reply(body_text, status=200):
    try:
        envelope = json.loads(body_text)
    except ValueError as exc:
        raise LinkError("reply is not JSON: %s" % exc, status=status)
    if not isinstance(envelope, dict) or ENVELOPE_OK not in envelope:
        raise LinkError("reply has no ok field", status=status)
    if not envelope[ENVELOPE_OK]:
        raise LinkError(envelope.get("error", "unknown error"), envelope.get("kind", "LinkError"), status)
    return envelope.get("result")


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_key_values(pairs):
    arguments = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError("expected key=value, got %r" % pair)
        key, value = pair.split("=", 1)
        arguments[key] = parse_value(value)
    return arguments


def find_command(description, name):
    for command in description["commands"]:
        if command["name"] == name:
            return command
    return None


def missing_required(command_spec, arguments):
    return [a["name"] for a in command_spec["args"] if a["required"] and a["name"] not in arguments]
