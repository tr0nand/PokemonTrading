import socket

class Peer(object):
    tracker_port = 12001
    def __init__(self):
        self.peer_list = []
        self.tracker = None

    def connect_to_network(self, tracker_addr):
        sock = socket.sockets(socket.AF_INET, socket.SOCK_STREAM)
        addr = None
        try:
            addr = socket.inet_aton(tracker_addr)
        except socket.error:
            print("Tracking server address is not a valid IPv4 address.")
            return

        if addr is not None:
            try:
                sock.connect((addr, Peer.tracker_port))
            except:
                print("Tracker not responding.")
                return

        sock.send(b"\xAA",1)
        resp = sock.recv(1)
        if resp == b"\x55":
            print("Tracker found, joining the network.")


