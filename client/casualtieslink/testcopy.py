import os
import shutil

from .launcher import game_dir

COPY_ENVIRONMENT_VARIABLE = "CU_TEST_COPY_DIR"
FALLBACK_COPY_SUBDIR = "CU-test-client"
MARKER_NAME = ".cu-test-copy"
BOOT_CONFIG_RELATIVE = os.path.join("CasualtiesUnknown_Data", "boot.config")
SINGLE_INSTANCE_KEY = "single-instance"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SKIPPED_NAMES = {"LogOutput.log", "TogetherLogs", "cache"}


def default_destination():
    override = os.environ.get(COPY_ENVIRONMENT_VARIABLE)
    if override:
        return override
    return os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), FALLBACK_COPY_SUBDIR)


def without_single_instance(text):
    kept = []
    removed = False
    for line in text.splitlines(keepends=True):
        if line.split("=", 1)[0].strip() == SINGLE_INSTANCE_KEY:
            removed = True
            continue
        kept.append(line)
    return "".join(kept), removed


def assert_safe_destination(source, destination):
    source_path = os.path.normcase(os.path.abspath(source))
    target = os.path.normcase(os.path.abspath(destination))
    if target == source_path or source_path.startswith(target + os.sep) or target.startswith(source_path + os.sep):
        raise ValueError("destination %s overlaps the source %s" % (destination, source))
    if target == os.path.normcase(REPO_ROOT) or target.startswith(os.path.normcase(REPO_ROOT) + os.sep):
        raise ValueError("game files are not kept inside this repository: %s" % destination)


def _remove_previous(destination):
    if not os.path.exists(destination):
        return
    if not os.path.exists(os.path.join(destination, MARKER_NAME)):
        raise ValueError("%s exists and is not a test copy (no %s); refusing to delete it" % (destination, MARKER_NAME))
    shutil.rmtree(destination)


def make_copy(destination=None, source=None, remove_single_instance=False):
    source = source or game_dir()
    destination = destination or default_destination()
    assert_safe_destination(source, destination)
    _remove_previous(destination)
    shutil.copytree(source, destination, ignore=lambda folder, names: [n for n in names if n in SKIPPED_NAMES])
    boot_config = os.path.join(destination, BOOT_CONFIG_RELATIVE)
    with open(boot_config, encoding="utf-8") as handle:
        text = handle.read()
    new_text, removed = without_single_instance(text)
    if remove_single_instance:
        if not removed:
            raise RuntimeError("boot.config has no single-instance line; the copy would not differ from the install")
        with open(boot_config, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
    with open(os.path.join(destination, MARKER_NAME), "w") as handle:
        handle.write("test copy of %s, single-instance line %s\n" % (source, "removed" if remove_single_instance else "kept"))
    return destination


def remove_copy(destination=None):
    destination = destination or default_destination()
    if os.path.exists(destination):
        _remove_previous(destination)
