from logging import getLogger
from typing import Union, Optional

from TwitchChannelPointsMiner.classes.entities.LockedObject import LockedObject

logger = getLogger(__name__)


class Game(LockedObject):
    __slots__ = [
        '_id',
        '_name',
        '_displayName',
    ]

    def __init__(self,
                 gid: Optional[Union[int, str]] = None,
                 name: Optional[str] = None,
                 display_name: Optional[str] = None):
        super().__init__()
        # self.id = gid
        if gid and (gid:=int(gid)):
            self._id = gid
        else:
            self._id = None
        # self.name = name
        if name:
            self._name = name
        else:
            self._name = None

        # if display_name:
        #     self._displayName: str = display_name
        # else:
        #     self._displayName = None
        self.display_name = display_name

    def __str__(self) -> str:
        with self:
            if self._displayName:
                return self._displayName
            elif self._name:
                return self._name
        return ''

    def __repr__(self):
        return f"Game(id={self._id}, game={self})"

    @property
    def id(self) -> Optional[str]:
        if self._id:
            # return str(self._id)
            return self._id
        return None

    # @id.setter
    # def id(self, id: Optional[Union[int, str]]):
    #     if id:
    #         self._id = id
    #     else:
    #         self._id = None

    @property
    def name(self) -> Optional[str]:
        if self._name:
            return self._name
        return None

    # @name.setter
    # def name(self, name: Optional[str]):
    #     if name:
    #         self._name = name
    #     else:
    #         self._name = None

    @property
    def display_name(self) -> Optional[str]:
        if self._displayName:
            return self._displayName
        return None

    @display_name.setter
    def display_name(self, name: Optional[str]):
        if hasattr(self, '_displayName'):
            if not self._displayName:
                if name:
                    self._name = name
                else:
                    self._name = None
        else:
            self._displayName = None
            self.display_name = name
