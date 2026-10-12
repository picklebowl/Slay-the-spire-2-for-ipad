"""Recover publication from a completed build; never compile or run a downloaded app."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REPO = os.environ['GITHUB_REPOSITORY']
ARTIFACT = 'StS2-iPad-Windows-Assistant'

def gh(*arguments):
    result = subprocess.run(['gh', *arguments], check=False, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('GitHub command failed: ' + result.stderr.strip()[:1000])
    return result.stdout.strip()

def api(suffix):
    return json.loads(gh('api', 'repos/' + REPO + ('/' + suffix if suffix else '')))

def exists_release(tag):
    result = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPO], capture_output=True)
    return result.returncode == 0

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def record(**values):
    (ROOT / 'publish-result.json').write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(values, ensure_ascii=True))

def main():
    if not api('')['private']:
        raise ValueError('Private game builds may only be published in a private repository')
    requested = os.environ.get('BUILD_RUN_ID', '')
    if requested:
        if not re.fullmatch(r'[0-9]{1,20}', requested):
            raise ValueError('Invalid build run ID')
        run = api('actions/runs/' + requested)
    else:
        runs = api('actions/workflows/build-assistant.yml/runs?per_page=30')['workflow_runs']
        completed = [r for r in runs if r['status'] == 'completed' and r['head_branch'] == 'main']
        if not completed:
            record(publication='waiting_for_completed_build')
            return
        run = completed[0]
    if run['status'] != 'completed' or run['head_branch'] != 'main' or run['name'] != 'Build Windows iPad assistant' or run['head_repository']['id'] != run['repository']['id']:
        raise ValueError('Expected a completed main-branch assistant build')
    matches = [a for a in api('actions/runs/' + str(run['id']) + '/artifacts')['artifacts']
               if a['name'] == ARTIFACT and not a['expired']]
    if len(matches) != 1:
        record(build_run=run['id'], publication='no_completed_package')
        return
    package = ROOT / 'publish-input'
    package.mkdir()
    gh('run', 'download', str(run['id']), '--repo', REPO, '--name', ARTIFACT, '--dir', str(package))
    checksums = {}
    for line in (package / 'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        expected, name = line.split('  ', 1)
        if name not in ('StS2-iPad-Assistant-Setup.exe', 'StS2-iPad-Assistant-portable.zip'):
            raise ValueError('Unexpected package entry')
        if digest(package / name) != expected.lower():
            raise ValueError('Package checksum does not match the completed build')
        checksums[name] = expected.lower()
    if len(checksums) != 2:
        raise ValueError('Incomplete assistant package')
    spec = json.loads((ROOT / 'windows-assistant/payload.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(package / 'StS2-iPad-Assistant-portable.zip') as archive:
        ipa_entry = archive.getinfo('payload/StS2-iPad-unsigned.ipa')
        if ipa_entry.file_size != spec['ipa_bytes']:
            raise ValueError('Unexpected game IPA size')
        ipa = package / 'StS2-iPad-unsigned.ipa'
        with archive.open(ipa_entry) as source, ipa.open('wb') as output:
            while data := source.read(1024**2):
                output.write(data)
        if digest(ipa) != spec['ipa_sha256']:
            raise ValueError('Unverified game build')
        paths = archive.getinfo('payload/cs_paths.txt')
        if paths.file_size > 1024**2:
            raise ValueError('Unexpected script path list')
        (package / 'cs_paths.txt').write_bytes(archive.read(paths))
        info = json.loads(archive.read('payload/build-info.json')) if 'payload/build-info.json' in archive.namelist() else None
    game_tag = 'game-build-' + spec['game_version']
    if not exists_release(game_tag):
        gh('release', 'create', game_tag, '--repo', REPO, '--target', 'main', '--prerelease',
           '--title', '已验证的私有游戏构建 ' + spec['game_version'],
           '--notes', '游戏 IPA 源自 ae02eef29f48a8ed142f0c2fc1469673565993ce；本次保存前校验固定 SHA256。不得公开。')
    gh('release', 'upload', game_tag, str(ipa), str(package / 'cs_paths.txt'), '--repo', REPO, '--clobber')
    if not info:
        record(build_run=run['id'], game_build_preserved=True, publication='old_package_without_provenance')
        return
    if info['assistant_source_commit'] != run['head_sha']:
        raise ValueError('Package source revision does not match its workflow run')
    comparison = api('compare/' + run['head_sha'] + '...main')
    if comparison['status'] not in ('ahead', 'identical') or len(comparison['files']) >= 300:
        raise ValueError('Cannot establish package source equivalence')
    relevant = ('windows-assistant/', 'tools/', 'private-inputs-manifest.json', 'UPSTREAM-LICENSE.txt')
    changed = [f['filename'] for f in comparison['files'] if f['filename'].startswith(relevant)]
    if changed:
        record(build_run=run['id'], game_build_preserved=True, publication='newer_assistant_source_exists', changed=changed)
        return
    version = info['assistant_version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Invalid assistant version')
    tag = 'assistant-v' + version
    title = 'iPad 安装与续签助手 v' + version
    notes = str(ROOT / 'windows-assistant/START-HERE.md')
    if not exists_release(tag):
        gh('release', 'create', tag, '--repo', REPO, '--target', 'main', '--title', title, '--notes-file', notes, '--latest')
    else:
        gh('release', 'edit', tag, '--repo', REPO, '--title', title, '--notes-file', notes, '--latest')
    gh('release', 'upload', tag, *(str(package / name) for name in (*checksums, 'SHA256SUMS.txt')),
       '--repo', REPO, '--clobber')
    release = api('releases/tags/' + tag)
    assets = {a['name']: a for a in release['assets']}
    for name, expected in checksums.items():
        if name not in assets or assets[name].get('digest') != 'sha256:' + expected:
            raise ValueError('Published asset digest does not match the verified package')
    record(build_run=run['id'], source_commit=run['head_sha'], assistant_version=version,
           game_build_preserved=True, publication='verified', release_url=release['html_url'], sha256=checksums)

if __name__ == '__main__':
    main()
