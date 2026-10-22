"""Bounded HTTP/1 request bodies, including reverse-proxy chunked requests."""


def read_body(handler, limit):
    handler.connection.settimeout(15)
    lengths = handler.headers.get_all("Content-Length", [])
    encodings = handler.headers.get_all("Transfer-Encoding", [])
    if encodings:
        if lengths or len(encodings) != 1 or encodings[0].lower().strip() != "chunked":
            raise ValueError("ambiguous request framing")
        chunks = []
        total = 0
        for _ in range(4096):
            line = handler.rfile.readline(128)
            if not line.endswith(b"\r\n"):
                raise ValueError("bad chunk header")
            size = int(line[:-2].split(b";", 1)[0], 16)
            if size < 0 or total + size > limit:
                raise ValueError("request too large")
            if size == 0:
                if handler.rfile.readline(2) != b"\r\n":
                    raise ValueError("trailers are not supported")
                return b"".join(chunks)
            chunk = handler.rfile.read(size)
            if len(chunk) != size or handler.rfile.read(2) != b"\r\n":
                raise ValueError("truncated chunk")
            chunks.append(chunk)
            total += size
        raise ValueError("too many chunks")
    if len(lengths) != 1:
        raise ValueError("missing body length")
    size = int(lengths[0])
    if not 0 < size <= limit:
        raise ValueError("request too large")
    body = handler.rfile.read(size)
    if len(body) != size:
        raise ValueError("truncated body")
    return body
