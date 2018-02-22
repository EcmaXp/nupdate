import json
import os
from pathlib import Path
from typing import Mapping

import requests

from nupdate.config import MOJANG_RESOURCES_URL
from nupdate.mojang.utils import FileSystemMapping
from nupdate.utils import Namespace, calc_sha1_hash, Fetchable

if False:
    from nupdate.mojang.minecraft import MojangMinecraftPackage


class Asset(Fetchable):
    __slots__ = "name", "info"

    def __init__(self, name, info):
        self.name = name
        self.info = info

    @property
    def url(self):
        return MOJANG_RESOURCES_URL.format(self._path)

    @property
    def _path(self):
        obj_hash = self.info['hash']
        return f'{obj_hash[:2]}/{obj_hash}'

    @property
    def path(self):
        return f'assets/objects/{self._path}'

    def _check(self, path):
        obj_hash = self.info['hash']
        obj_size = self.info['size']

        if not path.exists():
            return False

        if path.stat().st_size != obj_size:
            return False

        if calc_sha1_hash(path) != obj_hash.lower():
            return False

        return True

    def __repr__(self):
        return f"<{type(self).__name__}: {self.name}>"


class MojangAssets(dict, Mapping[str, Asset]):
    def __init__(self, name, data):
        self.name = name
        super().__init__(self._parse(data))

    @staticmethod
    def _parse(data):
        return {key: Asset(key, value) for key, value in data['objects'].items()}

    def __iter__(self):
        return iter(self.values())


class MojangAssetIndexes(FileSystemMapping, Mapping[str, MojangAssets]):
    def __init__(self, mm: "MojangMinecraftPackage"):
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
