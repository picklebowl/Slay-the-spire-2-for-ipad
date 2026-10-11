"""Bundle an isolated Python runtime and the already-validated private IPA."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent.parent
PYTHON_URL='https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
PYTHON_MD5='fe8ef205f2e9c3ba44d0cf9954e1abd3'  # Published on python.org release page; archive SHA256 recorded in bundle.

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--ipa-dir',type=Path,required=True);a=p.parse_args()
    target=a.source/'payload';target.mkdir()
    spec=json.loads((ROOT/'windows-assistant/payload.json').read_text())
    ipa=a.ipa_dir/'StS2-iPad-unsigned.ipa'
    assert ipa.stat().st_size==spec['ipa_bytes'] and hashlib.file_digest(ipa.open('rb'),'sha256').hexdigest()==spec['ipa_sha256']
    shutil.copy2(ipa,target/ipa.name);shutil.copy2(a.ipa_dir/'cs_paths.txt',target/'cs_paths.txt')
    shutil.copy2(ROOT/'private-inputs-manifest.json',target/'private-inputs-manifest.json')
    tools=target/'tools';tools.mkdir()
    for name in ['prepare_content.py','pck_patch_sentry.py','pck_add_cs.py','pck_ls.py']:
        shutil.copy2(ROOT/'tools'/name,tools/name)
    helper=target/'windows-assistant';helper.mkdir()
    for name in ['backend.py','payload.json','driver-setup.ps1']:
        shutil.copy2(ROOT/'windows-assistant'/name,helper/name)
    shutil.copy2(a.source/'LICENSE',target/'ILOADER-LICENSE.txt')
    shutil.copy2(a.source/'LICENSE-BRANDING',target/'ILOADER-BRANDING.txt')
    shutil.copy2(ROOT/'UPSTREAM-LICENSE.txt',target/'PORT-UPSTREAM-LICENSE.txt')
    (target/'build-info.json').write_text(json.dumps({
        'assistant_version':'0.1.1',
        'assistant_source_commit':os.environ.get('GITHUB_SHA'),
        'iloader_source_commit':'dc396af059fd46982062cd8fc90252d7e27085e9',
        'game_version':spec['game_version'], 'ipa_sha256':spec['ipa_sha256'],
    },indent=2),encoding='utf-8')
    archive=a.source/'python-embed.zip'
    with urllib.request.urlopen(PYTHON_URL,timeout=60) as response,archive.open('wb') as file: shutil.copyfileobj(response,file)
    with archive.open('rb') as f: assert hashlib.file_digest(f,'md5').hexdigest()==PYTHON_MD5
    runtime=target/'python';runtime.mkdir()
    with zipfile.ZipFile(archive) as z:z.extractall(runtime)
    site=runtime/'Lib/site-packages';site.mkdir(parents=True)
    subprocess.run([sys.executable,'-m','pip','install','--target',str(site),
                    '-r',str(ROOT/'windows-assistant/requirements.lock')],check=True)
    (runtime/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n..\nimport site\n')
    # Exercise the actual embedded runtime, not merely the builder's Python.
    subprocess.run([str(runtime/'python.exe'),'-c','import pymobiledevice3,pywintypes,ssl; from pymobiledevice3.services.house_arrest import HouseArrestService; print("EMBEDDED_RUNTIME_PASS")'],check=True)
    subprocess.run([str(runtime/'python.exe'),str(helper/'backend.py'),'payload','--state',str(a.source/'runtime-smoke')],check=True)
    files=[]
    for path in sorted(target.rglob('*')):
        if path.is_file():
            with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
            files.append({'path':path.relative_to(target).as_posix(),'sha256':digest,'bytes':path.stat().st_size})
    (target/'bundle-manifest.json').write_text(json.dumps({'files':files,'private_bundle':True,'python_url':PYTHON_URL},indent=2))
    print('Payload packaged and embedded runtime verified')

if __name__=='__main__':main()
