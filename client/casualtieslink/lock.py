import os

LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".game.lock")


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
