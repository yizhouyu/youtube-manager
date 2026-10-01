#!/usr/bin/env python3
"""Render a comparison cut without overwriting the source project's EDL or exports.

A variant EDL is rendered inside an isolated staging project that symlinks the original
raw-media directory and copies its edit assets.  The final master, captions, and the
exact EDL used are copied to the requested destination.

Example:
  ./venv/bin/python scripts/render_variant.py \
    "$HOME/Desktop/101 - Princeton" ./edl/princeton-film.json \
    --output "$HOME/Desktop/101 - Princeton/02 - Export/manus-demo/princeton-film-4k.mov"
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


IGNORE_EDIT = shutil.ignore_patterns('preview.mp4', 'previews', 'render_status.json', 'scan', '__pycache__')


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path, help='Existing project folder containing 01 - Unedited and 02 - Export/edit')
    p.add_argument('variant_edl', type=Path, help='JSON EDL for the alternate cut')
    p.add_argument('--output', type=Path, required=True, help='Destination .mov for the 4K comparison master')
    p.add_argument('--name', help='Stage directory name (defaults to the output filename stem)')
    p.add_argument('--keep-stage', action='store_true', help='Keep the isolated staging project for later inspection')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project.expanduser().resolve()
    variant = args.variant_edl.expanduser().resolve()
    output = args.output.expanduser().resolve()
    source_edit = project / '02 - Export' / 'edit'
    raw = project / '01 - Unedited'
    if not raw.is_dir() or not source_edit.is_dir():
        raise SystemExit(f'Not a video project: {project}')
    if variant.suffix.lower() != '.json' or not variant.is_file():
        raise SystemExit(f'Variant EDL is missing or not JSON: {variant}')
    if output.suffix.lower() != '.mov':
        raise SystemExit('--output must be a .mov 4K master path')
    if output == raw or raw in output.parents or output == source_edit or source_edit in output.parents:
        raise SystemExit('Refusing to write a comparison master inside raw media or the source edit folder')

    captions = output.with_suffix('.captions.srt')
    delivered_edl = output.with_suffix('.edl.json')
    manifest = output.with_suffix('.manifest.json')
    # Keep dependencies version-scoped so v2 never replaces v1's editable assets.
    assets_name = f'{output.stem}.assets'
    delivered_assets = output.parent / assets_name
    targets = [output, captions, delivered_edl, manifest, delivered_assets]
    collisions = [str(path) for path in targets if path.exists()]
    if collisions:
        raise SystemExit('Refusing to overwrite existing comparison deliverables:\n' + '\n'.join(collisions))

    with variant.open(encoding='utf-8') as f:
        edl = json.load(f)
    if not isinstance(edl.get('shots'), list) or not edl['shots']:
        raise SystemExit('Variant EDL needs a non-empty shots array')

    stage_parent = Path(tempfile.mkdtemp(prefix='yt-editor-variant-'))
    stage = stage_parent / (args.name or output.stem)
    try:
        (stage / '02 - Export').mkdir(parents=True)
        (stage / '01 - Unedited').symlink_to(raw, target_is_directory=True)
        stage_edit = stage / '02 - Export' / 'edit'
        shutil.copytree(source_edit, stage_edit, ignore=IGNORE_EDIT)
        # A self-contained variant can carry generated music / TTS / cards in a sibling
        # edit-assets directory (or in the directory recorded by its delivered EDL).
        variant_meta = edl.get('variant_metadata') or {}
        relative_assets = variant_meta.get('editable_assets')
        asset_overlay = (variant.parent / relative_assets).resolve() if relative_assets else variant.parent / 'edit-assets'
        has_asset_overlay = asset_overlay.is_dir()
        if has_asset_overlay:
            shutil.copytree(asset_overlay, stage_edit, dirs_exist_ok=True)

        # An alternate EDL may choose a different shot list, but it always resolves clips and assets
        # relative to this staging project, never the source project.
        edl['project'] = str(stage)
        edl.setdefault('source_dir', '01 - Unedited')
        prior_output = edl.get('output') or {}
        edl['output'] = {**prior_output, 'width': 3840, 'height': 2160,
                          'fps': prior_output.get('fps', '30000/1001')}
        # This is an EDL extension, not a second metadata system: it lets a later edit reconnect
        # this delivered variant to the original Manager project after the temporary stage is gone.
        edl['variant_metadata'] = {
            **variant_meta,
            'base_project': str(project),
            'base_raw_media': str(raw),
            'variant_edl_source': variant.name,
            'editable_assets': assets_name if has_asset_overlay else None,
            'reproduction': 'Use this delivered EDL with scripts/render_variant.py and its version-scoped assets directory; edit EDL subtitles, not the rendered SRT.',
        }
        with (stage_edit / 'edl.json').open('w', encoding='utf-8') as f:
            json.dump(edl, f, ensure_ascii=False, indent=1)

        repo = Path(__file__).resolve().parents[1]
        python = repo / 'venv' / 'bin' / 'python'
        subprocess.run([str(python), '-m', 'src.editor.render', str(stage), '--final'], cwd=repo, check=True)

        stage_master = stage / '02 - Export' / f'{stage.name}.mov'
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
             'stream=width,height', '-of', 'json', str(stage_master)],
            capture_output=True, text=True, check=True,
        )
        video_streams = json.loads(probe.stdout).get('streams', [])
        if not video_streams or (video_streams[0].get('width'), video_streams[0].get('height')) != (3840, 2160):
            raise SystemExit(f'Rendered comparison master is not 4K UHD (3840x2160): {stage_master}')
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage_master, output)
        shutil.copy2(stage_edit / 'captions.srt', captions)
        shutil.copy2(stage_edit / 'edl.json', delivered_edl)
        if has_asset_overlay:
            shutil.copytree(asset_overlay, delivered_assets)
        manifest.write_text(json.dumps({
            'schema_version': 1,
            'kind': 'isolated_comparison_master',
            'rendered_at': datetime.now(timezone.utc).isoformat(),
            'source_project': str(project),
            'source_raw_media': str(raw),
            'master': output.name,
            'captions': captions.name,
            'edit_decision_list': delivered_edl.name,
            'editable_assets': assets_name if has_asset_overlay else None,
            'caption_editing': 'Edit the EDL source-time subtitles, then rerun this command; do not edit the SRT as the source of truth.',
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(output)
    finally:
        if args.keep_stage:
            print(f'Staging project retained: {stage}')
        else:
            shutil.rmtree(stage_parent, ignore_errors=True)


if __name__ == '__main__':
    main()
