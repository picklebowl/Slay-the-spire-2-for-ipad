import sys,re,plistlib
from pathlib import Path
root=Path(sys.argv[1])
project=root/'StS2.xcodeproj/project.pbxproj'
text=project.read_text()
text=re.sub(r'DEVELOPMENT_TEAM = [^;]*;', 'DEVELOPMENT_TEAM = "";',text)
text=text.replace('Apple Distribution','Apple Development')
project.write_text(text)
dummy=root/'StS2/dummy.cpp'
with dummy.open('a') as f:
    f.write('\nextern "C" __attribute__((visibility("default"))) __attribute__((used))\nunsigned int *load_all_fmod_plugins(void *, unsigned int *count) { if (count) *count = 0; return nullptr; }\n')
