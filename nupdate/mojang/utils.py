from typing import Mapping


class FileSystemMapping(Mapping):
    def read(self, name):
        raise NotImplementedError

    def build(self, name, data):
        raise NotImplementedError

    def __getitem__(self, item: str):
        try:
            data = self.read(item)
        except FileNotFoundError as e:
            raise KeyError(item) from e

        return self.build(item, data)

    def __len__(self):
        return sum(map(bool, self.__iter__()))

    def __contains__(self, item):
        return item in iter(self)
