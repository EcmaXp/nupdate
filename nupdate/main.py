import encodings
import json
import os
import pkgutil
import platform
import shutil
import subprocess
import sys
import traceback
import webbrowser
from functools import lru_cache
from json import JSONDecodeError
from pathlib import Path

import mojang_api
import requests

from nupdate import LAUNCHER_VERSION
from nupdate.mojang.java import MojangJava
from nupdate.mojang.minecraft import MojangMinecraftPackage
from nupdate.utils import Namespace, NSFileFetchable, calc_sha1_hash, clear_session

if not getattr(sys, "frozen", False):
    for module in pkgutil.iter_modules(encodings.__path__, encodings.__name__ + "."):
        if not module.ispkg:
            __import__(module.name)


class ModpackSingleDownload(NSFileFetchable):
    def __init__(self, data, path: Path):
        super().__init__(data)
        self._basepath = path

    def _get_default_basepath(self):
        return self._basepath

    @property
    def local_path(self) -> Path:
        return self._basepath / self.path

    def json(self, ignore_check=False):
        if not ignore_check and not self.check():
            self.fetch()

        return json.loads(self.local_path.read_text(encoding="utf-8"))


class Modpack(Namespace):
    def __init__(self, file: ModpackSingleDownload, path: Path, is_fresh):
        data = file.json()
        super().__init__(data)
        self.file = file
        self.path = path
        self.is_fresh = is_fresh

    def __call__(self):
        return self.sequence()

    def sequence(self):
        result_set = {True}

        if not self.path.exists():
            self.path.mkdir(parents=True, exist_ok=True)

        donefile = self.path / 'modpack.done'
        if self.is_fresh or not donefile.exists():
            if donefile.exists():
                donefile.unlink()
            self._download_files()
            donefile.touch()

        keepmods = self.path / 'keepmods'
        if not keepmods.is_dir():
            keepmods.mkdir(exist_ok=True)

        has_keepmods = False
        mods = self.path / 'mods'
        for src in keepmods.rglob("**/*"):  # type: Path
            has_keepmods = True
            dst: Path = mods / src.relative_to(keepmods)
            if src.stat().st_size == 0:
                if dst.exists():
                    dst.unlink()
            elif not dst.exists() or calc_sha1_hash(src) != calc_sha1_hash(dst):
                if not dst.parent.exists():
                    dst.parent.mkdir(exist_ok=True, parents=True)

                shutil.copy(str(src), str(dst))

        if has_keepmods:
            result_set.add("has_keepmods")

        return result_set

    def _download_files(self):
        files = self.files

        @lru_cache()
        def ignore_folder(spath: str):
            if spath + '.__ignore__' in files:
                return True

            seq = tuple(spath.split('/'))
            for x in range(1, len(seq) - 1):
                if ignore_folder('.'.join(seq[:x])):
                    return True

            return False

        for name in "mods", "config", "scripts":
            folder = self.path / name
            for path in folder.glob("**/*"):  # type: Path
                rpath = path.relative_to(self.path)
                spath = rpath.as_posix()
                if ignore_folder(spath):
                    continue

                if path.is_file():
                    if spath not in files:
                        path.unlink()
                elif path.is_dir() and spath in files:
                    path.rmdir()

        for key, file in files.items():
            if key.endswith('.__ignore__'):
                continue

            file.download(self.path)

    @property
    def files(self):
        return {file_info['path']: NSFileFetchable(file_info) for file_info in self['files']}


class Modpacks(Namespace):
    def __init__(self, url, path: Path):
        self.url = url
        self.path = path
        super().__init__(self._fetch())

    def _fetch(self):
        with requests.session() as session:
            return session.get(self.url).json()

    def raw_package(self, name):
        package = self['packages'][name]
        return ModpackSingleDownload(package, self.path / name).json(ignore_check=True)

    def package(self, name) -> Modpack:
        package = self['packages'][name]
        file = ModpackSingleDownload(package, self.path / name)

        is_fresh = not file.check()
        if is_fresh:
            file.fetch()

        return Modpack(file, self.path / name, is_fresh)


log_file = (Path.cwd() / "launcher.log").open('w')


def rawlog(*args, sep=" ", end="\n"):
    print(*args, sep=sep, end=end, file=log_file)
    log_file.flush()


def log(*args, sep=" ", end="\n", file=sys.stdout):
    print(*args, sep=sep, end=end, file=file)
    rawlog(*args, sep=sep, end=end)


def prettyjson(obj):
    return json.dumps(obj, indent=4, default=Namespace._json_dumper)


def launch():
    log(f"I: SM-REBoot Launcher v{LAUNCHER_VERSION}")

    BASE = Path.cwd()

    options_file = BASE / 'options.txt'
    if not options_file.exists():
        log("E: options missing error", file=sys.stderr)
        sys.exit(1)

    options = json.loads(options_file.read_text())  # type: dict

    try:
        options.setdefault("version", "0.1")
        options.setdefault("java_reversion", "0.1")
        package_index_url = options['url']  # 'file:///D:/Launcher/Remote/index.json'
        package_name = options['package']  # hello
    except KeyError as e:
        log(f"E: setting {e.args[0]!r} missing", file=sys.stderr)
        sys.exit(1)
    else:
        vm_opt_str = options.setdefault('vm_opt',
                                        "-Xmx8G -XX:+UseConcMarkSweepGC -XX:+CMSIncrementalMode -XX:-UseAdaptiveSizePolicy -Xmn768M")
        keep_launcher = options.setdefault('keep_launcher', True)

    try:
        java = MojangJava(BASE / "Runtime")

        if options["version"] == "0.1":
            options["version"] = "0.2"
            options["package"] = "mint"

        if options["java_reversion"] == "0.1":
            for _, _, _, folder in java.find_runtime():
                shutil.rmtree(folder)

            options["java_reversion"] = "0.2"

        options_file.write_text(json.dumps(options, indent=4))
    except BaseException:
        log("has error while setup options")
    finally:
        log()

        mps = Modpacks(package_index_url, BASE / 'Instance')

        log("I: server's general infomation")
        log(prettyjson(mps))
        log()

        launcher = mps.get("launcher", {})
        if not launcher:
            log("W: there is no launcher infomation")
        else:
            if launcher.get("version") != LAUNCHER_VERSION:
                log("I: You need update to new launcher!")
                url = launcher.get("url")
                if url:
                    log("I: launcher url =", url)
                    webbrowser.open(url)
                sys.exit(1)
            else:
                log("I: launcher is latest.")

    try:
        lmp = mps.raw_package(package_name)
    except JSONDecodeError as e:
        log(f"I: local package {package_name!r} are broken")
        log("I: - JSONDecodeError:", e)
    except FileNotFoundError:
        log(f"I: local package {package_name!r} missing")
    else:
        if (mps.path / package_name / "modpack.done").exists():
            log(f"I: local package {package_name!r} infomation")
            log(prettyjson({
                "id": lmp.get("id"),
                "name": lmp.get("name"),
                "time": lmp.get("time"),
                "version": lmp.get("version"),
            }))
            log()
        else:
            log(f"W: local package {package_name!r} required update (modpack.done missing)")

    mp = mps.package(package_name)

    log("I: enter package update")
    try:
        mp_result = mp()
        if "has_keepmods" in mp_result:
            log("I: package has keepmods!")
    except:
        log("E: failure package update", file=sys.stderr)
        raise
    else:
        log("I: finish package update")

    if java.runtime is None:
        log("I: enter java update")

    try:
        runtime = java()  # type: Path
    except:
        log("E: failure java update", file=sys.stderr)
        raise
    else:
        log("I: java updated")

    APPDATA = Path(os.environ.get("APPDATA"))
    mpkg = MojangMinecraftPackage(APPDATA / ".minecraft")
    mc = mpkg.build(package_name, mp)

    log("I: enter minecraft update")
    try:
        mc()
    except:
        log("E: failure minecraft update", file=sys.stderr)
        raise
    else:
        log("I: finish minecraft update")

    print("I: minecraft profile checking")

    try:
        profile = mpkg.profile
    except FileNotFoundError:
        log("E: minecraft profile missing (please download minecraft launcher)")
        sys.exit(1)

    clientToken = profile.clientToken
    if not clientToken:
        log("E: minecraft profile currupt (missing clientToken)", file=sys.stderr)
        sys.exit(1)

    selectedAccount = profile.selectedAccount
    if not selectedAccount:
        log("E: minecraft profile currupt (missing selectedUser)", file=sys.stderr)
        sys.exit(1)

    auth_uuid = selectedAccount.auth_uuid
    if not auth_uuid:
        log("E: minecraft profile currupt (missing selectedUser.profile)", file=sys.stderr)
        sys.exit(1)

    auth_player_name = selectedAccount.auth_player_name
    if not auth_player_name:
        log("E: minecraft profile currupt (missing displayName)", file=sys.stderr)
        sys.exit(1)

    auth_access_token = selectedAccount.auth_access_token
    if not auth_access_token:
        log("E: minecraft profile currupt (missing accessToken)", file=sys.stderr)
        sys.exit(1)

    try:
        api_result = mojang_api.validate_access_token(auth_access_token, client_token=clientToken)
    except ValueError:
        # Actually this is successful response..?
        api_result = {}

    if api_result.get('error'):
        log("I: mojang token refreshing...")
        api_result = mojang_api.refresh_access_token(auth_access_token, client_token=clientToken)
        if not api_result.get('error'):
            auth_access_token = api_result.accessToken

            profile["authenticationDatabase"][selectedAccount.account]['accessToken'] = auth_access_token + "!"
            selectedAccount["accessToken"] = auth_access_token

            try:
                mpkg.profile_write(profile)
            except:
                log("E: mojang profile write failure", file=sys.stderr)
                raise
            else:
                log("I: mojang token successful refreshed")
        else:
            log("E: mojang token refresh failed (please login with minecraft launcher)", file=sys.stderr)
            log("E: error message from mojang:", api_result.get('errorMessage', 'errorMessage missing'),
                file=sys.stderr)
            sys.exit(1)

    print("I: finish profile checking")

    options = {
        'version_name': mp['version'],
        'game_directory': mp.path.relative_to(mp.path),
        'assets_root': mc.path / 'assets',
        'assets_index_name': mc['assets'],
        'auth_uuid': auth_uuid,
        'auth_access_token': auth_access_token,
        'auth_player_name': auth_player_name,
        'user_type': 'mojang',
    }

    arguments = mc['minecraftArguments']
    for key, value in options.items():
        arguments = arguments.replace("${" + key + "}", str(value))

    classpath = []

    for library in mc.libraries:
        if library.action == 'allow':
            path = mc.path / library.local_path
            if path.exists():
                classpath.append(path)

    classpath.append(mc.client.local_path)

    os_version_options = []
    if platform.system() == 'Windows' and platform.release() == '10':
        os_version_options.extend([
            "-Dos.name=Windows 10",
            "-Dos.version=10.0",
        ])

    if not keep_launcher:
        runtime = runtime.with_name("javaw.exe")

    # https://github.com/EcmaXp/LilyLauncher/blob/master/LilyLauncher/Minecraft/McOptions.cs
    args = [
        f'{runtime}',
        *os_version_options,
        f"-Djava.library.path={mc.native_path}",
        f'-Dminecraft.launcher.brand=SM_REBoot-Launcher',
        f'-Dminecraft.launcher.version=1.0',
        f'-Dminecraft.client.jar={mc.client.local_path}',
        "-cp",
        ";".join(map(str, classpath)),
        *vm_opt_str.split(),
        f"{mc['mainClass']}",
        *arguments.split(),
    ]

    log()
    log("I: argument info:")
    has_classpath = False
    for arg in args:
        if has_classpath:
            for p in arg.split(";"):
                log(" ", p)
            has_classpath = False
            continue

        if arg.startswith("--"):
            log(arg, end=" ")
        elif arg.startswith("-cp"):
            log(arg)
            has_classpath = True
        else:
            log(arg)
    log()
    log("I: start minecraft")

    proc = subprocess.Popen(
        args,
        cwd=f'{mp.path}'
    )

    if keep_launcher:
        sys.exit(proc.wait())
    else:
        try:
            sys.exit(proc.wait(timeout=10))
        except subprocess.TimeoutExpired:
            sys.exit(0)


def main():
    try:
        launch()
    except SystemExit as e:
        if e.code != 0:
            log("E: exitcode =", e.code)
            subprocess.Popen(["pause"], shell=True).wait()

        raise
    except Exception:
        traceback.print_exc()
        traceback.print_exc(file=log_file)
        subprocess.Popen(["pause"], shell=True).wait()
    finally:
        clear_session()


if __name__ == '__main__':
    main()
