import os
import zipfile
from pathlib import Path
from typing import Mapping

from nupdate.mojang.assets import MojangAssetIndexes
from nupdate.mojang.download import SingleDownload
from nupdate.mojang.library import MojangLibrary
from nupdate.mojang.profile import MojangLauncherProfileJson
from nupdate.mojang.utils import FileSystemMapping
from nupdate.utils import Namespace


class MojangMinecraftJson(Namespace):
    def __init__(self, mm: "MojangMinecraftPackage", name, data):
        super().__init__(data)
        self.name = name
        self.mm = mm

    @property
    def path(self):
        return self.mm.path

    def merge(self, other):
        obj = self.copy()
        for key, value in other.items():
            if key == "libraries":
                everything = set(library.id for library in self.libraries)
                libraries = []

                for library in obj.libraries:
                    libraries.append(dict(library))

                for library in other.libraries:
                    if library.id not in everything:
                        libraries.append(dict(library))

                obj[key] = libraries
            elif isinstance(value, list):
                obj[key].extend(value)
            elif isinstance(value, dict):
                obj[key].update(value)
            else:
                obj[key] = value

        return obj

    @property
    def native_path(self):
        return self.path / 'natives'

    @property
    def assets(self):
        return self.mm.assets[self['assets']]

    @property
    def assetIndex(self):
        assetIndex = self['assetIndex']
        return SingleDownload(assetIndex, self, f'assets/indexes/{assetIndex["id"]}.json')

    @property
    def client(self):
        clientDownload = self['downloads']['client']
        version = self['jar']
        return SingleDownload(clientDownload, self, f"versions/{version}/{version}.jar")

    @property
    def id(self):
        return self['id']

    @property
    def libraries(self):
        return (MojangLibrary(self, library) for library in self['libraries'])

    def __call__(self):
        return self.sequence()

    def sequence(self):
        self.assetIndex.download()
        self.client.download()

        for library in self.libraries:  # type: MojangLibrary
            library.download()

        for asset in self.assets:
            asset.download(self.path)

        self.extract_natives()

        return True

    def extract_natives(self):
        for library in self.libraries:
            if library.action != 'allow':
                continue

            if library.natives and library.extract:
                zf = zipfile.ZipFile(library.mc.path / library.native.path)

                excludes = tuple(library.extract.get('exclude', ()))
                zf.extractall(
                    self.native_path,
                    (zipinfo for zipinfo in zf.namelist()
                     if not zipinfo.startswith(excludes)),
                )

    def __repr__(self):
        return f"<{type(self).__name__}: {self.id}>"


class MojangMinecraftPackage(FileSystemMapping, Mapping[str, MojangMinecraftJson]):
    def __init__(self, path: os.PathLike):
        self.path = Path(path)

    @property
    def profile(self) -> MojangLauncherProfileJson:
        return MojangLauncherProfileJson.from_path(self.path / "launcher_profiles.json")

    def profile_write(self, profile: MojangLauncherProfileJson):
        profile.to_path(self.path / "launcher_profiles.json")

    @property
    def assets(self):
        return MojangAssetIndexes(self)

    def __getitem__(self, item) -> MojangMinecraftJson:
        return super().__getitem__(item)

    def read(self, version: str):
        try:
            return Namespace.from_path(self.path / f'versions/{version}/{version}.json')
        except FileNotFoundError:
            raise

    def build(self, name, data) -> MojangMinecraftJson:
        result = MojangMinecraftJson(self, name, data)
        if "inheritsFrom" in result:
            return self[result.pop('inheritsFrom')].merge(result)

        return result

    def __iter__(self):
        for dir_path in (self.path / "versions").iterdir():  # type: Path
            json_path = dir_path / f'{dir_path.name}.json'
            if json_path.exists():
                yield dir_path.name
