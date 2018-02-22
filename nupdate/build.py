import datetime
import hashlib
import json
import os
import shutil
import tempfile
import zipapp
from pathlib import Path
from pprint import pprint

from nupdate import LAUNCHER_VERSION
from nupdate.mojang.library import MavenDownload
from nupdate.mojang.minecraft import MojangMinecraftJson, MojangMinecraftPackage
from nupdate.utils import calc_sha1_hash, Namespace


def current_date():
    return datetime.datetime.now().strftime("%Y%m%d")


def current_time():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+0000")


def minecraft_build(mc_version, forge_version, path_lib: Path, url_builder) -> MojangMinecraftJson:
    mm = MojangMinecraftPackage(Path(os.environ["APPDATA"]) / '.minecraft')
    name = f'{mc_version}-{forge_version}'

    release_time = current_time()
    modpack_version_info = {
        'id': name,
        'inheritsFrom': name,
        'releaseTime': release_time,
        'time': release_time,
        'type': 'release',
    }

    mc_pack = mm.build(name, modpack_version_info)
    mc_lib_path = mc_pack.path / 'libraries'
    for library in mc_pack['libraries']:
        if library.get('url') or library.get('serverreq') or library.get('clientreq'):
            download = MavenDownload(MavenDownload._get_maven_download(library, library['name']))

            source = mc_pack.path / download.path
            if not source.exists():
                print("warning", source, "missing")
                raise Exception(source)

            rpath = source.relative_to(mc_lib_path)
            target = path_lib / rpath
            target.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy(source, target)

            file_sha1_hash = calc_sha1_hash(target)
            file_size = target.stat().st_size

            artifact = library.setdefault('downloads', {}).setdefault('artifact', {})
            artifact.update({
                'sha1': file_sha1_hash,
                'size': file_size,
                'path': str(rpath.as_posix()),
                'url': url_builder(target),
            })

    return mc_pack


def from_content(path: Path):
    return json.loads(path.read_text())


def render_json(data):
    content = json.dumps(data, indent=4, default=Namespace._json_dumper)
    content = content.encode('utf-8')
    return content


def as_content(data, path: Path, base: Path, url_builder):
    content = render_json(data)
    (base / path).write_bytes(content)

    if path.name in ("index.json", "modpack.json"):
        urlpath = path.parent
        tail = "/"
    else:
        urlpath = path
        tail = ""

    return {
        'url': url_builder(urlpath) + tail,
        'path': path.relative_to(base).as_posix(),
        'sha1': hashlib.sha1(content).hexdigest().lower(),
        'size': len(content),
    }


def build_files(path: Path, url_builder):
    files = []
    for file in path.glob("**/*"):  # type: Path
        if file.is_file():
            file_size = file.stat().st_size
            file_sha1_hash = calc_sha1_hash(file)
            file_info = {
                'url': url_builder(file),
                'path': file.relative_to(path).as_posix(),
                'sha1': file_sha1_hash,
                'size': file_size,
            }

            files.append(file_info)

    return {
        'files': files,
    }


def build_package(id_, name, version, path: Path, mc_pack: MojangMinecraftJson, url_builder):
    now = current_time()

    basic_info = {
        'name': name,
        'version': version,
        'time': now,
    }

    detail_info = {
        'id': id_,
        'releaseTime': now,
    }

    mc_pack = mc_pack.copy()
    mc_pack.update(basic_info)
    mc_pack.update(build_files(path / "files", url_builder))
    mc_pack.update(detail_info)

    pack_detail_info = as_content(
        mc_pack,
        (path / Path('modpack.json')),
        path,
        url_builder,
    )

    pack_info = basic_info.copy()
    pack_info.update(pack_detail_info)

    return pack_info


def build(path, url_builder):
    packages = {}
    for folder in path.iterdir():  # type: Path
        # TODO: update with target modpack only?
        if folder.is_dir():
            info_file = (folder / 'info.txt')
            if info_file.exists():
                info = json.loads(info_file.read_text())
            else:
                info = {}

            path_lib = (folder / 'libraries')

            pkg_id = info['id'] = folder.name.lower()  # type: str

            mc_file = (folder / 'minecraft.json')
            if mc_file.exists():
                mps = MojangMinecraftPackage(Path.cwd())
                mc_pack = mps.build(pkg_id, json.loads(mc_file.read_text()))
            else:
                mc_pack = minecraft_build(
                    info['mc_version'],  # '1.10.2'
                    info['forge_version'],  # 'forge1.10.2-12.18.3.2511'
                    path_lib,
                    url_builder,
                )

                as_content(mc_pack, mc_file, folder, url_builder)

            version = info.get('version', current_date())
            dt, sep, idx = version.partition("-")

            if sep:
                if dt == current_date():
                    idx = int(idx) + 1
                else:
                    dt = current_date()
                    idx = 0
            elif dt == current_date():
                idx = 0

            info['version'] = f'{dt}-{idx}'

            pkg = build_package(
                pkg_id,
                info.setdefault('name', pkg_id.capitalize()),
                info.setdefault('version', None),
                folder,
                mc_pack,
                url_builder,
            )

            info['time'] = current_time()
            info_file.write_text(json.dumps(info, indent=4))

            assert pkg_id not in packages
            packages[pkg_id] = pkg

    data = {
        'version': '1.0',
        'time': current_time(),
        'launcher': LAUNCHER_INFO,
        'packages': packages,
    }

    return as_content(
        data,
        path / 'index.json',
        path,
        url_builder,
    )


class URLBuilder:
    def __init__(self, prefix, root):
        assert prefix.endswith("/")
        self.prefix = prefix
        self.root = root

    def __call__(self, path: Path):
        return (self.prefix + path.relative_to(self.root).as_posix())


LAUNCHER_INFO = {
    'version': LAUNCHER_VERSION,
    'url': "https://mc.nyang.kr/launcher/",
}


def build_pyz():
    dir = tempfile.mkdtemp()
    try:
        pkg_path = Path(__file__).parent
        shutil.copytree(pkg_path, os.path.join(dir, pkg_path.name))
        path = pkg_path.with_name(pkg_path.name + '.pyz')
        zipapp.create_archive(
            dir,
            target=path,
            main="nupdate.build:build_main",
            interpreter="/usr/bin/env python3.6",
        )

        return Path(path)
    finally:
        shutil.rmtree(dir, ignore_errors=True)


def build_mcjson():
    url = "https://mc.nyang.kr/packages/mint/libraries/"
    assert url.endswith("/")
    mc_json = minecraft_build("1.12.2", "forge1.12.2-14.23.1.2608", Path("."), lambda x: url + x.as_posix())
    pprint(dict(mc_json))
    content = render_json(mc_json)
    (Path.cwd() / "minecraft.json").write_bytes(content)


def build_main():
    site = "https://mc.nyang.kr/"
    root = Path("/home/signet/web/")
    url_builder = URLBuilder(site, root)
    path = root / "packages"
    result = build(path, url_builder)
    print(result['url'])


if __name__ == '__main__':
    build_mcjson()
    # build_pyz()
