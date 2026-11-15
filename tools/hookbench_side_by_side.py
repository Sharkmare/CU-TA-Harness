"""Side by side table of granular hookbench reports: frame time and the per-frame cost of chosen hooks, host and client.

Usage: python tools/hookbench_side_by_side.py label=path.json [label=path.json ...] [--hooks Name,Name] [--pass wrapped]
"""
import argparse
import json

DEFAULT_HOOKS = (
    "Together.Plugin.Update",
    "Together.ChunkSleep.Tick",
    "Together.ChunkSleep.WakeFreshChunks",
    "Together.ChunkSleep.WakeChunk",
    "Together.ChunkSleep.WakeSlot",
    "Together.ChunkSleep.ChunkIsHot",
    "Together.ChunkSleep.ChunkShown",
    "Together.ChunkSleep.FillSlot",
    "Together.ChunkSleep.Shown",
    "Together.ChunkSleep.Visit",
    "Together.ChunkSleep.Wake",
    "Together.ChunkSleep.Hot",
    "KrokV5Optimization.OptimizerMain.Tick",
    "Together.ClientMain.Update",
)


def per_frame_ms(hook):
    return hook["netMeanUs"] * hook["callsPerFrame"] / 1000.0


def side(report, pass_name, which):
    section = report[pass_name]
    return section if which == "host" else section.get("client")


def frame_row(section):
    frames = section["frames"]
    return "n=%d mean=%.2f p50=%.2f p95=%.2f p99=%.2f max=%.1f" % (frames["n"], frames["meanMs"], frames["p50Ms"], frames["p95Ms"], frames["p99Ms"], frames["maxMs"])


def main(arguments):
    labelled = []
    for spec in arguments.reports:
        label, path = spec.split("=", 1)
        with open(path, encoding="utf-8") as handle:
            labelled.append((label, json.load(handle)))
    hooks = arguments.hooks.split(",") if arguments.hooks else DEFAULT_HOOKS
    for pass_name in arguments.passes.split(","):
        for which in ("host", "client"):
            print("=== %s, %s side" % (pass_name, which))
            tables = []
            for label, report in labelled:
                section = side(report, pass_name, which)
                if section is None:
                    print("%-10s no data" % label)
                    continue
                print("%-10s frames: %s  objects=%s" % (label, frame_row(section), section.get("sceneObjects")))
                tables.append((label, {hook["name"]: hook for hook in section["hooks"]}))
            print("%-44s %s" % ("ms per frame", " ".join("%9s" % label for label, _ in tables)))
            for name in hooks:
                cells = []
                for _, by_name in tables:
                    hook = by_name.get(name)
                    cells.append("%9.4f" % per_frame_ms(hook) if hook and hook["calls"] else "%9s" % "-")
                print("%-44s %s" % (name, " ".join(cells)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--hooks")
    parser.add_argument("--passes", default="wrapped,wrapped2")
    main(parser.parse_args())
