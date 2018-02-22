import copy
import hashlib
import json
import tempfile
from collections import UserDict
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import certifi
import hyper.tls
import progressbar
import requests
from hyper.contrib import HTTP20Adapter

hyper.tls.cert_loc = certifi.where()


class ChunkTransferBar(progressbar.DataTransferBar):
    def __next__(self):
        try:
            value = next(self._iterable)
            if self.start_time is None:
                self.start()
            else:
                self.update(self.value + len(value))
            return value
        except StopIteration:
            self.finish()
            raise


def fetch(url, path):
    for i in range(3):
        if fetch_interanl(url, path):
            break
    else:
        raise Exception("request failed. check your internet")

    return True


_session: requests.Session = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.mount('https://mc.nyang.kr', HTTP20Adapter())
        # TODO: fix hard corded?

    return _session


def clear_session():
    global _session
    sess, _session = _session, None
    if sess is not None:
        sess.close()


def fetch_interanl(url, path):
    sess = get_session()
    req = sess.get(url, stream=True)
    if req.status_code != 200:
        print('err', req.status_code, url)
        return False

    with path.open('wb') as fp:
        total_length = req.headers.get('content-length')
        expected_size = int(total_length) if total_length else progressbar.UnknownLength

        print(urlparse(url).path.rpartition('/')[2])

        bar = ChunkTransferBar(
            max_value=expected_size
        )

        for chunk in bar(req.iter_content(chunk_size=4096)):
            fp.write(chunk)

    return True


def calc_sha1_hash(path: Path):
    with path.open('rb') as fp:
        hobj = hashlib.sha1()
        buf = True
        while buf:
            buf = fp.read(4096)
            hobj.update(buf)

    return hobj.hexdigest().lower()


@contextmanager
def mktemp(suffix="", prefix=tempfile.template, dir=None) -> Path:
    tpath = Path(tempfile.mktemp(suffix, prefix, dir))
    try:
        yield tpath
    finally:
        try:
            tpath.unlink()
        except FileNotFoundError:
            pass


class Namespace(UserDict):
    # noinspection PyMissingConstructor
    def __init__(self, data):
        self.data = data
        self.init()

    def init(self):
        pass

    def copy(self):
        return copy.copy(self)

    @classmethod
    def from_path(cls, path: Path):
        with path.open('r') as fp:
            return cls(data=json.load(fp, object_hook=Namespace))

    def to_path(self, path: Path):
        with path.open('w') as fp:
            json.dump(self.data, fp, indent=2, default=self._json_dumper)

    @staticmethod
    def _json_dumper(obj):
        return obj.data if isinstance(obj, Namespace) else obj


class Fetchable:
    @property
    def url(self) -> str:
        raise NotImplementedError

    @property
    def path(self) -> str:
        raise NotImplementedError

    def _get_default_basepath(self):
        raise Exception

    def __call__(self, mc_basepath: Path = None):
        return self.download(mc_basepath)

    def download(self, mc_basepath: Path = None):
        if mc_basepath is None:
            mc_basepath = self._get_default_basepath()

        if not self.check(mc_basepath):
            return self.fetch(mc_basepath)

        return True

    def check(self, basepath: Path = None):
        if basepath is None:
            basepath = self._get_default_basepath()

        result = self._check(basepath / self.path)
        return result

    def fetch(self, mc_basepath: Path = None):
        if mc_basepath is None:
            mc_basepath = self._get_default_basepath()

        path = mc_basepath / self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        result = self._fetch(path)
        return result

    def _check(self, path: Path):
        raise NotImplementedError

    def _fetch(self, path: Path, require_check=True):
        result = fetch(self.url, path)
        if not result:
            return False

        if require_check and not self._check(path):
            print('hash mismatch', self.url)
            path.unlink()
            return False

        return True


class Sha1Fetchable(Fetchable):
    @property
    def sha1(self) -> str:
        raise NotImplementedError

    @property
    def size(self) -> int:
        raise NotImplementedError

    def _check(self, path: Path):
        if not path.exists():
            return False

        file_size = self.size
        if file_size is not None:
            file_size = int(file_size)
            if path.stat().st_size != file_size:
                return False

        sha1_hash = self.sha1
        if not sha1_hash:
            # there is no hash, no way to vaild
            return True

        file_sha1_hash = calc_sha1_hash(path)
        return file_sha1_hash == sha1_hash.lower()


class NSFileFetchable(Sha1Fetchable, Namespace):
    @property
    def url(self) -> str:
        return self['url']

    @property
    def path(self) -> str:
        return self['path']

    @property
    def sha1(self):
        return self.get('sha1')

    @property
    def size(self):
        return self.get('size')
