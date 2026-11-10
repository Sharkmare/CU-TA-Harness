import re

from .parsing import LinkError

ERROR_PATTERN = re.compile(r"exception|\[error|nullreference|no receiver|unknown message|unknown custom|duplicate", re.I)
OUR_MARKERS = ("casualtiessize", "casualtiescharacters", "customnessage", "custommessage", "bridge")
GATE_ABSENT = "absent"


def suspicious_lines(text, markers=OUR_MARKERS, anywhere=False):
    found = []
    for line in text.splitlines():
        if not ERROR_PATTERN.search(line):
            continue
        if anywhere or any(marker in line.lower() for marker in markers):
            found.append(line.strip())
    return found


def sent_by_direction(counts, names_by_hash):
    result = {}
    for key, count in counts.items():
        direction, _, digest = key.partition(":")
        result.setdefault(direction, {})[names_by_hash.get(digest, digest)] = count
    return result


def read_or_absent(game, target, path):
    try:
        return game.call("get", target=target, path=path, depth=0, nonpublic=True)
    except LinkError:
        return GATE_ABSENT


def size_gate_host_state(game):
    return read_or_absent(game, "static:CasualtiesSize.TogetherBridge", "Gate.Host")


def loader_host_state(game):
    return read_or_absent(game, "static:CasualtiesCharacters.StockBridge", "channel.HostState")


def size_gate_peers(game):
    try:
        reply = game.call("get", target="static:CasualtiesSize.TogetherBridge", path="Gate.peers", depth=2, nonpublic=True)
    except LinkError:
        return {}
    return reply if isinstance(reply, dict) else {}


FLAVOUR_LINE_PATTERN = re.compile(r"CT_FlavourSwitch\]\s*(.*)")
TOGETHER_LOADED_PATTERN = re.compile(r"Plugin CasualtiesMP version (\S+) is loaded")


def flavour_switch_lines(log_text):
    lines = []
    for match in FLAVOUR_LINE_PATTERN.finditer(log_text):
        fields = dict(pair.split("=", 1) for pair in match.group(1).split() if "=" in pair)
        lines.append(fields)
    return lines


def together_version(log_text):
    match = TOGETHER_LOADED_PATTERN.search(log_text)
    return match.group(1) if match else None


def names_seen(counts, names_by_hash, prefix):
    seen = set()
    for key in counts:
        digest = key.partition(":")[2]
        name = names_by_hash.get(digest)
        if name is not None and name.startswith(prefix):
            seen.add(name)
    return seen


def skin_appliers(game):
    try:
        return len(game.call("find", type="SkinApplier"))
    except LinkError:
        return 0


def message_hashes(game, names):
    return {game.call("message_hash", name=name)["hash"]: name for name in names}
