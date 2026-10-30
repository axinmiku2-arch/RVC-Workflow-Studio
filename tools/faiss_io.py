"""FAISS I/O through Python streams, including Unicode Windows paths."""
import faiss


def read_index(path):
    with open(path, "rb") as stream:
        return faiss.read_index(faiss.PyCallbackIOReader(stream.read))


def write_index(index, path):
    with open(path, "wb") as stream:
        faiss.write_index(index, faiss.PyCallbackIOWriter(stream.write))
