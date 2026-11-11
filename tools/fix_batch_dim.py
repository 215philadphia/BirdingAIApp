"""Pin a TFLite model's dynamic batch dimension (-1) to 1.

LiteRT.js (used by the browser version of the app) refuses inputs whose shape
signature contains -1. Each tensor's `shape_signature` is rewritten in place:
-1 becomes 1. The file size and everything else stay identical.

    python tools/fix_batch_dim.py in.tflite out.tflite
"""

import struct
import sys

import flatbuffers
from flatbuffers.table import Table

# Field indexes from the TFLite schema (tensorflow/lite/schema/schema.fbs).
MODEL_SUBGRAPHS = 2
SUBGRAPH_TENSORS = 0
TENSOR_SHAPE_SIGNATURE = 7


def field(tab: Table, index: int) -> int:
    return tab.Offset(4 + 2 * index)


def tables(buf: bytearray, tab: Table, index: int):
    o = field(tab, index)
    if not o:
        return
    start = tab.Vector(o)
    for i in range(tab.VectorLen(o)):
        pos = start + 4 * i
        yield Table(buf, tab.Indirect(pos))


def main(src: str, dst: str) -> None:
    buf = bytearray(open(src, "rb").read())
    root = Table(buf, flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, 0))
    patched = 0
    for subgraph in tables(buf, root, MODEL_SUBGRAPHS):
        for tensor in tables(buf, subgraph, SUBGRAPH_TENSORS):
            o = field(tensor, TENSOR_SHAPE_SIGNATURE)
            if not o:
                continue
            start = tensor.Vector(o)
            for i in range(tensor.VectorLen(o)):
                pos = start + 4 * i
                if struct.unpack_from("<i", buf, pos)[0] == -1:
                    struct.pack_into("<i", buf, pos, 1)
                    patched += 1
    open(dst, "wb").write(buf)
    print(f"patched {patched} dynamic dimension(s) -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
