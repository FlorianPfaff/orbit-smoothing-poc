"""Private historical exporter output; original scientific paths/bytes stay fixed.

The frozen objective script creates prepared/output even though its generated
profiles live elsewhere. The historical output directory is absent. Supply a
read-only, byte-identical prepared-parent view with one private mountpoint, then
bind a different fresh output for each objective stage. Never modify the host
prepared parent, request, generated XML, or native implementation.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat

TARGET = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/development-02/prepared')
STAGES = ('objective-log_drag_ou', 'objective-pulses')
LEAF = 'legacy-output'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(path):
    info = Path(path).stat()
    return {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid}


def tree(path, exclude_children=()):
    path = Path(path)
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Output parent view must be an ordinary directory')
    rows = []
    for item in sorted(path.rglob('*')):
        info = item.lstat()
        relative = str(item.relative_to(path))
        if Path(relative).parts[0] in exclude_children:
            continue
        if stat.S_ISDIR(info.st_mode):
            rows.append({'relative': relative, 'kind': 'directory'})
        elif stat.S_ISREG(info.st_mode):
            rows.append({'relative': relative, 'kind': 'file', 'bytes': info.st_size, 'sha256': digest(item)})
        elif stat.S_ISLNK(info.st_mode) and Path(relative).parts[0] == 'data':
            # Preserve literal old links only inside the subtree that the
            # existing mandatory frozen data overlay completely replaces.
            rows.append({'relative': relative, 'kind': 'symlink', 'link_target': os.readlink(item)})
        else:
            raise ValueError('Linked or special parent-view member rejected: ' + str(item))
    return rows


def fresh_directory(path, parent):
    path, parent = Path(path), Path(parent)
    if not path.is_relative_to(parent) or path == parent or path.resolve() != path:
        raise ValueError('Private output escapes fresh attempt')
    if not path.is_dir() or path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ValueError('Private output must be an ordinary owned directory')


def create(output, mount_identity, target=TARGET):
    output, target = Path(output), Path(target)
    fresh_directory(output / 'prepared', output)
    if (target / 'output').exists() or (target / 'output').is_symlink():
        raise ValueError('Historical output already exists; preserve it')
    before = tree(target)
    resolved = target.resolve(strict=True)
    if mount_identity['path'] != str(resolved):
        raise ValueError('Historical prepared parent resolution differs')
    view = output / 'objective-parent-view'
    shutil.copytree(target, view, symlinks=True)
    if tree(view) != before or tree(target) != before:
        raise ValueError('Parent copy or original bytes changed')
    (view / 'output').mkdir()
    outputs = {}
    for stage in STAGES:
        folder = output / stage / LEAF
        folder.mkdir(parents=True)
        outputs[stage] = {'path': str(folder), 'identity': identity(folder)}
    return {'schema': 'orbit-reference-private-objective-output-v2-composition07',
            'target': str(target), 'mount_identity': mount_identity,
            'host_identity': identity(resolved), 'host_data_identity': identity(target / 'data'), 'original_tree': before,
            'view': str(view), 'view_identity': identity(view), 'view_tree': tree(view),
            'stage_outputs': outputs, 'host_output_absent_at_preparation': True,
            'scope': 'Exporter storage only; unchanged native commands and scientific paths'}


def verify_composed_data(plan, row, target, base_tree, *, objective=False):
    """Certify the complete view after the mandatory exact data overmount."""
    matches = [r for r in plan['directory_overlays'] if r['target'] == str(target / 'data')]
    if len(matches) != 1:
        raise ValueError('Original prepared parent changed: ambiguous data overlay')
    overlay = matches[0]
    source = Path(overlay['source'])
    if source.is_symlink() or not source.is_dir() or source.resolve() != source:
        raise ValueError('Original prepared parent changed: invalid data backing')
    if identity(target / 'data') != identity(source):
        raise ValueError('Original prepared parent changed: data backing identity differs')
    pin = overlay['inventory']
    inventory_path = Path(pin['path'])
    if digest(inventory_path) != pin['sha256'] or inventory_path.stat().st_size != pin['bytes']:
        raise ValueError('Frozen data inventory changed')
    inventory = json.loads(inventory_path.read_text())
    if inventory['root'] != str(source):
        raise ValueError('Frozen data inventory root differs')
    expected_data = []
    for entry in inventory['entries']:
        relative = Path(entry['relative'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Unsafe frozen data inventory member')
        if entry.get('link_target') is not None:
            raise ValueError('Unexpected frozen data symlink')
        item = {'relative': entry['relative'], 'kind': entry['kind']}
        if entry['kind'] == 'file':
            item.update(bytes=entry['bytes'], sha256=entry['sha256'])
        elif entry['kind'] != 'directory':
            raise ValueError('Unsupported frozen data member')
        expected_data.append(item)
    expected_data.sort(key=lambda r: r['relative'])
    if tree(target / 'data') != expected_data:
        raise ValueError('Visible data overlay differs from frozen inventory')
    excluded = ('data', 'output') if objective else ('data',)
    expected_parent = [r for r in base_tree if Path(r['relative']).parts[0] not in excluded]
    if tree(target, exclude_children=excluded) != expected_parent:
        raise ValueError('Original prepared parent changed outside the data overlay')


def verify(plan, overlay_identity):
    row = plan['objective_outputs']
    output = Path(plan['output'])
    if (row['schema'] != 'orbit-reference-private-objective-output-v2-composition07'
            or row['target'] != str(TARGET)
            or set(row['stage_outputs']) != set(STAGES)
            or row['host_output_absent_at_preparation'] is not True):
        raise ValueError('Unexpected objective output mapping')
    if overlay_identity(row['target']) != row['mount_identity']:
        raise ValueError('Historical objective parent resolution changed')
    required_data = str(Path(row['target']) / 'data')
    if required_data not in [r['target'] for r in plan['directory_overlays']]:
        raise ValueError('Private parent requires exact frozen data overlay')
    target, view = Path(row['target']), Path(row['view'])
    if view != output / 'objective-parent-view':
        raise ValueError('Unexpected parent view location')
    fresh_directory(view, output)
    if identity(view) != row['view_identity'] or tree(view) != row['view_tree']:
        raise ValueError('Read-only parent view changed')
    expected = sorted([*row['original_tree'], {'relative': 'output', 'kind': 'directory'}], key=lambda x: x['relative'])
    if row['view_tree'] != expected:
        raise ValueError('Parent view does not preserve exact original members')
    for stage, backing in row['stage_outputs'].items():
        folder = Path(backing['path'])
        if folder != output / stage / LEAF:
            raise ValueError('Unexpected objective stage backing')
        fresh_directory(folder, output)
        if identity(folder) != backing['identity']:
            raise ValueError('Objective stage backing identity changed')
    actual = identity(target)
    if actual == row['host_identity']:
        if identity(target / 'data') == row['host_data_identity']:
            if tree(target) != row['original_tree']:
                raise ValueError('Original prepared parent changed')
        else:
            verify_composed_data(plan, row, target, row['original_tree'])
    elif actual == row['view_identity']:
        # Certify the complete mandatory data substitution as well as parent
        # membership; only this stage's named output subtree is writable.
        if sorted(p.name for p in target.iterdir()) != sorted(p.name for p in view.iterdir()):
            raise ValueError('Namespace prepared parent membership changed')
        stage = Path(os.environ.get('TMPDIR', '')).parent.name
        if stage not in STAGES or identity(target / 'output') != row['stage_outputs'][stage]['identity']:
            raise ValueError('Namespace objective output backing differs')
        verify_composed_data(plan, row, target, row['view_tree'], objective=True)
    else:
        raise ValueError('Prepared parent is neither original nor private view')
    return row


def binds(plan, writable, overlay_identity):
    row = verify(plan, overlay_identity)
    stage = Path(writable).name
    if stage not in STAGES:
        return []
    target = row['mount_identity']['path']
    return ['--ro-bind', row['view'], target,
            '--bind', row['stage_outputs'][stage]['path'], str(Path(target) / 'output')]


def proof(plan, stage, containing):
    """Check actual kernel flags and identities; never probe original writes."""
    if stage not in STAGES:
        return {'active': False}
    row = plan['objective_outputs']
    target = Path(row['target'])
    backing = Path(row['stage_outputs'][stage]['path'])
    if identity(target) != row['view_identity']:
        raise ValueError('Actual prepared view is not the frozen copy')
    if identity(target / 'output') != identity(backing):
        raise ValueError('Exporter output does not refer to this stage backing')
    parent_mount = containing(str(target))
    output_mount = containing(str(target / 'output'))
    if 'ro' not in parent_mount['options'] or 'rw' not in output_mount['options']:
        raise ValueError('Private objective mount flags differ')
    if output_mount['filesystem_type'] in ('tmpfs', 'ramfs'):
        raise ValueError('Named exporter output must remain on D filesystem')
    return {'active': True, 'target': str(target / 'output'), 'backing': str(backing),
            'same_backing_identity': True, 'parent_mount': parent_mount,
            'output_mount': output_mount, 'host_original_written': False}
