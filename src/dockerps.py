import connection as ds
import gevent.socket
#======= Docker stuff ======

import json
import logging

log = logging.getLogger("docker-ps.container")

class NoDataException(Exception):
    pass

def cleanup(greenlet):
    if greenlet is not None:
        greenlet.kill()

def shell(container, incoming_socket):
    """
    Gives interactive prompt; uses `docker exec`.
    IMPORTANT: This is *not* the same as `docker attach`; it instead attaches a shell to containers
    (even when there might not be one) via `docker exec ID /bin/bash`.
    """
    exec_req = \
    {
        "AttachStdin":True,
        "AttachStdout":True,
        "AttachStderr":True,
        "Tty":True,
        "Cmd": ["/bin/bash"],
        "Container": container
    }
    exec_url = '/containers/{0}/exec'.format(container)
    with ds.send_and_receive('POST', exec_url, data=json.dumps(exec_req)) as dsock:
        exec_id = json.loads(dsock.body)["Id"]

    start_req = \
    {
        "Detach":False,
        "Tty":True
    }
    start_url = '/exec/{0}/start'.format(exec_id)

    with ds.send_and_receive('POST', start_url, data=json.dumps(start_req)) as dsock:
        sock = dsock.socket

        def write_loop():
            while True:
                try:
                    data = sock.recv(128)
                    if data:
                        incoming_socket.send(data)
                    else:
                        raise NoDataException("No data from docker socket.")
                except Exception as e:
                    print e
                    cleanup(read_greenlet)
                    break

        def read_loop():
            while True:
                try:
                    if hasattr(incoming_socket, 'receive'):
                        data = incoming_socket.receive()
                    else:
                        data = incoming_socket.recv(128)
                    if data:
                        sock.send(data)
                    else:
                        raise NoDataException("No data from input source.")

                except Exception as e:
                    print e
                    cleanup(write_greenlet)
                    break

        write_greenlet = gevent.spawn(write_loop)
        read_greenlet = gevent.spawn(read_loop)
        gevent.joinall([write_greenlet, read_greenlet])

def containers(incoming_socket=None):
    """
    Docker ps, except with the option to forward the data through another
    socket.
    """
    params = {
        'all': 1
    }
    with ds.send_and_receive('GET', '/containers/json', data=json.dumps(params)) as dsock:
        if incoming_socket is None:
            return json.loads(dsock.body)
        else:
            incoming_socket.sendall(dsock.body)
