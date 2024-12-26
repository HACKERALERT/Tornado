from PyQt6.QtCore import *
from PyQt6.QtWidgets import *
from PyQt6.QtGui import *
from sys import argv, exit
from stem.control import Controller
from flask import Flask, request
from socketserver import TCPServer
from gevent.pywsgi import WSGIServer
from threading import Thread
from requests import get, post
from datetime import datetime
from time import sleep
from os.path import expanduser, exists
from os import mkdir
from json import loads, dumps

window = None
myaddr = None
viewing = None
controller = None
needscroll = False
messages = {}
sending = {}
unread = []
app = Flask(__name__)


@app.route("/alive")
def alive():
    return "", 204


@app.route("/message", methods=["POST"])
def message():
    global needscroll
    addr = request.form["addr"]
    if addr not in messages.keys():
        messages[addr] = []
    messages[addr].append(
        {
            "type": request.form["type"],
            "content": request.form["content"],
            "time": request.form["time"],
            "me": False,
        }
    )
    if addr not in unread:
        if viewing is None or addr != list(messages.keys())[viewing]:
            unread.append(addr)
    if viewing is not None and addr == list(messages.keys())[viewing]:
        needscroll = True
    window.needRepaint.emit()
    return "", 204


class MainWindow(QMainWindow):
    needRepaint = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tornado")
        self.setMinimumSize(1000, 600)
        self.needRepaint.connect(lambda: (self.repaintChat(), self.loadChat(viewing)))

        self.start = QVBoxLayout()
        self.startWidget = QWidget()
        self.startWidget.setLayout(self.start)
        self.start.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start.addWidget(
            QLabel("Tornado uses Tor's hidden services to send messages securely.")
        )
        self.start.addWidget(
            QLabel("It's completely peer-to-peer, and no central server is involved.")
        )
        self.start.addWidget(
            QLabel("Before continuing, make sure that the Tor Browser is running.")
        )
        self.start.addWidget(
            QLabel("Once the browser is connected, hit the button below to begin.")
        )
        self.startButton = QPushButton("Start")
        self.startButton.clicked.connect(self.connect)
        self.start.addWidget(self.startButton)
        self.setCentralWidget(self.startWidget)
        self.show()

        self.connecting = QVBoxLayout()
        self.connectingWidget = QWidget()
        self.connectingWidget.setLayout(self.connecting)
        self.connecting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connecting.addWidget(QLabel("Connecting to the Tor control port..."))

        self.failed = QVBoxLayout()
        self.failedWidget = QWidget()
        self.failedWidget.setLayout(self.failed)
        self.failed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.failed.addWidget(
            QLabel(
                "It seems like the Tor Browser isn't running. Start it and try again."
            )
        )
        self.failedButton = QPushButton("Close")
        self.failedButton.clicked.connect(self.close)
        self.failed.addWidget(self.failedButton)

        self.test = QVBoxLayout()
        self.testWidget = QWidget()
        self.testWidget.setLayout(self.test)
        self.test.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.test.addWidget(QLabel("Performing self-test..."))

        self.testfailed = QVBoxLayout()
        self.testfailedWidget = QWidget()
        self.testfailedWidget.setLayout(self.testfailed)
        self.testfailed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.testfailed.addWidget(
            QLabel(
                "Self-test failed. Ensure you are connected to the Internet and try again."
            )
        )
        self.testfailedButton = QPushButton("Close")
        self.testfailedButton.clicked.connect(self.close)
        self.testfailed.addWidget(self.testfailedButton)

        self.connected = QVBoxLayout()
        self.connectedWidget = QWidget()
        self.connectedWidget.setLayout(self.connected)
        self.connected.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connected.addWidget(
            QLabel(
                "Connected successfully! You are now ready to start chatting. Keep in mind:"
            )
        )
        self.connected.addWidget(
            QLabel(
                "- You must keep Tornado running to receive messages. Minimizing the window is fine."
            )
        )
        self.connected.addWidget(
            QLabel(
                "- Your identity, contacts, and messages will be stored locally in your home directory."
            )
        )
        self.connected.addWidget(
            QLabel(
                "- Do not start more than one instance of Tornado because bad things will happen."
            )
        )
        self.connected.addWidget(
            QLabel(
                "- Nothing is completely secure. Make sure to use common sense and exercise caution."
            )
        )
        self.connectedButton = QPushButton("Got it")
        self.connectedButton.clicked.connect(
            lambda: (
                self.setCentralWidget(self.chatWidget),
                self.chatWidget.show(),
                self.repaint(),
                self.repaintChat(),
                Thread(target=self.syncWorker, daemon=True).start(),
            )
        )
        self.connected.addWidget(self.connectedButton)

        self.chat = QVBoxLayout()
        self.chatWidget = QWidget()
        self.chatWidget.setLayout(self.chat)
        self.me = QLabel()
        self.me.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.chat.addWidget(self.me)
        self.messages = QHBoxLayout()
        self.contacts = QTableWidget()
        self.contacts.setColumnCount(1)
        self.contacts.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.contacts.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.contacts.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.contacts.horizontalHeader().setVisible(False)
        self.contacts.verticalHeader().setVisible(False)
        self.messages.addWidget(self.contacts)
        self.right = QVBoxLayout()
        self.viewer = QTableWidget()
        self.viewer.setColumnCount(1)
        self.viewer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewer.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.viewer.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.viewer.horizontalHeader().setVisible(False)
        self.viewer.verticalHeader().setVisible(False)
        self.right.addWidget(self.viewer)
        self.input = QLineEdit()
        self.input.returnPressed.connect(
            lambda: (
                self.sendMessage(self.input.text()),
                self.input.clear(),
                self.me.setFocus(),
            )
        )
        self.right.addWidget(self.input)
        self.messages.addLayout(self.right)
        self.chat.addLayout(self.messages)
        self.add = QHBoxLayout()
        self.add.addWidget(QLabel("Message a new identity:"))
        self.addIdentity = QLineEdit()
        self.addIdentity.returnPressed.connect(self.newChat)
        self.add.addWidget(self.addIdentity)
        self.chat.addLayout(self.add)

    def connect(self):
        global controller, myaddr, messages, sending, unread
        self.setCentralWidget(self.connectingWidget)
        self.connectingWidget.show()
        self.repaint()
        try:
            controller = Controller.from_port(address="127.0.0.1", port=9151)
            controller.authenticate()

            with TCPServer(("127.0.0.1", 0), None) as s:
                port = s.server_address[1]
            if not exists(expanduser("~/.tornado/key")):
                svc = controller.create_ephemeral_hidden_service(
                    {80: port}, await_publication=True
                )
                myaddr = svc.service_id
                mkdir(expanduser("~/.tornado"))
                with open(expanduser("~/.tornado/key"), "w") as key:
                    key.write("%s:%s" % (svc.private_key_type, svc.private_key))
            else:
                with open(expanduser("~/.tornado/key")) as key:
                    keyType, keyContent = key.read().split(":", 1)
                svc = controller.create_ephemeral_hidden_service(
                    {80: port},
                    key_type=keyType,
                    key_content=keyContent,
                    await_publication=True,
                )
                myaddr = svc.service_id
                try:
                    with open(expanduser("~/.tornado/messages.json"), "r") as file:
                        messages = loads(file.read())
                    with open(expanduser("~/.tornado/sending.json"), "r") as file:
                        sending = loads(file.read())
                    with open(expanduser("~/.tornado/unread.json"), "r") as file:
                        unread = loads(file.read())
                except:
                    pass
            Thread(target=self.serve, args=(port,), daemon=True).start()
            window.me.setText("My identity: " + myaddr)

            self.setCentralWidget(self.testWidget)
            self.testWidget.show()
            self.repaint()

            try:
                res = get(
                    f"http://{myaddr}.onion/alive",
                    proxies={"http": "socks5h://127.0.0.1:9150"},
                )
                if res.status_code != 204:
                    raise Exception()

                self.setCentralWidget(self.connectedWidget)
                self.connectedWidget.show()
                self.repaint()
            except:
                self.setCentralWidget(self.testfailedWidget)
                self.testfailedWidget.show()
                self.repaint()
        except:
            self.setCentralWidget(self.failedWidget)
            self.failedWidget.show()
            self.repaint()

    def serve(self, port):
        WSGIServer(("127.0.0.1", port), app).serve_forever()

    def newChat(self):
        if self.addIdentity.text() and len(self.addIdentity.text()) == 56:
            if self.addIdentity.text() not in messages.keys():
                messages[self.addIdentity.text()] = []
            self.repaintChat()
            i = list(messages.keys()).index(self.addIdentity.text())
            self.contacts.cellWidget(i, 0).setFocus()
            self.loadChat(i)
        self.addIdentity.clear()
        self.me.setFocus()

    def repaintChat(self):
        self.contacts.setRowCount(len(messages.keys()))
        for i in range(len(messages.keys())):
            widget = QWidget()
            layout = QVBoxLayout()
            text = QLabel(list(messages.keys())[i])
            if list(messages.keys())[i] in unread:
                text.setStyleSheet("font-weight:bold")
            layout.addWidget(text)
            status = QLabel("All messages synced.")
            status.setStyleSheet("color:#357a38")
            if list(messages.keys())[i] in sending:
                status.setText("Messages are not synced.")
                status.setStyleSheet("color:#dc143c")
            layout.addWidget(status)
            widget.setLayout(layout)
            widget.mouseReleaseEvent = self.loadChatClosure(i)
            self.contacts.setCellWidget(i, 0, widget)
        self.contacts.resizeRowsToContents()

    def loadChat(self, i, _needscroll=False):
        global viewing, needscroll
        if i is None:
            return
        if _needscroll and viewing == i:
            self.contacts.clearSelection()
            self.viewer.setRowCount(0)
            viewing = None
            return
        viewing = i
        key = list(messages.keys())[i]
        if key in unread:
            unread.remove(key)
            self.repaintChat()
        self.viewer.setRowCount(len(messages[key]))
        for j in range(len(messages[key])):
            if messages[key][j]["type"] == "text":
                layout = QVBoxLayout()
                sender = QLabel("Me")
                if not messages[key][j]["me"]:
                    sender.setText(key)
                sender.setStyleSheet("color:#888888")
                layout.addWidget(sender)
                text = QLabel(messages[key][j]["content"])
                text.setWordWrap(True)
                layout.addWidget(text)
                ts = datetime.fromtimestamp(float(messages[key][j]["time"]))
                time = QLabel(ts.strftime("%Y-%m-%d %H:%M") + " (UTC)")
                time.setStyleSheet("color:#888888")
                layout.addWidget(time)
                widget = QWidget()
                widget.setLayout(layout)
                self.viewer.setCellWidget(j, 0, widget)
        self.viewer.resizeRowsToContents()
        if needscroll or _needscroll:
            self.viewer.scrollToBottom()
            needscroll = False

    def loadChatClosure(self, i):
        return lambda _: self.loadChat(i, _needscroll=True)

    def sendMessage(self, message):
        if viewing is None or not message:
            return
        time = datetime.utcnow().timestamp()
        addr = list(messages.keys())[viewing]
        data = {
            "addr": myaddr,
            "type": "text",
            "content": message,
            "time": time,
            "me": True,
        }
        messages[addr].append(data)
        if addr not in sending.keys():
            sending[addr] = []
        sending[addr].append(data)
        self.repaintChat()
        self.loadChat(viewing)
        self.viewer.scrollToBottom()

    def backup(self):
        with open(expanduser("~/.tornado/messages.json"), "w") as file:
            file.write(dumps(messages))
        with open(expanduser("~/.tornado/sending.json"), "w") as file:
            file.write(dumps(sending))
        with open(expanduser("~/.tornado/unread.json"), "w") as file:
            file.write(dumps(unread))

    def sync(self):
        for i in range(len(sending.keys()) - 1, -1, -1):
            addr = list(sending.keys())[i]
            for j in range(len(sending[addr])):
                message = sending[addr][j]
                if message is None:
                    continue
                try:
                    res = post(
                        f"http://{addr}.onion/message",
                        proxies={"http": "socks5h://127.0.0.1:9150"},
                        data=message,
                    )
                    if res.status_code != 204:
                        raise Exception()
                    sending[addr][j] = None
                except:
                    pass
            done = True
            for message in sending[addr]:
                if message is not None:
                    done = False
            if done:
                del sending[addr]
        self.needRepaint.emit()

    def syncWorker(self):
        while True:
            if sending:
                self.sync()
            self.backup()
            sleep(5)


if __name__ == "__main__":
    qapp = QApplication(argv)
    qapp.setStyle("Fusion")
    window = MainWindow()
    qapp.exec()
    if myaddr is not None:
        window.backup()
    if controller is not None:
        controller.remove_ephemeral_hidden_service(myaddr)
    exit()
