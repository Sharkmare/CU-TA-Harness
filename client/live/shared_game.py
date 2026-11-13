import os
import unittest

from casualtieslink import Game
from casualtieslink.transport import default_port

MUTATION_ENVIRONMENT_VARIABLE = "CASUALTIES_TEST_MUTATION"
PAIR_ENABLED_ENVIRONMENT_VARIABLE = "CASUALTIES_PAIR_TESTS"

_game = None


def bind(game):
    global _game
    _game = game


def game():
    global _game
    if _game is None:
        _game = Game(default_port())
        if not _game.transport.is_up():
            raise unittest.SkipTest("no game answering on port %d; use run_tests.py" % default_port())
    return _game


def fresh_run(character=0, **options):
    link = game()
    link.ensure_menu()
    link.wait_state("menu")
    return link.start_run(character=character, **options)


def mutation_active(name):
    return os.environ.get(MUTATION_ENVIRONMENT_VARIABLE, "") == name


def limb_index(snapshot, name_fragment):
    for limb in snapshot["limbs"]:
        if name_fragment in limb["name"].lower():
            return limb["index"]
    raise AssertionError("no limb with %r in %s" % (name_fragment, [l["name"] for l in snapshot["limbs"]]))
