import sys,re,plistlib
from pathlib import Path
root=Path(sys.argv[1])
project=root/'StS2.xcodeproj/project.pbxproj'
text=project.read_text()
text=re.sub(r'DEVELOPMENT_TEAM = [^;]*;', 'DEVELOPMENT_TEAM = "";',text)
text=text.replace('Apple Distribution','Apple Development')
# FMOD's dynamic framework looks this symbol up in the main executable.
# `used` keeps it in the object file, but Xcode's -dead_strip removes it unless
# the linker retains it. Export it for dyld's dynamic-lookup binding as well.
def retain_fmod_loader(match):
    flags=match.group(2)
    for flag in ('-Wl,-u,_load_all_fmod_plugins','-Wl,-export_dynamic'):
        if flag not in flags:
            flags+=' '+flag
    return match.group(1)+flags+match.group(3)
text,config_count=re.subn(r'(OTHER_LDFLAGS\s*=\s*")([^"]*)(";)',retain_fmod_loader,text)
assert config_count==2, f'Expected Debug/Release linker settings, found {config_count}'
project.write_text(text)
dummy=root/'StS2/dummy.cpp'
if 'load_all_fmod_plugins' not in dummy.read_text():
    with dummy.open('a') as f:
        f.write('\nextern "C" __attribute__((visibility("default"))) __attribute__((used))\nunsigned int *load_all_fmod_plugins(void *, unsigned int *count) { if (count) *count = 0; return nullptr; }\n')
