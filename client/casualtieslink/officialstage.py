import argparse
import hashlib
import os
import zipfile

from . import instances

OFFICIAL_ZIP_NAME = "MPMod_5.5.0_fullgame1.0_bepinex5.4.23.5.zip"
OFFICIAL_ZIP_SHA256 = "9bb980b88f6045c884350bd6e01b61b82d3e243795787415dca53fa5f643e68b"
OFFICIAL_REFERENCE_FOLDER = os.path.join("reference", "official_together_5_5_0")
PLUGIN_PREFIX = "mod/BepInEx/plugins/Together/"
MAIN_DLL = "CasualtiesMP.dll"
SELF_UPDATER = "Multiupdater.dll"
ZIP_ENVIRONMENT_VARIABLE = "CU_OFFICIAL_ZIP"


def sha256_of_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def default_zip_path():
    explicit = os.environ.get(ZIP_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(instances.mods_root()), OFFICIAL_REFERENCE_FOLDER, OFFICIAL_ZIP_NAME)


def plugin_entries(archive):
    entries = []
    for info in archive.infolist():
        if info.is_dir() or not info.filename.startswith(PLUGIN_PREFIX):
            continue
        name = info.filename[len(PLUGIN_PREFIX):]
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("unexpected path in the plugin folder of the zip: %r" % info.filename)
        if name == SELF_UPDATER:
            continue
        entries.append((info, name))
    return entries


def extract_official_stage(zip_path, destination, expected_sha256=OFFICIAL_ZIP_SHA256):
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(zip_path)
    actual = sha256_of_file(zip_path)
    if actual != expected_sha256:
        raise ValueError("the zip %s has sha256 %s, expected %s" % (zip_path, actual, expected_sha256))
    target = os.path.join(destination, "plugins", instances.TOGETHER_FOLDER)
    if os.path.exists(target) and os.listdir(target):
        raise FileExistsError("the stage folder is not empty: %s" % target)
    os.makedirs(target, exist_ok=True)
    written = {}
    with zipfile.ZipFile(zip_path) as archive:
        entries = plugin_entries(archive)
        if MAIN_DLL not in [name for _, name in entries]:
            raise ValueError("%s is not in the plugin folder of %s" % (MAIN_DLL, zip_path))
        for info, name in entries:
            content = archive.read(info)
            with open(os.path.join(target, name), "wb") as handle:
                handle.write(content)
            written[name] = hashlib.sha256(content).hexdigest()
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the official Together plugin files from the pinned release zip into a stage folder.")
    parser.add_argument("--zip", default=None)
    parser.add_argument("--destination", default=None)
    arguments = parser.parse_args(argv)
    written = extract_official_stage(arguments.zip or default_zip_path(), arguments.destination or instances.official_stage_directory())
    for name, digest in sorted(written.items()):
        print("%s  %s" % (digest, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
