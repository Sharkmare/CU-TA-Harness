#!/bin/bash
# usage: run_ilcost.sh <Together stage folder holding CasualtiesMP.dll> [extra IlCost arguments]
GAME="${CU_GAME_DIR:-C:/Program Files (x86)/Steam/steamapps/common/Casualties Unknown}"
STAGE="$1"; shift
HERE="$(cd "$(dirname "$0")" && pwd)"
dotnet "$HERE/bin/IlCost.dll" --mod "$STAGE/CasualtiesMP.dll" --search "$GAME/CasualtiesUnknown_Data/Managed;$GAME/BepInEx/core;$STAGE" "$@"
