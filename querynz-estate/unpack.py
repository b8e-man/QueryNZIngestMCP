import zstandard, tarfile, io, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, 'rb') as f:
    d = zstandard.ZstdDecompressor().stream_reader(f)
    with tarfile.open(fileobj=io.BufferedReader(d), mode='r|') as t:
        t.extractall(dst, filter='data')
print('extracted', src)
