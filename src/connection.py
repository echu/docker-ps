import contextlib
import logging
import gevent.socket as socket

import os


# Fix for sslwrap being dumped from python 2.7.9
# Re-add sslwrap to Python 2.7.9
# https://github.com/gevent/gevent/issues/477

import inspect
__ssl__ = __import__('ssl')

try:
    _ssl = __ssl__._ssl
except AttributeError:
    _ssl = __ssl__._ssl2


OldSSLSocket = __ssl__.SSLSocket

class NewSSLSocket(OldSSLSocket):
    """Fix SSLSocket constructor."""
    def __init__(
        self, sock, keyfile=None, certfile=None, server_side=False, cert_reqs=0,
        ssl_version=2, ca_certs=None, do_handshake_on_connect=True,
        suppress_ragged_eofs=True, ciphers=None,
        server_hostname=None, _context=None
    ):
        OldSSLSocket.__init__(
            self, sock, keyfile=None, certfile=None, server_side=False, cert_reqs=0,
            ssl_version=2, ca_certs=None, do_handshake_on_connect=True,
            suppress_ragged_eofs=True, ciphers=None
        )


def new_sslwrap(
    sock, server_side=False, keyfile=None, certfile=None,
    cert_reqs=__ssl__.CERT_NONE, ssl_version=__ssl__.PROTOCOL_SSLv23,
    ca_certs=None, ciphers=None
):
    context = __ssl__.SSLContext(ssl_version)
    context.verify_mode = cert_reqs or __ssl__.CERT_NONE
    if ca_certs:
        context.load_verify_locations(ca_certs)
    if certfile:
        context.load_cert_chain(certfile, keyfile)
    if ciphers:
        context.set_ciphers(ciphers)

    caller_self = inspect.currentframe().f_back.f_locals['self']
    return context._wrap_socket(sock, server_side=server_side, ssl_sock=caller_self)

if not hasattr(_ssl, 'sslwrap'):
    _ssl.sslwrap = new_sslwrap
    __ssl__.SSLSocket = NewSSLSocket
# End fix

__TLS = False
if os.environ.get('DOCKER_TLS_VERIFY') == "1":
    import gevent.ssl
    __TLS = True


log = logging.getLogger("docker.connection")

docker_socket_host = os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock')
log.debug("Using Docker socket at " + docker_socket_host)

if docker_socket_host.startswith('unix://'):
    @contextlib.contextmanager
    def docker_socket():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(docker_socket_host[7:])
        try:
            yield sock
        finally:
            sock.close()
elif docker_socket_host.startswith('tcp://'):
    __addr = docker_socket_host[6:]
    if ":" in __addr:
        __host_parts = __addr.split(':')
        if len(__host_parts) != 2:
            raise Exception(
                "Invalid bind address format: %s" % __addr
            )
        if __host_parts[0]:
            __host = __host_parts[0]

        try:
            __port = int(__host_parts[1])
        except Exception:
            raise Exception(
                "Invalid port: %s", __addr
            )
    else:
        __host = __addr
        __port = 2376

    @contextlib.contextmanager
    def docker_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if __TLS:
            cert_path = os.environ.get('DOCKER_CERT_PATH')
            if not cert_path:
                raise Exception("Expecting DOCKER_CERT_PATH defined for boot2docker.")
            keyfile = cert_path + "/key.pem"
            certfile = cert_path + "/cert.pem"
            ca_certs = cert_path + "/ca.pem"
            sock = gevent.ssl.SSLSocket(sock, keyfile=keyfile, certfile=certfile, ca_certs=ca_certs, ssl_version=3)

        sock.connect((__host, __port))
        try:
            yield sock
        finally:
            sock.close()
else:
    raise Exception("Docker host socket should be either unix or tcp socket.")

class DockerResponse(object):
    def __init__(self, socket, response, body, status):
        self.socket = socket
        self.response = response
        self.body = body
        self.status = status

def recv_docker_resp(sock):
    data_buffer = ""
    data_buffer = sock.recv(1024)
    header_end = '\r\n\r\n'
    content_len = 'Content-Length'
    chunked_encoding = 'Transfer-Encoding: chunked'

    body = ""

    while header_end not in data_buffer:
        data_buffer += sock.recv(1024)

    return_code = int(data_buffer[9:12])

    if content_len in data_buffer:
        idx = data_buffer.find(content_len) + len(content_len)+ 2
        idx_end = data_buffer.find('\r', idx)
        length = int(data_buffer[idx:idx_end])

        header_idx = data_buffer.find(header_end)
        body = data_buffer[header_idx+4:]

        while len(body) < length:
            body += sock.recv(1024)
    elif chunked_encoding in data_buffer:
        chunks = ""
        header_idx = data_buffer.find(header_end)
        body_start = header_idx+4
        body = data_buffer[body_start:]

        try:
            # Read chunks
            while True:
                clen_idx = body.find('\r\n')
                if clen_idx == -1:
                    body += sock.recv(1024)
                    continue
                clen = int(body[:clen_idx], 16)
                if clen == 0:
                    break
                elif clen > (len(body) - clen_idx - 2):
                    body += sock.recv(1024)
                else:
                    body = body[clen_idx+2:]
                    chunks += body[:clen]
                    body = body[clen+2:]
        except:
            chunks += '\nException fetching logs\n'
        body = chunks

    return data_buffer, body, return_code

http_method_header = {
    'POST': 'POST %s HTTP/1.1\r\nContent-Type: %s\r\n', # vnd.docker.raw-stream\r\n',
    'GET': 'GET %s HTTP/1.1\r\nContent-Type: %s\r\n',
    'DELETE': 'DELETE %s HTTP/1.1\r\nContent-Type: %s\r\n'
}

@contextlib.contextmanager
def send_and_receive(method, path, content_type='application/json', data=None):
    '''
    Sends the command given by path using the method specified.
    Receives the response and validates that the return code was OK.
    Hands the response object back to the context.
    '''
    with docker_socket() as sock:
        try:
            msg = http_method_header[method] % (path,content_type)
        except KeyError:
            print "No header for method", method
            raise

        if data is not None:
            msg += 'Content-Length: %d\r\n\r\n' % len(data)
            msg += data
        else:
            msg += '\r\n'

        sock.send(msg)
        resp, body, code = recv_docker_resp(sock)
        if code in [200, 201, 204]:
            yield DockerResponse(sock, resp, body, code)
        else:
            print msg
            raise Exception("%d RESPONSE. %s." % (code, resp))
