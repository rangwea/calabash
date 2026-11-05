"""Package a pinned official Node runtime and host-controlled frontend compiler."""

import hashlib
import json
import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = 'v24.22.2'


def build_runtime():
    system = {'Darwin': 'darwin', 'Linux': 'linux', 'Windows': 'win'}[platform.system()]
    arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'x64'
    extension = 'zip' if system == 'win' else 'tar.gz'
    prefix = f'node-{NODE_VERSION}-{system}-{arch}'
    filename = prefix + '.' + extension
    cache = ROOT / 'build/node-cache'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / filename
    base = f'https://nodejs.org/dist/{NODE_VERSION}/'
    with urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60) as response:
        expected = next(line.split()[0] for line in response.read().decode().splitlines() if line.split()[-1] == filename)
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        temporary = archive.with_suffix('.download')
        with urllib.request.urlopen(base + filename, timeout=120) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            temporary.unlink()
            raise ValueError('Official Node archive checksum mismatch')
        temporary.replace(archive)
    destination = ROOT / 'build/frontend-runtime'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    members = {'node.exe': 'node.exe', 'LICENSE': 'NODE-LICENSE'} if system == 'win' else {'bin/node': 'node', 'LICENSE': 'NODE-LICENSE'}
    # Extract only exact regular files, never archive paths or symlinks.
    if extension == 'zip':
        with ZipFile(archive) as source:
            for relative, name in members.items():
                (destination / name).write_bytes(source.read(prefix + '/' + relative))
    else:
        with tarfile.open(archive) as source:
            for relative, name in members.items():
                member = source.getmember(prefix + '/' + relative)
                if not member.isfile():
                    raise ValueError('Unexpected Node archive entry')
                (destination / name).write_bytes(source.extractfile(member).read())
    (destination / ('node.exe' if system == 'win' else 'node')).chmod(0o755)
    pending = [ROOT / 'node_modules' / name for name in ('vite', '@vitejs/plugin-vue', 'vue', 'element-plus', '@element-plus/icons-vue', 'echarts', 'typescript', 'vue-tsc')]
    copied = set()
    while pending:
        package = pending.pop()
        if package in copied or not (package / 'package.json').is_file():
            continue
        copied.add(package)
        manifest = json.loads((package / 'package.json').read_text())
        target = destination / package.relative_to(ROOT)
        shutil.copytree(package, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.map', '.cache'))
        for dependency in {**manifest.get('dependencies', {}), **manifest.get('optionalDependencies', {})}:
            for parent in (package, *package.parents):
                candidate = parent / 'node_modules' / dependency
                if (candidate / 'package.json').is_file():
                    pending.append(candidate)
                    break
                if parent == ROOT:
                    break
    (destination / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/tool_frontend.mjs', destination / 'scripts/tool_frontend.mjs')
    shutil.copy2(ROOT / 'scripts/tool_runtime_ui.mjs', destination / 'scripts/tool_runtime_ui.mjs')
    shutil.copy2(ROOT / 'scripts/tool_runtime_guard.js', destination / 'scripts/tool_runtime_guard.js')
    shutil.copy2(ROOT / 'scripts/tool_api_client.ts', destination / 'scripts/tool_api_client.ts')
    (destination / 'component').mkdir()
    shutil.copy2(ROOT / 'component/frontend_probe.js', destination / 'component/frontend_probe.js')
    (destination / 'package.json').write_text(json.dumps({'private': True, 'type': 'module'}))
    (destination / 'provenance.json').write_text(json.dumps({'node': NODE_VERSION, 'archive': filename, 'sha256': expected, 'source': base}))
    return destination


if __name__ == '__main__':
    print(build_runtime())
