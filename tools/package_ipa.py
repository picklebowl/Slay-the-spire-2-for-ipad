import sys,shutil,subprocess,plistlib,json,zipfile,hashlib
from pathlib import Path
archive=Path(sys.argv[1]); output=Path(sys.argv[2])
apps=list((archive/'Products/Applications').glob('*.app'))
assert len(apps)==1, 'Expected exactly one archived app'
stage=output.parent/'ipa-stage/Payload'; stage.mkdir(parents=True,exist_ok=True)
app=stage/apps[0].name
assert not app.exists(), 'Packaging stage already exists'
shutil.copytree(apps[0],app,symlinks=True)
plist=app/'Info.plist'
info=plistlib.loads(plist.read_bytes())
info.update(UIFileSharingEnabled=True,LSSupportsOpeningDocumentsInPlace=True,
    UIDeviceFamily=[2],godot_cmdline=['--main-pack','user://StS2.pck','--rendering-method','mobile','--','nomods'],
    UISupportedInterfaceOrientations=['UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight'])
assert (app/info['CFBundleExecutable']).is_file(), 'Main executable missing'
plist.write_bytes(plistlib.dumps(info))
for p in app.glob('*.pck'):p.unlink()
ent=output.parent/'entitlements.plist'
ent.write_bytes(plistlib.dumps({'com.apple.developer.kernel.increased-memory-limit':True}))
frameworks=app/'Frameworks'
for p in sorted(frameworks.rglob('*.framework'),key=lambda x:len(x.parts),reverse=True):
    subprocess.run(['codesign','--force','--sign','-',str(p)],check=True)
for p in frameworks.rglob('*.dylib'):
    subprocess.run(['codesign','--force','--sign','-',str(p)],check=True)
subprocess.run(['codesign','--force','--sign','-','--entitlements',str(ent),str(app)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
subprocess.run(['zip','-qry',str(output.resolve()),'Payload'],cwd=stage.parent,check=True)
with zipfile.ZipFile(output) as z:
    assert not any(n.endswith('.pck') for n in z.namelist())
    bundled=plistlib.loads(z.read('Payload/'+app.name+'/Info.plist'))
    assert bundled['godot_cmdline'][1]=='user://StS2.pck'
manifest={'ipa_sha256':hashlib.file_digest(output.open('rb'),'sha256').hexdigest(),
    'bytes':output.stat().st_size,'game_version':'v0.111.0',
    'bundle_id':info['CFBundleIdentifier'], 'runtime':'NativeAOT; no JIT',
    'status':'Build only; iPad Air device/offline/performance tests pending'}
(output.parent/'build-manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps(manifest,indent=2))
