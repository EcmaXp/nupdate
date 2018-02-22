from nupdate.utils import Namespace, NSFileFetchable

if False:
    from nupdate.mojang.minecraft import MojangMinecraftJson


class MojangDownload(NSFileFetchable, Namespace):
    @property
    def path(self) -> str:
        raise NotImplementedError


class SingleDownload(MojangDownload):
    def __init__(self, data, mc: "MojangMinecraftJson", path):
        super().__init__(data)
        self._mc = mc
        self._path = path

    @property
    def path(self):
        return self._path

    @property
    def local_path(self):
        return self._mc.path / self.path

    def _get_default_basepath(self):
        return self._mc.path
