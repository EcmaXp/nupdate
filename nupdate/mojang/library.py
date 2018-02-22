from pathlib import Path
from urllib.parse import urljoin

from nupdate.config import OS_NAME
from nupdate.mojang.download import MojangDownload
from nupdate.utils import Namespace, Fetchable

if False:
    from nupdate.mojang.minecraft import MojangMinecraftJson


class Downloads(Namespace):
    @property
    def maven(self):
        return MavenDownload(self['maven'])

    @property
    def artifact(self):
        return ArtifactDownload(self['artifact'])

    @property
    def classifiers(self):
        classifiers = self.get('classifiers')
        return ClassifiersDownloads(classifiers) if classifiers else None

    def __iter__(self):
        for name in super().__iter__():
            if name == 'maven':
                yield self.maven
            elif name == 'artifact':
                yield self.artifact
            elif name == 'classifiers':
                pass
            else:
                raise Exception


class MojangLibrary(Namespace):
    def __init__(self, mc: "MojangMinecraftJson", data):
        super().__init__(data)
        self.mc = mc
        self._action = None

    @property
    def id(self):
        domain, name, version = self.name.split(":")
        return domain, name

    @property
    def name(self) -> str:
        return self['name']

    @property
    def path(self):
        domain, name, version = self.name.split(":")
        return f"libraries/{domain.replace('.', '/')}/{name}/{version}/{name}-{version}.jar"

    @property
    def local_path(self):
        return self.mc.path / self.path

    @property
    def rules(self):
        yield from self.get('rules', ())

    @property
    def downloads(self) -> Downloads:
        downloads = self.setdefault('downloads', {})
        if self._has_url():
            downloads['maven'] = MavenDownload._get_maven_download(self, self.name)

        return Downloads(downloads)

    def _has_url(self):
        return "url" in self

    @property
    def action(self):
        if self._action is not None:
            return self._action
        os_info = {'name': OS_NAME}

        rule = None
        action = None
        for rule in self.rules:
            new_action = rule.get('action')
            rule_os_info = rule.get('os')
            if not rule_os_info or rule_os_info == os_info:
                action = new_action

        if action is None:
            action = 'disallow' if rule else 'allow'

        self._action = action
        return action

    @property
    def natives(self):
        return self.get('natives')

    @property
    def extract(self):
        return self.get('extract')

    @property
    def native(self):
        natives = self.natives
        if natives:
            classifiers = self.downloads.classifiers
            if classifiers is None:
                raise Exception

            return classifiers[natives.get(OS_NAME)]

        return None

    def download(self):
        action = self.action
        if action == "allow":
            for download in self.downloads:
                if isinstance(download, ArtifactDownload):
                    download(self.mc.path)
                elif isinstance(download, MavenDownload):
                    download(self.mc.path)
                else:
                    raise Exception

            if self.natives:
                download = self.native
                download(self.mc.path)
        elif action == 'disallow':
            return
        else:
            raise Exception

    def __repr__(self):
        return f"<{type(self).__name__}: {self.name}>"


class LibraryDownload(Fetchable, Namespace):
    @property
    def path(self):
        return f"libraries/{self['path']}"


class ClassifiersDownloads(Namespace):
    def __getitem__(self, item):
        return ArtifactDownload(super().__getitem__(item))


class ArtifactDownload(LibraryDownload, MojangDownload):
    pass


class MavenDownload(LibraryDownload):
    def init(self):
        self._domain, self._name, self._version = self.name.split(":")

    @property
    def name(self) -> str:
        return self['name']

    @property
    def repo(self) -> str:
        return self.get('repo')

    @property
    def _file(self):
        return f'{self._name}-{self._version}.jar'

    @property
    def url(self) -> str:
        return f'{urljoin(self.repo, self.path)}.pack.xz'

    @property
    def path(self) -> str:
        return '/'.join((
            'libraries',
            self._domain.replace('.', '/'),
            self._name,
            self._version,
            self._file,
        ))

    def _fetch(self, path: Path):
        return True

    def _check(self, path: Path):
        return True

    @staticmethod
    def _get_maven_download(ctx, name):
        download_maven = {
            'name': name,
            'repo': ctx.get('url'),
        }

        for key in 'checksums', 'serverreq', 'clientreq':
            value = ctx.get(key)
            if value is not None:
                download_maven[key] = value

        return download_maven
