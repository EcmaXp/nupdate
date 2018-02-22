import lzma
import os
import platform
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from nupdate.config import OS_NAME
from nupdate.utils import Namespace, mktemp, fetch, calc_sha1_hash


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
                seq.append((group, folder.name, java, folder.absolute()))

        def sorter(x):
            group, version, _, _ = x
            return group, version.partition("_")

        yield from sorted(seq, key=sorter)

    @property
    def runtime(self):
        for group, version, java, folder in self.find_runtime():
            return java

        return None
