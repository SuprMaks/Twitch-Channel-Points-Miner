from threading import Lock


class LockedObject(object):
    __slots__ = ('_lock',)

    def __init__(self):
        self._lock = Lock()

    def __enter__(self):
        """Context manager enter the block, acquire the lock."""
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit the block, release the lock."""
        self._lock.release()

    def __getstate__(self):
        """Enable Pickling inside context blocks,
        through inclusion of the slot entries without the lock."""
        return dict(
            (slot, getattr(self, slot))
            for slot in self.__slots__
            if hasattr(self, slot) and slot != '_lock'
        )

    def __setstate__(self, state):
        """Restore the instance from pickle including the slot entries,
        without addition of a fresh lock.
        """
        for slot, value in getattr(state, 'items')():
            setattr(self, slot, value)
        self._lock = Lock()
