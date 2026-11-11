"""Assemble the claude.ai artifact version of Birding AI.

The artifact runs BirdNET in the browser with LiteRT.js, so it needs no server.
This script builds the folder that gets published:

    dist/index.html              artifact/page.html with LiteRT.js inlined
    dist/wasm/...                LiteRT.js WebAssembly runtime (two variants)
    dist/models/acoustic-N.wasm  BirdNET 2.4 acoustic model (fp16), in <15 MB parts
    dist/models/geo-N.wasm       BirdNET 2.4 range model, in <15 MB parts
                             (.wasm only because the service serves a fixed list of types)
    dist/models/labels.txt       species names

Prerequisites (see artifact/README.md):
  * the BirdNET models, downloaded by the `birdnet` Python package
  * npm packages @litertjs/core@2.6.0 and esbuild in NODE_DIR

    python artifact/build.py NODE_DIR OUT_DIR
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
from fix_batch_dim import main as fix_batch_dim  # noqa: E402

BIRDNET = Path.home() / ".local/share/birdnet"
ACOUSTIC = BIRDNET / "acoustic-models/v2.4/tf/model-fp16.tflite"
GEO = BIRDNET / "geo-models/v2.4/tf/model-fp32.tflite"
LABELS = BIRDNET / "acoustic-models/v2.4/tf/labels/en_us.txt"
PART_BYTES = 14_200_000  # the artifact service accepts binary files up to 15 MB
WASM = ["litert_wasm_internal.js", "litert_wasm_internal.wasm",
        "litert_wasm_compat_internal.js", "litert_wasm_compat_internal.wasm"]


def split(src: Path, prefix: Path) -> list[Path]:
    data = src.read_bytes()
    parts = []
    for n, start in enumerate(range(0, len(data), PART_BYTES)):
        part = prefix.with_name(f"{prefix.name}-{n}.wasm")  # see FILES in page.html
        part.write_bytes(data[start:start + PART_BYTES])
        parts.append(part)
    return parts


def main(node_dir: str, out_dir: str) -> None:
    node, out = Path(node_dir).resolve(), Path(out_dir).resolve()
    for needed in (ACOUSTIC, GEO, LABELS):
        if not needed.is_file():
            sys.exit(f"missing {needed}: run python -c \"import birdnet; "
                     "birdnet.load('acoustic','2.4','tf',library='litert',precision='fp16'); "
                     "birdnet.load('geo','2.4','tf',library='litert')\"")
    if out.exists():
        shutil.rmtree(out)
    (out / "wasm").mkdir(parents=True)
    (out / "models").mkdir()

    entry = node / "entry.js"
    entry.write_text('export * from "@litertjs/core";\n')
    bundle = node / "litert.iife.js"
    subprocess.run(["npx", "esbuild", str(entry), "--bundle", "--format=iife", "--global-name=LiteRT",
                    "--minify", f"--outfile={bundle}"], cwd=node, check=True)
    js = bundle.read_text()
    if "</script" in js.lower():
        js = js.replace("</script", "<\\/script").replace("</SCRIPT", "<\\/SCRIPT")
    page = (HERE / "page.html").read_text()
    marker = "/*LITERT_BUNDLE*/"
    assert page.count(marker) == 1, "page.html must contain the bundle marker once"
    (out / "index.html").write_text(page.replace(marker, js))

    for name in WASM:
        shutil.copy(node / "node_modules/@litertjs/core/wasm" / name, out / "wasm" / name)

    # LiteRT.js rejects models whose input shape has a flexible (-1) batch size.
    tmp = out / "models"
    fix_batch_dim(str(ACOUSTIC), str(tmp / "acoustic.tflite"))
    fix_batch_dim(str(GEO), str(tmp / "geo.tflite"))
    sizes = {}
    for name in ("acoustic", "geo"):
        model = tmp / f"{name}.tflite"
        sizes[name] = (model.stat().st_size, [p.name for p in split(model, tmp / name)])
        model.unlink()
    shutil.copy(LABELS, tmp / "labels.txt")

    # The page hard-codes the model sizes and part names; fail loudly if they drifted.
    html = (out / "index.html").read_text()
    for name, (size, parts) in sizes.items():
        expected = f'{name}: {{ parts: [{", ".join(f"{chr(34)}models/{p}{chr(34)}" for p in parts)}], bytes: {size} }}'
        if expected not in html:
            sys.exit(f"update FILES.{name} in page.html to: {expected}")
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"built {out} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
