import os
import re
import unittest

REPOSITORY_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DOCUMENT_PATHS = ["README.md"] + ["docs/" + name for name in sorted(os.listdir(os.path.join(REPOSITORY_ROOT, "docs")))]
BACKTICKED = re.compile(r"`([^`\n]+)`")
PATH_TOKEN = re.compile(r"^(?:(?:client|tools|plugin|plugin-tests|docs|casualtieslink|scenarios|live|unit|profiles)/)[A-Za-z0-9_./-]*\.(?:py|json|md|cs|csproj)$")
SEARCH_ROOTS = ("", "client")
ALLOWED_MISSING = {
    "client/.test_state.json",
}


def existing_path(token):
    for root in SEARCH_ROOTS + ("client/casualtieslink",):
        if os.path.exists(os.path.join(REPOSITORY_ROOT, root, token)):
            return True
    return False


def documented_paths():
    for document in DOCUMENT_PATHS:
        with open(os.path.join(REPOSITORY_ROOT, document), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                for token in BACKTICKED.findall(line):
                    if PATH_TOKEN.match(token) and "<" not in token and "*" not in token:
                        yield document, number, token


class DocumentedPathTests(unittest.TestCase):
    def test_every_file_path_the_documents_name_exists(self):
        missing = ["%s:%d %s" % (document, number, token) for document, number, token in documented_paths()
                   if token not in ALLOWED_MISSING and not existing_path(token)]
        self.assertEqual(missing, [])

    def test_the_scan_finds_the_paths_the_documents_name(self):
        self.assertGreater(len({token for _, _, token in documented_paths()}), 20)


if __name__ == "__main__":
    unittest.main()
