import json
import lzma
import os
import platform
import zipfile
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import requests

from nupdate.data.asset import Asset
from nupdate.data.download import SingleDownload
from nupdate.data.library import Library
from nupdate.data.namespace import Namespace
from nupdate.utils import OS_NAME, mktemp, fetch, calc_sha1_hash


class MojangMinecraftJson(Namespace):
    def __init__(self, mm: "MojangMinecraft", name, data):
        super().__init__(data)
        self.name = name
        self.mm = mm

    @property
    def path(self):
        return self.mm.path

    def merge(self, other):
        obj = self.copy()
        for key, value in other.items():
            if isinstance(value, list):
                obj[key].extend(value)
            elif isinstance(value, dict):
                obj[key].update(value)
            else:
                obj[key] = value

        return obj

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
        return (Library(self, library) for library in self['libraries'])

    def __call__(self):
        return self.sequence()

    def sequence(self):
        self.assetIndex.download()
        self.client.download()

        for library in self.libraries:  # type: Library
            library.download()

        for asset in self.assets:
            asset.download(self.path)

        return True

    def __repr__(self):
        return f"<{type(self).__name__}: {self.id}>"


class MojangAssets(dict, Mapping[str, Asset]):
    def __init__(self, name, data):
        self.name = name
        super().__init__(self._parse(data))

    @staticmethod
    def _parse(data):
        return {key: Asset(key, value) for key, value in data['objects'].items()}

    def __iter__(self):
        return iter(self.values())


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


class MojangAssetIndexes(FileSystemMapping, Mapping[str, MojangAssets]):
    def __init__(self, mm: "MojangMinecraft"):
        self.mm = mm

    @property
    def path(self):
        return self.mm.path

    def _get_json_path(self, version):
        return self.path / f'assets/indexes/{version}.json'

    def load(self, version, url, force_download=False):
        try:
            if not force_download:
                return self.read(version)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        version_json_path = self._get_json_path(version)
        raw_data = requests.get(url).text

        try:
            json.loads(raw_data)
        except json.JSONDecodeError as e:
            raise Exception from e

        with version_json_path.open('w') as fp:
            fp.write(raw_data)

        return self.read(version)

    def read(self, version):
        version_json_path = self._get_json_path(version)
        try:
            with version_json_path.open('r') as fp:
                return json.load(fp, object_hook=Namespace)
        except FileNotFoundError:
            raise

    def build(self, name, data):
        return MojangAssets(name, data)

    def __iter__(self):
        for json_path in (self.path / "assets/indexes").iterdir():  # type: Path
            if json_path.exists():
                basename, ext = os.path.splitext(json_path.name)
                if ext == ".json":
                    yield basename


class MojangMinecraft(FileSystemMapping, Mapping[str, MojangMinecraftJson]):
    def __init__(self, path: os.PathLike):
        self.path = Path(path)

    @property
    def assets(self):
        return MojangAssetIndexes(self)

    def __getitem__(self, item) -> MojangMinecraftJson:
        return super().__getitem__(item)

    def read(self, version: str):
        version_json_path = self.path / f'versions/{version}/{version}.json'
        try:
            with version_json_path.open('r') as fp:
                return json.load(fp, object_hook=Namespace)
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


class MojangJava(Namespace):
    LAUNCHER_CONFIG_URL = "http://launchermeta.mojang.com/mc/launcher.json"

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__({})

    def __call__(self):
        return self.sequence()

    def sequence(self):
        runtime = self.runtime
        if not runtime:
            self.fetch_info()
            arch = self._get_arch()

            if not self.download(OS_NAME, arch, 'jre'):
                raise Exception

        return self.runtime

    def fetch_info(self):
        data = requests.get(self.LAUNCHER_CONFIG_URL).json()
        self.update(data)

    def download(self, osname, arch, jname):
        farch = {'x86': '32', 'x64': '64'}.get(arch)
        info = self[osname][farch][jname]
        url = info['url']
        version = info['version']

        path = self.path / f'{jname}-{arch}/{version}'

        up = urlparse(url)  # type: ParseResult
        sha1_hash = info['sha1']
        name, ext = os.path.splitext(os.path.basename(up.path))

        with mktemp(ext, name + ".") as tpath:
            if not fetch(url, tpath):
                return False

            file_sha1_hash = calc_sha1_hash(tpath)
            if sha1_hash != file_sha1_hash:
                return False

            with lzma.open(tpath) as fp:
                zf = zipfile.ZipFile(fp, 'r')
                path.mkdir(parents=True, exist_ok=True)
                zf.extractall(path)

        return True

    def _get_arch(self):
        arch = {'i386': 'x86', 'AMD64': 'x64'}.get(platform.machine(), 'x86')
        return arch

    def find_runtime(self, group=None):
        if group is None:
            arch = self._get_arch()
            for jname in 'jdk', 'jre':
                yield from self.find_runtime(f'{jname}-{arch}')

            return

        base = self.path / group
        if not base.exists():
            return

        seq = []
        for folder in base.iterdir():  # type: Path
            java = folder / "bin" / "java.exe"  # type: Path
            if java.exists():
                seq.append((group, folder.name, java))

        def sorter(x):
            group, version, _ = x
            return group, version.partition("_")

        yield from sorted(seq, key=sorter)

    @property
    def runtime(self):
        for group, version, java in self.find_runtime():
            return java

        return None