import base64
import json
import runpy
import shutil
import sys
from pathlib import Path
from pprint import pprint

import paramiko
import requests

from nupdate.build import build_pyz
from nupdate.utils import calc_sha1_hash


def build_launcher():
    DIST_FOLDER = Path('dist')
    LAUNCHER_DIR = (DIST_FOLDER / "launcher")

    json.loads((LAUNCHER_DIR / "options.txt").read_text())

    prev_hash = calc_sha1_hash(DIST_FOLDER / "SM-RE.exe")

    argv, sys.argv = sys.argv = ['...', 'bdist_exe']
    try:
        runpy.run_path("setup.py")
    finally:
        sys.argv = argv

    next_hash = calc_sha1_hash(DIST_FOLDER / "SM-RE.exe")

    if prev_hash != next_hash:
        shutil.copy((DIST_FOLDER / "SM-RE.exe"), LAUNCHER_DIR)
        return Path(shutil.make_archive("launcher", "zip", LAUNCHER_DIR))
    else:
        raise Exception("failure compile")


launcher_path = build_launcher()
pyz_path = build_pyz()
assert pyz_path.exists()
assert launcher_path.exists()

# Note. this is not password
server_auth_key = b'AAAAB3NzaC1yc2EAAAADAQABAAABAQDILRxAzEUdZZU9zNXJTF8L5UAuZKW0nsSF3yBfOM0U8bHt98Qa8v5FELRnbLYXcCK3x9UJ55O9U5VnX4tKEiSoXc3IoxfQrQfTuOpMJsvpAbfRrIFKSrRTBD3VoCWB4gBpuQEGzrhZW9VIV3nFiufuu0dMzmJyuPcWbYmoTlpAiyzs/68GuXW82DuPCv69X3LD2GCcSqZ6lA8P8JNwXuIbAEZMfBq/Ts8QV8TNHdV9uE/FjZa1a6vpporf+2C34Mk/pesqROBL2UsZUEDbL1S1kbHXwMr5Wn3q8tr+n+TRsYItRP0J7vjTdDbBcTrIAKCabCuwCTjLdD2j9dC/Mi47'

skey = paramiko.RSAKey(data=base64.b64decode(server_auth_key))

key = paramiko.RSAKey(filename="ssh-rsa.key")

client = paramiko.SSHClient()
client.get_host_keys().add('mc.nyang.kr', 'ssh-rsa', skey)
client.connect('mc.nyang.kr', username='signet', pkey=key)

sftp: paramiko.SFTPClient = client.open_sftp()

sftp.put(pyz_path, "/home/signet/.nupdate.pyz")
# noinspection PyTypeChecker
sftp.put(launcher_path, "/home/signet/web/launcher.zip")

stdin, stdout, stderr = client.exec_command("/home/signet/instance/etp/update-etp.sh")
for line in stderr:
    print(line, end='')

pprint(requests.get("https://mc.nyang.kr/packages/").json())
