import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parents[1]/'backend.py'
spec=importlib.util.spec_from_file_location('backend',path)
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class Afc:
    def __init__(self, files=None, corrupt=False, disconnect=False):
        self.files=dict(files or {});self.handles={};self.writes=0;self.renames=[];self.corrupt=corrupt;self.disconnect=disconnect
    async def exists(self,p): return p in self.files or any(x.startswith(p+'/') for x in self.files)
    async def stat(self,p):
        if p in self.files:return {'st_ifmt':'S_IFREG','st_size':len(self.files[p])}
        return {'st_ifmt':'S_IFDIR'}
    async def listdir(self,p):return sorted(set(x.removeprefix(p+'/').split('/')[0] for x in self.files if x.startswith(p+'/')))
    async def get_file_contents(self,p):return self.files[p]
    async def fopen(self,p,mode):
        handle=len(self.handles)+1;self.handles[handle]=[p,0]
        if mode=='w': self.files[p]=b''
        elif mode=='a': self.files.setdefault(p,b'')
        return handle
    async def fread(self,h,n):
        p,off=self.handles[h];data=self.files[p][off:off+n];self.handles[h][1]+=len(data);return data
    async def fwrite(self,h,data):
        self.writes+=1
        if self.disconnect:raise ConnectionError('disconnect')
        p,_=self.handles[h];self.files[p]+= (b'x'*len(data) if self.corrupt else data)
    async def fclose(self,h):pass
    async def rename(self,a,c):self.renames.append((a,c));self.files[c]=self.files.pop(a)

class Tests(unittest.TestCase):
    def setUp(self):
        base=(Path.cwd()/'work/assistant-tests').resolve();base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.state=Path(self.tmp.name).resolve()
        assert self.state.is_relative_to(base)
        self.data=b'verified owned game content'
        self.spec={'resource_sha256':hashlib.sha256(self.data).hexdigest(),'resource_bytes':len(self.data),'game_version':'v0.111.0','original_assembly_sha256':hashlib.sha256(b'dll').hexdigest()}
        (self.state/'content').mkdir();(self.state/'content/StS2.pck').write_bytes(self.data)
        self.patcher=patch.object(b,'manifest',return_value=self.spec);self.patcher.start()
    def tearDown(self):self.patcher.stop();self.tmp.cleanup()
    def upload(self,afc):return asyncio.run(b.upload(afc,self.state))
    def test_valid_upload_verified_before_activation(self):
        afc=Afc();r=self.upload(afc)
        self.assertTrue(r['resource_verified']);self.assertEqual(afc.files['/Documents/StS2.pck'],self.data);self.assertEqual(len(afc.renames),1)
    def test_interrupted_upload_never_activates(self):
        afc=Afc(disconnect=True)
        with self.assertRaises(ConnectionError):self.upload(afc)
        self.assertNotIn('/Documents/StS2.pck',afc.files);self.assertEqual(afc.renames,[])
    def test_corrupt_readback_never_activates(self):
        afc=Afc(corrupt=True)
        with self.assertRaises(ValueError):self.upload(afc)
        self.assertNotIn('/Documents/StS2.pck',afc.files);self.assertEqual(afc.renames,[])
    def test_same_resource_is_not_rewritten(self):
        afc=Afc({'/Documents/StS2.pck':self.data});r=self.upload(afc)
        self.assertTrue(r['resource_reused']);self.assertEqual(afc.writes,0);self.assertEqual(afc.renames,[])
    def test_partial_resource_resumes_after_prefix_check(self):
        stage='/Documents/StS2.pck.uploading-assistant-'+self.spec['resource_sha256'][:16]
        afc=Afc({stage:self.data[:10]});self.upload(afc)
        self.assertEqual(afc.files['/Documents/StS2.pck'],self.data)
    def test_corrupt_owned_staging_is_rebuilt(self):
        stage='/Documents/StS2.pck.uploading-assistant-'+self.spec['resource_sha256'][:16]
        afc=Afc({stage:b'garbage'});self.upload(afc)
        self.assertEqual(afc.files['/Documents/StS2.pck'],self.data)
    def test_different_resource_is_not_overwritten(self):
        afc=Afc({'/Documents/StS2.pck':b'old'})
        with self.assertRaises(ValueError):self.upload(afc)
        self.assertEqual(afc.files['/Documents/StS2.pck'],b'old');self.assertEqual(afc.writes,0)
    def test_bad_local_resource_prevents_usb_write(self):
        (self.state/'content/StS2.pck').write_bytes(b'bad');afc=Afc()
        with self.assertRaises(ValueError):self.upload(afc)
        self.assertEqual(afc.writes,0);self.assertEqual(afc.files,{})
    def test_backup_only_own_saves_and_settings(self):
        afc=Afc({'/Documents/default/1/settings.save':b'settings','/Documents/default/1/profile1/saves/progress.save':b'progress','/Documents/StS2.pck':self.data,'/Documents/logs/log.txt':b'private'})
        result=asyncio.run(b.backup(afc,self.state));entries=json.loads((Path(result['backup_folder'])/'manifest.json').read_text())
        self.assertEqual(len(entries),2);self.assertTrue(all(e['path'].startswith('default/') for e in entries));self.assertEqual(afc.writes,0)
    def test_backup_verification_detects_changed_save(self):
        afc=Afc({'/Documents/default/1/profile1/saves/progress.save':b'progress'})
        r=asyncio.run(b.backup(afc,self.state));afc.files['/Documents/default/1/profile1/saves/progress.save']=b'changed!'
        with self.assertRaises(ValueError):asyncio.run(b.verify_backup(afc,self.state,r['backup_folder']))
        self.assertEqual(afc.writes,0)
    def test_backup_verification_detects_missing_save(self):
        afc=Afc({'/Documents/default/1/profile1/saves/progress.save':b'progress'})
        r=asyncio.run(b.backup(afc,self.state));afc.files.clear()
        with self.assertRaises(ValueError):asyncio.run(b.verify_backup(afc,self.state,r['backup_folder']))
    def test_renew_check_does_not_write_saves(self):
        afc=Afc({'/Documents/default/1/profile1/saves/progress.save':b'progress'})
        r=asyncio.run(b.backup(afc,self.state));v=asyncio.run(b.verify_backup(afc,self.state,r['backup_folder']))
        self.assertTrue(v['saves_preserved']);self.assertEqual(afc.writes,0)
    def test_backup_folder_cannot_escape(self):
        with self.assertRaises(ValueError):asyncio.run(b.verify_backup(Afc(),self.state,self.state.parent))
    def test_backup_manifest_cannot_escape(self):
        folder=self.state/'backups/test';folder.mkdir(parents=True)
        (folder/'manifest.json').write_text(json.dumps([{'path':'default/../../secret','bytes':0,'sha256':''}]))
        with self.assertRaises(ValueError):asyncio.run(b.verify_backup(Afc(),self.state,folder))
    def game(self,version='v0.111.0',dll=b'dll'):
        game=self.state/'game';game.mkdir();(game/'release_info.json').write_text(json.dumps({'version':version}));(game/'data_sts2_windows_x86_64').mkdir();(game/'data_sts2_windows_x86_64/sts2.dll').write_bytes(dll);return game
    def test_matching_steam_game(self):self.assertEqual(b.validate_game(self.game()),(self.state/'game').resolve())
    def test_game_version_mismatch_stops(self):
        with self.assertRaises(ValueError):b.validate_game(self.game('v9.0'))
    def test_game_assembly_mismatch_stops(self):
        with self.assertRaises(ValueError):b.validate_game(self.game(dll=b'updated'))
    def test_multiple_game_copies_require_selection(self):
        game=self.game()
        with patch.object(b,'game_roots',return_value=[game,game]):
            with self.assertRaises(ValueError):b.detect_game()
    def test_manual_valid_game_selection(self):self.assertEqual(b.detect_game(str(self.game())),(self.state/'game').resolve())
    def test_state_write_is_readable(self):b.write_state(self.state,{'bundle_id':b.BUNDLE_PREFIX});self.assertEqual(b.read_state(self.state)['bundle_id'],b.BUNDLE_PREFIX)

if __name__=='__main__':unittest.main()
