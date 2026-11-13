import os
import tempfile

LOCK_ENVIRONMENT_VARIABLE = "CU_GAME_LOCK"
LOCK_FILE_NAME = "CU-TA-Harness.game.lock"


def default_lock_path(environment=None, temporary_directory=None):
    """One lock for the whole machine. The game link ports are machine-wide, so a lock beside the checkout lets a second checkout or worktree drive the same ports at the same time."""
    environment = os.environ if environment is None else environment
    override = environment.get(LOCK_ENVIRONMENT_VARIABLE)
    if override:
        return os.path.abspath(override)
    return os.path.join(temporary_directory or tempfile.gettempdir(), LOCK_FILE_NAME)


LOCK_PATH = default_lock_path()


class GameLockHeld(RuntimeError):
    pass


class GameLock:

    def __init__(self, owner, path=LOCK_PATH):
        self.owner = owner
        self.path = os.path.abspath(path)
        self.held = False

    def acquire(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            with open(self.path, encoding="utf-8", errors="replace") as handle:
                raise GameLockHeld("game lock held: %s" % handle.read().strip())
        with os.fdopen(descriptor, "w") as handle:
            handle.write("%s, pid %d\n" % (self.owner, os.getpid()))
        self.held = True
        return self

    def release(self):
        if self.held and os.path.exists(self.path):
            os.remove(self.path)
        self.held = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc_info):
        self.release()
