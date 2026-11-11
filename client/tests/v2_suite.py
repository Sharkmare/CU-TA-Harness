import copy

from . import desync_scenarios as base
from . import hook_scenarios as hooks

GROUP = "hook-evidence"
MINING_NAME = "v2check_dig_cracks"


def in_evidence_group(scenario, name, **changes):
    clone = copy.copy(scenario)
    clone.name = name
    clone.group = GROUP
    for attribute, value in changes.items():
        setattr(clone, attribute, value)
    return clone


MINING = in_evidence_group(hooks.HOOK_MINING, MINING_NAME)

base.SERIES_SCENARIOS.append(MINING)
