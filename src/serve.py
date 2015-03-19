import dockerps
import gevent.socket
import gevent.server
import gevent.pool

class EmptyException(Exception):
    pass

# handle request
def handle_connection(socket, address):
    print "New connection from", address
    try:
        # first, receive bytes to figure out what they want
        data = socket.recv(1024)
        if not data:
            socket.sendall("Don't know how to handle an empty request.\r\n\r\n")
            return

        if ':' in data:
            task, subtask = data.lower().strip().split(':')
            if task == "containers":
                dockerps.containers(incoming_socket=socket)
            elif task == "shell":
                dockerps.shell(subtask, incoming_socket=socket)
            else:
                socket.sendall("Invalid task '{0}' requested.".format(data))
        else:
            socket.sendall("Task request must contain ':' (e.g., 'containers:' or 'shell:foo')")
    finally:
        # terminator
        print "Sending terminator to", address
        socket.sendall("\r\n\r\n")
        socket.close()

# limit total number of connections
pool = gevent.pool.Pool(10000)
server = gevent.server.StreamServer(('0.0.0.0', 6728), handle_connection, spawn=pool)
server.serve_forever()

