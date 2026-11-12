import re

HEADER = re.compile(r"\[PR24V\] swing=(\d+) t=(\S+) result=(\w+) hookCalls=(\d+) vanillaBlockDamages=(\d+) lastHitWasBlock=(\w+) lastHitPos=(\S+) attackerPos=(\S+)(.*)")
HOOK = re.compile(r"hook#(\d+)\((.*?) tag=(\S*) at=(\S+) dist=(\S+) building=(\w+) body=(\w+) took=(\w+) breakLoop=(\w+) block=(\w+)\)")
DAMAGE = re.compile(r"damageBlock\(pos=(\S+) dmg=(\S+) total=(\S+)\)")
CONTINUATION = re.compile(r"^\s+(hook#|damageBlock\()")


def parse_swings(text):
    swings = []
    current = None
    for line in text.splitlines():
        found = HEADER.search(line)
        if found:
            current = {"swing": int(found.group(1)), "t": float(found.group(2)), "result": found.group(3) == "True", "hookCalls": int(found.group(4)),
                       "vanillaBlockDamages": int(found.group(5)), "lastHitWasBlock": found.group(6) == "True", "lastHitPos": found.group(7), "attackerPos": found.group(8),
                       "hooks": [], "damageBlocks": [], "raw": [line.strip()]}
            swings.append(current)
            tail = found.group(9)
        elif current is not None and CONTINUATION.match(line):
            tail = line
            current["raw"].append(line.strip())
        else:
            continue
        for hook in HOOK.finditer(tail):
            current["hooks"].append({"index": int(hook.group(1)), "collider": hook.group(2), "tag": hook.group(3), "at": hook.group(4), "dist": hook.group(5), "building": hook.group(6) == "True",
                                     "body": hook.group(7) == "True", "took": hook.group(8) == "True", "breakLoop": hook.group(9) == "True", "block": hook.group(10) == "True"})
        for damage in DAMAGE.finditer(tail):
            current["damageBlocks"].append({"pos": damage.group(1), "dmg": damage.group(2), "total": damage.group(3)})
    return swings


def split_by_counts(swings, counts):
    runs = []
    start = 0
    for count in counts:
        runs.append(swings[start:start + count])
        start += count
    return runs, len(swings) - start


def summarise(swings):
    took = [s for s in swings if any(h["took"] for h in s["hooks"])]
    no_damage = [s for s in swings if s["vanillaBlockDamages"] == 0]
    return {"swings": len(swings), "swingsWithTookTrue": len(took), "swingsWithNoVanillaBlockDamage": len(no_damage),
            "noDamageAndNoTook": len([s for s in no_damage if s not in took]), "firstDamagingSwing": next((index for index, s in enumerate(swings) if s["vanillaBlockDamages"] > 0), None),
            "tookColliders": sorted({h["collider"] + "/" + h["tag"] for s in took for h in s["hooks"] if h["took"]})}
