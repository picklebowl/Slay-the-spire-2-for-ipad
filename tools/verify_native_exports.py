"""Check the arm64 executable's actual dyld export trie, not just its symbols."""
import struct
from pathlib import Path


def exported_symbols(data):
    if data[:4] == bytes.fromhex('cafebabe'):
        slices = [struct.unpack_from('>IIIII', data, 8 + 20*i)
                  for i in range(struct.unpack_from('>I', data, 4)[0])]
        arm64 = next(s for s in slices if s[0] == 0x100000c)
        data = data[arm64[2]:arm64[2]+arm64[3]]
    assert data[:4] == bytes.fromhex('cffaedfe'), 'Expected 64-bit Mach-O'
    assert struct.unpack_from('<I', data, 4)[0] == 0x100000c, 'Expected arm64'
    offset, trie_range = 32, None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, offset)
        if cmd == 0x80000033:  # LC_DYLD_EXPORTS_TRIE
            trie_range = struct.unpack_from('<II', data, offset+8)
        elif cmd in (0x22, 0x80000022):  # LC_DYLD_INFO / LC_DYLD_INFO_ONLY
            if trie_range is None:
                trie_range = struct.unpack_from('<II', data, offset+40)
        assert size >= 8
        offset += size
    assert trie_range and trie_range[1], 'Dynamic exports missing'
    start, size = trie_range
    trie = data[start:start+size]
    assert len(trie) == size, 'Truncated export trie'

    def uleb(position):
        value, shift = 0, 0
        while True:
            byte = trie[position]
            position += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value, position
            shift += 7
            assert shift < 64, 'Invalid export value'

    symbols, pending, seen = {}, [(0, '')], set()
    while pending:
        position, prefix = pending.pop()
        assert position not in seen, 'Invalid export trie cycle'
        seen.add(position)
        terminal_size, position = uleb(position)
        children_position = position + terminal_size
        if terminal_size:
            flags, value_position = uleb(position)
            value, _ = uleb(value_position)
            symbols[prefix] = (flags, value)
        child_count = trie[children_position]
        position = children_position + 1
        for _ in range(child_count):
            end = trie.index(0, position)
            suffix = trie[position:end].decode('utf-8')
            child, position = uleb(end+1)
            pending.append((child, prefix+suffix))
    return symbols


def verify_fmod_loader(executable):
    symbols = exported_symbols(Path(executable).read_bytes())
    entry = symbols.get('_load_all_fmod_plugins')
    assert entry is not None, 'FMOD plugin-loader entry missing from dynamic exports'
    flags, address = entry
    assert flags == 0 and address > 0, 'FMOD loader must be a defined regular export'
    print(f'FMOD plugin loader dynamically exported at 0x{address:x}')
    return address


if __name__ == '__main__':
    import sys
    verify_fmod_loader(sys.argv[1])
