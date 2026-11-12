import hashlib
import os
import shutil
import zipfile

ZIP_ENVIRONMENT_VARIABLE = "CU_FRIENDS_ZIP"
DEFAULT_ZIP_NAME = "CasualtiesUnknown-Mods.zip"
PLUGINS_PREFIX = "BepInEx/plugins/"
NOT_INSTALLED_ROOT_FILES = ("INSTALL.txt", "changelog.txt")
LINK_FOLDER = "CasualtiesLink"


def default_zip_path():
    explicit = os.environ.get(ZIP_ENVIRONMENT_VARIABLE)
    if explicit:
        return explicit
    return os.path.join(os.path.expanduser("~"), "Downloads", DEFAULT_ZIP_NAME)


def md5_of_bytes(content):
    return hashlib.md5(content).hexdigest()


def md5_of_file(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def installable_entries(archive):
    entries = []
    for info in archive.infolist():
        name = info.filename
        if info.is_dir() or name in NOT_INSTALLED_ROOT_FILES:
            continue
        parts = name.split("/")
        if name.startswith("/") or "\\" in name or ".." in parts or ":" in name:
            raise ValueError("unsafe path in the zip: %r" % name)
        entries.append(info)
    return entries


def dll_md5_by_path(archive):
    return {info.filename: md5_of_bytes(archive.read(info)) for info in installable_entries(archive) if info.filename.lower().endswith(".dll")}


def plugin_names_in_zip(archive):
    names = set()
    for info in installable_entries(archive):
        if info.filename.startswith(PLUGINS_PREFIX):
            names.add(info.filename[len(PLUGINS_PREFIX):].split("/")[0])
    return names


def plugin_names_in_copy(copy):
    folder = os.path.join(copy, *PLUGINS_PREFIX.strip("/").split("/"))
    try:
        return set(os.listdir(folder))
    except OSError:
        return set()


def extract_into_copy(zip_path, copy, together_folder="Together", remove_extras=False):
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(zip_path)
    together = os.path.join(copy, "BepInEx", "plugins", together_folder)
    if os.path.isdir(together):
        shutil.rmtree(together)
    with zipfile.ZipFile(zip_path) as archive:
        entries = installable_entries(archive)
        for info in entries:
            destination = os.path.join(copy, *info.filename.split("/"))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "wb") as handle:
                handle.write(archive.read(info))
        expected = dll_md5_by_path(archive)
        zip_plugins = plugin_names_in_zip(archive)
    mismatched = {path: (md5, md5_of_file(os.path.join(copy, *path.split("/")))) for path, md5 in expected.items()
                  if md5_of_file(os.path.join(copy, *path.split("/"))) != md5}
    if mismatched:
        raise ValueError("DLLs in the copy differ from the zip after extraction: %s" % mismatched)
    extras = sorted(plugin_names_in_copy(copy) - zip_plugins - {LINK_FOLDER})
    if extras and not remove_extras:
        raise ValueError("the copy has plugins that are not in the zip: %s" % extras)
    plugins_folder = os.path.join(copy, "BepInEx", "plugins")
    for name in extras:
        path = os.path.join(plugins_folder, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    return {"removedFromCopy": extras, "zip": zip_path, "zipMd5": md5_of_file(zip_path), "files": len(entries), "dllMd5": expected, "pluginFolders": sorted(zip_plugins)}


def verify_copy(zip_path, copy):
    with zipfile.ZipFile(zip_path) as archive:
        expected = dll_md5_by_path(archive)
    return {path: md5_of_file(os.path.join(copy, *path.split("/"))) == md5 for path, md5 in expected.items()}
