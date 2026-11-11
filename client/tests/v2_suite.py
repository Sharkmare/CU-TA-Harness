import copy

from . import desync_scenarios as base
from . import hook_scenarios as hooks
from . import regression_scenarios as regression

GROUP = "hook-evidence"
MINING_NAME = "v2check_dig_cracks"
PVP_NAME = "v2check_pvp_melee_by_client"
PVP_RUNS = 2
SOURCE_PVP_NAME = "regress_pvp_melee_by_client"


def in_evidence_group(scenario, name, **changes):
    clone = copy.copy(scenario)
    clone.name = name
    clone.group = GROUP
    for attribute, value in changes.items():
        setattr(clone, attribute, value)
    return clone


def pvp_source():
    for scenario in regression.REGRESSION_SCENARIOS:
        if scenario.name == SOURCE_PVP_NAME:
            return scenario
    raise LookupError(SOURCE_PVP_NAME)


MINING = in_evidence_group(hooks.HOOK_MINING, MINING_NAME)
PVP = in_evidence_group(pvp_source(), PVP_NAME, max_repeat=PVP_RUNS)

base.SERIES_SCENARIOS.append(MINING)
base.SCENARIOS.append(PVP)
