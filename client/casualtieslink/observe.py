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


def message_hashes(game, names):
    return {game.call("message_hash", name=name)["hash"]: name for name in names}
