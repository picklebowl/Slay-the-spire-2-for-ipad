"""Prepare only a local copy of user-owned assets; never modifies Steam files."""
import argparse,hashlib,json,re,struct,tempfile
from pathlib import Path
from pck_patch_sentry import patch as strip_sentry
from pck_add_cs import patch as add_scripts
from pck_ls import read_dir

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--game',type=Path,required=True)
    parser.add_argument('--paths',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args()
    src=(a.game/'SlayTheSpire2.pck').resolve()
    out=a.out.resolve()
    if out==src or a.game.resolve() in out.parents:
        raise SystemExit('Output must be outside the Steam installation')
    if out.exists():raise SystemExit('Output already exists; choose a new path')
    release=json.loads((a.game/'release_info.json').read_text())
    if release['version']!='v0.111.0':raise SystemExit('This port is validated only against v0.111.0 metadata')
    manifest=json.loads((Path(__file__).parent.parent/'private-inputs-manifest.json').read_text())
    dll=a.game/'data_sts2_windows_x86_64/sts2.dll'
    with dll.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual!=manifest['original_assembly_sha256']:raise SystemExit('Game assembly changed; rebuild the port first')
    paths=[p.strip() for p in a.paths.read_text().splitlines() if p.strip()]
    assert len(set(paths))>600
    assert all(re.fullmatch(r'res://[A-Za-z0-9_/.]+\.cs',p) and '..' not in p.split('/') for p in paths)
    out.parent.mkdir(parents=True,exist_ok=True)
    # Temporary intermediate sits next to the chosen output and is removed only
    # by TemporaryDirectory, never by a computed recursive shell deletion.
    with tempfile.TemporaryDirectory(prefix='sts2-content-',dir=out.parent) as stage:
        temp=Path(stage)/'nosentry.pck'
        strip_sentry(src,temp)
        add_scripts(temp,a.paths,out)
    with out.open('rb') as f:
        entries=read_dir(f)
        lookup={name:(off,size,flags) for name,off,size,flags in entries}
        assert 'addons/sentry/sentry.gdextension' not in lookup
        for name in paths:assert name in lookup, name
        for name in ['.godot/extension_list.cfg','project.binary']:
            off,size,_=lookup[name]; f.seek(off); b=f.read(size)
            assert b'sentry.gdextension' not in b and b'autoload/Sentry' not in b
        # The copy preserves all original asset offsets; validate every file's
        # directory hash, including changed config and new script placeholders.
        f.seek(32); directory=struct.unpack('<Q',f.read(8))[0]
        f.seek(directory); count=struct.unpack('<I',f.read(4))[0]
        expected=[]
        for _ in range(count):
            length=struct.unpack('<I',f.read(4))[0]; name=f.read(length).rstrip(b'\0').decode()
            stored,size=struct.unpack('<QQ',f.read(16)); md5=f.read(16); flags=struct.unpack('<I',f.read(4))[0]
            expected.append((name,md5))
        checked=0
        for name,md5 in expected:
            off,size,flags=lookup[name]
            assert not flags&1, 'Encrypted asset is not supported by this validator'
            f.seek(off); h=hashlib.md5(); remaining=size
            while remaining:
                block=f.read(min(remaining,1024*1024))
                assert block, 'Truncated asset: '+name
                h.update(block); remaining-=len(block)
            assert h.digest()==md5,'Asset hash mismatch: '+name
            checked+=1
    with out.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    report={'game_version':release['version'],'bytes':out.stat().st_size,'sha256':digest,
        'verified_entries':checked,'script_paths':len(set(paths)),
        'sentry_extension_removed':True,'sentry_autoload_disabled':True,
        'status':'Resource integrity verified; iOS execution not tested'}
    out.with_suffix('.manifest.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
