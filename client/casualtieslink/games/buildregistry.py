"""The registry of game builds and plugin sets, read from local/builds.json (see casualtieslink.localcontent).

Without that file the registry is empty: only the built-in choices `stock` (CU_STOCK_TOGETHER_DIR) and `keep` exist.

{
  "default": "example-build",                       the build used when none is named
  "builds": {
    "example-flavour": {"kind": "flavour"},         installed from the flavour package zip (CU_FLAVOUR_ZIP) and started with --mp-flavour
    "example-stage":   {"kind": "stage", "directory_env": "CU_EXAMPLE_STAGE", "directory": "builds/example/stage",
                        "library_folders": ["ExampleLib"]},   plugins/Together (and the library folders) copied from a stage folder
    "example-python":  {"kind": "python", "install": "package.module:function"}   function(copy, debug) installs it and returns a path
  },
  "plugin_sets": {
    "example-dll":  {"kind": "dll", "source": "example/bin/Example.dll", "folder": "Example", "debug_guid": "example.guid"},
    "example-dir":  {"kind": "directory", "source": "example/fixtures/pack", "folder": "ExamplePack"},
    "example-zip":  {"kind": "release-zip", "directory": "example/dist", "prefix": "Example-0", "folder": "Example"}
  },
  "probe_config": {"file": "Example.cfg", "text": "[Probe]\n"}
}
Relative paths are under the mods root (CU_MODS_ROOT, default the folder that holds this repository).
"""
import contextlib
import os

from casualtieslink import localcontent
from casualtieslink.games import testcopy

BUILDS_FILE = "builds.json"
MODS_ROOT_ENVIRONMENT_VARIABLE = "CU_MODS_ROOT"
KNOWN_KINDS = ("flavour", "stage", "python")
_override = [None]


def mods_root():
    return os.environ.get(MODS_ROOT_ENVIRONMENT_VARIABLE) or os.path.dirname(testcopy.REPO_ROOT)


def under_mods_root(path):
    return path if os.path.isabs(path) else os.path.join(mods_root(), path)


def registry():
    data = _override[0] if _override[0] is not None else (localcontent.read_json(BUILDS_FILE, {}) or {})
    for name, spec in data.get("builds", {}).items():
        if spec.get("kind") not in KNOWN_KINDS:
            raise ValueError("build %r has kind %r; known kinds: %s" % (name, spec.get("kind"), ", ".join(KNOWN_KINDS)))
    return data


@contextlib.contextmanager
def use(data):
    """Replace the registry for a with block (tests)."""
    previous = _override[0]
    _override[0] = data
    try:
        yield
    finally:
        _override[0] = previous


def builds():
    return registry().get("builds", {})


def plugin_sets():
    return registry().get("plugin_sets", {})


def probe_config():
    return registry().get("probe_config")


def default_build():
    return registry().get("default")


def desync_builds():
    """The builds a desync run can name: those installed as a flavour or as a stage."""
    return tuple(name for name, spec in builds().items() if spec["kind"] in ("flavour", "stage"))
